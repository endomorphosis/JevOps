#!/usr/bin/env python3
"""Exact-pin, resumable LRA project preparation in an owned 8 GiB volume.

Only corpus-selected public Git commits are fetched. Builds are serial direct
Lean compilations of the required import closure; Lake cannot fan out jobs or
silently update dependencies. A ready source/import binding is not a proof.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time
import tomllib
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jevops import arena_prepare, arena_lean
from jevops.arena import strip_comments
from jevops.lean import VersionPin
from jevops.seals import Fingerprinter

SCHEMA = 'jevops.lean-refactor.project-readiness.v1'
CORPUS = ROOT / 'papers/completion/lean_refactor_arena/data/benchmark_data_warmup.jsonl'
CORPUS_SHA = '6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804'
MAX_BYTES = 8 * 1024 ** 3
FUSE_URL = 'https://archive.ubuntu.com/ubuntu/pool/universe/e/e2fsprogs/fuse2fs_1.47.0-2.4~exp1ubuntu4.1_amd64.deb'
FUSE_SHA = '03a8c0d82b57f470994eb64349441bbc5eba02d7ebe0f48b6af0587414d0f728'
AUTH = {'completion_authority': False, 'proof_authority': False, 'official_score': None}


def require(value, reason):
    if not value:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def file_sha(path):
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    after = path.stat()
    require((before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'input changed while hashing')
    return digest.hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.is_symlink(), 'refuse symlink output')
    temp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    with temp.open('xb') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode() + b'\n')
        stream.flush(); os.fsync(stream.fileno())
    os.replace(temp, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def records(path=CORPUS):
    raw = path.read_bytes()
    require(sha(raw) == CORPUS_SHA, 'frozen corpus changed')
    rows = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    require(len(rows) == 15 and len({row['name'] for row in rows}) == 15, 'wrong corpus population')
    return rows


def group_for(rows, source, tag):
    selected = [(row, version[tag]) for row in rows if row['source'] == source
                for version in row['version_info'] if tag in version]
    require(selected, 'source/toolchain pair is not declared by the frozen benchmark')
    identities = {(row['url'], commit) for row, commit in selected}
    require(len(identities) == 1, 'ambiguous corpus project pin')
    repository, commit = identities.pop()
    require(re.fullmatch(r'[0-9a-f]{40}', commit) is not None, 'exact Git commit required')
    return {'source': source, 'repository': repository, 'lean_tag': tag, 'git_commit': commit,
            'problems': [row['name'] for row, _ in selected]}


def owned_directory(path):
    require(path.is_absolute() and not path.is_symlink(), 'exact absolute pilot directory required')
    for item in (path, *path.parents):
        require(not item.is_symlink(), 'pilot directory has a symlink ancestor')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    require(path.stat().st_uid == os.getuid(), 'pilot directory belongs to another UID')
    return path


def contained(path, volume):
    require(path.absolute().is_relative_to(volume.absolute()), 'write path outside capped volume')
    current=path.absolute()
    while current!=volume.absolute():
        require(not current.is_symlink(), 'write path contains a symlink')
        current=current.parent
    require(path.resolve().is_relative_to(volume.resolve()), 'write path escapes capped volume')


@contextmanager
def lock(path):
    require(not path.is_symlink(), 'lock path is a symlink')
    with path.open('a+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def command(argv, cwd, volume, *, timeout=60, label='command'):
    """One owned command at a time, no shell/ambient credentials, durable logs."""
    require(type(timeout) in (int, float) and 0 < timeout <= 1800, 'bounded command timeout required')
    logs = volume / 'logs'; logs.mkdir(exist_ok=True)
    target = logs / (label + '-' + uuid.uuid4().hex)
    home = volume / 'home'; home.mkdir(exist_ok=True)
    scratch = volume / 'tmp'; scratch.mkdir(exist_ok=True)
    environment = {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'TMPDIR': str(scratch),
                   'XDG_CACHE_HOME': str(volume / 'cache'), 'GIT_CONFIG_NOSYSTEM': '1',
                   'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_TERMINAL_PROMPT': '0',
                   'GIT_OPTIONAL_LOCKS': '0', 'GIT_LFS_SKIP_SMUDGE': '1',
                   'LEAN_NUM_THREADS': '1', 'MATHLIB_NO_CACHE_ON_UPDATE': '1'}
    started = time.monotonic()
    with target.with_suffix('.stdout').open('xb') as out, target.with_suffix('.stderr').open('xb') as err:
        proc = subprocess.Popen(argv, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                                stdout=out, stderr=err, shell=False, start_new_session=True)
        try:
            code = proc.wait(timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGTERM)
            try: proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL); proc.wait(timeout=3)
            code, timed_out = 124, True
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL); proc.wait(timeout=3)
    result = {'argv': list(map(str, argv)), 'cwd': str(cwd), 'exit_code': code, 'timed_out': timed_out,
              'duration_seconds': time.monotonic() - started, 'pid': proc.pid,
              'stdout': str(target.with_suffix('.stdout')), 'stderr': str(target.with_suffix('.stderr')),
              'stdout_sha256': sha(target.with_suffix('.stdout').read_bytes()),
              'stderr_sha256': sha(target.with_suffix('.stderr').read_bytes()), **AUTH}
    save(target.with_suffix('.json'), result)
    if code:
        tail = target.with_suffix('.stderr').read_text(errors='replace')[-1500:]
        raise RuntimeError(f'{label} failed ({code}): {tail}; logs={target}')
    return target.with_suffix('.stdout').read_text(errors='replace').strip()


def bootstrap_volume(root, maximum=MAX_BYTES):
    require(type(maximum) is int and 232_000_000 <= maximum <= MAX_BYTES, 'pilot exceeds the reviewed 8 GiB cap')
    descriptor = root / 'preparation.json'
    if descriptor.exists():
        cfg = json.loads(descriptor.read_text())
        require(cfg['max_bytes'] == maximum, 'existing volume cap differs')
        if not os.path.ismount(root/'work'):
            image,mount=Path(cfg['image']),Path(cfg['mount'])
            require(cfg.get('schema')==arena_prepare.SCHEMA and Path(cfg['root'])==root and
                    image==root/'volume.ext4' and mount==root/'work' and
                    not image.is_symlink() and not mount.is_symlink() and
                    image.stat().st_uid==os.getuid() and image.stat().st_ino==cfg['image_inode'] and
                    image.stat().st_size==arena_prepare.volume_bytes(maximum) and
                    mount.is_dir() and not any(mount.iterdir()), 'refuse to reconcile a changed/nonempty unmounted workspace')
            bootstrap=json.loads((root/'bootstrap.json').read_text())
            binary=Path(cfg['fuse2fs'])
            require(binary.resolve().is_relative_to((root/'bootstrap').resolve()) and
                    file_sha(binary)==bootstrap['binary_sha256'] and
                    file_sha(root/'bootstrap/fuse2fs.deb')==FUSE_SHA, 'private filesystem helper changed')
            subprocess.run([str(binary),'-o','rw,nosuid,nodev,fakeroot',str(image),str(mount)],
                           stdin=subprocess.DEVNULL,check=True,timeout=15)
        return cfg, arena_prepare.validate_volume(cfg)
    bootstrap = root / 'bootstrap'; bootstrap.mkdir(exist_ok=True)
    package = bootstrap / 'fuse2fs.deb'
    if not package.exists():
        with urllib.request.urlopen(FUSE_URL, timeout=30) as response:
            raw = response.read(1_048_577)
        require(len(raw) <= 1_048_576 and sha(raw) == FUSE_SHA, 'fuse2fs public package hash mismatch')
        with package.open('xb') as stream: stream.write(raw)
    require(sha(package.read_bytes()) == FUSE_SHA, 'private fuse2fs package changed')
    unpack = bootstrap / 'unpacked'
    if not unpack.exists():
        subprocess.run(['/usr/bin/dpkg-deb', '--extract', str(package), str(unpack)],
                       stdin=subprocess.DEVNULL, check=True, timeout=15)
    binary = unpack / 'usr/bin/fuse2fs'
    if not binary.exists(): binary = unpack / 'usr/sbin/fuse2fs'
    require(binary.is_file(), 'private fuse2fs executable missing')
    cfg = arena_prepare.initialize(root, binary, maximum)
    save(root / 'bootstrap.json', {'package_url': FUSE_URL, 'package_sha256': FUSE_SHA,
                                  'binary_sha256': sha(binary.read_bytes()), **AUTH})
    return cfg, arena_prepare.validate_volume(cfg)


def git(path, volume, *args, timeout=90):
    return command(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', '-c', 'protocol.file.allow=never',
                    '-C', str(path), *args], path, volume, timeout=timeout, label='git')


def clone_exact(repository, commit, path, volume, deadline):
    require(re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?', repository),
            'only explicit public GitHub repositories from pinned manifests are supported')
    require(re.fullmatch(r'[0-9a-f]{40}', commit), 'dependency must have an exact commit')
    contained(path,volume)
    remaining = lambda: min(120, max(.01, deadline - time.monotonic()))
    path.mkdir(parents=True, exist_ok=True)
    if not (path / '.git').exists():
        require(not any(path.iterdir()), 'refuse to adopt a non-Git nonempty project')
        git(path, volume, 'init', timeout=remaining())
        git(path, volume, 'remote', 'add', 'origin', repository, timeout=remaining())
    require(git(path, volume, 'remote', 'get-url', 'origin') == repository, 'existing project origin differs')
    head = subprocess.run(['/usr/bin/git', '-C', str(path), 'rev-parse', '--verify', 'HEAD'],
                          capture_output=True, timeout=10, check=False,
                          env={'PATH':'/usr/bin:/bin','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null'})
    if head.returncode == 0:
        require(head.stdout.decode().strip() == commit, 'existing checkout has a different pin; never reset it')
    else:
        git(path, volume, 'fetch', '--depth=1', '--no-tags', 'origin', commit, timeout=remaining())
        git(path, volume, '-c', 'advice.detachedHead=false', 'checkout', '--detach', commit, timeout=remaining())
    require(git(path, volume, 'rev-parse', 'HEAD') == commit, 'checkout did not reach exact requested commit')
    require(not git(path, volume, 'status', '--porcelain', '--untracked-files=no'), 'tracked project source is dirty')


def dependencies(project, volume, deadline):
    path = project / 'lake-manifest.json'
    raw = path.read_bytes(); manifest = json.loads(raw)
    require(manifest.get('version') in {'1.1.0', '1.2.0'}, 'unsupported Lake lockfile schema')
    require(isinstance(manifest.get('packages'), list) and len(manifest['packages']) <= 64, 'dependency bound exceeded')
    directory = manifest.get('packagesDir', '.lake/packages')
    require(not Path(directory).is_absolute() and '..' not in Path(directory).parts, 'unsafe dependency directory')
    for row in manifest['packages']:
        require(row.get('type') == 'git', 'non-Git dependency needs a separately reviewed adapter')
        name = str(row['name']).strip('«»')
        require(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*', name), 'unsafe package name')
        clone_exact(row['url'], row['rev'], project / directory / name, volume, deadline)
    require(path.read_bytes() == raw, 'provisioning changed the frozen dependency lockfile')
    return arena_lean.lake_environment(project)


def import_names(source):
    clean = strip_comments(source)
    result = []
    for line in clean.splitlines():
        match = re.match(r'^\s*(?:public\s+)?(?:meta\s+)?import\s+(.+)$', line)
        if match:
            names = match[1].split()
            if names and names[0]=='all':names=names[1:]
            require(names, 'empty import declaration')
            require(all(re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*', x) for x in names),
                    'unsupported import syntax; do not guess a partial module set')
            result.extend(names)
    return list(dict.fromkeys(result))


def package_options(root):
    path=root/'lakefile.toml'
    require(path.is_file(), 'direct serial build requires a reviewed lakefile.toml adapter: '+str(root))
    configuration=tomllib.loads(path.read_text())
    require(not configuration.get('moreLeanArgs'), 'custom compiler argv requires a reviewed adapter')
    for library in configuration.get('lean_lib',[]):
        require(not library.get('leanOptions') and not library.get('moreLeanArgs'),
                'library-specific compiler options require a reviewed adapter')
    result=[]
    def flatten(value,prefix=''):
        for key,item in sorted(value.items()):
            require(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*',key), 'unsupported Lean option name')
            name=prefix+key
            if type(item) is dict:flatten(item,name+'.');continue
            require(type(item) in (str,int,bool), 'unsupported Lean option type')
            text=('true' if item else 'false') if type(item) is bool else str(item)
            require('\n' not in text and len(text)<1024, 'invalid Lean option value')
            result.append('-D'+name+'='+text)
    flatten(configuration.get('leanOptions',{}))
    return result


def compilation_identity(plan, roots, lean):
    # Every receipt is invalidated by changes to ANY source in this closure,
    # package configuration, compiler, serialized stdlib, or shared runtime.
    # Never use file age, a previous exit status, or artifact existence alone.
    inputs = [Path(__file__), lean, *arena_lean.BOUNDARY_FILES]
    inputs.extend(arena_lean._artifacts(lean.parent.parent / 'lib'))
    for root in roots:
        inputs.extend(root / name for name in ('lean-toolchain', 'lake-manifest.json', 'lakefile.toml', 'lakefile.lean')
                      if (root / name).is_file())
        # Package-wide source identity permits the SAME built module to serve
        # two corpus targets with different import subsets. Additional source
        # changes invalidate conservatively, rather than accepting a stale dep.
        inputs.extend(path for path in arena_lean._artifacts(root) if path.suffix=='.lean')
    return sha(canonical({str(path):file_sha(path) for path in sorted(set(inputs))}))


def artifact_info(item):
    target = Path(item['package']) / '.lake/build/lib/lean' / Path(*item['module'].split('.')).with_suffix('.olean')
    # Lean 4.26 and newer may split a serialized environment into sidecars.
    return target, {str(path):file_sha(path) for path in sorted(target.parent.glob(target.name + '*'))
                    if path.is_file()}


def checked_artifacts(plan, roots, lean, volume, identity=None):
    identity = identity or compilation_identity(plan, roots, lean)
    gaps = []
    for item in plan:
        target, artifacts = artifact_info(item)
        key = sha(canonical({'module':item, 'input_identity':identity}))
        receipt = volume / 'compile-receipts' / (key + '.json')
        if not target.is_file() or not receipt.is_file():
            gaps.append('compiled_import_receipt_missing:' + item['module']); continue
        old = json.loads(receipt.read_text())
        if (old.get('exit_code') != 0 or old.get('input_identity') != identity or
                old.get('artifacts') != artifacts or old.get('source_sha256') != item['source_sha256']):
            gaps.append('compiled_import_binding_mismatch:' + item['module'])
    return gaps


def import_plan(project, environment, record, lean):
    """A bounded transitive source/import graph, excluding the target module."""
    roots = [project, *[item.root for item in environment.packages]]
    builtin = lean.parent.parent / 'lib/lean'
    visited, visiting, ordered = set(), set(), []
    def visit(name):
        if name in visited: return
        require(name not in visiting, 'cyclic module import graph')
        require(len(visited) + len(visiting) < 1024, 'import closure exceeds module bound')
        relative = Path(*name.split('.'))
        candidates = [(root, root / relative.with_suffix('.lean')) for root in roots
                      if (root / relative.with_suffix('.lean')).is_file()]
        if not candidates:
            require((builtin / relative.with_suffix('.olean')).is_file(), 'missing module source/artifact: ' + name)
            visited.add(name); return
        require(len(candidates) == 1, 'ambiguous import module: ' + name)
        package, source = candidates[0]
        require(source.resolve().is_relative_to(package.resolve()), 'module source escapes package')
        visiting.add(name)
        for dependency in import_names(source.read_text()): visit(dependency)
        visiting.remove(name);visited.add(name)
        ordered.append({'module':name,'source':str(source),'package':str(package), 'source_sha256':sha(source.read_bytes())})
    target = project / record['file_path']
    require(target.is_file(), 'target file absent at frozen source location')
    for name in import_names(target.read_text()): visit(name)
    return ordered


def build_imports(project, environment, record, lean, volume, deadline):
    plan = import_plan(project, environment, record, lean)
    roots = [project, *[item.root for item in environment.packages]]
    search = [root / '.lake/build/lib/lean' for root in roots]
    for path in search: path.mkdir(parents=True, exist_ok=True)
    identity = compilation_identity(plan, roots, lean)
    receipts = volume / 'compile-receipts'; receipts.mkdir(exist_ok=True)
    calls, hits = 0, 0
    for item in plan:
        require(time.monotonic() < deadline, 'whole preparation deadline reached')
        target = Path(item['package']) / '.lake/build/lib/lean' / Path(*item['module'].split('.')).with_suffix('.olean')
        contained(target,volume)
        target.parent.mkdir(parents=True, exist_ok=True)
        key = sha(canonical({'module': item, 'input_identity':identity}))
        receipt = receipts / (key + '.json')
        if target.is_file() and receipt.is_file():
            old = json.loads(receipt.read_text())
            if not checked_artifacts([item], roots, lean, volume, identity):
                hits += 1;continue
        # The direct compiler has exactly one native invocation, not an
        # unbounded Lake dependency scheduler. One command is launched at a time.
        log = volume / 'logs' / ('lean-' + uuid.uuid4().hex)
        environment_vars = {'PATH': '/usr/bin:/bin', 'HOME': str(volume/'home'), 'TMPDIR':str(volume/'tmp'),
                            'LEAN_NUM_THREADS':'1','LEAN_PATH':os.pathsep.join(map(str,search))}
        start = time.monotonic()
        with log.with_suffix('.stdout').open('xb') as out, log.with_suffix('.stderr').open('xb') as err:
            proc = subprocess.Popen([str(lean), '-j1', '-M4096', *package_options(Path(item['package'])),
                                     '-o', str(target), str(Path(item['source']).relative_to(item['package']))],
                                    cwd=item['package'],env=environment_vars,stdin=subprocess.DEVNULL,
                                    stdout=out,stderr=err,start_new_session=True)
            try:code=proc.wait(timeout=min(60,max(.01,deadline-time.monotonic())))
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid,signal.SIGTERM)
                try:proc.wait(timeout=3)
                except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=3)
                raise RuntimeError('native import compiler timed out: '+item['module'])
            finally:
                if proc.poll() is None:
                    os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=3)
        calls += 1
        require(code == 0 and target.is_file(), 'import compilation failed: '+item['module']+'; log='+str(log))
        _,artifacts = artifact_info(item)
        save(receipt, {**item,'exit_code':0,'input_identity':identity,'artifacts':artifacts,'artifact':str(target),
                       'duration_seconds':time.monotonic()-start,'stdout':str(log.with_suffix('.stdout')),
                       'stderr':str(log.with_suffix('.stderr')), 'proofs_verified':0,**AUTH})
    return {'module_count':len(plan),'compile_invocations':calls,'reused_checked_artifacts':hits,
            'max_concurrent_compilers':1,'proofs_verified':0}


def inventory(rows, pilot, elan_home):
    projects, result = [], []
    reader=Fingerprinter()  # Local ns-ctime reuse; fuse whole-second ctime disables reuse internally.
    for record in rows:
        for version in record['version_info']:
            for tag, commit in version.items():
                path = pilot / 'work/projects' / f"{record['source']}-{tag}-{commit[:12]}"
                project = {'repository':record['url'],'lean_tag':tag,'git_commit':commit,'root':str(path),
                           'kind':'putnam' if record['source']=='putnambench' else 'repo','resolve_lake_manifest':True}
                gaps, binding, details = [], None, {}
                try:lean=arena_lean.pinned_lean(elan_home,tag)
                except ValueError as exc:gaps.append(str(exc));lean=None
                if not path.is_dir():gaps.append('exact_project_checkout_missing')
                elif lean:
                    try:
                        binding=arena_lean.project_binding(record,VersionPin(tag,commit),project,elan_home)
                        environment=binding.lake
                        plan=import_plan(path,environment,record,lean) if not binding.putnam else []
                        roots=[path,*[item.root for item in environment.packages]]
                        gaps.extend(checked_artifacts(plan,roots,lean,pilot/'work'))
                        details={'compiler_path':str(lean),'compiler_sha256':file_sha(lean),
                                 'target_source_sha256':file_sha(path/record['file_path']) if record['file_path'] else None,
                                 'exact_reference_occurrences':1,'source_prefix_sha256':sha(binding.prefix.encode()),
                                 'lake_manifest_sha256':environment.manifest_sha256,
                                 'dependencies':[{'name':p.name,'repository':p.repository,'git_commit':p.commit,
                                                  'root':str(p.root)} for p in environment.packages],
                                 'import_module_count':len(plan),
                                 'imports':[{'module':p['module'],'source':p['source'],'source_sha256':p['source_sha256'],
                                             'artifacts':artifact_info(p)[1]} for p in plan]}
                        digest=binding.fingerprint(reader) if not gaps else None
                    except (ValueError,OSError,subprocess.SubprocessError) as exc:
                        gaps.append(str(exc));digest=None
                else:digest=None
                if gaps:digest=None
                result.append({'name':record['name'],'source':record['source'],'repository':record['url'],
                               'lean_tag':tag,'git_commit':commit,'status':'READY' if not gaps else 'UNAVAILABLE',
                               'capability_gaps':gaps,'source_path':str(path/record['file_path']) if record['file_path'] else None,
                               'project':project,'binding_sha256':digest,'current_binding':details,'proofs_verified':0})
                if not gaps and project not in projects:projects.append(project)
    require(len(result)==36,'full required pin matrix was not enumerated')
    return projects,result


def produce(args):
    rows=records();pilot=owned_directory(args.pilot_root.absolute())
    require(args.timeout_seconds in range(1,1801), 'whole preparation timeout must be 1..1800 seconds')
    started=time.monotonic();error=None;build=None
    with lock(pilot/'project-readiness.lock'):
        if args.provision:
            group=group_for(rows,args.source,args.tag)
            require(group['repository'], 'Putnam requires a reviewed exact Mathlib wrapper; no repository URL may be invented')
            cfg,volume=bootstrap_volume(pilot,args.max_bytes)
            deadline=started+args.timeout_seconds
            project=volume/'projects'/f"{args.source}-{args.tag}-{group['git_commit'][:12]}"
            try:
                clone_exact(group['repository'],group['git_commit'],project,volume,deadline)
                require((project/'lean-toolchain').read_text().strip()=='leanprover/lean4:'+args.tag,'project toolchain differs from corpus pin')
                env=dependencies(project,volume,deadline)
                lean=arena_lean.pinned_lean(args.elan_home,args.tag)
                if args.build_imports:
                    selected=next(row for row in rows if row['name']==args.problem) if args.problem else next(row for row in rows if row['name'] in group['problems'])
                    require(selected['name'] in group['problems'],'problem is outside the selected exact project')
                    build=build_imports(project,env,selected,lean,volume,deadline)
            except (OSError,ValueError,RuntimeError) as exc:error=str(exc)
        cfg=json.loads((pilot/'preparation.json').read_text()) if (pilot/'preparation.json').exists() else None
        volume=arena_prepare.validate_volume(cfg) if cfg else None
        projects,matrix=inventory(rows,pilot,args.elan_home)
        report={'schema':SCHEMA,'corpus_sha256':CORPUS_SHA,'producer_sha256':sha(Path(__file__).read_bytes()),
                'pilot_root':str(pilot),'elan_home':str(args.elan_home.resolve()),'observed_at_unix':time.time(),
                'duration_seconds':time.monotonic()-started,'required_pin_count':36,'projects':projects,'rows':matrix,
                'ready_pin_count':sum(r['status']=='READY' for r in matrix),'build':build,'provision_error':error,
                'storage_cap_bytes':args.max_bytes,'max_concurrent_compilers':1,'proofs_verified':0,**AUTH}
        if volume:
            fs=os.statvfs(volume);report['volume_capacity_bytes']=fs.f_blocks*fs.f_frsize
            report['volume_used_bytes']=(fs.f_blocks-fs.f_bfree)*fs.f_frsize
        save(args.output,report)
        save(args.output.with_name(args.output.stem+'.projects.json'),projects)
        return report


def validate(path):
    report=json.loads(path.read_text());require(report.get('schema')==SCHEMA,'unknown readiness schema')
    require(report['producer_sha256']==sha(Path(__file__).read_bytes()),'readiness producer changed')
    require(report['corpus_sha256']==sha(CORPUS.read_bytes())==CORPUS_SHA,'corpus changed')
    require(type(report['storage_cap_bytes']) is int and report['storage_cap_bytes']<=MAX_BYTES and
            type(report['max_concurrent_compilers']) is int and report['max_concurrent_compilers']==1,'resource contract changed')
    pilot=Path(report['pilot_root']);cfg=json.loads((pilot/'preparation.json').read_text())
    arena_prepare.validate_volume(cfg)
    require(cfg['max_bytes']==report['storage_cap_bytes'],'actual filesystem cap differs from receipt')
    projects,matrix=inventory(records(),pilot,Path(report['elan_home']))
    require(projects==report['projects'] and matrix==report['rows'],'current source/toolchain/dependency/import binding differs')
    require(report['ready_pin_count']==sum(r['status']=='READY' for r in matrix)>0,'no genuinely ready corpus pin')
    require(report['proofs_verified']==0 and report['completion_authority'] is False and report['proof_authority'] is False,
            'readiness must not self-authorize proof or task completion')
    return {'valid':True,'ready_pin_count':report['ready_pin_count'],'required_pin_count':36,**AUTH}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pilot-root',type=Path,default=ROOT/'data/lean_refactor_campaign_20261024/project-pilot')
    parser.add_argument('--output',type=Path,default=ROOT/'data/lean_refactor_campaign_20261024/JLR-016.result.json')
    parser.add_argument('--elan-home',type=Path,default=Path.home()/'.elan')
    parser.add_argument('--source',default='strata');parser.add_argument('--tag',default='v4.26.0')
    parser.add_argument('--problem');parser.add_argument('--provision',action='store_true')
    parser.add_argument('--build-imports',action='store_true');parser.add_argument('--validate',action='store_true')
    parser.add_argument('--timeout-seconds',type=int,default=900);parser.add_argument('--max-bytes',type=int,default=MAX_BYTES)
    args=parser.parse_args(argv)
    old_handler=signal.signal(signal.SIGTERM,lambda *_: (_ for _ in ()).throw(InterruptedError('owned preparation terminated')))
    try:
        result=validate(args.output) if args.validate else produce(args)
        print(json.dumps(result,sort_keys=True,allow_nan=False))
        return 0 if args.validate or result['ready_pin_count']>0 else 75
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
        print(json.dumps({'error':str(exc),**AUTH}),file=sys.stderr);return 1
    finally:signal.signal(signal.SIGTERM,old_handler)


if __name__=='__main__':raise SystemExit(main())

"""Offline artifact tests; synthetic projects have no benchmark proof authority."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace

import pytest

TOOL=Path(__file__).resolve().parents[1]/'tools/lean_refactor_project_readiness.py'
spec=importlib.util.spec_from_file_location('project_readiness',TOOL)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def fixture(tmp_path):
    volume=tmp_path/'volume';volume.mkdir()
    project=volume/'project';project.mkdir()
    (project/'lake-manifest.json').write_text('{"version":"1.1.0","packages":[]}')
    (project/'lean-toolchain').write_text('leanprover/lean4:v4.26.0\n')
    (project/'lakefile.toml').write_text('name = "test"\n')
    (project/'Base.lean').write_text('def base : Nat := 1\n')
    (project/'Middle.lean').write_text('import Base\ndef middle := base\n')
    (project/'Target.lean').write_text('import Middle\ntheorem target : True := by trivial\n')
    compiler=tmp_path/'toolchain/bin/lean';compiler.parent.mkdir(parents=True)
    (compiler.parent.parent/'lib/lean').mkdir(parents=True)
    compiler.write_text('#!/usr/bin/python3\nimport pathlib,sys\np=pathlib.Path(sys.argv[sys.argv.index("-o")+1]);p.write_text("artifact:"+pathlib.Path(sys.argv[-1]).read_text())\n')
    compiler.chmod(0o700)
    for name in ('logs','home','tmp'): (volume/name).mkdir()
    record={'file_path':'Target.lean'}
    env=SimpleNamespace(packages=())
    return project,env,record,compiler,volume


def test_frozen_corpus_has_all_required_pairs():
    rows=m.records()
    assert len(rows)==15
    assert sum(len(v) for row in rows for v in row['version_info'])==36
    assert m.group_for(rows,'strata','v4.26.0')['git_commit']=='451e5f047bafa010d178856db76c00029bfa4d7f'


@pytest.mark.parametrize('source,tag',[('strata','v9.0.0'),('unknown','v4.26.0')])
def test_no_unlisted_pin_substitution(source,tag):
    with pytest.raises(ValueError,match='not declared'):m.group_for(m.records(),source,tag)


def test_corpus_tamper_rejected(tmp_path):
    path=tmp_path/'bad';path.write_bytes(m.CORPUS.read_bytes()+b' ')
    with pytest.raises(ValueError,match='corpus changed'):m.records(path)


def test_ambiguous_project_pin_rejected():
    rows=[{'source':'x','name':'a','url':'https://github.com/a/a','version_info':[{'v1.0.0':'a'*40}]},
          {'source':'x','name':'b','url':'https://github.com/a/b','version_info':[{'v1.0.0':'b'*40}]}]
    with pytest.raises(ValueError,match='ambiguous'):m.group_for(rows,'x','v1.0.0')


def test_imports_do_not_include_comments_or_target():
    assert m.import_names('-- import Bad\n/- import Worse -/\npublic meta import A.B C\nimport all Init.Data.List\n')==['A.B','C','Init.Data.List']


def test_declared_package_options_are_preserved(tmp_path):
    (tmp_path/'lakefile.toml').write_text('name="test"\n[leanOptions]\nexperimental.module=true\nmaxRecDepth=1000\n')
    assert m.package_options(tmp_path)==['-Dexperimental.module=true','-DmaxRecDepth=1000']


def test_unknown_lake_program_and_custom_args_refused(tmp_path):
    with pytest.raises(ValueError,match='lakefile.toml'):m.package_options(tmp_path)
    (tmp_path/'lakefile.toml').write_text('name="test"\nmoreLeanArgs=["--run"]\n')
    with pytest.raises(ValueError,match='custom compiler'):m.package_options(tmp_path)


def test_unknown_import_syntax_fails_closed():
    with pytest.raises(ValueError,match='unsupported import'):m.import_names('import A; import B')


def test_topological_import_closure(tmp_path):
    project,env,record,lean,volume=fixture(tmp_path)
    assert [r['module'] for r in m.import_plan(project,env,record,lean)]==['Base','Middle']


def test_missing_import_is_not_ready(tmp_path):
    project,env,record,lean,volume=fixture(tmp_path)
    (project/'Target.lean').write_text('import Absent\n')
    with pytest.raises(ValueError,match='missing module'):m.import_plan(project,env,record,lean)


def test_cyclic_imports_fail_closed(tmp_path):
    project,env,record,lean,volume=fixture(tmp_path)
    (project/'Base.lean').write_text('import Middle\n')
    with pytest.raises(ValueError,match='cyclic'):m.import_plan(project,env,record,lean)


def test_ambiguous_namespace_rejected(tmp_path):
    project,env,record,lean,volume=fixture(tmp_path)
    dep=tmp_path/'dependency';dep.mkdir();(dep/'Base.lean').write_text('def base := 2')
    env.packages=(SimpleNamespace(root=dep),)
    with pytest.raises(ValueError,match='ambiguous import'):m.import_plan(project,env,record,lean)


def test_symlink_source_escape_rejected(tmp_path):
    project,env,record,lean,volume=fixture(tmp_path)
    outside=tmp_path/'outside.lean';outside.write_text('def base := 3')
    (project/'Base.lean').unlink();(project/'Base.lean').symlink_to(outside)
    with pytest.raises(ValueError,match='escapes'):m.import_plan(project,env,record,lean)


def test_artifact_existence_is_not_a_success_receipt(tmp_path):
    project,env,record,lean,volume=fixture(tmp_path)
    target=project/'.lake/build/lib/lean/Base.olean';target.parent.mkdir(parents=True);target.write_text('forged')
    plan=m.import_plan(project,env,record,lean)
    assert len(m.checked_artifacts(plan,[project],lean,volume))==2


def test_real_child_compile_receipts_resume_and_tamper(tmp_path):
    project,env,record,lean,volume=fixture(tmp_path)
    first=m.build_imports(project,env,record,lean,volume,time.monotonic()+10)
    assert first['compile_invocations']==2 and first['max_concurrent_compilers']==1
    second=m.build_imports(project,env,record,lean,volume,time.monotonic()+10)
    assert second['compile_invocations']==0 and second['reused_checked_artifacts']==2
    plan=m.import_plan(project,env,record,lean)
    assert not m.checked_artifacts(plan,[project],lean,volume)
    (project/'.lake/build/lib/lean/Base.olean').write_text('tampered')
    assert m.checked_artifacts(plan,[project],lean,volume)==['compiled_import_binding_mismatch:Base']


def test_source_change_invalidates_entire_closure(tmp_path):
    project,env,record,lean,volume=fixture(tmp_path)
    m.build_imports(project,env,record,lean,volume,time.monotonic()+10)
    (project/'Base.lean').write_text('def base : Nat := 9\n')
    plan=m.import_plan(project,env,record,lean)
    assert len(m.checked_artifacts(plan,[project],lean,volume))==2


def test_compiler_or_stdlib_change_invalidates_receipts(tmp_path):
    project,env,record,lean,volume=fixture(tmp_path)
    m.build_imports(project,env,record,lean,volume,time.monotonic()+10)
    (lean.parent.parent/'lib/lean/Init.olean').write_text('different stdlib')
    assert len(m.checked_artifacts(m.import_plan(project,env,record,lean),[project],lean,volume))==2


def test_dependency_manifest_change_invalidates_receipts(tmp_path):
    project,env,record,lean,volume=fixture(tmp_path)
    m.build_imports(project,env,record,lean,volume,time.monotonic()+10)
    (project/'lake-manifest.json').write_text('{"version":"1.1.0","packages":[],"name":"changed"}')
    assert len(m.checked_artifacts(m.import_plan(project,env,record,lean),[project],lean,volume))==2


def test_preparer_bytes_invalidate_compilation_receipts(tmp_path,monkeypatch):
    project,env,record,lean,volume=fixture(tmp_path)
    preparer=tmp_path/'preparer.py';preparer.write_bytes(TOOL.read_bytes())
    monkeypatch.setattr(m,'__file__',str(preparer))
    m.build_imports(project,env,record,lean,volume,time.monotonic()+10)
    preparer.write_bytes(preparer.read_bytes()+b'\n# changed compiler policy\n')
    assert len(m.checked_artifacts(m.import_plan(project,env,record,lean),[project],lean,volume))==2


def test_same_package_import_can_serve_another_exact_target(tmp_path):
    project,env,record,lean,volume=fixture(tmp_path)
    (project/'Other.lean').write_text('import Base\ntheorem other : True := by trivial\n')
    m.build_imports(project,env,record,lean,volume,time.monotonic()+10)
    second=m.build_imports(project,env,{'file_path':'Other.lean'},lean,volume,time.monotonic()+10)
    assert second['compile_invocations']==0 and second['reused_checked_artifacts']==1


def test_resume_write_path_cannot_escape_capped_volume(tmp_path):
    volume=tmp_path/'volume';volume.mkdir();outside=tmp_path/'outside';outside.mkdir()
    (volume/'link').symlink_to(outside)
    with pytest.raises(ValueError,match='symlink'):m.contained(volume/'link/new.olean',volume)
    with pytest.raises(ValueError,match='outside'):m.contained(outside/'x',volume)


def test_deadline_prevents_any_native_launch(tmp_path):
    project,env,record,lean,volume=fixture(tmp_path)
    with pytest.raises(ValueError,match='deadline'):m.build_imports(project,env,record,lean,volume,time.monotonic()-1)
    assert not list((volume/'logs').iterdir())


def test_owned_directory_rejects_symlink(tmp_path):
    target=tmp_path/'actual';target.mkdir();link=tmp_path/'link';link.symlink_to(target)
    with pytest.raises(ValueError,match='directory required'):m.owned_directory(link)


@pytest.mark.parametrize('cap',[True,0,9*1024**3])
def test_storage_cap_rejected_before_bootstrap(tmp_path,cap):
    with pytest.raises(ValueError,match='8 GiB'):m.bootstrap_volume(tmp_path,cap)


def test_command_timeout_is_recorded_and_owned_child_reaped(tmp_path):
    volume=tmp_path
    with pytest.raises(RuntimeError,match='124'):
        m.command(['/usr/bin/python3','-c','import time;time.sleep(30)'],tmp_path,volume,timeout=.05,label='slow')
    receipt=json.loads(next((volume/'logs').glob('*.json')).read_text())
    assert receipt['timed_out'] is True and receipt['exit_code']==124
    with pytest.raises(ProcessLookupError):os.kill(receipt['pid'],0)
    assert receipt['completion_authority'] is False


def test_no_ambient_secret_environment_is_passed(tmp_path,monkeypatch):
    monkeypatch.setenv('GROK_API_KEY','never-print-this')
    output=m.command(['/usr/bin/python3','-c','import os; print("GROK_API_KEY" in os.environ)'],tmp_path,tmp_path)
    assert output=='False'


def test_report_cannot_self_authorize_or_skip_currentness(tmp_path):
    path=tmp_path/'result.json';path.write_text(json.dumps({'schema':m.SCHEMA,'producer_sha256':'0'*64}))
    with pytest.raises(ValueError,match='producer changed'):m.validate(path)


def test_cli_rejects_unknown_args_without_provision():
    assert subprocess.run(['/usr/bin/python3',str(TOOL),'--unsafe-fetch'],capture_output=True).returncode==2

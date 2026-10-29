"""Closed source inventory and exact imports for the compiled coupled backend.

Loading an implementation never registers it. The registered execution loader
must independently approve this inventory before either native entry point runs.
"""
from contextlib import contextmanager
import hashlib
import importlib.abc
import importlib.util
import json
from pathlib import Path
import sys
import threading

HERE = Path(__file__).resolve().parent
LOCAL = (
    'lean_refactor_compiled_registry_v1.py', 'lean_refactor_compiled_sources_v1.json',
    'lean_refactor_compiled_lineage_v1.py', 'lean_refactor_compiled_admission_v1.py',
    'lean_refactor_compiled_inputs_v1.py', 'lean_refactor_compiled_coupled_v1.py',
    'validate_lean_refactor_compiled_coupled_v1.py',
    'lean_refactor_compiled_replay_v1.py', 'validate_lean_refactor_compiled_replay_v1.py',
)
TESTS = ('tests/test_lean_refactor_compiled_canonical_v1.py',)
INVENTORY = 'lean_refactor_compiled_sources_v1.json'
_LOCK = threading.RLock()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'ordinary exact source required: ' + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory():
    path = HERE / INVENTORY
    digest(path)
    value = json.loads(path.read_text())
    require(value['schema'] == 'jevops.lean-refactor.compiled-source-inventory.v1'
        and set(value) == {'schema', 'retained', 'imports', 'baseline_profile_sha256',
                          'baseline_profile', 'extension_changes'}, 'closed inventory schema required')
    require(set(value['imports'].values()) <= set(value['retained']), 'unbound retained import')
    for name in value['retained']:
        path = Path(name)
        require((path.is_absolute() or '..' not in path.parts) and path.suffix in
            ('.py', '.json', '.lean', '.xml', '.c', '.so', '.txt', '.md', '.jsonl', ''),
            'unreviewed source/evidence path')
    return value


def sources(root):
    """Nonrecursive inventory; no freeze, imports, native child, or profile read."""
    value = inventory()
    found = {}
    for name, expected in value['retained'].items():
        actual = digest(root / name)
        require(actual == expected, 'retained active source/evidence changed: ' + name)
        found[name] = actual
    for name in LOCAL:
        found['tools/' + name] = digest(HERE / name)
    for name in TESTS:
        found[name] = digest(HERE.parent / name)
    return found


def peer(filename):
    require(filename in LOCAL and filename.endswith('.py'), 'unreviewed canonical peer')
    path = HERE / filename
    require(path.resolve().parent == HERE and not path.is_symlink(), 'canonical peer escape')
    sha = digest(path)
    key = '_jlr_compiled_v1_' + hashlib.sha256(str(path).encode()).hexdigest() + '_' + sha
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, path)
        value = importlib.util.module_from_spec(spec)
        sys.modules[key] = value
        try:
            spec.loader.exec_module(value)
        except BaseException:
            sys.modules.pop(key, None)
            raise
    return sys.modules[key]


class _ExactImports(importlib.abc.MetaPathFinder):
    def __init__(self, root, value):
        self.root, self.value = root, value

    def find_spec(self, fullname, path=None, target=None):
        name = self.value['imports'].get(fullname)
        if name is None:
            return None
        source = self.root / name
        require(digest(source) == self.value['retained'][name], 'exact retained import drift: ' + fullname)
        return importlib.util.spec_from_file_location(fullname, source)


@contextmanager
def retained_imports(root):
    """Short-name collisions cannot select a different retained implementation.

    Restore all affected import state, including after a signal or failed import.
    The two custody worker threads read bytes only; they do not import modules.
    """
    with _LOCK:
        value = inventory()
        old_path, old_meta = sys.path[:], sys.meta_path[:]
        old = {name: sys.modules.pop(name) for name in value['imports'] if name in sys.modules}
        finder = _ExactImports(root, value)
        sys.meta_path.insert(0, finder)
        sys.path[:0] = [str(root), str(root / 'tools')]
        try:
            yield
        finally:
            for name in value['imports']:
                sys.modules.pop(name, None)
            sys.modules.update(old)
            sys.path[:], sys.meta_path[:] = old_path, old_meta


def runtime(root):
    with retained_imports(root):
        return __import__('snapshot_runtime_v3')


def registered(root, c):
    profile = c.load(root)[0]
    active = sources(root)
    require(all(profile['source_sha256'].get(name) == sha for name, sha in active.items()),
            'compiled backend has not passed closed registration')
    return profile, active

from pathlib import Path
import importlib.util
_spec = importlib.util.spec_from_file_location('_canonical_compiled_registry',
    Path(__file__).with_name('lean_refactor_compiled_registry_v1.py'))
registry = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(registry)
import lean_refactor_execution_v2 as c
ROOT = c.ROOT
runtime = registry.runtime(ROOT)
from contextlib import contextmanager
import math
import signal
import time
from types import SimpleNamespace
legacy = runtime.m.stage.base
qualifier, compiled, arena = legacy.qualifier, legacy.compiled, legacy.arena
PINS, ORDERS, AUTH, POLICY = legacy.PINS, legacy.ORDERS, legacy.AUTH, legacy.POLICY
ORIGINAL = ROOT / 'data/lean_refactor_arena_20261024/execution-v2/maintenance-0412'
lineage = registry.peer('lean_refactor_compiled_lineage_v1.py')
protected = SimpleNamespace(lineage=lineage, **{name:getattr(legacy.protected,name)
    for name in ('edit_check','native_sample','validate_archive','import_custody')})
def inputs(tag):
    c.require(tag in PINS, 'closed original coupled pin required')
    if tag in qualifier.PINS:
        return qualifier.inputs(tag)
    record, bindings = qualifier.frontier.target_inputs(ROOT)
    pin = qualifier.VersionPin(tag, PINS[tag])
    return qualifier.prior_workflow.per_pin_record(record, pin), pin, bindings[pin], ROOT / c.RUNTIME / 'native-pins-v1/work'


def capture_input(tag, record, pin, binding, identity, drafts):
    """Read independently checked native parser packets, never a proof cache."""
    if tag == 'v4.29.1':
        directory = qualifier.PRIOR / 'capture-closure-v4/capture-v1'
        observation = c.read(directory / 'observation.json')
        context = observation['validation']['context']
        raw = directory / 'child-2'
        prepared_path = qualifier.PRIOR / 'capture-closure-v4/prepared.json'
        source_key = 'source_sha256'
    else:
        directory = ORIGINAL / 'capture-pins' / ('qualify-' + tag + '-v1')
        observation = c.read(directory / 'observation.json')
        context = observation['validation']['context']
        raw = directory / 'child-8'
        prepared_path = ORIGINAL / 'capture-pins/prepared.json'
        source_key = 'sources'
    preparation = c.read(prepared_path)
    c.require(observation['prepared_sha256'] == c.sha(prepared_path)
              and all(c.sha(ROOT / name) == digest for name, digest in preparation[source_key].items()),
              'original parser qualification producer/validator/Lean sources changed')
    c.require(observation['status'] == 'OBSERVED' and observation['owned_hold_released'] is True
              and observation['production_sources_unchanged'] is True
              and observation['historical_evidence_unchanged'] is True
              and context['pin'] == pin.to_dict() and context['import_identity'] == identity
              and context['source_sha256'] == arena.source_hash(record['src'])
              and context['statement_sha256'] == arena.source_hash(record['statement'])
              and context['prefix_sha256'] == arena.source_hash(binding.prefix)
              and context['scientific_sources'] == preparation['scientific_sources'],
              'current genuine exact-pin parser qualification is required')
    protected.lineage.validate(ROOT, tag, prepared_path, observation, context)
    payload = c.read(raw / 'input.json')
    out, err, execution = (raw / 'stdout').read_bytes(), (raw / 'stderr').read_bytes(), c.read(raw / 'execution.json')
    qualifier.validator.raw_binding(payload, out, err, execution)
    from validate_compiled_capture import transport
    stage = transport(payload, out, err, execution, source=record['src'], prefix=binding.prefix,
                      target=record['name'], pin=pin, environment=arena.content_hash(context))
    from jevops import proof_state
    proof_state.validate_trace(stage['report'], source=record['src'], environment=arena.content_hash(context),
                               node_budget=20000, event_budget=256)
    anchors = qualifier.validator.edit_anchors(record, drafts, stage['report']['events'])
    return {'path': str((directory / 'observation.json').relative_to(ROOT)),
            'sha256': c.sha(directory / 'observation.json'), 'import_identity': identity,
            'raw_sha256': {name: c.sha(raw / name) for name in ('input.json', 'stdout', 'stderr', 'execution.json')},
            'coupled_edit_anchors': anchors, 'whole_source_acceptance': False}


@contextmanager
def bounded(seconds, started=None):
    c.require(seconds in (360, 780) and signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0),
              'explicit unchanged foreground phase timer required')
    started = time.monotonic() if started is None else started
    c.require(type(started) in (int, float) and math.isfinite(started)
              and 0 <= time.monotonic() - started <= seconds - 1,
              'retain actual original operational phase clock')
    deadline = started + seconds
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGALRM, signal.SIGTERM, signal.SIGINT)}
    def stop(sig, frame):
        raise TimeoutError('compiled coupled foreground interruption ' + str(sig))
    for sig in handlers:
        signal.signal(sig, stop)
    signal.setitimer(signal.ITIMER_REAL, deadline - time.monotonic())
    try:
        yield deadline
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


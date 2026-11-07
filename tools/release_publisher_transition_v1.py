#!/usr/bin/env python3
"""Prepare an additive publisher transition after an explicitly reviewed source port.

No unit, existing source, old configuration, preservation map, profile or task is
modified. The generated bounded consumer reuses the unchanged publisher. Install
its rendered service only as a separately reviewed integration transaction step.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import time
import types
import xml.etree.ElementTree as ET

ROOT = Path('/home/barberb/lift_coding/JevOps')
CONSUMER_SHA = '653e840a78fe553433bc9695a01e625a3c2c03a6ffafe9f97318196308eeec38'
PROFILE = 'config/lean_refactor_arena_20261024_execution_v2.json'
BASE_SHA = '56aba2cffd9a2c5ec3a71873883556f691b316ff17398cfc9973b94087d7f6cd'
PATCHES = frozenset({'tools/lean_refactor_execution_v2.py', 'tools/run_lean_refactor_stage_v2.py',
    'tools/check_lean_refactor_stage_v2.py', 'tools/lean_refactor_compiled_lineage_v1.py',
    'tests/test_lean_refactor_source_refresh.py'})
ALLOWED = PATCHES | {PROFILE}
ADDITIONS = frozenset({'tools/lean_refactor_release_registry_v2.py', 'tools/lean_refactor_release_sources_v2.json',
    'tools/lean_refactor_release_inventory_v2.py', 'tools/validate_lean_refactor_release_inventory_v2.py',
    'tests/test_lean_refactor_release_canonical_v2.py'})
PORT = 'data/lean_refactor_arena_20261024/execution-v2/maintenance-20261030T0355Z-release-adapter'
OUTPUT_PREFIX = 'data/lean_refactor_arena_20261024/official-release-publisher-transitions'
ORIGINAL_EVENT = '9305e80c17bd463c9fb8323b57e010ea'
PYTHON = '/home/barberb/lift_coding/external/ipfs_datasets/.venv/bin/python'
CANDIDATE_SHA = '582d4a7368561a2c5ba9cac9f7dbc106a5694e85062490376ee672cc370902da'
REVIEW_SHA = '9e0817e282c1c3588a918d682b314631d39c6b0b372ccd949997cd04c77a9554'
ORIGINAL_JUNIT = {'path':'data/lean_refactor_arena_20261024/execution-v2/maintenance-1838-fixture/transaction/canonical-focused.xml',
    'sha256':'81dd5fec2f94a29018df5e7bd49e1ad81cc1c7b7024cfccb6ac7662bd8da2693'}
MIN_ORIGINAL_CASES = 334
MIN_NEW_CASES = 75


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()


def consumer(root):
    path = root/'tools/publish_official_release_watch.py'
    require(sha(path.read_bytes()) == CONSUMER_SHA, 'Unchanged reviewed original consumer required')
    name = '_unchanged_official_release_consumer'
    raw = path.read_bytes()
    require(sha(raw) == CONSUMER_SHA, 'Original consumer changed before verified-byte import')
    module = types.ModuleType(name); module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def object_value(raw):
    def unique(rows):
        value = {}
        for key, item in rows:
            require(key not in value, 'Duplicate transition JSON key')
            value[key] = item
        return value
    value = json.loads(raw, object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite transition JSON')))
    require(type(value) is dict, 'Transition object required')
    return value


def case_ids(raw, c):
    c.passing_junit(raw)
    cases = list(ET.fromstring(raw).iter('testcase'))
    names = [(row.get('classname', '').rsplit('.', 1)[-1], row.get('name', '')) for row in cases]
    require(all(module and name for module,name in names) and len(set(names)) == len(names),
        'Unique genuine software case identities required')
    return set(names)


def approval(root, ref, c):
    _, raw = c.referenced(root, ref, 262144)
    value = object_value(raw)
    keys = {'schema', 'candidate', 'review', 'changes', 'profile_after', 'transaction',
        'activation', 'materialization', 'test_receipt', 'canonical_junit', 'transition_junit',
        'transition_qualification', 'original_delivery'}
    require(set(value) == keys and value['schema'] == 'jevops.reviewed-release-publisher-transition.v1',
        'Exact explicitly approved transition manifest required')
    candidate_path, candidate_raw = c.referenced(root, value['candidate'], 1048576)
    require(candidate_path == root/PORT/'candidate.json', 'Only the reviewed0355 private source port is supported')
    require(value['candidate']['sha256'] == CANDIDATE_SHA, 'Only the actually sealed reviewed0355 candidate is supported')
    review_path, review_raw = c.referenced(root, value['review'], 1048576)
    require(review_path == root/PORT/'review.py', 'Exact independent port reviewer required')
    require(value['review']['sha256'] == REVIEW_SHA, 'Exact actual independent port review bytes required')
    candidate = object_value(candidate_raw)
    require(candidate['schema'] == 'jevops.lean-refactor.release-port-private-candidate.v2'
        and candidate['baseline_profile_sha256'] == BASE_SHA
        and candidate['integration_prepared'] is False and candidate['canonical_changed'] is False,
        'Genuine retained private candidate required')
    require(candidate.get('source_sha256', {}).get(str(review_path.relative_to(root))) == sha(review_raw),
        'Candidate must bind its independent reviewer')
    require(set(candidate['destinations']) == PATCHES | ADDITIONS, 'Exact independently reviewed ten-path source port required')
    for name, row in candidate['destinations'].items():
        c.referenced(root, {'path':row['candidate'], 'sha256':row['sha256']}, 1048576)
        c.referenced(root, {'path':name, 'sha256':row['sha256']}, 1048576)
    changes = value['changes']
    require(type(changes) is list and len(changes) == 6 and all(type(row) is dict for row in changes)
        and {row.get('path') for row in changes} == ALLOWED, 'Only the closed five-path source port plus profile may change')
    for row in changes:
        require(set(row) == {'path', 'before_sha256', 'after_sha256', 'before_image'}, 'Exact before/after source authority required')
        _, before = c.referenced(root, row['before_image'], 1048576)
        require(sha(before) == row['before_sha256'] != row['after_sha256'], 'Original before-image custody required')
        _, after = c.referenced(root, {'path':row['path'], 'sha256':row['after_sha256']}, 1048576)
        if row['path'] in PATCHES:
            retained = candidate['destinations'][row['path']]
            require(retained['before_sha256'] == row['before_sha256'] and retained['sha256'] == row['after_sha256'],
                'After bytes must match exact independently reviewed candidate')
            c.referenced(root, {'path':retained['candidate'], 'sha256':retained['sha256']}, 1048576)
    bypath = {row['path']: row for row in changes}
    require(bypath[PROFILE]['before_sha256'] == BASE_SHA and value['profile_after'] ==
        {'path':PROFILE, 'sha256':bypath[PROFILE]['after_sha256']}, 'Exact accepted profile transition required')
    _, baseline_raw = c.referenced(root, bypath[PROFILE]['before_image'], 1048576)
    baseline = object_value(baseline_raw)
    _, profile_raw = c.referenced(root, value['profile_after'], 1048576)
    profile = object_value(profile_raw)
    require(len(baseline['source_sha256']) == 253 and set(baseline['source_sha256']) <= set(profile['source_sha256']),
        'All original253 source identities must remain represented')
    require({name for name, digest in baseline['source_sha256'].items()
        if profile['source_sha256'][name] != digest} == PATCHES, 'Unreviewed original scientific source changed')
    require(all(profile['source_sha256'][name] == bypath[name]['after_sha256'] for name in PATCHES),
        'Accepted profile differs from source-reviewed port')
    inventory = object_value(c.owned(root/'tools/lean_refactor_release_sources_v2.json', 1048576)[0])
    require(inventory.get('schema') == 'jevops.lean-refactor.release-canonical-sources.v2'
        and inventory.get('baseline', {}).get('sha256') == BASE_SHA,
        'Reviewed additive release source inventory required')
    require(set(profile['source_sha256']) == set(baseline['source_sha256']) | set(inventory['retained']) | ADDITIONS,
        'Accepted profile includes unreviewed extra source identities')
    for name, digest in inventory['retained'].items():
        require(profile['source_sha256'].get(name) == digest, 'Retained release source not bound by accepted profile')
        c.referenced(root, {'path':name, 'sha256':digest}, 8*1024*1024)
    require(all(profile['source_sha256'].get(name) == candidate['destinations'][name]['sha256'] for name in ADDITIONS),
        'Accepted additive source bytes differ from reviewed candidate')
    for key in ('schema', 'board', 'contracts', 'goals_sha256', 'base_profile_sha256',
                'continuation_plan', 'phase_budget', 'scientific_route'):
        require(profile[key] == baseline[key], 'Original contract/goal/budget semantics changed: '+key)
    history = 'data/lean_refactor_arena_20261024/execution-v2/history/'+Path(PROFILE).name+'.'+BASE_SHA
    require(profile['previous_profiles'].get(BASE_SHA) == history, 'Historical profile lineage must remain exact')
    require(all(profile['previous_profiles'].get(key) == old for key, old in baseline.get('previous_profiles', {}).items()),
        'Prior historical profile mappings must remain unchanged')
    c.referenced(root, {'path':history, 'sha256':BASE_SHA}, 1048576)
    records = {key: object_value(c.referenced(root, value[key], 4*1024*1024)[1]) for key in
        ('transaction', 'activation', 'materialization', 'test_receipt')}
    tx, active, material, tested = (records[key] for key in ('transaction', 'activation', 'materialization', 'test_receipt'))
    require(tx.get('activated') is True and tx.get('owned_hold_released') is True
        and tx.get('scientific_stage_accepted') is False
        and tx.get('profile_sha256') == value['profile_after']['sha256']
        and tx.get('activation_sha256') == value['activation']['sha256']
        and tx.get('materialization_sha256') == value['materialization']['sha256'],
        'Actual released successful integration receipt must bind all acceptance records')
    for item in (active, material):
        require(item.get('profile_sha256') == value['profile_after']['sha256']
            and item.get('quiescent_maintenance_review') is True
            and item.get('preflight', {}).get('valid') is True,
            'Full quiescent protected acceptance and matching profile required')
    require(material.get('previous_profile_sha256') == BASE_SHA
        and material.get('bootstrap_restarted') is False, 'Original accepted owner must be retained')
    require(tested.get('passed') is True and tested.get('source_sha256') == profile['source_sha256']
        and tested.get('junit_path') == value['canonical_junit']['path']
        and tested.get('junit_sha256') == value['canonical_junit']['sha256'],
        'Actual canonical JUnit must bind accepted complete source population')
    for key in ('canonical_junit', 'transition_junit'):
        c.passing_junit(c.referenced(root, value[key], 8*1024*1024)[1])
    original_cases = case_ids(c.referenced(root, ORIGINAL_JUNIT, 8*1024*1024)[1], c)
    new_row = next(row for row in candidate['test_evidence'] if row['path'] == PORT+'/focused-v4.xml')
    new_ref = {'path':new_row['path'], 'sha256':new_row['sha256']}
    new_cases = case_ids(c.referenced(root, new_ref, 8*1024*1024)[1], c)
    actual_cases = case_ids(c.referenced(root, value['canonical_junit'], 8*1024*1024)[1], c)
    require(len(original_cases) >= MIN_ORIGINAL_CASES and len(new_cases) >= MIN_NEW_CASES
        and original_cases | new_cases <= actual_cases,
        'Full original334 and reviewed new75 canonical case identities must actually pass')
    qualified = object_value(c.referenced(root, value['transition_qualification'], 65536)[1])
    require(set(qualified) == {'schema', 'runtime_source', 'test_source', 'junit'}
        and qualified['schema'] == 'jevops.release-publisher-transition-qualification.v1'
        and qualified['junit'] == value['transition_junit'], 'Actual transition qualification source/test/XML closure required')
    runtime_raw = c.referenced(root, qualified['runtime_source'], 1048576)[1]
    require(runtime_raw == Path(__file__).read_bytes(), 'Passing transition tests qualify different runtime source')
    c.referenced(root, qualified['test_source'], 1048576)
    delivery = value['original_delivery']
    require(type(delivery) is dict and set(delivery) == {'event', 'marker', 'request', 'receipt'},
        'Exact original event delivery custody required')
    for row in delivery.values():
        c.referenced(root, row, 262144)
    require(delivery['event']['path'] == 'data/lean_refactor_arena_20261024/official-release-watch/outbox/events/'+ORIGINAL_EVENT+'.json'
        and delivery['event']['sha256'] == '0858f83af110da0a91447cb5b110292bfc161d5b07853d904e0e9808a8b924f8',
        'Only the actual original delivered event can bridge epochs')
    return value


def context(root, ref):
    c = consumer(root)
    old = c.load_contract(root)
    approved = approval(root, ref, c)
    changes = {row['path']:row for row in approved['changes']}
    require(len({row['path'] for row in old['preservation_rows']}) == 266, 'Duplicate baseline preservation member')
    updated = []
    for row in old['preservation_rows']:
        expected = changes.get(row['path'])
        if expected:
            require(row['sha256'] == expected['before_sha256'], 'Approved before SHA differs from original preservation')
            updated.append({'path':row['path'], 'sha256':expected['after_sha256']})
        else:
            path = Path(row['path']); path = path if path.is_absolute() else root/path
            require(sha(c.owned(path, 8*1024*1024)[0]) == row['sha256'], 'Unapproved preserved input changed: '+row['path'])
            updated.append(dict(row))
    require({row['path'] for row, previous in zip(updated, old['preservation_rows']) if row != previous} == ALLOWED,
        'Every approved change must belong to the original preservation population')
    preservation = {'schema':'jevops.repair-publication-preservation.v1', 'files':updated}
    return c, old, approved, preservation


def prepare(root, ref, relative):
    """Write new immutable plan artifacts only; caller separately reviews/installs."""
    c, old, approved, preservation = context(root, ref)
    require(relative.startswith(OUTPUT_PREFIX+'/') and len(Path(relative).parts) == len(Path(OUTPUT_PREFIX).parts)+1,
        'A distinct versioned transition output directory is required')
    directory = c.path_in(root, relative)
    def put(name, raw):
        path = directory/name
        c.same_or_new(path, raw)
        return {'path':str(path.relative_to(root)), 'sha256':sha(raw)}
    helper = put('runtime.py', Path(__file__).read_bytes())
    preserved = put('preservation.json', canonical(preservation))
    tests = list(old['preflight']['test_evidence'])
    if approved['transition_junit'] not in tests:
        tests.append(approved['transition_junit'])
    preflight = {**old['preflight'], 'preservation':preserved, 'test_evidence':tests}
    preflight_ref = put('preflight.json', canonical(preflight))
    config_ref = put('config.json', canonical({**old['config'], 'preflight':preflight_ref}))
    wrapper = wrapper_bytes(root, helper, ref, relative)
    wrapper_ref = put('consumer.py', wrapper)
    manifest = {'schema':'jevops.release-publisher-transition-plan.v1', 'approval':ref,
        'runtime':helper, 'wrapper':wrapper_ref, 'config':config_ref, 'preservation':preserved,
        'preflight':preflight_ref, 'original_config':old['config_ref'], 'original_preflight':old['preflight_ref'],
        'proposed_exec_start':[PYTHON, '-B', str(root/wrapper_ref['path']), '--approval-sha256', ref['sha256']],
        'installed':False, 'services_changed':False, **c.AUTH}
    put('plan.json', canonical(manifest))
    return manifest


def wrapper_bytes(root, helper, ref, relative):
    return ('''#!/usr/bin/env python3
import argparse,hashlib,sys,types
from pathlib import Path
ROOT=Path(%r)
HELPER=%r
require_sha=%r
APPROVAL=%r
parser=argparse.ArgumentParser()
parser.add_argument('--approval-sha256',required=True)
args=parser.parse_args()
if args.approval_sha256!=APPROVAL['sha256']:raise SystemExit('Explicit approval pin differs')
raw=(ROOT/HELPER).read_bytes()
if hashlib.sha256(raw).hexdigest()!=require_sha:raise SystemExit('Reviewed transition runtime changed')
module=types.ModuleType('_approved_release_publisher_transition');module.__file__=str(ROOT/HELPER)
sys.modules[module.__name__]=module
exec(compile(raw,module.__file__,'exec'),module.__dict__)
raise SystemExit(module.run(ROOT,APPROVAL,%r))
''' % (str(root), helper['path'], helper['sha256'], ref, relative)).encode()


def load_transition(root, ref, relative):
    c, old, approved, expected = context(root, ref)
    path = c.path_in(root, relative+'/plan.json')
    plan = object_value(c.owned(path, 65536)[0])
    require(set(plan) == {'schema', 'approval', 'runtime', 'wrapper', 'config', 'preservation', 'preflight',
        'original_config', 'original_preflight', 'proposed_exec_start', 'installed', 'services_changed', *c.AUTH}
        and plan['schema'] == 'jevops.release-publisher-transition-plan.v1'
        and plan['installed'] is False and plan['services_changed'] is False
        and all(type(plan[key]) is type(value) and plan[key] == value for key,value in c.AUTH.items()),
        'Exact immutable transition plan required')
    require(plan.get('approval') == ref and plan.get('original_config') == old['config_ref']
        and plan.get('original_preflight') == old['preflight_ref'], 'Transition plan authority differs')
    require(plan['proposed_exec_start'] == [PYTHON, '-B', str(root/relative/'consumer.py'), '--approval-sha256', ref['sha256']],
        'Reviewed proposed service command must visibly bind exact approval SHA')
    require(c.referenced(root, plan['preservation'], 262144)[1] == canonical(expected), 'New preservation differs from approved exact transition')
    for key, name in [('runtime','runtime.py'),('wrapper','consumer.py'),('config','config.json'),
                      ('preservation','preservation.json'),('preflight','preflight.json')]:
        require(plan[key]['path'] == relative+'/'+name, 'Transition output path differs')
    require(c.referenced(root, plan['wrapper'], 65536)[1] == wrapper_bytes(root, plan['runtime'], ref, relative),
        'Transition wrapper differs from reviewed deterministic template')
    tests = list(old['preflight']['test_evidence'])
    if approved['transition_junit'] not in tests: tests.append(approved['transition_junit'])
    expected_preflight = {**old['preflight'], 'preservation':plan['preservation'], 'test_evidence':tests}
    require(c.referenced(root, plan['preflight'], 262144)[1] == canonical(expected_preflight), 'Transition preflight differs from exact approved closure')
    require(c.referenced(root, plan['config'], 65536)[1] == canonical({**old['config'], 'preflight':plan['preflight']}),
        'Transition configuration differs from deterministic approved template')
    current = c.load_contract(root, config_relative=plan['config']['path'], approved_preservation=plan['preservation'])
    require(current['config_ref'] == plan['config'] and current['preflight_ref'] == plan['preflight'], 'Transition configuration changed')
    extra = [plan['runtime'], plan['wrapper'], ref, *[approved[key] for key in
        ('candidate', 'review', 'transaction', 'activation', 'materialization', 'test_receipt', 'canonical_junit',
         'transition_junit', 'transition_qualification')]]
    extra += [row['before_image'] for row in approved['changes']]
    extra += list(approved['original_delivery'].values())
    qualified = object_value(c.referenced(root, approved['transition_qualification'], 65536)[1])
    extra += [qualified['runtime_source'], qualified['test_source']]
    extra.append(ORIGINAL_JUNIT)
    candidate = object_value(c.referenced(root, approved['candidate'], 1048576)[1])
    extra += [{'path':row['path'], 'sha256':row['sha256']} for row in candidate['test_evidence']]
    for row in extra:
        c.referenced(root, row, 8*1024*1024)
    require(plan['runtime']['sha256'] == sha(Path(__file__).read_bytes()), 'Reviewed runtime differs')
    # The strict on-disk four-source contract is unchanged. This reviewed
    # additive runtime/source/acceptance closure is also checked under the
    # existing publisher fence before any new event publication.
    current = dict(current)
    current['preflight'] = {**current['preflight'], 'sources':[*current['preflight']['sources'], *extra]}
    return c, old, current, plan


def original_delivery(root, old, selected, c, approved):
    """Authenticate an old exact receipt across a reviewed config transition."""
    event = selected['event']
    if event['event_id'] != ORIGINAL_EVENT:
        return None
    custody = approved['original_delivery']
    require(custody['event'] == selected['event_ref'], 'Original approved event differs')
    marker = old['state']/'outbox/delivered'/(event['event_id']+'.json')
    require(custody['marker']['path'] == str(marker.relative_to(root)), 'Original marker path differs')
    c.referenced(root, custody['marker'], 65536)
    value = object_value(c.owned(marker, 65536)[0])
    require(set(value) == {'schema', 'event', 'fingerprint', 'receipt', *c.AUTH}
        and value['schema'] == 'jevops.official-release-delivered.v1'
        and value['event'] == selected['event_ref'] and value['fingerprint'] == event['fingerprint']
        and all(type(value[k]) is type(v) and value[k] == v for k,v in c.AUTH.items()), 'Invalid original delivery marker')
    directory = old['state']/'outbox/requests'/event['event_id']/old['preflight_ref']['sha256']
    expected_receipt = str((directory/'publication-receipt.json').relative_to(root))
    require(value['receipt'] == custody['receipt'] and value['receipt']['path'] == expected_receipt,
        'Unknown delivery epoch; explicit review required')
    c.referenced(root, value['receipt'], 262144)
    require(custody['request']['path'] == str((directory/'request.json').relative_to(root)), 'Original request path differs')
    request = object_value(c.referenced(root, custody['request'], 65536)[1])
    require(request['preserve'] == old['preservation'] and request['receipt'] == expected_receipt,
        'Original request preservation/receipt differs')
    expected = [dict(kind='source', **row) for row in old['preflight']['sources']]
    expected += [dict(kind='test_evidence', **row) for row in old['preflight']['test_evidence']]
    expected += [dict(kind='source', **row) for row in [selected['pointer_ref'], selected['event_ref'], old['config_ref'], old['preflight_ref']]]
    expected += [dict(kind='source', path=row['path'], sha256=row['sha256']) for row in event['observation'].get('evidence', [])]
    require(request['verify'] == expected, 'Original publication verification closure differs')
    for key, filename in [('handoff', 'handoff.json'), ('append', 'append.txt')]:
        require(request[key]['path'] == str((directory/filename).relative_to(root)), 'Original publication output path differs')
        c.referenced(root, request[key], 262144)
    require(c.receipt_verified(root, request) == value['receipt'], 'Original exact publication receipt differs')
    return value['receipt']


def consume_transition(root, ref, relative, *, timeout=1800, **kwargs):
    c, old, current, plan = load_transition(root, ref, relative)
    selected = c.read_event(current)
    approved = approval(root, ref, c)
    receipt = original_delivery(root, old, selected, c, approved)
    if receipt is not None:
        return dict(schema='jevops.official-release-outbox-delivery-status.v1', delivered=True, pending=False,
            reason='ALREADY_DELIVERED_ORIGINAL_EPOCH', event=selected['event_ref'], receipt=receipt, **c.AUTH), 0
    def load(ignored):
        return load_transition(root, ref, relative)[2]
    return c.consume(root, current['state'], timeout=timeout, load=load, **kwargs)


def run(root, ref, relative):
    previous = {}
    def interrupt(_sig, _frame):
        raise InterruptedError('Release publisher transition interrupted')
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous[sig] = signal.signal(sig, interrupt)
        result, code = consume_transition(root, ref, relative)
        print(json.dumps(result, sort_keys=True)); return code
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo-root', type=Path, required=True)
    p.add_argument('--approval', required=True); p.add_argument('--approval-sha256', required=True)
    p.add_argument('--output-dir', required=True)
    a = p.parse_args(argv); root = a.repo_root.resolve(strict=True)
    require(root == ROOT, 'Only the reviewed repository scope is supported')
    print(json.dumps(prepare(root, {'path':a.approval, 'sha256':a.approval_sha256}, a.output_dir), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

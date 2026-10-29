"""Prospective registration lineage; historical native identities remain read-only."""
from pathlib import Path
import importlib.util
_spec = importlib.util.spec_from_file_location('_compiled_lineage_registry',
    Path(__file__).with_name('lean_refactor_compiled_registry_v1.py'))
registry = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(registry)
import lean_refactor_execution_v2 as c
from jevops.arena import content_hash

REBASE = 'data/lean_refactor_arena_20261024/execution-v2/maintenance-0658/coupled-archive-v3/rebase.json'
ORIGINAL = 'c939a7dacef30db8449a0d681619713b7d1fe939c576a9f5d51b8538afc0fb81'


def historical(root, name, sha):
    """Authenticate a genuine before-image; never rewrite a historical input."""
    path = root / name
    if path.is_file() and not path.is_symlink() and c.sha(path) == sha:
        return path
    path = root / c.RUNTIME / 'history' / (Path(name).name + '.' + sha)
    c.require(c.sha(path) == sha, 'historical source custody missing: ' + name)
    return path


def retain_heads(root):
    """Preserve genuine mutable heads before the normal runner publishes anew."""
    value=c.read(root/REBASE)
    retained={}
    for name,sha in value['protected_current'].items():
        path=root/name
        if path.is_file() and not path.is_symlink() and c.sha(path)==sha:
            destination=root/c.RUNTIME/'history'/(Path(name).name+'.'+sha)
            raw=path.read_bytes()
            c.require(c.sha(path)==sha, 'historical head changed before archival')
            try:
                with destination.open('xb') as stream:stream.write(raw)
            except FileExistsError:
                pass
            c.require(c.sha(destination)==sha, 'existing historical destination differs')
            retained[name]=str(destination.relative_to(root))
        else:
            historical(root,name,sha)
    return retained


def prospective(before, after, inventory, local):
    """Closed integration surface; all original contracts and usage survive."""
    changed = {name for name in set(before['source_sha256']) | set(after['source_sha256'])
        if before['source_sha256'].get(name) != after['source_sha256'].get(name)}
    additions = set(inventory['retained']) | {'tools/' + name for name in local} | set(registry.TESTS)
    expected = set(inventory['extension_changes']) | (additions - set(before['source_sha256']))
    c.require(changed == expected, 'unreviewed canonical source addition/removal/change')
    for name in ('contracts', 'goals_sha256', 'base_profile_sha256', 'continuation_plan',
                 'phase_budget', 'scientific_route'):
        c.require(after[name] == before[name], 'original contract, goal, route or usage changed: ' + name)
    c.require(set(before['source_sha256']) <= set(after['source_sha256']), 'historical source removed')


def contract(root):
    inventory = registry.inventory()
    current, active = registry.registered(root, c)
    baseline_path = root / inventory['baseline_profile']
    sha = inventory['baseline_profile_sha256']
    c.require(c.sha(baseline_path) == sha and current['previous_profiles'].get(sha)
        == inventory['baseline_profile'], 'genuine registered baseline profile required')
    baseline = c.read(baseline_path)
    prospective(baseline, current, inventory, registry.LOCAL)
    for name in inventory['extension_changes']:
        historical(root, name, baseline['source_sha256'][name])
    rebase = c.read(root / REBASE)
    c.require(c.sha(root / REBASE) == inventory['retained'][REBASE]
        and rebase['schema'] == 'jevops.lean-refactor.private-capture-lineage-rebase.v1'
        and rebase['current_profile_sha256'] == sha
        and rebase['original_preparation_sha256'] == ORIGINAL
        and rebase['new_scientific_calls'] == 0
        and rebase['registration_authority'] is rebase['proof_authority'] is False,
        'unchanged retained capture lineage required')
    original = c.read(historical(root, rebase['original_preparation'], ORIGINAL))
    prior_sha = rebase['prior_profile_sha256']
    prior = c.read(historical(root, baseline['previous_profiles'][prior_sha], prior_sha))
    c.require(prior_sha == original['frozen']['profile_sha256']
        and prior['source_sha256'] == original['frozen']['scientific_sources'],
        'historical registered parser source identity differs')
    changes = {name: {'before': prior['source_sha256'].get(name),
                      'after': baseline['source_sha256'].get(name)}
        for name in sorted(set(prior['source_sha256']) | set(baseline['source_sha256']))
        if prior['source_sha256'].get(name) != baseline['source_sha256'].get(name)}
    c.require(changes == rebase['changes'], 'retained before/after lineage changed')
    for name in ('contracts', 'goals_sha256', 'continuation_plan', 'phase_budget'):
        c.require(prior[name] == baseline[name], 'retained parser contract/goal/usage changed')
    for values in (original['frozen']['source_sha256'], original['workflow_sources'],
                   rebase['retained_before_images'], rebase['protected_current'], rebase['spent_predecessor']):
        for name, digest in values.items():
            historical(root, name, digest)
    for head, row in rebase['pending_receipt_archives'].items():
        receipt = c.read(historical(root, row['path'], row['sha256']))
        c.require(receipt['archive_path'] == row['path']
            and receipt['task_id'] == Path(head).name.split('.')[0]
            and receipt['schema'] == 'jevops.lean-refactor.stage-run.v2',
            'genuine immutable pending receipt required')
    return rebase


def validate(root, tag, preparation_path, observation, context):
    rebase = contract(root)
    c.require(tag in rebase['captures'], 'closed original capture pin required')
    row = rebase['captures'][tag]
    c.require(preparation_path == root / row['preparation']
        and c.sha(preparation_path) == row['preparation_sha256'], 'original capture preparation changed')
    c.require(c.sha(root / row['observation']) == row['observation_sha256']
        and c.read(root / row['observation']) == observation, 'original capture observation changed')
    preparation = c.read(preparation_path)
    c.require(preparation['profile_sha256'] == rebase['prior_profile_sha256']
        and context == observation['validation']['context']
        and content_hash(context) == row['context_sha256'] == observation['validation']['context_sha256']
        and context['scientific_sources'] == preparation['scientific_sources'],
        'historical parser context may not be restamped')
    for name, digest in row['raw_sha256'].items():
        c.require(c.sha(root / name) == digest, 'original native capture packet changed')
    return {'retained_context_sha256': row['context_sha256'],
        'historical_registration_sha256': rebase['current_profile_sha256'],
        'current_registration_sha256': c.sha(root / c.PROFILE),
        'historical_context_rewritten': False, 'proof_authority': False}

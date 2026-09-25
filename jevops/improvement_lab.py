"""Python/autoencoder experiments with an immutable evaluator and no host imports.

Changes are deployed as managed Python source overlays for subsequent sandbox
workers. They never overwrite the user's checkout or alter the native verifier.
"""
from __future__ import annotations

import ast
from dataclasses import asdict
import json
import math
from pathlib import Path
import secrets
import tempfile
import time
import uuid

from .arena import content_hash, intake_error, reference_tokens
from .arena_trial import Candidate

EDITABLE = frozenset({'jevops/logic_refactor.py', 'jevops/folds.py', 'jevops/tactics.py',
    'jevops/proof_slicing.py', 'jevops/autoencoder.py', 'jevops/autoencoder_training.py', 'jevops/nca.py'})


def edit_sources(files, changes):
    if not isinstance(changes, list) or not 0 <= len(changes) <= 3:
        raise ValueError('bounded exact Python changes required')
    result = dict(files)
    for edit in changes:
        if not isinstance(edit, dict) or set(edit) != {'path', 'old', 'new'} or edit['path'] not in EDITABLE:
            raise ValueError('protected source file')
        old, new = edit['old'], edit['new']
        if (not isinstance(old, str) or not old or not isinstance(new, str) or old == new
                or len(old) + len(new) > 32768 or result[edit['path']].count(old) != 1):
            raise ValueError('one exact bounded nonempty replacement required')
        source = result[edit['path']].replace(old, new, 1)
        ast.parse(source, filename=edit['path'])
        result[edit['path']] = source
    return result


def random_canaries(tag, seed=None):
    seed = secrets.token_hex(8) if seed is None else seed
    rows = []
    for i in range(3):
        name, h = f'watch_canary_{seed}_{i}', f'h_{seed}_{i}'
        statement = f'theorem {name} (P : Prop) ({h} : P) : P'
        body = f'  have a : P := {h}\n  have b : P := a\n  exact b'
        if i == 1:
            statement = f'theorem {name} (P Q : Prop) ({h} : P) (q : Q) : P ∧ Q'
            body = f'  constructor\n  · exact {h}\n  · exact q'
        elif i == 2:
            statement = f'theorem {name} (x : Nat) : x = x'
            body = '  rfl'
        rows.append({'name': name, 'statement': statement, 'src': statement + ' := by\n' + body,
                     'version_info': [{tag: 'local-stdlib-smoke'}]})
    return rows


def measure_checkpoint(state, teachers, holdouts):
    """Frozen host implementation; never import the experimental Python here."""
    from . import autoencoder as ae
    from .autoencoder_training import LeanIRAutoencoder, coerce_training_example, loss_for_example
    if state is not None and len(json.dumps(state, allow_nan=False)) > 4_000_000:
        raise ValueError('checkpoint size bound')
    model = LeanIRAutoencoder.from_dict(state)
    if model.state['vocab'] != LeanIRAutoencoder().state['vocab']:
        raise ValueError('changed vocabulary requires a separate migration, not reward comparison')
    groups = {'train': teachers, 'canary': [{'input': r['src'], 'target': r['src']} for r in holdouts]}
    measured = {}
    for group, pairs in groups.items():
        rows = [loss_for_example(model, coerce_training_example({'id': str(i), 'text': p['input'],
                  'target_ir': ae.encode_lean_ir(p['target'])})) for i, p in enumerate(pairs)]
        if not rows:
            raise ValueError('nonempty training and validation data required')
        ce = sum(r.cross_entropy for r in rows) / len(rows)
        cosine = sum(r.cosine_similarity for r in rows) / len(rows)
        if not math.isfinite(ce) or not math.isfinite(cosine):
            raise ValueError('nonfinite frozen checkpoint metric')
        measured[group] = {'cross_entropy': ce, 'cosine_similarity': cosine, 'samples': len(rows)}
    return measured


def checkpoint_gate(before, after):
    return (after['train']['cross_entropy'] < before['train']['cross_entropy']
        and after['train']['cosine_similarity'] >= before['train']['cosine_similarity'] - 0.01
        and after['canary']['cross_entropy'] <= before['canary']['cross_entropy'] + 0.01
        and after['canary']['cosine_similarity'] >= before['canary']['cosine_similarity'] - 0.01)


class PythonSandbox:
    def __init__(self, config, isolation):
        self.config, self.isolation = config, isolation

    def run(self, payload):
        """Only stdin/stdout crosses the untrusted Python boundary. No host writes."""
        from .arena_isolation import OWNER_LABEL, capture_process
        raw = json.dumps(payload, allow_nan=False).encode()
        if len(raw) > 16_777_216:
            raise ValueError('worker input budget')
        code = (Path(self.config.runtime) / 'jevops/improvement_worker.py').read_text()
        isolation = self.isolation
        deadline = time.monotonic() + self.config.timeout_seconds
        owner, identity = uuid.uuid4().hex, None
        scratch = self.config.state
        isolation.preflight(scratch=scratch, deadline=deadline)
        args = ['create', '--pull=never', '--name', 'jevops-check-' + owner,
            '--label', OWNER_LABEL + '=' + owner, '--read-only', '--network=none', '--ipc=none',
            '--cap-drop=ALL', '--security-opt=no-new-privileges', '--user=65534:65534',
            '--log-driver=none', '--no-healthcheck', '--interactive', '--pids-limit=64',
            '--cpus=1', '--memory=2147483648', '--memory-swap=2147483648', '--ulimit=core=0:0',
            '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=134217728,mode=1777',
            '--mount', 'type=bind,src=/usr,dst=/usr,readonly', '--workdir=/tmp',
            '--env', 'PYTHONDONTWRITEBYTECODE=1', '--entrypoint=/usr/bin/python3',
            isolation.image_id, '-I', '-B', '-c', code]
        try:
            identity = isolation.control(args, scratch=scratch, deadline=deadline).strip()
            with tempfile.TemporaryFile(dir=scratch) as request:
                request.write(raw)
                request.seek(0)
                output, _errors, status = capture_process([*isolation.client, 'start', '--attach', '--interactive', identity],
                    stdin=request, env=isolation.client_env(scratch), timeout=max(1, deadline-time.monotonic()),
                    output_limit=8_388_608)
            if status:
                raise RuntimeError('isolated Python experiment failed; no host code executed')
            return json.loads(output)
        finally:
            isolation.cleanup(identity, owner, scratch=scratch)


class Lab:
    def __init__(self, service):
        self.service = service
        self.worker = PythonSandbox(service.config, service.experiments.isolation)
        runtime = Path(service.config.runtime)
        manifest = json.loads((runtime / 'snapshot.json').read_text())
        self.base = {name: (runtime/name).read_text() for name in manifest['files']
                     if name.startswith('jevops/') and name.endswith('.py')}

    @staticmethod
    def teachers(service):
        store = service.store
        teachers = store.get('verified_teachers', [])[-16:] + store.get('historical_teachers', [])[:8]
        for name, candidate in store.db.execute('SELECT problem,candidate FROM policy').fetchall():
            if name in service.config.development:
                teachers.append({'input': service.records[name]['src'], 'target': json.loads(candidate)['source']})
        unique = {}
        for pair in teachers:
            unique.setdefault(content_hash([pair['input'], pair['target']]), pair)
        return list(unique.values())[:32]

    def prepare(self, action, record):
        from .improvement_service import encoded
        from .improvement_analysis import prepare_editor, editor_metrics, editor_gate
        service, store = self.service, self.service.store
        steps = action.get('train_steps', 8 if action['action'] == 'train' else 0)
        lr = action.get('learning_rate', 0.04)
        if type(steps) is not int or not 0 <= steps <= 32 or type(lr) not in (int, float) or not 0.0005 <= lr <= 0.25:
            raise ValueError('bounded training steps and learning rate required')
        if action['action'] == 'train' and steps == 0:
            raise ValueError('training requires actual updates')
        teachers = self.teachers(service)
        if steps and not teachers:
            raise ValueError('no source-bound development teachers')
        old_files = {**self.base, **store.get('deployed_code', {})}
        new_files = edit_sources(old_files, action.get('changes', []))
        if not steps and new_files == old_files:
            raise ValueError('experiment makes no code or training change')
        active = store.get('deployed_checkpoint')
        start = store.get('experimental_checkpoint', active) if steps else active
        grammar = None
        if steps:
            start, grammar = prepare_editor(start, teachers)
            if not grammar['supported_teachers']:
                return {'status': 'NO_SUPPORTED_REWRITE_TEACHERS', 'diagnostics': grammar,
                        'reason': 'Collect fresh verified local edits; more reconstruction SGD cannot teach these multi-span targets.'}, None
        tag = next(iter(record['version_info'][0]))
        canaries = random_canaries(tag)
        origin = 'model' if steps else 'strategy'
        strategy = action.get('strategy', 'local_alias_reduce')
        if not isinstance(strategy, str) or len(strategy) > 80:
            raise ValueError('bounded strategy name')
        request = {'files': new_files, 'teachers': teachers if steps else [], 'train_steps': steps,
            'learning_rate': lr, 'checkpoint': start, 'records': [record], 'origin': origin, 'strategy': strategy}
        result = self.worker.run(request)
        checkpoint = result['checkpoint']
        metrics = None
        if steps:
            if checkpoint.get('rewrite_templates') != start['rewrite_templates']:
                raise ValueError('worker changed the frozen development-only edit grammar')
            before = measure_checkpoint(active, teachers, canaries)
            after = measure_checkpoint(checkpoint, teachers, canaries)
            edit_before, edit_after = editor_metrics(start, teachers), editor_metrics(checkpoint, teachers)
            metrics = {'before': before, 'after': after, 'gate_passed': checkpoint_gate(before, after),
                       'scorer': 'frozen_host', 'steps_requested': steps, 'learning_rate': lr,
                       'checkpoint_changed': content_hash(start) != content_hash(checkpoint),
                       'grammar': grammar, 'edit_before': edit_before, 'edit_after': edit_after,
                       'edit_gate_passed': editor_gate(edit_before, edit_after)}
            metrics['gate_passed'] = metrics['gate_passed'] and metrics['edit_gate_passed']
            store.event('training', {'name': record['name'], **metrics})
            # Preserve real experiment output even if it cannot be deployed.
            store.set('last_training', metrics)
            store.artifact('training_checkpoint', {'name': record['name'], 'checkpoint': checkpoint,
                'metrics': metrics, 'deployed': False, 'code_sha256': content_hash(new_files),
                'predicted_proofs': result['outputs']})
            if not metrics['checkpoint_changed'] or not metrics['gate_passed']:
                return {'status': 'TRAINING_GATE_REJECTED', 'metrics': metrics}, None
            store.set('experimental_checkpoint', checkpoint)
        outputs = result['outputs']
        if len(outputs) != 1 or outputs[0]['name'] != record['name']:
            raise ValueError('worker output identity mismatch')
        source = outputs[0]['source']
        error = intake_error(source, record['statement'])
        if error:
            return {'status': 'MODEL_OUTPUT_REJECTED', 'metrics': metrics, 'source': source,
                    'reason': error}, None
        candidate = Candidate('lab-' + content_hash(source)[:16], source, 'sandboxed Python/model output; unverified')
        before_outputs = self.worker.run({**request, 'files': old_files, 'teachers': [], 'train_steps': 0,
            'checkpoint': active, 'records': canaries})['outputs']
        after_outputs = self.worker.run({**request, 'teachers': [], 'train_steps': 0,
            'checkpoint': checkpoint, 'records': canaries})['outputs']
        artifact = {'status': 'LAB_PREPARED', 'code': {k: v for k, v in new_files.items() if v != self.base[k]},
            'checkpoint': checkpoint if steps else active, 'training': metrics,
            'canaries': canaries, 'before_outputs': before_outputs, 'after_outputs': after_outputs,
            'changes': action.get('changes', []), 'origin': origin}
        # Full candidate Python and model stay in bounded, versioned experiment receipts.
        if len(encoded(artifact).encode()) > 8_388_608:
            raise ValueError('lab artifact byte limit')
        store.artifact('python_generation', artifact)
        return artifact, candidate

    def canary_gate(self, artifact):
        from .arena_lean import NativeLeanVerifier, ProjectBinding, pinned_lean
        from .arena_pareto import _costs, heartbeat_relation
        from .arena_prepare import exclusive
        from .arena_trial import ORDERS, run_trial, trial_plan
        from .lean import VersionPin
        from .seals import Fingerprinter
        service, reports = self.service, []
        records = artifact['canaries']
        before, after = artifact['before_outputs'], artifact['after_outputs']
        if (len(before) != len(records) or len(after) != len(records)
                or [r['name'] for r in before] != [r['name'] for r in records]
                or [r['name'] for r in after] != [r['name'] for r in records]):
            raise ValueError('complete canary output coverage required')
        # Full reserve before checking anything; interruption does not refund it.
        if not service.store.reserve('native_requests', 36, service.config.native_budget):
            return False, {'status': 'CANARY_BUDGET_EXHAUSTED'}
        lock = Path(service.config.volume_config).parent / 'single-build.lock'
        with exclusive(lock):
            for record, old, new in zip(records, before, after):
                if any(intake_error(r['source'], record['statement']) for r in (old, new)):
                    return False, {'status': 'CANARY_INTAKE_REJECTED', 'reports': reports}
                pin = VersionPin(next(iter(record['version_info'][0])), 'local-stdlib-smoke')
                arms, labels = [], []
                sources = {record['src']: 'control'}
                for label, row in (('previous', old), ('challenger', new)):
                    if row['source'] not in sources:
                        arms.append(Candidate(label, row['source'], 'sandbox harness canary output'))
                        sources[row['source']] = label
                    labels.append(sources[row['source']])
                plan = trial_plan(record, arms, repetitions=2, seed=17)
                reader = Fingerprinter()
                binding = ProjectBinding(pin, pinned_lean(Path(service.config.elan_home), pin.lean_tag),
                    Path(service.config.state), '', project_backed=False)
                verifiers = {(pin, order): NativeLeanVerifier({pin: binding}, max_processes=plan['planned_requests'],
                    timeout=service.config.timeout_seconds, fingerprinter=reader, branch_order=order,
                    isolation=service.experiments.isolation) for order in ORDERS}
                trial = run_trial(record, arms, verifiers, max_calls=plan['planned_requests'], repetitions=2, seed=17)
                reports.append(trial)
                costs = _costs(trial)
                left, right = costs[labels[0]], costs[labels[1]]
                if (not left['admissible'] or not right['admissible'] or right['tokens'] > left['tokens']
                        or any(set(values) - set(left['axioms_by_version'][pin]) for pin, values in right['axioms_by_version'].items())
                        or any(heartbeat_relation(a, b) not in {'EQUAL', 'LOWER'} for a, b in
                               zip(right['raw_heartbeats_by_stratum'], left['raw_heartbeats_by_stratum']))):
                    return False, {'status': 'CANARY_REGRESSION', 'reports': reports}
        return True, {'status': 'CANARIES_PASSED', 'reports': reports,
                      'scope': 'three fresh stdlib canaries, not the full Arena holdout or a generalization guarantee'}

    def deploy(self, artifact):
        store = self.service.store
        identity = content_hash({'code': artifact['code'], 'checkpoint': artifact['checkpoint']})
        generation = store.directory / 'generations' / identity
        generation.mkdir(parents=True, exist_ok=True)
        payloads = {**artifact['code'], 'checkpoint.json': json.dumps(artifact['checkpoint'], allow_nan=False)}
        for name, text in payloads.items():
            path = generation / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                if path.read_text() != text:
                    raise ValueError('generation identity collision or source mutation')
            else:
                with path.open('x') as stream:
                    stream.write(text)
                path.chmod(0o444)
        # Caller owns the same transaction as the policy/receipt promotion.
        for key, value in (('deployed_code', artifact['code']), ('deployed_checkpoint', artifact['checkpoint']),
                           ('generation_directory', str(generation))):
            store.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, json.dumps(value, allow_nan=False)))
        # Next workers consume these exact Python source edits and checkpoint.
        # They are never imported/executed in the host process or user's checkout.

"""Bounded source analysis and training support, never proof admission.

No intermediate state from a multi-edit historical pair is invented as a
verified teacher. Unsupported targets remain explicitly unsupported.
"""
from __future__ import annotations

import difflib
import json

from .arena import content_hash, intake_error, reference_tokens
from .arena_trial import Candidate


def teacher_examples(teachers):
    from .autoencoder import encode_lean_ir
    from .autoencoder_training import coerce_training_example
    return [coerce_training_example({'id': str(i), 'text': p['input'],
             'target_ir': encode_lean_ir(p['target'])}) for i, p in enumerate(teachers)]


def prepare_editor(state, teachers):
    """Mine only supplied development endpoints, before freezing the loss domain."""
    from .autoencoder_training import AutoencoderConfig, LeanIRAutoencoder
    model = LeanIRAutoencoder.from_dict(state, config=AutoencoderConfig(train_rewrite_policy=True))
    grammar = model.prepare_rewrite_training(teacher_examples(teachers))
    checkpoint = model.to_dict()
    return checkpoint, {**grammar, **editor_metrics(checkpoint, teachers)}


def editor_metrics(state, teachers):
    from .autoencoder_training import AutoencoderConfig, LeanIRAutoencoder
    model = LeanIRAutoencoder.from_dict(state, config=AutoencoderConfig(train_rewrite_policy=True))
    values = [(i, model.rewrite_objective(row)) for i, row in enumerate(teacher_examples(teachers))]
    # Identity-only choices cannot teach compression; do not count them as coverage.
    labeled = [(i, row) for i, row in values if row is not None and row['choice_count'] > 1]
    return {'grammar_sha256': content_hash(model.state['rewrite_templates']),
            'template_count': len(model.state['rewrite_templates']),
            'teacher_count': len(teachers), 'supported_teacher_ids': [i for i, _ in labeled],
            'supported_teachers': len(labeled),
            'cross_entropy': sum(r['cross_entropy'] for _, r in labeled)/len(labeled) if labeled else None,
            'expected_cosine_loss': sum(r['expected_cosine_loss'] for _, r in labeled)/len(labeled) if labeled else None}


def editor_gate(before, after):
    return (before['supported_teachers'] > 0
            and before['grammar_sha256'] == after['grammar_sha256']
            and before['supported_teacher_ids'] == after['supported_teacher_ids']
            and after['cross_entropy'] < before['cross_entropy']
            and after['expected_cosine_loss'] <= before['expected_cosine_loss'] + 1e-12)


def compact_observation(value):
    """Preserve failure/cost fields even when proof bytes cannot fit the prompt."""
    result = dict(value)
    for field in ('source', 'proof', 'input', 'target'):
        text = result.pop(field, None)
        if isinstance(text, str):
            result[field + '_summary'] = {'sha256': content_hash(text), 'bytes': len(text.encode()),
                                          'full_source_retained_in_ledger': True}
    if len(json.dumps(result)) > 6000:
        result = {k: result[k] for k in ('kind', 'name', 'status', 'reason', 'error_type',
                  'before_tokens', 'after_tokens', 'diagnostics') if k in result}
        result['large_fields_omitted'] = True
    return result


def proposal_menu(record, incumbent, teachers=(), tried=(), limit=12):
    """Frozen heuristics nominate hypotheses; none is labeled verified here.

    Include both local, potentially learnable edits and historical endpoints.
    No modified generator Python is executed in this host-side analysis.
    """
    from .arena_rules import PORTABLE_RULES, portable_proposal
    from .logic_refactor import reduction_variants
    from .rewrite_policy import body_of, mine_template
    base = incumbent.source if incumbent else record['src']
    statement = record['statement']
    prefix, body = body_of(base)
    base_tokens = reference_tokens(base, statement)
    rows, seen = [], set(tried) | {content_hash(base)}

    def add(source, origin):
        digest = content_hash(source)
        if digest in seen or intake_error(source, statement):
            return
        seen.add(digest)
        count = reference_tokens(source, statement)
        if count >= base_tokens:
            return
        template = mine_template(base, body_of(source)[1])
        diff = '\n'.join(difflib.unified_diff(base.splitlines(), source.splitlines(), n=1))
        rows.append({'id': digest, 'source': source, 'origin': origin,
                     'tokens': count, 'saved_tokens': base_tokens-count,
                     'single_span_teacher_possible': template is not None,
                     'diff_excerpt': diff[:1800], 'diff_truncated': len(diff) > 1800,
                     'verified': False})

    for pair in teachers:
        if pair['input'] == record['src']:
            add(pair['target'], 'historical/development teacher; fresh native check required')
    for rule in PORTABLE_RULES:
        candidate = portable_proposal(base, statement, rule)
        if candidate:
            add(candidate, rule)
    # Small local variants can yield source-bound teachers the edit head supports.
    for strategy in ('local_alias_reduce', 'application_reduce', 'eta_reduce', 'proof_slice'):
        for _label, draft, _ops in reduction_variants(body, strategy=strategy, cap=8):
            import textwrap
            add(prefix + '\n' + textwrap.indent(draft, '  '), strategy)
    by_cost = sorted(rows, key=lambda r: (r['tokens'], r['id']))
    local = [r for r in by_cost if r['single_span_teacher_possible']]
    selected = {r['id']: r for r in by_cost[:limit//2] + local[:limit//2]}
    for row in by_cost:
        if len(selected) >= limit:
            break
        selected.setdefault(row['id'], row)
    return list(selected.values())


def menu_candidate(proposal, menu):
    selected = next((row for row in menu if row['id'] == proposal.get('proposal_id')), None)
    if selected is None:
        raise ValueError('unknown or already evaluated analysis proposal')
    return Candidate('analysis-' + selected['id'][:16], selected['source'],
                     'source analysis hypothesis; unverified: ' + selected['origin'])

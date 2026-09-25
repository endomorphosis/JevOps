"""Fixed sandbox entrypoint. Model-edited modules may emit data, never scores.

Executed as a script in a networkless container, not imported on the host.
The host ignores any worker-reported metric and recomputes checkpoint losses
using the frozen implementation. Input files contain no private canaries while
training; prediction-only calls receive fresh validation problems afterwards.
"""
import contextlib
import json
from pathlib import Path
import re
import sys


def proof_source(statement, rendered):
    """A decoded body cannot change the benchmark's theorem envelope."""
    _header, separator, body = rendered.partition(' := by\n')
    return statement + ' := by\n' + body if separator else rendered


def main():
    payload = json.loads(sys.stdin.buffer.read(16_777_217))
    root = Path('/tmp/harness')
    for name, text in payload['files'].items():
        rel = Path(name)
        if rel.is_absolute() or '..' in rel.parts or not name.startswith('jevops/'):
            raise ValueError('unsafe package path')
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    sys.path.insert(0, str(root))
    with contextlib.redirect_stdout(sys.stderr):
        from jevops import autoencoder as ae
        from jevops import autoencoder_training as training
        from jevops.logic_refactor import reduction_variants
        # The host has already mined and frozen a development-only grammar.
        # Merely fitting operation frequencies cannot learn argument rewrites.
        cfg = training.AutoencoderConfig(learning_rate=payload['learning_rate'], train_rewrite_policy=True)
        model = training.LeanIRAutoencoder.from_dict(payload.get('checkpoint'), config=cfg)
        teachers = [training.coerce_training_example({'id': str(i), 'text': pair['input'],
            'target_ir': ae.encode_lean_ir(pair['target'])}) for i, pair in enumerate(payload['teachers'])]
        for _ in range(payload['train_steps']):
            model.train_batch(teachers)
        outputs = []
        for record in payload['records']:
            source = record['src']
            if payload['origin'] == 'model':
                prediction = model.predict_ir(source, source_ir=ae.encode_lean_ir(source))
                rendered = ae.decode_lean_ir(prediction)
                # The general IR renderer uses a convenience `_rt` declaration
                # and normalized binders. An Arena proposal owns ONLY the body:
                # bind it to the caller's exact immutable statement instead.
                source = proof_source(record['statement'], rendered)
            else:
                suffix = source[len(record['statement']):]
                marker = re.match(r'\s*:=\s*by\b', suffix)
                if marker:
                    body = suffix[marker.end():].lstrip('\n')
                    variants = reduction_variants(body, strategy=payload['strategy'], cap=4)
                    if variants:
                        # Heuristic choice only. Host counts tokens and checks Lean.
                        source = record['statement'] + suffix[:marker.end()] + '\n' + variants[0][1]
            outputs.append({'name': record['name'], 'source': source,
                            'decoder': ({key: prediction.get(key) for key in ('rewrite_policy', 'binding_policy', 'dependency_guard')}
                                        if payload['origin'] == 'model' else {'strategy': payload['strategy']})})
        result = {'checkpoint': model.to_dict(), 'outputs': outputs}
    print(json.dumps(result, allow_nan=False))


if __name__ == '__main__':
    main()

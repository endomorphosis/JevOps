"""Record a source-location discrepancy without relaxing native admission."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
corpus = WORK / 'full15-benchmark-20260923-IrlqY5/runtime/inputs/corpus.jsonl'
name = 'Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius'
record = next(r for r in map(json.loads, corpus.read_text().splitlines()) if r['name'] == name)
path = WORK / 'projects/arklib-v4.30.0/ArkLib/ProofSystem/Binius/BinaryBasefold/Prelude.lean'
source = path.read_text()
needle = 'have h_elemenet_Y_bad : y_of_x'
replacement = 'have h_elemenet_Y_bad :  y_of_x'
assert record['src'].count(needle) == 1
variant = record['src'].replace(needle, replacement)
result = {
    'schema': 'jevops-arena-source-location-diagnostic/v1',
    'problem': name, 'lean_tag': 'v4.30.0', 'pinned_source_path': str(path),
    'corpus_sha256': hashlib.sha256(corpus.read_bytes()).hexdigest(),
    'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
    'original_reference_occurrences': source.count(record['src']),
    'exact_statement_occurrences': source.count(record['statement']),
    'one_internal_space_variant_occurrences': source.count(variant),
    'variant_start_line': source[:source.index(variant)].count('\n') + 1 if variant in source else None,
    'reference_change_bytes': len(variant.encode()) - len(record['src'].encode()),
    'before': needle, 'after': replacement,
    'admission_changed': False, 'proofs_verified': 0,
    'status': 'UNAVAILABLE',
    'note': 'Read-only diagnostic. A unique formatting variant is not a native proof receipt.'}
with (HERE / 'source-gap-diagnostic.json').open('x') as stream:
    json.dump(result, stream, indent=2)
print(json.dumps(result, indent=2))

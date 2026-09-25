# Goal-only library reuse regression

Frozen bounded library pool; no supplied solution names in the query. Not a blind benchmark, graph ablation or learning claim.

Original reference: 3 lexical proof-body tokens.

Application mode: bare-then-apply. Candidate checks count recipes, not distinct declarations.

| Policy | Discovery status | Selected declaration | Method | Candidate checks | Tokens |
| --- | --- | --- | --- | ---: | ---: |
| direct-scan | FOUND | Nat.le_trans | apply-assumption | 5 | 7 |
| bm25 | FOUND | Nat.le_trans | apply-assumption | 4 | 7 |

BM25 vs direct lookup: NO_CLEAR_DIFFERENCE; identical sources: True; native paired coverage: True.

Fresh discovery processes: 18; confirmation processes: 24.
Inventory exports are accounted separately. Non-found policies use unchanged-reference fallback, not discovered proofs.
Lookup covers only the frozen application recipes. Failure does not establish novelty, semantic inequivalence or absence of a compositional proof.

## Fresh command-elaboration measurements

Raw heartbeat units, two branch orders; not end-to-end search or library build costs.

| Lean | Order | Original reference | Direct scan | BM25 |
| --- | --- | ---: | ---: | ---: |
| v4.26.0 | reference-first | 16066.0 | 19655.0 | 19655.0 |
| v4.26.0 | candidate-first | 16086.0 | 19675.0 | 19675.0 |
| v4.29.1 | reference-first | 15000.0 | 19063.0 | 19063.0 |
| v4.29.1 | candidate-first | 15038.0 | 19101.0 | 19101.0 |

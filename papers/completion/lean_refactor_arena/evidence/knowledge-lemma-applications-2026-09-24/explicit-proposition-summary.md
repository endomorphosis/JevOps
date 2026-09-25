# Goal-only library reuse regression

Frozen bounded library pool; no supplied solution names in the query. Not a blind benchmark, graph ablation or learning claim.

Original reference: 2 lexical proof-body tokens.

Application mode: bare-then-apply. Candidate checks count recipes, not distinct declarations.

| Policy | Discovery status | Selected declaration | Method | Candidate checks | Tokens |
| --- | --- | --- | --- | ---: | ---: |
| direct-scan | FOUND | and_not_self_iff | apply-assumption | 6 | 7 |
| bm25 | FOUND | and_not_self_iff | apply-assumption | 3 | 7 |

BM25 vs direct lookup: NO_CLEAR_DIFFERENCE; identical sources: True; native paired coverage: True.

Fresh discovery processes: 18; confirmation processes: 24.
Inventory exports are accounted separately. Non-found policies use unchanged-reference fallback, not discovered proofs.
Lookup covers only the frozen application recipes. Failure does not establish novelty, semantic inequivalence or absence of a compositional proof.

## Fresh command-elaboration measurements

Raw heartbeat units, two branch orders; not end-to-end search or library build costs.

| Lean | Order | Original reference | Direct scan | BM25 |
| --- | --- | ---: | ---: | ---: |
| v4.26.0 | reference-first | 5765.0 | 8531.0 | 8531.0 |
| v4.26.0 | candidate-first | 5785.0 | 8551.0 | 8551.0 |
| v4.29.1 | reference-first | 5771.0 | 8644.0 | 8644.0 |
| v4.29.1 | candidate-first | 5812.0 | 8685.0 | 8685.0 |

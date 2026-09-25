# Goal-only library reuse regression

Frozen bounded library pool; no supplied solution names in the query. Not a blind benchmark, graph ablation or learning claim.

Original reference: 57 lexical proof-body tokens.

| Policy | Discovery status | Selected declaration | Candidate checks | Tokens |
| --- | --- | --- | ---: | ---: |
| direct-scan | FOUND | and_or_left | 18 | 1 |
| bm25 | FOUND | and_or_left | 3 | 1 |

BM25 vs direct lookup: NO_CLEAR_DIFFERENCE; identical sources: True; native paired coverage: True.

Fresh discovery processes: 42; confirmation processes: 24.
Inventory exports are accounted separately. Non-found policies use unchanged-reference fallback, not discovered proofs.
Direct lookup covers bare constants with implicit inference only, not all possible lemma applications or semantic equivalents.

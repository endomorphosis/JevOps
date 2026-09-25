# Goal-only library reuse regression

Frozen bounded library pool; no supplied solution names in the query. Not a blind benchmark, graph ablation or learning claim.

Original reference: 5 lexical proof-body tokens.

Application mode: bare-then-apply. Candidate checks count recipes, not distinct declarations.

| Policy | Discovery status | Selected declaration | Method | Candidate checks | Tokens |
| --- | --- | --- | --- | ---: | ---: |
| direct-scan | NO_SUPPORTED_APPLICATION_IN_SEARCHED_SET | None | None | 6 | 5 |
| bm25 | NO_SUPPORTED_APPLICATION_IN_SEARCHED_SET | None | None | 6 | 5 |

BM25 vs direct lookup: INCOMPLETE; identical sources: True; native paired coverage: False.

Fresh discovery processes: 24; confirmation processes: 24.
Inventory exports are accounted separately. Non-found policies use unchanged-reference fallback, not discovered proofs.
Lookup covers only the frozen application recipes. Failure does not establish novelty, semantic inequivalence or absence of a compositional proof.

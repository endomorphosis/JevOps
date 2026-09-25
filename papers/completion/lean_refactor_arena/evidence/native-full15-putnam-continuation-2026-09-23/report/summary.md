# Full 15-problem benchmark

Status: **INCOMPLETE**.

Native baseline coverage: 26/36 pins; fully checked problems: 9/15. Reported native processes across contributing runs: 66.

Reference tokens: 17595; declared candidate tokens: 17474. Accepted full-set total: None. Official score: unavailable.

| Problem | Tokens: reference → candidate | Baseline pins | Candidate | Baseline raw heartbeats (available pins) | Matched heartbeat reduction |
| --- | ---: | ---: | --- | ---: | ---: |
| CallElimCorrect.substOldPostSubset | 313 → 237 | 1/1 | VERIFIED | 5,205,992–5,205,992 | 1.681–1.682% |
| CallElimCorrect.extractedOldExprInVars | 222 → 185 | 1/1 | VERIFIED | 2,607,584–2,607,584 | 10.860–10.860% |
| Core.InitsUpdatesComm | 224 → 216 | 3/3 | VERIFIED | 4,227,568–4,689,118 | 37.887–42.398% |
| fundamental_theorem_of_variational_calculus' | 851 → 851 | 1/1 | UNCHANGED | 12,454,940–12,454,940 | — |
| Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema | 1372 → 1372 | 1/1 | UNCHANGED | 27,475,681–27,475,681 | — |
| FieldSpecification.WickAlgebra.ι_timeOrderF_superCommuteF_eq_time | 1217 → 1217 | 1/1 | UNCHANGED | 42,721,989–42,721,989 | — |
| Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress | 408 → 408 | 3/3 | UNCHANGED | 60,078,237–62,227,633 | — |
| Cslib.SKI.parallelReduction_diamond | 407 → 407 | 4/4 | UNCHANGED | 1,634,260–1,657,055 | — |
| Cslib.CCS.bisimilarity_congr_choice | 251 → 251 | 3/3 | UNCHANGED | 4,020,386–4,024,952 | — |
| Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius | 1463 → 1463 | 1/4 | INCOMPLETE | 16,664,188–16,664,188 | — |
| Binius.BinaryBasefold.fold_advances_evaluation_poly | 1906 → 1906 | 2/3 | INCOMPLETE | 47,012,062–48,413,229 | — |
| interleaved_affine_gaps_imply_tensor_gaps | 1353 → 1353 | 2/3 | INCOMPLETE | 9,972,291–9,976,769 | — |
| putnam_1964_a4 | 1769 → 1769 | 1/3 | INCOMPLETE | 140,508,429–140,508,429 | — |
| putnam_1964_b2 | 1754 → 1754 | 1/2 | INCOMPLETE | 120,777,934–120,777,934 | — |
| putnam_1995_a3 | 4085 → 4085 | 1/3 | INCOMPLETE | 19,628,468–19,628,468 | — |

Offline summary of recorded native observations; not receipt authentication or a new proof check.
Source-token totals count each problem once; declared lengths are not an accepted full-set score.
One fresh baseline process per available pin; refactors use at least two repeats in each branch order.
Raw heartbeats / 1000 are Lean display units, not milliseconds; failed/missing measurements are not zero.
Unchanged rows are baseline-only, not compression wins. No full-set heartbeat aggregate is inferred.
Cumulative coverage from disjoint native runs; earlier checks were not rerun. Per-row source hashes identify the originating reports.

## Missing/failed checks

- `Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius` / `v4.30.0`: reference_source_not_uniquely_located
- `Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius` / `v4.29.0`: project_commit_mismatch
- `Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius` / `v4.28.0`: project_commit_mismatch
- `Binius.BinaryBasefold.fold_advances_evaluation_poly` / `v4.29.0`: project_commit_mismatch
- `interleaved_affine_gaps_imply_tensor_gaps` / `v4.29.0`: project_commit_mismatch
- `putnam_1964_a4` / `v4.26.0`: putnam_compiled_import_missing: Mathlib
- `putnam_1964_a4` / `v4.27.0`: [Errno 2] No such file or directory: '/home/barberb/.local/state/ipfs_accelerate_py/vericodegen-2026-lra/track1-lake/putnam_lake/v4.27.0'
- `putnam_1964_b2` / `v4.26.0`: putnam_compiled_import_missing: Mathlib
- `putnam_1995_a3` / `v4.26.0`: putnam_compiled_import_missing: Mathlib
- `putnam_1995_a3` / `v4.27.0`: [Errno 2] No such file or directory: '/home/barberb/.local/state/ipfs_accelerate_py/vericodegen-2026-lra/track1-lake/putnam_lake/v4.27.0'

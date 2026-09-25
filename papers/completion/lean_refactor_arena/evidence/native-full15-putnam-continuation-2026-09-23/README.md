# Preparation and benchmark continuation

[Benchmark results](report/summary.md)

The benchmark combines earlier observations with disjoint new native checks. Builds and cached unit tests do not establish proof success. No training or model calls.

| Preparation run | Exit code | Timed out | Wall seconds |
| --- | ---: | --- | ---: |
| 1790150072654781028 | 0 | False | 1.2 |
| 1790150126535508494 | 0 | False | 619.4 |
| 1790150752301250269 | 124 | True | 1800.4 |
| 1790152583426052327 | 0 | False | 3500.3 |
| 1790157414426464156 | 1 | False | 176.6 |
| 1790157775374634229 | 1 | False | 5.8 |
| 1790157826893340655 | 0 | False | 352.6 |

## Preparation limits

Recorded available space: 8.421 GB within the 50 GB allowance. Environments below their free-space preflight: putnam-v4.26.0, putnam-v4.27.0.
Other unprepared jobs are listed separately in `preparation/storage-preflight.json`; a passing storage preflight is not a successful build. No cache deletion is authorized by this report.

## Source-binding gap

`Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius` / `v4.30.0` remains UNAVAILABLE. Exact reference occurrences: 0; one-space variant occurrences: 1. This is a location diagnostic, not a proof receipt or a change to admission rules.

Original logs, frozen-source checks, input hashes and per-environment native reports are archived alongside this generated summary. No official Arena score is inferred.

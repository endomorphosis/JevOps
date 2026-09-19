---
name: jevops-kernel
description: JevOps NCA cache L0–L3, CID put/get, negative TTL, single-flight, context budget. Use for caching, in-flight oracle keys, or CALL ptr://skill/port_{cache_put,cache_get,negative_ttl,singleflight,context_budget}. Cache hits never admit Lean.
---

# NCA kernel

Module: `jevops.kernel`. Lake (or another oracle) still admits. PYTHONPATH must include JevOps.

| Tier | Store |
| --- | --- |
| L0 | neural tape / DT window |
| L1 | `nca.kernel.l1` process dict (ARC default, or LRU) |
| L2 | host CAS files (`JEVOPS_CAS_DIR`) |
| L3 | optional JSON-LD DuckDB |

- Put/get by `sha256:` CID. `theorem_ok` is stripped.
- CALL `port_cache_arc` / `port_cache_lru`.
- Negative cache expires after N ticks (default 32).
- Single-flight: second begin returns `in_flight`. Durable inflight TTL 180s.
- Context budget: `keep_k` plus byte trim on tape payloads.

Never docker0. Jev does not write Lean.

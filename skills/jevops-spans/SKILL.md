---
name: jevops-spans
description: Nested header spans, insert-before, JSONL load with digest. Use for case_spans, prefix haves, warmup JSONL. Never writes Lean.
---

# Spans / JSONL

- `mask.nested_header_spans` / `replace_span` / `lines_until` / `insert_before` / `split_before` / `top_level_labels` / `header_map`
- `mask.split_top_level` / `drop_spans` / `splice_from` — depth-0 comma split; delete spans; copy a src span into dst
- `outer.split_after_prefix` / `strip_leading_prefixes` / `join_decl` — prefix-bind a statement to a body; never scan for `:=`
- `search.last_header_tag`
- `outer.load_jsonl_objects` / `digest_hex` — optional digest, count, required fields
- LRA still owns `case … =>` regex, frozen warmup SHA, and lake splice.

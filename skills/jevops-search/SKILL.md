---
name: jevops-search
description: Coordinate keep-best accept and prefix-beam extend. Use for SGD hole descent, constrained beam, or accept_keepbest. Lake admits. Never writes Lean.
---

# Search helpers

Module: `jevops.search`.

- `apply_keepbest` / `token_ratio` / `high_p_ids` / `strip_tactics` — SGD/diffuse keep updates.
- `accept_keepbest` — shortest theorem_ok eval strictly under keep_tokens.
- `minibatch_ids` — greedy choice + ranked + rng, unique cap k.
- `metropolis_token_accept` — MH on token delta.
- `unused_items` — vocab not already in the prefix.
- `ablate_then_combine` — drop one hole at a time, then combine lake-ok drops (compile_fn injected).
- `unique_cap` / `pin_then_rank` — unique candidates; pin Choice then sort by p.
- `extend_prefix` — indent-aware append; stop token injected.
- `structure_status` / `guided_next` / `filter_to_earliest` / `empty_headers` / `structure_complete` — fill nested headers in order (present/remaining/header fns injected).
- `proposal_bag` — unique edit bag with optional accept_fn (locked names stay LRA).
- `weighted_sum` — weight×value pairs (token/elab composite).
- `count_matches` — regex findall length (local tokenizer).
- `parse_marked_list` — unique names after a printed-list prefix (axiom dump).
- `index_order` — rank 0..n-1 by `{prefix}{i}` probs and pin Choice.
- `name_match_score` / `hit_row` / `rank_hits` — unique scored hits (weights injected).
- `search_rg` — ripgrep over globs; ident regex and hit_fn injected. Never docker0.
- `expand_beam` / `beam_until` — keep stopped items, expand the rest, cap; loop until all stopped. Propose/prune/stop fns injected.
- `pick_min_tiers` — first non-empty pred, then min by key_fn.
- `pin_front` — prefer[:n] first, then the rest of order.
- LRA `sgd_fanout` / `constrained_beam` still own lake loops and Lean vocab.
- Not neural SGD. Never docker0.

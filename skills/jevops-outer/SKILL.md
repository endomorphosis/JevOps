---
name: jevops-outer
description: Outer JSON actions, deterministic route, run_steps, keep-best files. Use for parse_action, route_next, stall/stop, merge_keep_best. Grok does not write Lean.
---

# Outer loop

Module: `jevops.outer`.

- Actions: run, nest_inner, mint, skip_stem, install_fold, stop.
- `route_next` charges budget after LLM JSON. Deterministic fallback on stall.
- `starting_body` / `merge_keep_best` / `write_best_body` do not generate Lean.
- `load_env_file` / `pin_sys_path` — KEY=VALUE env files and sys.path front-pin.
- `retry_call` / `is_unavailable` — 503/429 backoff. `failed_leaves_from_history` reads JSON history.
- `fill_template` / `version_sort_key` / `mean_nonneg` / `listed_all_ok` / `flatten_version_tags`.
- `load_module_from_path` — file-backed import (TypeSafe module load).
- `http_get` / `require_positive_above` / `first_group_int` / `first_nonempty` / `contains_flags`.
- `load_env_file(strip_quotes=)` / `first_env_path` / `allow_or_deny` / `is_executable` / `url_cache_key` / `normalize_tag` / `copy_tree`.
- `redact_secret` / `require_host` / `estimate_tokens_chars` / `canonical_bytes`.
- `first_match` / `poll_until` / `sanitize_ident` / `write_cas` / `dump_tiny` / `keyed_pair` / `stat_dev_ino` / `object_fields`.
- `digest_file` / `digest_text` / `write_executable` / `write_json` / `first_where` / `after_named` / `unique_keep` / `merge_head_row`.
- `http_post` / `xdg_runtime_dir` / `try_import` / `dir_has_markers` / `run_process` / `usage_tokens` / `chat_choice_texts` / `integrity_conflict` / `guard_sql`.
- `contains_any` / `replace_once` / `mapping_line_in_span` / `jsonl_pred_in_span` / `proc_exclusive_holder` / `shared_lock_busy` / `git_head` / `require_basename`.
- `print_json` / `with_field` / `with_fields` / `join_under` / `plant_files` / `plant_git_skeleton`.
- `python_argv` / `state_home_candidates` / `exec_capable_dir` / `inspect_lock`.
- `run_process` accepts `env=` and `timeout=`; timeout returns `timeout=True` without taking exclusive locks.
- `refuse_basename` / `walk_suffix_files` / `existing_files` / `write_blobs` / `plant_executables` / `pinned_bin_paths`.
- `nonempty_file` / `path_parts_status` / `first_json_dict` / `http_ok` / `name_fallback_used`.
- `write_text` / `state_root_from_env` / `mkdtemp_under`.
- `timed_call` / `process_exit_code` / `write_named_jsons` / `which_bin` / `any_search`.
- `glob_after` / `first_file_text` / `is_stub_text`.
- `collect_until` / `first_or_last` / `require_exact_keys` / `reject_present_keys`.
- `quoted_strings` / `is_hex_digest`.
- `pin_env` / `require_env_eq` / `argv_layout`.
- `first_group` / `token_family` / `row_dict` / `row_cell` / `path_refused` / `without_prefix` / `cut_prefix`.
- `dumps_compact` / `digest_compact` / `connect_engine` (DuckDB if present, else sqlite3).
- `env_str` / `env_int` / `partition` / `map_partition` / `first_matching_line`.
- `first_token` / `result_usage` / `attr_map` / `client_kwargs` / `load_configured` / `unique_kind_bodies`.
- `iter_tag_commit_pins` — `{tag: commit}` maps to pin objects (`normalize_fn` / `pin_fn` injected).
- `field_of` / `filter_map` — getattr/mapping first-nonempty and pred+map with skip_exc.
- `open_readonly` / `query_engine` / `engine_tables` / `first_table_sql` — optional DuckDB SELECT. Missing/refused/unavailable → []. Never campaign writes. Never docker0.
- `insert_ignore_conflict` — INSERT that returns False on unique/integrity conflicts.
- `fetch_mapped` — map fetchall rows; None drops.

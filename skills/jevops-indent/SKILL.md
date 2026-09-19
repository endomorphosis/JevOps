---
name: jevops-indent
description: Match reference indent and flatten over-indented headers. Use for match_leading_indent / flatten_overindent after hosted fills. Never writes Lean.
---

# Indent repair

Module: `jevops.repair`.

- `match_leading_indent` prefixes tactic lines with the reference's first indent.
- `flatten_overindent` strips extra indent when header lines (injected `header_fn`) are deeper than the reference.
- LRA uses `case … =>` as the header predicate. Lake still admits.

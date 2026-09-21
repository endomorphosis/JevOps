"""LRA adapter — plan DAG / graph-of-thoughts lives in JevOps."""
from __future__ import annotations

import _jevops_path  # noqa: F401
from jevops import plan as _mod

globals().update({k: getattr(_mod, k) for k in dir(_mod) if not k.startswith("__")})

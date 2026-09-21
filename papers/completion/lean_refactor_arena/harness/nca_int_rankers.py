"""LRA adapter — integer milles rankers lives in JevOps."""
from __future__ import annotations

import _jevops_path  # noqa: F401
from jevops import int_rankers as _mod

globals().update({k: getattr(_mod, k) for k in dir(_mod) if not k.startswith("__")})

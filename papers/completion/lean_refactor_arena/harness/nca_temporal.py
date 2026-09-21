"""LRA adapter — Hawkes / CRF / submodular / tape conv lives in JevOps."""
from __future__ import annotations

import _jevops_path  # noqa: F401
from jevops import temporal as _mod

globals().update({k: getattr(_mod, k) for k in dir(_mod) if not k.startswith("__")})

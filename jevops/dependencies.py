"""Explicit boundary for deprecated Endomorphosis repository adapters.

The JevOps core is intended to run from one checkout with the Python
standard library.  Optional integrations with the separate
``ipfs_accelerate_py`` and ``ipfs_datasets_py`` repositories are therefore
disabled by default.  Set ``JEVOPS_USE_EXTERNAL_DEPS=1`` for a legacy
consumer that still needs them; every successful load emits a deprecation
warning and the caller must retain its local fallback.
"""
from __future__ import annotations

import importlib
import os
import warnings
from types import ModuleType
from typing import Any, Optional


def external_enabled(environ: Optional[dict[str, str]] = None) -> bool:
    env: Any = os.environ if environ is None else environ
    return str(env.get("JEVOPS_USE_EXTERNAL_DEPS") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def load_external_module(module_name: str, *, feature: str = "optional adapter") -> Optional[ModuleType]:
    """Load one legacy module only after explicit opt-in."""

    if not external_enabled():
        return None
    warnings.warn(
        f"{feature} uses deprecated external module {module_name}; "
        "prefer the in-tree JevOps implementation",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        return importlib.import_module(module_name)
    except Exception:
        return None


def load_external_symbol(
    module_name: str,
    symbol: str,
    *,
    feature: str = "optional adapter",
) -> Any:
    module = load_external_module(module_name, feature=feature)
    return getattr(module, symbol, None) if module is not None else None


__all__ = ["external_enabled", "load_external_module", "load_external_symbol"]

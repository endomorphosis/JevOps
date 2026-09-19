#!/usr/bin/env python3
"""Optional consumer hooks. Kernel never imports Lean, lake, or a paper board.

Implementations (LRA, other papers) register callables, or they stay importable
on PYTHONPATH and ``try_import`` finds them. Missing hooks fail closed.
"""
from __future__ import annotations

import importlib
from typing import Any, Callable, Optional

_HOOKS: dict[str, Callable[..., Any]] = {}


def register(name: str, fn: Callable[..., Any]) -> None:
    _HOOKS[str(name)] = fn


def get(name: str) -> Optional[Callable[..., Any]]:
    return _HOOKS.get(str(name))


def clear() -> None:
    _HOOKS.clear()


def try_import(module: str, attr: Optional[str] = None) -> Any:
    """Import a consumer module if the implementation is on sys.path."""

    try:
        mod = importlib.import_module(module)
    except Exception:
        return None
    if attr is None:
        return mod
    return getattr(mod, attr, None)


def call(name: str, *args: Any, default: Any = None, **kwargs: Any) -> Any:
    fn = _HOOKS.get(str(name))
    if fn is None:
        return default
    try:
        return fn(*args, **kwargs)
    except Exception:
        return default


def resolve(name: str, module: str, attr: Optional[str] = None) -> Any:
    """Prefer a registered hook, else a consumer module on PYTHONPATH."""

    fn = _HOOKS.get(str(name))
    if fn is not None:
        return fn
    return try_import(module, attr)


def const(name: str, default: Any = None) -> Any:
    """Read a thunk/constant hook (``root_goal``, ``blocked_ids``)."""

    fn = _HOOKS.get(str(name))
    if fn is None:
        return default
    try:
        return fn() if callable(fn) else fn
    except TypeError:
        return fn
    except Exception:
        return default

"""Lazy, fail-closed access to optional research-repository modules.

The LRA harness is runnable from a clean JevOps checkout.  TypeSafe now uses
the JevOps-owned stdlib client by default.  Remaining
``ipfs_accelerate_py`` integrations are loaded only at an explicit legacy
feature boundary and must never turn a missing dependency into a hidden
provider fallback.
"""
from __future__ import annotations

import importlib
import os
import warnings
from types import ModuleType
from typing import Optional

import _jevops_path


class OptionalDependencyError(RuntimeError):
    """An explicitly requested optional adapter is unavailable."""


def load_module(module_name: str) -> tuple[Optional[ModuleType], str]:
    """Load one configured accelerator module, returning ``(module, reason)``.

    ``reason`` is deliberately stable enough for receipts and self-checks but
    does not expose a traceback or credentials.  A configured path is
    authoritative: if it is absent, a globally installed package is not used.
    """

    if not _jevops_path.IPFS_ACCELERATE_ROOT.is_dir():
        return None, "accelerator_checkout_missing"
    _jevops_path.ensure_ipfs_accelerate_path()
    try:
        warnings.warn(
            f"{module_name} is a deprecated external Endomorphosis dependency; "
            "prefer the JevOps-owned compatibility surface",
            DeprecationWarning,
            stacklevel=2,
        )
        return importlib.import_module(module_name), "external_deprecated"
    except Exception as exc:  # optional integrations must not break the loop
        return None, f"{type(exc).__name__}: {str(exc)[:240]}"


def require_module(module_name: str) -> ModuleType:
    module, reason = load_module(module_name)
    if module is None:
        raise OptionalDependencyError(f"{module_name}: {reason}")
    return module


def load_typesafe() -> tuple[Optional[ModuleType], str]:
    """Load the in-tree TypeSafe protocol unless legacy mode is explicit."""

    external = str(
        os.environ.get("JEVOPS_USE_EXTERNAL_TYPESAFE")
        or os.environ.get("JEVOPS_USE_EXTERNAL_DEPS")
        or ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    if not external:
        try:
            return importlib.import_module("jevops.typesafe_inference"), "in_tree"
        except Exception as exc:
            return None, f"in_tree_error:{type(exc).__name__}"
    return load_module("ipfs_accelerate_py.typesafe_inference")


def require_typesafe() -> ModuleType:
    module, reason = load_typesafe()
    if module is None:
        raise OptionalDependencyError(f"typesafe_inference: {reason}")
    return module


def require_router() -> ModuleType:
    return require_module("ipfs_accelerate_py.llm_router")


def load_kernel_verifier() -> tuple[Optional[ModuleType], str]:
    return load_module("ipfs_accelerate_py.agent_supervisor.proof.kernel_verification")


def load_database_task_source() -> tuple[Optional[ModuleType], str]:
    return load_module("ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source")


def load_vector_index() -> tuple[Optional[ModuleType], str]:
    return load_module("ipfs_accelerate_py.agent_supervisor.analysis.code_symbol_vector_index")

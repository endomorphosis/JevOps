"""
Configuration for the Lean Client Server used in proof optimization.

This module provides configuration for the Lean compiler server used
by the optimizer workflow to check if optimized proofs compile.

The configuration supports two modes:
1. HTTP-based: Using KiminaClient to connect to a remote Lean server (legacy)
2. LSP-based: Using LeanClientScheduler with local Lean LSP (new)
"""

import os

from typing_extensions import Required, TypedDict

from lean_refactor.config.config import parsed_config


class LeanClientServerConfig(TypedDict):
    """
    Configuration for the Lean Client Server.

    Attributes
    ----------
    url : str
        The URL of the Lean compiler server (for HTTP mode).
    max_retries : int
        Maximum number of retries for server requests.
    workspace_path : str
        Path to the Lean project workspace (for LSP mode).
    max_concurrent_workers : int
        Number of parallel worker processes for LSP mode.
    timeout : int
        Per-request timeout in seconds for proof verification.
    """

    url: Required[str]
    max_retries: Required[int]
    workspace_path: Required[str]
    max_concurrent_workers: Required[int]
    timeout: Required[int]


# Default workspace path - can be overridden via config or environment variable
_DEFAULT_WORKSPACE = os.path.expanduser("~/mathlib4")

LEAN_CLIENT_SERVER: LeanClientServerConfig = {
    "max_retries": parsed_config.getint(section="LEAN_CLIENT_SERVER", option="max_retries", fallback=5),
    "workspace_path": parsed_config.get(
        section="LEAN_CLIENT_SERVER",
        option="workspace_path",
        fallback=os.environ.get("LEAN_WORKSPACE_PATH", _DEFAULT_WORKSPACE),
    ),
    "max_concurrent_workers": parsed_config.getint(
        section="LEAN_CLIENT_SERVER",
        option="max_concurrent_workers",
        fallback=int(os.environ.get("LEAN_MAX_CONCURRENT_WORKERS", "4")),
    ),
    "timeout": parsed_config.getint(
        section="LEAN_CLIENT_SERVER",
        option="timeout",
        fallback=int(os.environ.get("LEAN_TIMEOUT", "300")),
    ),
}

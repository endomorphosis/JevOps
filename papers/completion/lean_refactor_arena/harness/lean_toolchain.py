"""Small tag-pinned Lean toolchain boundary used by the LRA harness.

The original benchmark imported the much larger ``ipfs_datasets_py`` frontend
at module import time.  That made a frozen-data plan impossible to run from a
clean JevOps checkout.  Prefer the research frontend when it is explicitly
available, but keep the benchmark's path-pinning and process contract local so
missing optional dependencies are reported as capability gaps rather than
silently replaced with ``PATH`` binaries.
"""
from __future__ import annotations

import importlib
import os
import stat
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Optional, Sequence


KERNEL_COMMAND_TEMPLATE = "{lake} env {lean} --json {source_file}"


def _external_module() -> Any:
    candidates = []
    for key in ("JEVOPS_IPFS_DATASETS_PATH", "IPFS_DATASETS_PATH"):
        value = os.environ.get(key, "").strip()
        if value:
            candidates.append(Path(value))
    try:
        from _jevops_path import IPFS_DATASETS_ROOT

        candidates.append(IPFS_DATASETS_ROOT)
    except Exception:
        here = Path(__file__).resolve()
        candidates.append(here.parents[4] / "external" / "ipfs_datasets")
    for candidate in candidates:
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
    try:
        return importlib.import_module(
            "ipfs_datasets_py.logic.hammers.frontends.lean_toolchain"
        )
    except Exception:
        return None


_EXTERNAL = _external_module()

if _EXTERNAL is not None:
    KERNEL_COMMAND_TEMPLATE = str(
        getattr(_EXTERNAL, "KERNEL_COMMAND_TEMPLATE", KERNEL_COMMAND_TEMPLATE)
    )
    LeanToolchainMissing = getattr(
        _EXTERNAL, "LeanToolchainMissing", RuntimeError
    )
    LeanToolchainResolver = getattr(_EXTERNAL, "LeanToolchainResolver")
    run_lean_process = getattr(_EXTERNAL, "run_lean_process")
    audit_lean_frontend_path_json = getattr(
        _EXTERNAL,
        "audit_lean_frontend_path_json",
        lambda: {
            "available": True,
            "unchanged_path_lean_json": True,
        },
    )
else:

    class LeanToolchainMissing(RuntimeError):
        """A required elan toolchain is not installed."""


    @dataclass(frozen=True)
    class TagPinnedToolchain:
        lean_tag: str
        git_commit: str
        elan_home: str
        toolchain_name: str
        toolchain_dir: str
        lean_path: str
        lake_path: str
        lean_installed: bool
        lake_installed: bool

        @property
        def installed(self) -> bool:
            return bool(self.lean_installed and self.lake_installed)

        @property
        def executable_paths(self) -> dict[str, str]:
            return {"lean": self.lean_path, "lake": self.lake_path}

        def to_dict(self) -> dict[str, Any]:
            payload = asdict(self)
            payload["installed"] = self.installed
            payload["executable_paths"] = self.executable_paths
            payload["capability_gap"] = (
                "" if self.installed else "tag-pinned lean/lake missing"
            )
            return payload


    def _normalize_tag(tag: str) -> str:
        value = str(tag or "").strip()
        if not value:
            raise ValueError("lean tag must be nonempty")
        prefix = "leanprover--lean4---"
        if value.startswith(prefix):
            value = value[len(prefix) :]
        return value


    def _default_elan_home() -> Path:
        value = os.environ.get("ELAN_HOME", "").strip()
        return Path(value) if value else Path.home() / ".elan"


    def _is_executable(path: Path) -> bool:
        try:
            mode = path.stat().st_mode
        except OSError:
            return False
        return stat.S_ISREG(mode) and bool(
            mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        )


    class LeanToolchainResolver:
        """Resolve only ``ELAN_HOME/toolchains/<tag>/bin/{lean,lake}``."""

        def __init__(self, elan_home: Optional[os.PathLike[str] | str] = None):
            self.elan_home = (
                Path(elan_home) if elan_home is not None else _default_elan_home()
            )

        def resolve_tag(
            self,
            lean_tag: str,
            *,
            git_commit: str = "",
            require_installed: bool = True,
        ) -> TagPinnedToolchain:
            tag = _normalize_tag(lean_tag)
            toolchain_name = f"leanprover--lean4---{tag}"
            root = self.elan_home / "toolchains" / toolchain_name
            lean = root / "bin" / "lean"
            lake = root / "bin" / "lake"
            pin = TagPinnedToolchain(
                lean_tag=tag,
                git_commit=str(git_commit or ""),
                elan_home=str(self.elan_home),
                toolchain_name=toolchain_name,
                toolchain_dir=str(root),
                lean_path=str(lean),
                lake_path=str(lake),
                lean_installed=_is_executable(lean),
                lake_installed=_is_executable(lake),
            )
            if require_installed and not pin.installed:
                raise LeanToolchainMissing(
                    f"tag-pinned elan toolchain not installed at {root} "
                    f"(lean_tag={tag!r}); refusing PATH fallback"
                )
            return pin


    def run_lean_process(
        command: Sequence[str],
        *,
        timeout: float,
        cwd: Optional[str | Path] = None,
        input_text: Optional[str] = None,
        env: Optional[Mapping[str, str]] = None,
        **_kwargs: Any,
    ) -> Any:
        """Run a literal pinned argv through the JevOps bounded process helper."""

        from jevops.outer import run_process

        result = run_process(
            [str(item) for item in command],
            cwd=cwd,
            env=env,
            timeout=float(timeout),
        )
        return SimpleNamespace(
            stdout=str(result.get("stdout") or ""),
            stderr=str(result.get("stderr") or ""),
            returncode=result.get("exit_code"),
            exit_code=result.get("exit_code"),
            timed_out=bool(result.get("timeout")),
            timeout=bool(result.get("timeout")),
            error=str(result.get("error") or ""),
            cwd=str(result.get("cwd") or cwd or ""),
        )


    def audit_lean_frontend_path_json() -> dict[str, Any]:
        """Report the optional frontend gap without claiming it ran."""

        return {
            "available": False,
            "unchanged_path_lean_json": True,
            "capability_gap": "optional ipfs_datasets_py frontend unavailable",
        }

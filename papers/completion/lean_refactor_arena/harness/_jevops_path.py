"""Resolve the current JevOps checkout and optional LRA dependencies.

The Arena harness is intentionally usable without the private accelerator or
dataset repositories.  When those repositories are present, callers may use
them through these pinned paths; when they are absent, the harness reports a
capability gap instead of importing a host-specific absolute path or silently
falling back to a different provider.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

JEVOPS_ROOT = Path(__file__).resolve().parents[4]
if not JEVOPS_ROOT.is_dir():
    JEVOPS_ROOT = Path.home() / "lift_coding" / "JevOps"
if JEVOPS_ROOT.is_dir() and str(JEVOPS_ROOT) not in sys.path:
    sys.path.insert(0, str(JEVOPS_ROOT))


def _env_path(*names: str) -> Path | None:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return Path(value).expanduser()
    return None


def _first_existing(candidates: tuple[Path, ...]) -> Path:
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


# Keep all optional external-repository resolution in one place.  The sibling
# candidate preserves the layout used by the research checkout while the
# in-repository candidate makes a vendored/CI checkout work without edits.
_ACCELERATE_CANDIDATES = (
    JEVOPS_ROOT / "external" / "ipfs_accelerate",
    JEVOPS_ROOT.parent / "external" / "ipfs_accelerate",
    JEVOPS_ROOT.parent / "ipfs_accelerate",
)
_DATASETS_CANDIDATES = (
    JEVOPS_ROOT / "external" / "ipfs_datasets",
    JEVOPS_ROOT.parent / "external" / "ipfs_datasets",
    JEVOPS_ROOT.parent / "ipfs_datasets",
)

IPFS_ACCELERATE_ROOT = _env_path(
    "JEVOPS_IPFS_ACCELERATE_PATH",
    "LRA_IPFS_ACCELERATE_PATH",
    "IPFS_ACCELERATE_PATH",
    "IPFS_ACCELERATE_ROOT",
) or _first_existing(_ACCELERATE_CANDIDATES)
IPFS_ACCELERATE_PY_ROOT = IPFS_ACCELERATE_ROOT / "ipfs_accelerate_py"
TYPESAFE_INFERENCE_PATH = IPFS_ACCELERATE_PY_ROOT / "typesafe_inference.py"
LLM_ROUTER_PATH = IPFS_ACCELERATE_PY_ROOT / "llm_router.py"

IPFS_DATASETS_ROOT = _env_path(
    "JEVOPS_IPFS_DATASETS_PATH",
    "LRA_IPFS_DATASETS_PATH",
    "IPFS_DATASETS_PATH",
) or _first_existing(_DATASETS_CANDIDATES)

SCRIPTS_ROOT = _env_path("JEVOPS_SCRIPTS_PATH", "LRA_SCRIPTS_PATH") or _first_existing(
    (JEVOPS_ROOT / "scripts", JEVOPS_ROOT.parent / "scripts")
)

LRA_STATE_ROOT = _env_path("LRA_STATE_ROOT") or (
    Path.home() / ".local" / "state" / "ipfs_accelerate_py" / "vericodegen-2026-lra"
)
LRA_ARTIFACT_ROOT = _env_path("LRA_ARTIFACT_ROOT") or (LRA_STATE_ROOT / "artifacts")
LRA_CANARY_ROOT = _env_path("LRA_CANARY_ROOT") or (LRA_ARTIFACT_ROOT / "canaries")
LRA_NCA_ROOT = _env_path("LRA_NCA_ROOT") or (LRA_ARTIFACT_ROOT / "nca")
LRA_CAS_ROOT = _env_path("LRA_CAS_ROOT") or (LRA_ARTIFACT_ROOT / "cas")
TYPESAFE_KEYFILE = _env_path("LRA_TYPESAFE_KEYFILE", "TYPESAFE_KEYFILE") or (
    Path.home() / ".config" / "ipfs_accelerate_py" / "typesafe.env"
)


def ensure_ipfs_accelerate_path() -> None:
    """Opt in to imports from the configured accelerator checkout."""

    if not IPFS_ACCELERATE_ROOT.is_dir():
        return
    from jevops.outer import ensure_sys_path

    ensure_sys_path(IPFS_ACCELERATE_ROOT)

os.environ.setdefault("JEVOPS_CAS_DIR", str(LRA_CAS_ROOT))

def activate_lra_hooks() -> None:
    """Opt in to paper-consumer hooks for an actual harness process.

    Importing a benchmark adapter must not mutate the global JevOps kernel
    registry in a caller's process.  CLI entry points may call this explicitly
    when they want the full LRA consumer surface.
    """

    try:
        import _jevops_hooks

        _jevops_hooks.register_lra_hooks()
    except Exception:
        pass


if os.environ.get("JEVOPS_REGISTER_LRA_HOOKS") == "1":
    activate_lra_hooks()

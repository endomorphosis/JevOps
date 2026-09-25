"""JevOps: TypeSafe/Jev kernel, including Lean folds/binders/tactics/lake helpers.

Kernel never writes Lean. Lake (or other oracles) live in consumers.
Kernel cache hits never admit proofs; proof_ca validates typed cached evidence
before reusing an existing verification receipt. Never docker0.
"""

import sys
from pathlib import Path

# The legal compiler and parser live in this workspace. Prefer that tree over
# another checkout registered by an editable install, so the two cannot drift.
_WORKSPACE_DATASETS = Path(__file__).resolve().parents[2] / "external" / "ipfs_datasets"
if _WORKSPACE_DATASETS.is_dir():
    _workspace_entry = str(_WORKSPACE_DATASETS)
    if _workspace_entry in sys.path:
        sys.path.remove(_workspace_entry)
    sys.path.insert(0, _workspace_entry)

from jevops import (
    autoencoder,
    autoresearch,
    binders,
    board,
    catalogs,
    folds,
    graph,
    harness,
    hooks,
    inits,
    int_rankers,
    jev,
    jsonld,
    kernel,
    llm_router,
    lean,
    mask,
    memory,
    more_rankers,
    nca,
    oracle,
    outer,
    pick,
    plan,
    program,
    proof_ca,
    rankers,
    repair,
    router_tuning,
    search,
    skill_tree,
    stack,
    tactics,
    tape,
    tape_tools,
    temporal,
    typesafe_inference,
    tools,
    turing,
    walk,
)

__all__ = [
    "autoencoder",
    "autoresearch",
    "binders",
    "board",
    "catalogs",
    "folds",
    "graph",
    "harness",
    "hooks",
    "inits",
    "int_rankers",
    "jev",
    "jsonld",
    "kernel",
    "llm_router",
    "lean",
    "mask",
    "memory",
    "more_rankers",
    "nca",
    "oracle",
    "outer",
    "pick",
    "plan",
    "program",
    "proof_ca",
    "rankers",
    "repair",
    "router_tuning",
    "search",
    "skill_tree",
    "stack",
    "tactics",
    "tape",
    "tape_tools",
    "temporal",
    "typesafe_inference",
    "tools",
    "turing",
    "walk",
]

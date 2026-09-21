#!/usr/bin/env python3
"""Emit native LRA objective heap + todo board from the reviewed task seed."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAPER = "lean_refactor_arena"
NS = "vericodegen-2026-lean_refactor_arena"
HEAP = f"papers/completion/{PAPER}/paper.objectives.md"
TODO = f"papers/completion/{PAPER}/paper.todo.md"
PREFIX = "LRA-"
VERIFY = "python3 scripts/paper_supervisors.py verify-task --paper lean_refactor_arena --task {id}"

GOAL = (
    "Ship a Leanstral-backed local harness in this repo that rewrites warm-up "
    "proof bodies under Lean-as-oracle, without inventing Arena scores or treating "
    "Spark NVFP4 wall-clock as official Track 2."
)

SUBGOALS = [
    ("LRA-S01", "Leanstral generate_text and docker0 HTTP client",
     "Fail-closed generate_text against live docker0 Leanstral; never LOCK_EX; never a second llama-server."),
    ("LRA-S02", "Prefix splice and lexical admission",
     "Bind statement via src.startswith(statement) on all 15 warm-up records; admit tactic blocks only."),
    ("LRA-S03", "Lake compile toolchain and dedicated verifier",
     "Pin elan tags, bake oleans, compile one Strata file then all tags, fail-closed verify_lra_batch."),
    ("LRA-S04", "Warm-up loop v1 on this machine",
     "run_warmup.py: splice, Leanstral when /health is ok, lexical admit, lake compile, keep-best. Unscored."),
    ("LRA-S05", "TypeSafe Jev distill after v1",
     "Optional typed gates via ipfs_accelerate_py.typesafe_inference. Off on official Track 2."),
    ("LRA-S06", "Optional Track 1 budget path",
     "Prepare grok+Jev in-loop under US$3/problem. Not the default winning path."),
    ("LRA-S07", "Deferred lake-native hammers and JSONL retrieval",
     "Loop v2 only. Do not claim LeanFrontend.snapshot_goal is lake-ready."),
    ("LRA-S08", "Optional INSERT-only proof receipts",
     "Filesystem receipts remain authority for warm-up. DuckDB INSERT-only if used."),
    ("LRA-S09", "Official Track 2 gate",
     "SM80 GGUF derived from Frosty40 NVFP4 plus named 4xA100 by 2026-10-15, or do not enter Track 2."),
    ("LRA-S10", "Manuscript measured section and human submission",
     "Fill Approach/Models/Budget only from receipts. Submission is manual."),
]

TASKS = [
    dict(id="LRA-010", subgoal="LRA-S01", title="Thin fail-closed Leanstral generate_text entry point",
         priority="P0", depends=[], resource="cpu-medium", lane="lra-cpu-a",
         timeout=7200, status="todo", completion="auto",
         deliverables=["papers/completion/lean_refactor_arena/harness/generate_text.py",
                       "papers/completion/lean_refactor_arena/harness/lra_prompt.txt"],
         acceptance=["generate_text uses provider=leanstral_local, model_name=Leanstral, temperature=0.0, allow_local_fallback=False, allow_cross_provider_fallback=False, disable_model_retry=True.",
                     "Unreachable docker0 fails closed without Grok/HF fallback; receipts record resolved provider/model.",
                     "No LOCK_EX; no second llama-server; no compile; no Arena scores."],
         description="Implement papers/completion/lean_refactor_arena/harness/generate_text.py as an HTTP client of 172.17.0.1:8080. Probe /health. Call ipfs_accelerate_py.llm_router.generate_text with fail-closed kwargs. Do not import LeanstralProofProvider. Do not start llama-server. Do not claim scores."),
    dict(id="LRA-011", subgoal="LRA-S02", title="Prefix splice tests on all 15 warm-up records",
         priority="P0", depends=[], resource="cpu-medium", lane="lra-cpu-b",
         timeout=3600, status="todo", completion="auto",
         deliverables=["papers/completion/lean_refactor_arena/harness/splice.py",
                       "papers/completion/lean_refactor_arena/harness/test_splice.py"],
         acceptance=["Every warm-up record satisfies src.startswith(statement); body is the suffix after the statement.",
                     "Never scan for the first :=; named := inside types remains part of the frozen statement.",
                     "Unit test covers all 15 records; SHA-256 of the JSONL remains 6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804."],
         description="JSONL splice is src.startswith(statement). ArkLib/CSLib statements contain := in types. Write harness/splice.py and a unit test over data/benchmark_data_warmup.jsonl. Lexical admission uses statement + ' := by\\nsorry' plus tactic-only proof_text."),
    dict(id="LRA-012", subgoal="LRA-S03", title="Tag-pinned Lean/lake toolchain resolver",
         priority="P0", depends=[], resource="cpu-medium", lane="lra-cpu-c",
         timeout=3600, status="todo", completion="auto",
         deliverables=["external/ipfs_datasets/ipfs_datasets_py/logic/hammers/frontends/lean_toolchain.py"],
         acceptance=["Resolver returns tag-pinned elan lean and lake paths from JSONL version_info.",
                     "EnvironmentLockRecord is populated via executable_paths, not primary_executable.",
                     "LeanFrontend PATH lean --json behavior is unchanged."],
         description="Add lean_toolchain.py next to hammers/frontends/lean.py. Compile worker will use run_lean_process. Do not make LeanFrontend.snapshot_goal lake-aware in this task."),
    dict(id="LRA-013", subgoal="LRA-S03", title="Bake lake oleans and Putnam Mathlib lake projects",
         priority="P0", depends=["LRA-012"], resource="cpu-heavy", lane="lra-cpu-c",
         timeout=7200, status="todo", completion="auto",
         deliverables=["papers/completion/lean_refactor_arena/harness/putnam_lake/README.md",
                       "papers/completion/lean_refactor_arena/harness/bake_oleans.py"],
         acceptance=["Strata v4.26 olean bake is recorded first; missing cache fails closed under network=deny.",
                     "Putnam is a per-tag Mathlib+Aesop lake project, not Tmp.lean.",
                     "No Arena scores."],
         description="First lake build is hours. Bake oleans before the 48h clock. Putnam records have empty url/file_path and import Mathlib/Aesop."),
    dict(id="LRA-014", subgoal="LRA-S03", title="Multi-tag lake compile worker starting with one Strata file",
         priority="P0", depends=["LRA-011", "LRA-012", "LRA-013"], resource="cpu-heavy", lane="lra-cpu-c",
         timeout=7200, status="todo", completion="auto",
         deliverables=["papers/completion/lean_refactor_arena/harness/compile_worker.py"],
         acceptance=["One Strata module compiles via lake env lean with finite measurement maxHeartbeats.",
                     "Per-tag timeout and axiom-digest receipts are written.",
                     "IndependentKernelVerifier 30s default is not the lake oracle."],
         description="Cached clone, checkout commit, lake env lean. Measurement command forces finite maxHeartbeats even if Putnam headers zero it. Expand tags after one file is green."),
    dict(id="LRA-015", subgoal="LRA-S03", title="Dedicated verify_lra_batch fail-closed verifier",
         priority="P0", depends=["LRA-014"], resource="cpu-medium", lane="lra-cpu-b",
         timeout=3600, status="todo", completion="auto",
         deliverables=["papers/completion/lean_refactor_arena/tools/verify_lra_batch.py"],
         acceptance=["Verifier requires digest, statement-bind, all listed tags, no sorryAx, one receipt per scheduled problem.",
                     "Does not import law_to_action verify_batch.py.",
                     "Does not write Arena scores."],
         description="Copy the fail-closed pattern from law_to_action verify_batch without sharing that missing path. --require-complete."),
    dict(id="LRA-016", subgoal="LRA-S01", title="Docker0 HTTP client; never owner LOCK_EX",
         priority="P0", depends=["LRA-010"], resource="cpu-medium", lane="lra-cpu-a",
         timeout=3600, status="todo", completion="auto",
         deliverables=["papers/completion/lean_refactor_arena/harness/docker0_client.py"],
         acceptance=["Probe http://172.17.0.1:8080/health; if healthy, generate_text as client without LOCK_EX.",
                     "IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART=0; never start a second llama-server.",
                     "If unhealthy and gpu-0.lock free, may exec run_leanstral_ephemeral.py --bind docker0 --gpu 0; if EX held, wait or skip LLM."],
         description="gpu-0.lock is the owner lock held by law_to_action / run_leanstral_ephemeral.py. LRA is a client of the live server."),
    dict(id="LRA-017", subgoal="LRA-S04", title="run_warmup.py loop v1 using Leanstral on this machine",
         priority="P0", depends=["LRA-014", "LRA-016"], resource="gpu-leanstral", lane="lra-gpu",
         timeout=7200, status="todo", completion="auto",
         deliverables=["papers/completion/lean_refactor_arena/harness/run_warmup.py"],
         acceptance=["When /health is ok, loop v1 MUST call Leanstral; skip generate only if docker0 is down.",
                     "Loop is splice, optional generate, lexical admit, lake compile, keep-best; hammers and TypeSafe off.",
                     "Failures retained; no Arena scores; hardware_class=spark_gb10."],
         description="Primary execution path. Exclusive GPU client of 172.17.0.1:8080. Transfer is a hard filter; composite is tokens+elab among valid candidates. Reference proof is a legal no-op if generate is skipped."),
    dict(id="LRA-018", subgoal="LRA-S04", title="Warm-up runbook wired to verify_lra_batch",
         priority="P0", depends=["LRA-015", "LRA-017"], resource="gpu-leanstral", lane="lra-gpu",
         timeout=7200, status="todo", completion="auto",
         deliverables=["papers/completion/lean_refactor_arena/harness/RUNBOOK.md",
                       "papers/completion/lean_refactor_arena/evidence/run_freeze.json"],
         acceptance=["Operator command runs 15 problems on Spark with hardware_class=spark_gb10.",
                     "Completing requires verify_lra_batch --require-complete PASS.",
                     "Does not write Arena scores into the manuscript."],
         description="Freeze file schema plus runbook. Completing this task is not official Track 2."),
    dict(id="LRA-019", subgoal="LRA-S05", title="TypeSafe Jev router via in-tree typesafe_inference",
         priority="P1", depends=["LRA-017"], resource="cpu-medium", lane="lra-cpu-a",
         timeout=7200, status="todo", completion="auto",
         deliverables=["papers/completion/lean_refactor_arena/harness/typesafe_router.py"],
         acceptance=["Imports ipfs_accelerate_py.typesafe_inference, not a second typesafe_sdk client.",
                     "Default LRA_TYPESAFE=off; distill uses LRA_TYPESAFE=distill; official Track 2 stays off.",
                     "Score is a rubric index; Jev does not generate Lean."],
         description="TYPESAFE_API_KEY will exist. Frozen ROUTE_QUESTIONS. CI fixtures without live key. Additive on top of Leanstral, not a replacement."),
    dict(id="LRA-020", subgoal="LRA-S06", title="Optional Track 1 US$3 ledger and grok adapter",
         priority="P1", depends=["LRA-017", "LRA-019"], resource="cpu-medium", lane="lra-cpu-a",
         timeout=7200, status="todo", completion="auto",
         deliverables=["papers/completion/lean_refactor_arena/harness/track1_ledger.py"],
         acceptance=["Hard stop at US$3/problem including Jev+grok.",
                     "Not the default winning path; skip if keys missing.",
                     "Does not contaminate Track 2 receipts."],
         description="Closed generator is grok/grok-4.6 through llm_router.generate_text. Prepare, do not default."),
    dict(id="LRA-021", subgoal="LRA-S07", title="Lake-native tactic try without snapshot_goal",
         priority="P1", depends=["LRA-014"], resource="cpu-heavy", lane="lra-cpu-c",
         timeout=7200, status="todo", completion="auto",
         deliverables=["papers/completion/lean_refactor_arena/harness/lake_native_try.py"],
         acceptance=["Loop v2 path A uses lake env lean tactic try; does not require LeanFrontend.snapshot_goal.",
                     "Does not claim HAMMER-006 is LRA-ready.",
                     "Not on the 30 Sep critical path."],
         description="Deferred. PATH lean --json cannot see lake-project goals."),
    dict(id="LRA-022", subgoal="LRA-S07", title="Premise retrieval from 14 JSONL neighbors plus src lemmas",
         priority="P1", depends=["LRA-011"], resource="cpu-medium", lane="lra-cpu-b",
         timeout=3600, status="todo", completion="auto",
         deliverables=["papers/completion/lean_refactor_arena/harness/retrieve.py"],
         acceptance=["Retrieves other warm-up proofs and lemmas mentioned in src (simp/rw/exact).",
                     "No Mathlib-scale CorpusManifest ingest.",
                     "No invented scores."],
         description="Deferred. Do not parse Lean ourselves."),
    dict(id="LRA-023", subgoal="LRA-S08", title="Optional DuckDB INSERT-only proof receipts",
         priority="P2", depends=["LRA-015"], resource="cpu-medium", lane="lra-cpu-b",
         timeout=3600, status="todo", completion="auto",
         deliverables=["papers/completion/lean_refactor_arena/harness/receipt_store.py"],
         acceptance=["INSERT-only; no DELETE of existing edges; no upsert_task of huge parent rows.",
                     "All PROOF_AUTHORITY_DIMENSIONS populated; executable_paths not primary_executable.",
                     "run_warmup.py remains the control plane."],
         description="Learned from LA-031 ART crashes. Filesystem receipts are enough for warm-up."),
    dict(id="LRA-024", subgoal="LRA-S09", title="SM80 GGUF derived from Frosty40 NVFP4",
         priority="P2", depends=[], resource="cpu-heavy", lane="lra-cpu-c",
         timeout=7200, status="blocked", completion="auto",
         deliverables=["papers/completion/lean_refactor_arena/evidence/run_freeze.json"],
         acceptance=["Export is derived from Frosty40 revision abcc5ce2528c6375148d41dac6dce20f06c339f4 CID bafkreicgnd6su3jhmtpckbejqurdb2lchdvvydluswdg5m5zy3cpvroh3i.",
                     "New SHA recorded in evidence/run_freeze.json; do not cite unpublished SHA 3fe4e64d.",
                     "If no named 4xA100 by 2026-10-15, do not enter Track 2."],
         description="Blocked until an operator names a cluster and produces the SM80 artifact. NVFP4-on-Spark is resource=spark_gb10 only."),
    dict(id="LRA-025", subgoal="LRA-S09", title="Official Track 2 runner gated on cluster and SM80 GGUF",
         priority="P2", depends=["LRA-018", "LRA-024"], resource="gpu-a100", lane="lra-gpu",
         timeout=7200, status="blocked", completion="auto",
         deliverables=["papers/completion/lean_refactor_arena/harness/run_official_track2.py"],
         acceptance=["Records GPU inventory must be 4xA100 80GB; 48h wall clock; typesafe off; network=deny.",
                     "Cannot import Spark scorer aggregation.",
                     "If LRA-024 did not land by 2026-10-15, this task stays blocked."],
         description="Gated. Spark measurements are not official Track 2 scores."),
    dict(id="LRA-026", subgoal="LRA-S10", title="Fill manuscript measured sections from receipts only",
         priority="P1", depends=["LRA-018"], resource="cpu-medium", lane="lra-cpu-b",
         timeout=3600, status="todo", completion="auto",
         deliverables=["papers/completion/lean_refactor_arena/manuscript/main.tex"],
         acceptance=["Approach/Models/Budget/Reproduction updated only from receipts; unrun rows stay unrun.",
                     "No invented leaderboard ranks or general token savings.",
                     "Author line remains Benjamin Barber / starworks5@gmail.com unless explicitly changed."],
         description="If incomplete, keep unrun labels. Protocol LRA/v1 grows only if claims grow."),
    dict(id="LRA-027", subgoal="LRA-S10", title="Human Arena Space / OpenReview submission",
         priority="P2", depends=["LRA-026"], resource="cpu-small", lane="lra-cpu-b",
         timeout=3600, status="blocked", completion="manual",
         deliverables=["papers/completion/lean_refactor_arena/evidence/submission_decision.json"],
         acceptance=["Not authorized for automated completion.",
                     "Human author action only.",
                     "No workflow upload."],
         description="Blocked. Completion=manual. Do not submit from a worker."),
]


def emit_objectives() -> str:
    lines = [
        "# Lean Refactor Arena — objective heap",
        "",
        f"Reviewed scope: `papers/completion/{PAPER}/review.md`. Executable board: `papers/completion/{PAPER}/paper.todo.md`.",
        "",
        "A completed LRA board means Leanstral + in-repo `run_warmup.py` ran on this machine under Lean-as-oracle,",
        "with fail-closed receipts and no invented Arena scores. It does not mean official Track 2, OpenReview upload,",
        "or treating Spark NVFP4 wall-clock as 4×A100.",
        "",
        "## LRA-G000 Complete the Leanstral local harness and honest competition report",
        "",
        "- Status: active",
        "- Parent:",
        "- Depends on:",
        "- Fib priority: 1",
        "- Priority: P0",
        "- Track: lean_refactor_arena",
        "- Bundle: lean_refactor_arena/LRA-G000",
        f"- Goal: {GOAL}",
        f"- Outputs: {', '.join(dict.fromkeys(p for t in TASKS for p in t['deliverables']))}",
        f"- Gap task: {', '.join(t['id'] for t in TASKS)}",
        "- Acceptance: Linked task criteria have current artifact and validation evidence; numerical claims trace to real runs; unrun official rows stay unrun.",
        "- Validation: python3 scripts/paper_supervisors.py verify-goal --paper lean_refactor_arena --goal LRA-G000",
        "",
    ]
    for i, (gid, title, desc) in enumerate(SUBGOALS, start=2):
        tasks = [t for t in TASKS if t["subgoal"] == gid]
        outputs = list(dict.fromkeys(p for t in tasks for p in t["deliverables"]))
        lines.extend([
            f"## {gid} {title}",
            "",
            "- Status: active",
            "- Parent: LRA-G000",
            "- Depends on:",
            f"- Fib priority: {i}",
            "- Priority: P0" if any(t["priority"] == "P0" for t in tasks) else "- Priority: P1",
            "- Track: lean_refactor_arena",
            f"- Bundle: lean_refactor_arena/{gid}",
            f"- Goal: {desc}",
            f"- Outputs: {', '.join(outputs)}",
            f"- Gap task: {', '.join(t['id'] for t in tasks)}",
            "- Acceptance: Linked task criteria have current artifact and validation evidence; numerical claims trace to real runs; unrun official rows stay unrun.",
            f"- Validation: python3 scripts/paper_supervisors.py verify-goal --paper lean_refactor_arena --goal {gid}",
            "",
        ])
    return "\n".join(lines)


def emit_todo() -> str:
    lines = [
        "# Lean Refactor Arena — implementation taskboard",
        "",
        "Read `papers/completion/lean_refactor_arena/review.md` and `papers/completion/lean_refactor_arena/design_win_plan.md` before work.",
        f"Objective heap: `{HEAP}`. Board namespace: `{NS}`.",
        "",
        "Primary path: Leanstral on live docker0 (`172.17.0.1:8080`) + in-repo `harness/run_warmup.py`.",
        "Never invent Arena scores. Spark NVFP4 is not official Track 2. Jev does not generate Lean.",
        "Implement in native ephemeral worktrees. GPU tasks are exclusive clients of docker0; do not LOCK_EX.",
        "Each task writes its receipt using the contract in the runbook.",
        "",
    ]
    for t in TASKS:
        receipt = f"papers/completion/{PAPER}/receipts/{t['id']}.json"
        snapshots = f"papers/completion/{PAPER}/receipts/snapshots/{t['id']}/"
        outputs = t["deliverables"] + [receipt]
        predicted = outputs + [snapshots]
        allowed = [
            f"papers/completion/{PAPER}/harness/",
            f"papers/completion/{PAPER}/tools/",
            f"papers/completion/{PAPER}/evidence/",
            f"papers/completion/{PAPER}/manuscript/",
            f"papers/completion/{PAPER}/receipts/",
        ]
        if t["id"] == "LRA-012" or t["id"] == "LRA-021":
            allowed.append("external/ipfs_datasets/ipfs_datasets_py/logic/hammers/")
        if t["id"] in {"LRA-010", "LRA-016", "LRA-019"}:
            allowed.append("external/ipfs_accelerate/ipfs_accelerate_py/")
        acc = "; ".join(t["acceptance"])
        lines.extend([
            f"## {t['id']} {t['title']}",
            "",
            f"- Status: {t['status']}",
            f"- Completion: {t['completion']}",
            f"- Is schedulable: {'false' if t['completion'] == 'manual' else 'true'}",
            f"- Review only: false",
            f"- Priority: {t['priority']}",
            "- Track: lean_refactor_arena",
            f"- Depends on: {', '.join(t['depends'])}",
            f"- Goal id: {t['subgoal']}",
            "- Parent goal: LRA-G000",
            f"- Objective heap: {HEAP}",
            f"- Board namespace: {NS}",
            f"- Bundle: lean_refactor_arena/{t['subgoal']}",
            f"- Parallel lane: {t['lane']}",
            f"- Outputs: {', '.join(outputs)}",
            f"- Predicted files: {', '.join(predicted)}",
            f"- Allowed paths: {', '.join(allowed)}",
            f"- Resource class: {t['resource']}",
            "- Resource stage: execution",
            f"- Implementation timeout seconds: {t['timeout']}",
            f"- Validation: {VERIFY.format(id=t['id'])}",
            f"- Acceptance: {acc}",
            "- Paper evidence: design_win_plan.md; protocol.md LRA/v1; frozen warmup SHA-256 6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804",
            "- Reuse candidates: papers/completion/lean_refactor_arena/design_win_plan.md, scripts/run_leanstral_ephemeral.py",
            f"- Receipt: {receipt}",
            "",
            t["description"],
            "",
            "Acceptance criteria:",
            "",
        ])
        for i, item in enumerate(t["acceptance"], 1):
            lines.append(f"{i}. {item}")
        lines.extend([
            "",
            "Record dependencies, exact code/data/model/tool versions, actual command logs, failures and claim limitations in the receipt.",
            "",
        ])
    return "\n".join(lines)


def emit_tasks_json() -> dict:
    return {
        "paper_id": PAPER,
        "title": "Warm-up Characterization and an Open-Weight Harness for Lean Refactor Arena",
        "pdf": "papers/completion/lean_refactor_arena/manuscript/main.pdf",
        "goal": GOAL,
        "subgoals": [{"id": gid, "title": title, "description": desc} for gid, title, desc in SUBGOALS],
        "tasks": [
            {
                "id": t["id"],
                "subgoal_id": t["subgoal"],
                "title": t["title"],
                "priority": t["priority"],
                "depends_on": t["depends"],
                "paper_evidence": [
                    "design_win_plan.md",
                    "protocol.md LRA/v1",
                    "frozen warmup SHA-256 6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804",
                ],
                "description": t["description"],
                "acceptance_criteria": t["acceptance"],
                "deliverables": t["deliverables"],
                "suggested_code_paths": [
                    "papers/completion/lean_refactor_arena/design_win_plan.md",
                    "scripts/run_leanstral_ephemeral.py",
                ],
                "implementation_paths": [],
            }
            for t in TASKS
        ],
    }


def main() -> None:
    (ROOT / "paper.objectives.md").write_text(emit_objectives(), encoding="utf-8")
    (ROOT / "paper.todo.md").write_text(emit_todo(), encoding="utf-8")
    (ROOT / "tasks.json").write_text(json.dumps(emit_tasks_json(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(SUBGOALS)} subgoals, {len(TASKS)} tasks")


if __name__ == "__main__":
    main()

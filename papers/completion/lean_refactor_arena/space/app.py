"""Lean Refactor Arena — competition UI.

This Space is UI-only. It renders the site, accepts submissions, and shows
progress + leaderboards. All Lean compilation and scoring happens on a
dedicated evaluation worker that talks to this Space exclusively through the
storage bucket mounted at /data:

  uploads/<user>/<ts>.jsonl     submission archive        (written here)
  artifacts/<user>/<ts>/        code bundle               (written here)
  jobs/pending/<sid>.json       job queue                 (written here,
                                                           consumed by worker)
  status/<user>.json            per-user progress         (written by worker,
                                                           polled here)
  leaderboard.json              scored results            (written by worker,
                                                           read here)
  worker/heartbeat.json         worker liveness           (written by worker)
  compat_logs/...               full compile logs         (written by worker)

Nothing in this container installs or runs Lean.
"""

import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path

import gradio as gr
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from markdown_it import MarkdownIt

from benchmark import (
    BENCHMARK,
    SOURCES,
    benchmark_file_link,
    benchmark_header,
    benchmark_names,
    benchmark_signature,
    benchmark_source,
    benchmark_versions,
    original_heartbeats,
    original_length,
)
from leaderboard import Leaderboard


# ── Storage plumbing ──────────────────────────────────────────────────────────
def _data_root() -> Path:
    """Bucket mount if present, else a local dir (dev runs outside HF).

    `LRA_DATA_DIR` overrides both, so a developer can point the app at a
    local mirror of the bucket without touching the live one."""
    override = os.environ.get("LRA_DATA_DIR")
    if override:
        d = Path(override)
        d.mkdir(parents=True, exist_ok=True)
        return d
    persistent = Path("/data")
    if persistent.is_dir() and os.access(persistent, os.W_OK):
        return persistent
    d = Path("/tmp/lra-data")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _uploads_dir() -> Path:
    d = _data_root() / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _artifacts_dir() -> Path:
    d = _data_root() / "artifacts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _jobs_pending_dir() -> Path:
    d = _data_root() / "jobs" / "pending"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _status_root() -> Path:
    d = _data_root() / "status"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_user(user: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", user)[:40] or "anon"


def _sanitize(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]", "_", name or "")[:60]
    return s or "Anon"


def _safe_component(value: str, *, default: str = "_") -> str:
    """A single path component safe to join under a data dir: no separators,
    no `..`, restricted charset. Blocks path traversal from user/worker-
    supplied submission_id / version fields."""
    s = re.sub(r"[^A-Za-z0-9._-]", "_", str(value or ""))[:80]
    s = s.replace("..", "_")
    return s or default


def _validate_user(user: str) -> str:
    user = (user or "").strip()
    if not user:
        raise ValueError("Username is required.")
    if len(user) > 40:
        raise ValueError("Username must be 40 characters or fewer.")
    if len(_user_key(user)) < 2:
        raise ValueError("Username must have at least 2 visible characters.")
    return user


# ── Username identity: one entry per name, owned by whoever claimed it ────────
# There is no login, so a username is claimed on first use: the submitter gets
# a one-time submission key, and later submissions under that name must present
# it. This is what makes usernames unique — two teams can't share a name, and
# nobody can overwrite a competitor's entry by typing their handle.
def _users_dir() -> Path:
    d = _data_root() / "users"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _user_key(user: str) -> str:
    """Identity key for a display name: case- and whitespace-insensitive, so
    `Team Alpha`, `team  alpha` and `TEAM ALPHA` are the same competitor
    rather than three leaderboard rows."""
    return re.sub(r"\s+", " ", (user or "")).strip().casefold()


def _claim_path(user: str) -> Path:
    digest = hashlib.sha256(_user_key(user).encode("utf-8")).hexdigest()[:32]
    return _users_dir() / f"{digest}.json"


def _load_claim(user: str) -> dict | None:
    try:
        p = _claim_path(user)
        return json.loads(p.read_text()) if p.is_file() else None
    except Exception:
        return None


def _hash_key(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def _mint_claim(user: str) -> tuple[str | None, str]:
    """Register `user`. Returns (key, "ok"), (None, "taken") if someone else
    claimed the name first, or (None, "error") if the write failed.

    Creation goes through `O_CREAT | O_EXCL`, which is atomic and — unlike
    `os.link` — is supported on the bucket mount, so two simultaneous
    first-time submitters still can't both claim the same name."""
    token = secrets.token_urlsafe(18)
    blob = json.dumps({
        "display": user,
        # The key is kept in the clear as well as hashed, so an organizer can
        # tell a competitor who lost theirs what it is. The bucket is private
        # and these are per-competition bearer tokens for "submit under this
        # name" — nothing else — so the recovery path is worth the exposure.
        # Verification still goes through the hash.
        "key": token,
        "key_hash": _hash_key(token),
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    p = _claim_path(user)
    try:
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return None, "taken"
    except OSError:
        fd = None
    if fd is not None:
        try:
            with os.fdopen(fd, "w") as f:
                f.write(blob)
            return token, "ok"
        except Exception:
            return None, "error"
    # Filesystem refused O_EXCL — fall back to check-then-write. The window is
    # tiny and losing it only means two submitters share a name, which the
    # organizers can untangle; refusing the submission outright would be worse.
    try:
        if p.exists():
            return None, "taken"
        p.write_text(blob)
        return token, "ok"
    except Exception:
        return None, "error"


def check_identity(user: str, submission_key: str) -> tuple[str, bool]:
    """Authorize `user` WITHOUT writing anything. Returns
    (canonical_display_name, is_new_name).

    Raises ValueError if the name is already claimed and the key doesn't
    match. The claim itself is minted later (`_mint_claim`), only once the
    submission is otherwise accepted — otherwise a rejected upload would burn
    the name and its key would never reach the submitter."""
    user = _validate_user(user)
    claim = _load_claim(user)
    if claim is None:
        return user, True
    supplied = (submission_key or "").strip()
    if not supplied or not hmac.compare_digest(
        _hash_key(supplied), str(claim.get("key_hash", ""))
    ):
        raise ValueError(
            f"the username **{html.escape(user)}** is already taken. If it is "
            "yours, paste the submission key you were given on your first "
            "submission. Otherwise pick a different username."
        )
    # Keep the originally claimed spelling so casing variants stay one entry.
    return str(claim.get("display") or user), False


def _archive_upload(user: str, source: str) -> tuple[str | None, str | None]:
    """Copy an uploaded JSONL into the bucket. Returns (abs_path, rel_path)."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    user_dir = _uploads_dir() / _safe_user(user)
    user_dir.mkdir(parents=True, exist_ok=True)
    dest = user_dir / f"{ts}.jsonl"
    try:
        shutil.copyfile(source, dest)
        return str(dest), f"uploads/{_safe_user(user)}/{ts}.jsonl"
    except Exception:
        return None, None


def _status_path(user: str) -> Path:
    return _status_root() / f"{_safe_user(user)}.json"


def _write_status(
    user: str, submission_id: str, status: str,
    rows: list, message: str,
) -> None:
    """Atomically persist the current submission status for `user`."""
    p = _status_path(user)
    payload = {
        "user": user,
        "submission_id": submission_id,
        "status": status,
        "progress_rows": rows,
        "message": message,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload))
        os.replace(tmp, p)
    except Exception:
        pass


def submission_status(user: str):
    """Read the persisted status for `user` (written by the evaluation
    worker). Returns (rows, status_md)."""
    user = (user or "").strip()
    if not user:
        return [], ""
    try:
        p = _status_path(user)
        if not p.exists():
            return [], ""
        d = json.loads(p.read_text())
    except Exception:
        return [], ""
    rows = d.get("progress_rows", []) or []
    msg = d.get("message", "") or ""
    status = d.get("status", "")
    ts = d.get("ts", "")
    prefix = {
        "queued": "📨", "running": "⏳", "done": "✅", "error": "❌",
    }.get(status, "")
    md = (f"{prefix} {msg}" if prefix else msg)
    if ts:
        md += f"  \n_updated {ts}_"
    return rows, md


def _enqueue_job(
    user: str, track: str, submission_id: str,
    upload_rel: str | None, num_rows: int,
) -> None:
    """Drop a job file for the evaluation worker to pick up."""
    payload = {
        "schema_version": 1,
        "user": user,
        "track": track,
        "submission_id": submission_id,
        "upload": upload_rel,
        "num_rows": num_rows,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    p = _jobs_pending_dir() / f"{submission_id}_{_safe_user(user)}.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.replace(tmp, p)


# ── Per-submission history ────────────────────────────────────────────────────
# `status/<user>.json` holds only the run in flight, and the leaderboard keeps
# a single record per user, so neither can answer "how did the submission I
# sent last Tuesday score?". Every submission therefore also gets its own
# record at `submissions/<user>/<sid>.json`, created when the job is queued and
# updated in place as the worker reports progress. The "My submissions" tab
# reads these back after checking the submitter's key.
def _submissions_root() -> Path:
    d = _data_root() / "submissions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _submission_dir(user: str) -> Path:
    return _submissions_root() / _safe_user(user)


def _update_submission(user: str, submission_id: str, **fields) -> None:
    """Merge `fields` into one submission's record, creating it if absent.

    Best-effort and atomic: the history is a convenience, so a failure here
    must never reject a submission or lose a worker report. `None` values are
    dropped rather than stored, so a partial update cannot blank a field an
    earlier one filled in."""
    sid = _safe_component(submission_id, default="")
    if not sid:
        return
    try:
        d = _submission_dir(user)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{sid}.json"
        rec: dict = {}
        if path.is_file():
            try:
                rec = json.loads(path.read_text()) or {}
            except Exception:
                rec = {}
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rec.setdefault("schema_version", 1)
        rec.setdefault("submission_id", sid)
        rec.setdefault("queued_at", now)
        rec["user"] = user
        rec.update({k: v for k, v in fields.items() if v is not None})
        rec["updated_at"] = now
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rec))
        os.replace(tmp, path)
    except Exception:
        pass


_SUMMARY_KEYS = (
    "avg_length_reduction_pct", "avg_heartbeat_reduction_pct",
    "avg_combined_pct", "avg_survival_rate", "num_compiled",
    "num_benchmark", "num_compat_passed", "num_compat_checks",
)


def _history_summary(record) -> dict:
    """The headline numbers of a scored run, copied out of the leaderboard
    record so this submission keeps them after the next one replaces it."""
    if not isinstance(record, dict):
        return {}
    return {k: record.get(k) for k in _SUMMARY_KEYS if k in record}


def _history_results(record, per_theorem: dict) -> dict:
    """Per-problem detail for one submission.

    The leaderboard record already carries the computed reductions and compat
    map, so it is the base; `per_theorem` adds the two flags the leaderboard
    drops (`rejected`, `statement_match`), which is what lets the UI tell a
    rejected proof apart from one that merely failed to compile."""
    base = {}
    if isinstance(record, dict):
        base = {k: dict(v) for k, v in (record.get("results") or {}).items()
                if isinstance(v, dict)}
    for name, row in (per_theorem or {}).items():
        if not isinstance(row, dict):
            continue
        dest = base.setdefault(name, {
            "compiled": bool(row.get("compiled")),
            "length": row.get("length"),
            "heartbeats": row.get("heartbeats"),
            "error": row.get("error", ""),
            "compat": row.get("compat") or {},
        })
        for flag in ("rejected", "statement_match"):
            if row.get(flag) is not None:
                dest[flag] = row[flag]
    return base


def _pending_sids(user: str) -> set:
    """Submission ids of this user's jobs still waiting on the worker."""
    safe = _safe_user(user)
    suffix = f"_{safe}.json"
    try:
        return {
            p.name[: -len(suffix)]
            for p in _jobs_pending_dir().glob(f"*{suffix}")
        }
    except Exception:
        return set()


def submission_history(user: str) -> list:
    """Every submission `user` has made, newest first.

    The per-submission records are the source of truth. Any archived upload
    without one — submitted before those records existed — is folded in as a
    summary-only entry, so the history never silently drops a submission the
    user actually made."""
    records: dict = {}
    try:
        for path in sorted(_submission_dir(user).glob("*.json")):
            try:
                rec = json.loads(path.read_text())
            except Exception:
                continue
            if isinstance(rec, dict):
                records[str(rec.get("submission_id") or path.stem)] = rec
    except Exception:
        pass

    safe = _safe_user(user)
    try:
        uploads = list((_uploads_dir() / safe).glob("*.jsonl"))
    except Exception:
        uploads = []
    for up in uploads:
        rec = records.setdefault(up.stem, {"submission_id": up.stem, "user": user})
        rec.setdefault("upload", f"uploads/{safe}/{up.name}")

    # The job file is the authority on whether a run is still outstanding: it
    # is written when the submission is accepted and consumed only when the
    # worker reports. A record can disagree — it was reconstructed by
    # scripts/backfill_submissions.py, or the run was scored by a build that
    # wrote no record — so reconcile against the queue rather than trusting a
    # stored "queued"/"running" that nothing will ever clear.
    pending = _pending_sids(user)
    for sid, rec in records.items():
        if sid in pending:
            if rec.get("status") != "running":
                rec["status"] = "queued"
        elif rec.get("status") in (None, "", "queued", "running"):
            rec["status"] = "done"
    return [records[sid] for sid in sorted(records, reverse=True)]


def _find_claim_by_key(submission_key: str):
    """The claim owning `submission_key`, so a submitter who remembers their
    key but not the exact spelling of their username can still get in."""
    wanted = _hash_key(submission_key)
    try:
        paths = sorted(_users_dir().glob("*.json"))
    except Exception:
        return None
    for path in paths:
        try:
            claim = json.loads(path.read_text())
        except Exception:
            continue
        if hmac.compare_digest(str(claim.get("key_hash") or ""), wanted):
            return claim
    return None


def authorize_viewer(user: str, submission_key: str) -> str:
    """Canonical display name for a submitter presenting `submission_key`.

    The username is optional — the key alone identifies the account. Raises
    ValueError with a message meant for the submitter."""
    key = (submission_key or "").strip()
    if not key:
        raise ValueError(
            "enter the submission key you were given on your first "
            "submission. It is the only thing that proves an entry is yours."
        )
    name = (user or "").strip()
    if name:
        claim = _load_claim(name)
        if claim is None:
            raise ValueError(
                "no submissions found under the username "
                f"<b>{html.escape(name)}</b>. Check the spelling, or leave "
                "the username blank and search by key alone."
            )
        if not hmac.compare_digest(
            _hash_key(key), str(claim.get("key_hash", ""))
        ):
            raise ValueError(
                "that key does not match the username "
                f"<b>{html.escape(name)}</b>."
            )
        return str(claim.get("display") or name)
    claim = _find_claim_by_key(key)
    if claim is None:
        raise ValueError(
            "no account matches that submission key. Keys are issued on your "
            "first successful submission — check the message you received "
            "then, or contact the organizers on Discord."
        )
    return str(claim.get("display") or "")


# ── Submission intake ─────────────────────────────────────────────────────────
# Patterns we refuse to accept in user proofs. Lean's `#eval` and `IO`
# primitives execute at elaboration time with full filesystem and process
# access on the evaluation worker; the rest are ways to bypass the kernel,
# fake a proof, or game the metrics. The evaluation worker enforces the same
# list — this early check just gives instant feedback at upload time.
_FORBIDDEN_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    ("#eval", re.compile(r"#\s*eval\b")),
    ("#reduce", re.compile(r"#\s*reduce\b")),
    ("IO.", re.compile(r"\bIO\.")),
    ("unsafe def/fun/theorem", re.compile(r"\bunsafe\s+(def|fun|theorem|lemma)\b")),
    ("extern", re.compile(r"\bextern\b")),
    ("initialize", re.compile(r"\binitialize\b")),
    ("@[implemented_by]", re.compile(r"@\[\s*implemented[_]?[Bb]y\b")),
    ("@[extern]", re.compile(r"@\[\s*extern\b")),
    ("sorry", re.compile(r"\bsorry\b")),
    ("sorryAx", re.compile(r"\bsorryAx\b")),
    ("admit", re.compile(r"\badmit\b")),
    ("axiom", re.compile(r"\baxiom\b")),
    ("native_decide", re.compile(r"\bnative_decide\b")),
    ("ofReduceBool", re.compile(r"\bofReduceBool\b")),
    ("ofReduceNat", re.compile(r"\bofReduceNat\b")),
    ("run_cmd", re.compile(r"\brun_cmd\b")),
    ("run_elab", re.compile(r"\brun_elab\b")),
    ("#exit", re.compile(r"#\s*exit\b")),
    ("#count_heartbeats", re.compile(r"#\s*count_heartbeats\b")),
    ("attribute command", re.compile(r"(?m)^\s*attribute\b")),
    ("macro/elab/notation", re.compile(
        r"\b(macro|macro_rules|elab|elab_rules|notation|syntax)\b")),
    ("deriving instance", re.compile(r"\bderiving\s+instance\b")),
    ("auxiliary declaration", re.compile(
        r"(?m)^\s*(def|abbrev|instance|structure|inductive|class|opaque)\b")),
]

# Real proofs are a few KB; anything past this is resource exhaustion.
_MAX_PROOF_BYTES = 256 * 1024


def _strip_lean_comments(text: str) -> str:
    """Drop `/- … -/` blocks (nested) and `--` line tails so comments can't
    trip the forbidden-pattern check. String-literal aware and a single O(n)
    scan — a regex here (`/-.*?-/`) both misses string-embedded delimiters
    (letting a proof hide `#eval` between two string literals) and goes
    quadratic on adversarial `/-` repetition. Mirrors the worker's
    `lra.lean_utils.remove_comments` scanner."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            out.append(c)
            i += 1
            while i < n:
                out.append(text[i])
                if text[i] == "\\" and i + 1 < n:
                    out.append(text[i + 1])
                    i += 2
                    continue
                if text[i] == '"':
                    i += 1
                    break
                i += 1
            continue
        if text.startswith("/-", i):
            depth, i = 1, i + 2
            while i < n and depth:
                if text.startswith("/-", i):
                    depth += 1
                    i += 2
                elif text.startswith("-/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            out.append(" ")
            continue
        if text.startswith("--", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _check_forbidden(code: str) -> str | None:
    if len(code) > _MAX_PROOF_BYTES:
        return f"too large (> {_MAX_PROOF_BYTES // 1024} KB)"
    stripped = _strip_lean_comments(code)
    for label, pat in _FORBIDDEN_PATTERNS:
        if pat.search(stripped):
            return label
    return None


TRACK_LABELS = {
    "Closed-source LLM": "closed",
    "Open-source LLM": "open",
}

# Submissions are live: the dedicated evaluation worker polls the job queue.
SUBMISSIONS_ENABLED = True
SUBMISSIONS_READY_DATE = "August 12, 2026"

# Code intake. Proofs are scored automatically; the code bundle is read by
# humans, so intake opens with the full benchmark rather than now. The tech
# report is *not* collected here — it goes to OpenReview (see OPENREVIEW_URL).
ARTIFACTS_ENABLED = False
CODE_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")

# A JSONL of benchmark proofs is well under a megabyte; cap intake so an
# oversized upload can't be persisted to the bucket or wedge validation.
_MAX_SUBMISSION_BYTES = 8 * 1024 * 1024
# Cap outstanding unscored jobs per user to blunt queue flooding.
_MAX_PENDING_PER_USER = 5


def verify_and_submit(user, submission_key, track_label, file):
    """Pre-validate a submission, archive it to the bucket, and enqueue a job
    for the evaluation worker. Returns immediately; the worker updates
    status/<user>.json as it compiles, which the UI polls."""
    if not SUBMISSIONS_ENABLED:
        return [], (
            "⚠️ **Submissions are not open yet.** Automated evaluation and "
            f"scoring is being prepared and will be ready by "
            f"**{SUBMISSIONS_READY_DATE}**. Please try again then."
        )
    # Usernames are unique: a name is owned by whoever claimed it first, and
    # re-submitting under it requires that submitter's key.
    try:
        user, is_new_name = check_identity(user, submission_key)
    except ValueError as e:
        return [], f"**Error:** {e}"
    track = TRACK_LABELS.get(track_label)
    if track is None:
        return [], "**Error:** pick a track (closed-source or open-source LLM)."
    if file is None:
        return [], "**Error:** upload a JSONL file."
    path = file if isinstance(file, str) else getattr(file, "name", None)
    if not path:
        return [], "**Error:** bad upload."

    # Reject oversized uploads before reading/copying them (a JSONL of
    # benchmark proofs is well under a megabyte).
    try:
        if os.path.getsize(path) > _MAX_SUBMISSION_BYTES:
            return [], (
                f"**Error:** file too large (limit "
                f"{_MAX_SUBMISSION_BYTES // (1024 * 1024)} MB)."
            )
    except OSError:
        return [], "**Error:** could not read upload."

    # Cheap pre-validation so obviously broken files never reach the worker.
    bench = set(benchmark_names())
    n_rows, n_scored, problems = 0, 0, []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for idx, raw in enumerate(f):
                if not raw.strip():
                    continue
                n_rows += 1
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError as e:
                    problems.append(f"line {idx + 1}: bad JSON ({str(e)[:80]})")
                    continue
                name = str(entry.get("name") or "")
                proof = str(entry.get("proof") or "")
                if not name or not proof:
                    problems.append(f"line {idx + 1}: needs `name` and `proof`")
                    continue
                bad = _check_forbidden(proof)
                if bad:
                    problems.append(f"`{name}`: proof contains `{bad}`, not allowed")
                    continue
                if name in bench:
                    n_scored += 1
    except Exception as e:
        return [], f"**Error:** could not read upload: {e}"

    if problems:
        listing = "\n".join(f"- {p}" for p in problems[:10])
        more = f"\n- …and {len(problems) - 10} more" if len(problems) > 10 else ""
        return [], f"**Rejected — fix these and re-upload:**\n{listing}{more}"
    if n_rows == 0:
        return [], "**Error:** the file has no rows."
    if n_scored == 0:
        return [], (
            "**Error:** no row names a benchmark theorem — nothing would be "
            "scored. Check `name` against the Benchmark tab."
        )

    # Don't let one user flood the queue: cap outstanding (unscored) jobs.
    safe = _safe_user(user)
    try:
        pending = list(_jobs_pending_dir().glob(f"*_{safe}.json"))
    except Exception:
        pending = []
    if len(pending) >= _MAX_PENDING_PER_USER:
        return [], (
            "**Error:** you already have "
            f"{len(pending)} submission(s) waiting to be scored. Please wait "
            "for those to finish before submitting again."
        )

    # The submission is good: claim the name now (first-time submitters only).
    minted_key = None
    if is_new_name:
        minted_key, why = _mint_claim(user)
        if minted_key is None:
            return [], (
                f"**Error:** the username **{html.escape(user)}** was just "
                "claimed by another submitter. Please choose a different one."
                if why == "taken" else
                "**Error:** could not register your username just now. "
                "Please try submitting again."
            )

    submission_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    _, rel = _archive_upload(user, path)
    if rel is None:
        return [], "**Error:** could not store the upload; try again."
    _enqueue_job(user, track, submission_id, rel, n_rows)
    queued_msg = (
        "Queued for the evaluation worker. Results appear here as each "
        "proof finishes compiling."
    )
    _write_status(user, submission_id, "queued", [], queued_msg)
    _update_submission(
        user, submission_id, track=track, status="queued", upload=rel,
        num_rows=n_rows, num_scored=n_scored, message=queued_msg,
    )
    key_note = (
        f"\n\n🔑 **Your submission key: `{minted_key}`**  \n"
        f"**Save it now — it is shown once.** `{html.escape(user)}` is now "
        "yours; you'll need this key to submit under that name again, to open "
        "**My submissions**, and it is what stops anyone else from "
        "overwriting your entry."
        if minted_key else ""
    )
    return [], (
        f"📨 **Submission queued** as `{user}` on the "
        f"**{track_label}** track ({submission_id}).  \n"
        f"{n_scored}/{n_rows} row(s) match benchmark theorems and will be "
        f"scored on the dedicated evaluation worker.  \n"
        f"**You can close this tab.** Open **My submissions** with your "
        f"submission key to follow this run and every earlier one, "
        f"problem by problem."
        f"{key_note}"
    )


def _upload_path(file) -> str | None:
    if file is None:
        return None
    return file if isinstance(file, str) else getattr(file, "name", None)


def submit_artifacts(user, submission_key, code_file):
    """Archive a team's code bundle to the bucket. Separate from the proof
    pipeline: it is read by the organizers, not scored, and may arrive long
    after the proofs — matched to the run by username. The tech report is not
    handled here at all; it is submitted to the workshop on OpenReview."""
    if not ARTIFACTS_ENABLED:
        return (
            "⚠️ **Code submission is not open yet.** It opens "
            f"with the full benchmark on **{FULL_BENCH_RELEASE}** — this page "
            "is here so you know what to prepare.\n\n"
            "**You can submit your proofs today** under the "
            "**Proofs** tab. Come back with the same username to "
            f"attach your code any time before {DEADLINE}.\n\n"
            f"**Your tech report does not go here.** Submit it on "
            f"[OpenReview]({OPENREVIEW_URL})."
        )
    # Same identity rule as proofs: the bundle is matched to a run by
    # username, so it must come from the submitter who owns that name.
    try:
        user, is_new_name = check_identity(user, submission_key)
    except ValueError as e:
        return f"**Error:** {e}"
    if is_new_name:
        return (
            "**Error:** no proof submission found under that username. "
            "Submit your proofs first (that is what reserves the name), then "
            "attach your code with the same username and submission key."
        )

    code_path = _upload_path(code_file)
    if not code_path:
        return "**Error:** attach a code archive."
    if not code_path.lower().endswith(CODE_SUFFIXES):
        return (
            "**Error:** the code bundle must be a "
            f"{' / '.join('`' + s + '`' for s in CODE_SUFFIXES)} archive."
        )

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest_dir = _artifacts_dir() / _safe_user(user) / ts
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        # Keep the full archive suffix — Path.suffix would clip .tar.gz.
        low = code_path.lower()
        suffix = max((s for s in CODE_SUFFIXES if low.endswith(s)), key=len)
        shutil.copyfile(code_path, dest_dir / f"code{suffix}")
    except Exception:
        return "**Error:** could not store the upload; try again."

    return (
        f"📦 **Received** as `{user}` — code{suffix} (`{ts}`).  \n"
        "The organizers review this by hand, so nothing else is needed "
        "unless we email you. You can upload again at any time; we read your "
        "most recent bundle.  \n"
        f"**Don't forget the tech report.** It is submitted separately on "
        f"[OpenReview]({OPENREVIEW_URL}), not here."
    )


# ── Admin endpoints (token-gated, hidden) ─────────────────────────────────────
def _check_admin_token(token: str) -> bool:
    expected = os.environ.get("ADMIN_RESET_TOKEN", "")
    return bool(expected) and token == expected


def admin_reset(token: str) -> str:
    """Wipe leaderboard + uploads + jobs + logs from /data. Token-gated."""
    if not _check_admin_token(token):
        return "denied"
    out = []
    data_dir = _data_root()
    lb = data_dir / "leaderboard.json"
    if lb.exists():
        lb.unlink()
        out.append("removed leaderboard.json")
    for sub in ("uploads", "compat_logs", "status", "jobs"):
        target = data_dir / sub
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
            out.append(f"removed {sub}/")
    LB.data = {"users": {}}
    LB.path.parent.mkdir(parents=True, exist_ok=True)
    return "ok: " + ", ".join(out) if out else "ok: nothing to remove"


def _compat_logs_root() -> Path | None:
    d = _data_root() / "compat_logs"
    return d if d.is_dir() else None


def compat_list(token: str, user: str = "", submission_id: str = "") -> str:
    """List stored compile logs (written by the worker). Token-gated."""
    if not _check_admin_token(token):
        return "denied"
    root = _compat_logs_root()
    if root is None:
        return "no logs"
    if not user:
        entries = sorted(p.name for p in root.iterdir() if p.is_dir())
        return "\n".join(entries) if entries else "(empty)"
    user_dir = root / _safe_user(user)
    if not user_dir.is_dir():
        return "not found"
    if not submission_id:
        entries = sorted(p.name for p in user_dir.iterdir() if p.is_dir())
        return "\n".join(entries) if entries else "(empty)"
    sub_dir = user_dir / _safe_component(submission_id)
    if not sub_dir.is_dir():
        return "not found"
    entries = sorted(p.name for p in sub_dir.iterdir() if p.is_file())
    return "\n".join(entries) if entries else "(empty)"


def compat_log(
    token: str, user: str, submission_id: str, name: str, version: str,
) -> str:
    """Return the full text of one compile log. Token-gated."""
    if not _check_admin_token(token):
        return "denied"
    root = _compat_logs_root()
    if root is None:
        return "no logs"
    ver_safe = _safe_component(version.replace(".", "_"))
    p = (root / _safe_user(user) / _safe_component(submission_id)
         / f"{_sanitize(name)}__{ver_safe}.log")
    if not p.is_file():
        return f"not found: {p}"
    try:
        return p.read_text()
    except Exception as e:
        return f"read error: {e}"


# ── Evaluation-worker endpoints (token-gated, hidden) ─────────────────────────
# The worker machine sits behind a firewall, so every interaction is an
# outbound call from it to these endpoints: poll the job queue, stream status,
# report the final scored record. The bucket has no external write API — the
# Space (owner of the /data mount) does all writes on the worker's behalf.
def _check_worker_token(token: str) -> bool:
    import hmac
    expected = os.environ.get("WORKER_TOKEN", "") or os.environ.get(
        "ADMIN_RESET_TOKEN", ""
    )
    return bool(expected) and hmac.compare_digest(token, expected)


_MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def worker_poll(token: str) -> str:
    """List pending jobs, each with its job payload and the uploaded JSONL
    content. Consuming a job happens in worker_report."""
    if not _check_worker_token(token):
        return json.dumps({"error": "denied"})
    jobs = []
    pending = _jobs_pending_dir()
    for p in sorted(pending.glob("*.json")):
        try:
            job = json.loads(p.read_text())
        except Exception:
            continue
        entry = {"job_file": p.name, "job": job, "upload_content": None}
        rel = job.get("upload")
        if rel:
            up = _data_root() / rel
            try:
                if up.is_file() and up.stat().st_size <= _MAX_UPLOAD_BYTES:
                    entry["upload_content"] = up.read_text(encoding="utf-8")
            except Exception:
                pass
        jobs.append(entry)
    return json.dumps({"jobs": jobs})


def worker_update(token: str, payload_json: str) -> str:
    """Persist in-flight progress for a user (the submit tab polls it)."""
    if not _check_worker_token(token):
        return json.dumps({"error": "denied"})
    try:
        d = json.loads(payload_json)
        status = d.get("status", "running")
        if status not in ("queued", "running", "done", "error"):
            status = "running"
        user = str(d.get("user") or "anon")
        sid = str(d.get("submission_id") or "")
        rows = d.get("progress_rows") or []
        message = str(d.get("message") or "")
        _write_status(user, sid, status, rows, message)
        _update_submission(
            user, sid, status=status, progress_rows=rows, message=message,
        )
        return json.dumps({"ok": True})
    except Exception as e:
        return json.dumps({"error": str(e)[:300]})


def worker_report(token: str, payload_json: str) -> str:
    """Final result of one job: store compat logs, record the submission on
    the worker leaderboard, consume the job file, and write final status."""
    if not _check_worker_token(token):
        return json.dumps({"error": "denied"})
    try:
        d = json.loads(payload_json)
        user = str(d.get("user") or "anon")
        sid = _safe_component(d.get("submission_id") or "", default="unknown")
        track = str(d.get("track") or "closed")
        # 1) compile logs -> /data/compat_logs/<user>/<sid>/  (all components
        # sanitized so a crafted submission_id/version can't escape the tree)
        logs_dir = _data_root() / "compat_logs" / _safe_user(user) / sid
        for item in d.get("logs") or []:
            try:
                logs_dir.mkdir(parents=True, exist_ok=True)
                ver_safe = _safe_component(
                    str(item.get("version", "")).replace(".", "_")
                )
                fn = f"{_sanitize(str(item.get('name', '')))}__{ver_safe}.log"
                (logs_dir / fn).write_text(
                    str(item.get("text") or ""), encoding="utf-8"
                )
            except Exception:
                pass
        # 2) leaderboard record (worker leaderboard file)
        record = None
        per_theorem = d.get("per_theorem") or {}
        if d.get("final_status") != "error":
            record = LB_WORKER.submit(
                user, per_theorem,
                upload_path=d.get("upload_path"), track=track,
            )
        # 2b) this submission's own history record. The leaderboard keeps only
        # the user's latest run; this is what the "My submissions" tab reads,
        # so it has to survive the next submission overwriting that entry.
        _update_submission(
            user, sid,
            track=track,
            status="error" if d.get("final_status") == "error" else "done",
            upload=d.get("upload_path"),
            progress_rows=d.get("progress_rows") or [],
            message=str(d.get("final_message") or "Evaluation finished."),
            results=_history_results(record, per_theorem),
            summary=_history_summary(record),
            # A real report supersedes anything scripts/backfill_submissions.py
            # reconstructed for this submission.
            backfilled=False,
        )
        # 3) consume the job file
        jf = str(d.get("job_file") or "")
        if jf and "/" not in jf and "\\" not in jf:
            (_jobs_pending_dir() / jf).unlink(missing_ok=True)
        # 4) final status for the submit tab
        _write_status(
            user, sid,
            "error" if d.get("final_status") == "error" else "done",
            d.get("progress_rows") or [],
            str(d.get("final_message") or "Evaluation finished."),
        )
        return json.dumps(record if record is not None else {"ok": True})
    except Exception as e:
        return json.dumps({"error": str(e)[:300]})


def worker_heartbeat(token: str, info_json: str) -> str:
    """Liveness marker: /data/worker/heartbeat.json."""
    if not _check_worker_token(token):
        return json.dumps({"error": "denied"})
    try:
        d = _data_root() / "worker"
        d.mkdir(parents=True, exist_ok=True)
        info = json.loads(info_json) if info_json else {}
        info["received"] = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
        tmp = d / "heartbeat.json.tmp"
        tmp.write_text(json.dumps(info))
        os.replace(tmp, d / "heartbeat.json")
        return json.dumps({"ok": True})
    except Exception as e:
        return json.dumps({"error": str(e)[:300]})


# Which leaderboard file the UI renders is env-switchable, but both display
# and worker default to the warmup file — the competition runs on the warmup
# development subset, and `leaderboard.json` holds records from the older,
# pre-arena benchmark that must never be mixed into the live board:
#   LEADERBOARD_DISPLAY_FILE  what the Leaderboard tab / home preview show
#                             (default: leaderboard_warmup.json)
#   LEADERBOARD_WORKER_FILE   where worker_report records land
#                             (default: leaderboard_warmup.json — scored on
#                             the warmup benchmark by the evaluation worker)
DISPLAY_LB_FILE = os.environ.get(
    "LEADERBOARD_DISPLAY_FILE", "leaderboard_warmup.json"
)
WORKER_LB_FILE = os.environ.get(
    "LEADERBOARD_WORKER_FILE", "leaderboard_warmup.json"
)

LB = Leaderboard(DISPLAY_LB_FILE)
LB_WORKER = LB if WORKER_LB_FILE == DISPLAY_LB_FILE else Leaderboard(WORKER_LB_FILE)

BENCHMARK_JSONL_PATH = "/home/user/app/benchmark_data_warmup.jsonl"
if not Path(BENCHMARK_JSONL_PATH).exists():
    _local_bench = Path(__file__).resolve().parent / "benchmark_data_warmup.jsonl"
    if _local_bench.exists():
        BENCHMARK_JSONL_PATH = str(_local_bench)

# Contribution guide. It is served as its own plain HTML page at
# CONTRIB_PAGE_PATH by the FastAPI app at the bottom of this file — not as a
# Gradio tab — so it opens in a new browser tab at a real URL. The Contribute
# tab and the home card only carry the pitch plus a link to it. The leading H1
# is dropped: the page supplies its own themed heading.
CONTRIB_PAGE_PATH = "/contribute"
_CONTRIB_PATH = Path(__file__).resolve().parent / "contribution.md"
try:
    _contrib_lines = _CONTRIB_PATH.read_text(encoding="utf-8").splitlines()
    if _contrib_lines and _contrib_lines[0].startswith("# "):
        _contrib_lines = _contrib_lines[1:]
    CONTRIBUTION_MD = "\n".join(_contrib_lines).strip()
except OSError:
    CONTRIBUTION_MD = "_Contribution guide coming soon._"

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
SPONSOR_ASSETS_DIR = ASSETS_DIR / "sponsors"
BENCH_ASSETS_DIR = ASSETS_DIR / "benchmarks"
APP_ICON_PATH = ASSETS_DIR / "icon.png"

try:
    _icon_b64 = base64.b64encode(APP_ICON_PATH.read_bytes()).decode("ascii")
    APP_ICON_DATA_URI = f"data:image/png;base64,{_icon_b64}"
except OSError:
    APP_ICON_DATA_URI = ""

# ── Sponsors ──────────────────────────────────────────────────────────────────
FINANCIAL_SPONSORS: list[dict[str, str]] = [
    {
        "name": "Amazon Automated Reasoning",
        "image": "https://raw.githubusercontent.com/vericodegen/vericodegen.github.io/main/images/White%20Amazon%20%2B%20AR.png",
        "url": "https://www.amazon.science/research-areas/automated-reasoning",
    },
    {"name": "Aretta AI", "image": "https://raw.githubusercontent.com/vericodegen/vericodegen.github.io/main/images/Aretta_AI.png", "url": "https://aretta.ai/"},
    {
        "name": "Logical Intelligence",
        "image": "https://raw.githubusercontent.com/vericodegen/vericodegen.github.io/main/images/logical_intelligence_logo.jpg",
        "url": "https://logicalintelligence.com/",
    },
    {
        "name": "Pramaana Labs",
        "image": "https://raw.githubusercontent.com/vericodegen/vericodegen.github.io/main/images/pramaana_labs_logo.webp",
        "url": "https://pramaanalabs.ai/",
    },
    {
        "name": "Reasonable",
        "image": "https://raw.githubusercontent.com/vericodegen/vericodegen.github.io/main/images/reasonable_logo.png",
        "url": "https://reasonable.io/",
        "class": "reasonable",
    },
    {
        "name": "Renaissance Philanthropy",
        "image": "https://raw.githubusercontent.com/vericodegen/vericodegen.github.io/main/images/renaissance_logo.webp",
        "url": "https://www.renaissancephilanthropy.org/",
    },
    {"name": "Harmonic", "image": "https://raw.githubusercontent.com/vericodegen/vericodegen.github.io/main/images/harmonic-logo.svg", "url": "https://harmonic.fun/"},
]

TECHNICAL_SPONSORS: list[dict[str, str]] = [
    {"name": "AWS", "image": "assets/sponsors/aws.png", "url": "https://aws.amazon.com/"},
    {"name": "Simon Fraser University", "image": "assets/sponsors/sfu.png", "url": "https://www.sfu.ca/"},
    {"name": "Cslib", "image": "assets/sponsors/cslib.png", "url": "https://cs-lean.github.io/"},
    {"name": "PhysLib", "image": "assets/sponsors/physlib.png", "url": "https://physlib.io/"},
    {"name": "ArkLib", "image": "assets/sponsors/arklib.png", "url": "https://github.com/Verified-zkEVM/ArkLib"},
    {"name": "The University of Texas at Austin", "image": "assets/sponsors/ut_austin.png", "url": "https://www.utexas.edu/"},
]

# Corpus logo files (assets/benchmarks/); falls back to a text badge.
SOURCE_LOGOS = {
    "strata": "assets/benchmarks/strata.png",
    "physlib": "assets/benchmarks/physlib.png",
    "cslib": "assets/benchmarks/cslib.png",
    "arklib": "assets/benchmarks/arklib.png",
    "putnambench": "assets/benchmarks/putnambench.png",
}

PRIZE_PER_TRACK = "$5,000"
CLOSED_BUDGET = "≤ US$3 API spend per problem"
OPEN_BUDGET = "4× 80 GB A100 · ≤ 48 h for the full benchmark"
FULL_BENCH_SIZE = 50
FULL_BENCH_RELEASE = "November 1, 2026"
DEADLINE = "November 8, 2026"
WINNERS_ANNOUNCED = "November 22, 2026"

DISCORD_URL = "https://discord.gg/zg88y8xyC"
# Discussion topic in #general on the Lean community's Zulip — their space,
# not ours, so it is labelled "Lean Zulip" wherever it is linked.
ZULIP_URL = (
    "https://leanprover.zulipchat.com/#narrow/channel/113488-general/topic/Lean.20Refactor.20Competition.2C/with/621991779"
)

# Tech report template. The Overleaf project is read-only and holds the whole
# NeurIPS 2026 AI for Verifiable Coding formatting bundle; competition reports
# use the *competition* template + style file, not the workshop-paper one.
REPORT_TEMPLATE_URL = "https://www.overleaf.com/read/fhmwmtrgwkmc#4d5413"
REPORT_TEMPLATE_TEX = "neurips_2026_vericode_workshop_competition.tex"
REPORT_TEMPLATE_STY = "neurips_2026_vericode_competition.sty"
# Body length of the tech report: a range, not just a cap.
REPORT_PAGE_LIMIT = "at least 3 pages and up to 9 pages"
REPORT_TEMPLATE_LINK = (
    f"<a href='{REPORT_TEMPLATE_URL}' target='_blank' rel='noopener noreferrer'>"
    "report template (Overleaf)</a>"
)

# Tech reports are NOT uploaded to this site — they are submitted to the
# workshop's OpenReview venue, which handles review and camera-ready.
OPENREVIEW_URL = (
    "https://openreview.net/group?id=NeurIPS.cc/2026/Workshop/VERICODEGEN"
)
OPENREVIEW_LINK = (
    f"<a href='{OPENREVIEW_URL}' target='_blank' rel='noopener noreferrer'>"
    "OpenReview</a>"
)

# The workshop this competition is part of.
WORKSHOP_URL = "https://vericodegen.github.io/"
WORKSHOP_NAME = "AI for Verifiable Coding"
WORKSHOP_VENUE = "NeurIPS 2026, Atlanta · Dec 12"
WORKSHOP_LINK = (
    f"<a href='{WORKSHOP_URL}' target='_blank' rel='noopener'>"
    f"{WORKSHOP_NAME}</a>"
)

# Shown wherever prize / benchmark-size numbers appear.
DISCLAIMER = (
    "Prize amounts and benchmark size are provisional and may be adjusted "
    "before Sep 1, 2026."
)


# ── Presentation helpers ──────────────────────────────────────────────────────
def _fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return "0"


def _benchmark_stats() -> list[tuple[str, str, str]]:
    return [
        (_fmt_int(FULL_BENCH_SIZE), "Benchmark problems",
         f"full benchmark released Nov 1 · {len(benchmark_names())}-problem "
         "subset live now"),
        (_fmt_int(len(SOURCES)), "Source repositories",
         "Strata · PhysLib · CSLib · ArkLib · PutnamBench"),
        ("2", "Competition tracks",
         "closed-source LLM · open-source LLM"),
        (PRIZE_PER_TRACK, "Prize per track",
         "plus a dedicated talk at the workshop"),
    ]


def _stat_band_html() -> str:
    cells = "".join(
        "<div class='lra-stat'>"
        f"<div class='lra-stat-num'>{value}</div>"
        f"<div class='lra-stat-label'>{label}</div>"
        f"<div class='lra-stat-note'>{note}</div>"
        "</div>"
        for value, label, note in _benchmark_stats()
    )
    return f"<section class='lra-stat-band'>{cells}</section>"


_LEAN_KEYWORDS = (
    "theorem", "lemma", "example", "def", "by", "fun", "intro", "intros",
    "exact_mod_cast", "exact", "simp_all", "simpa", "simp", "decide",
    "constructor", "refine", "rfl", "rw", "calc", "have", "show", "from",
    "with", "set_option", "import", "open", "sorry", "apply", "omega",
    "norm_num", "ring", "nlinarith", "linarith", "interval_cases", "induction",
)
_LEAN_KW_RE = re.compile(r"\b(" + "|".join(_LEAN_KEYWORDS) + r")\b")


def _lean_highlight(src: str) -> str:
    """Tiny, dependency-free Lean syntax highlighter for illustrative snippets."""
    s = src.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    out = []
    for line in s.split("\n"):
        idx = line.find("--")
        code, comment = (line[:idx], line[idx:]) if idx != -1 else (line, "")
        code = _LEAN_KW_RE.sub(r"<span class='k'>\1</span>", code)
        code = re.sub(r"\b(\d[\d.]*)\b", r"<span class='n'>\1</span>", code)
        if comment:
            comment = f"<span class='c'>{comment}</span>"
        out.append(code + comment)
    return "<pre class='lra-code'><code>" + "\n".join(out) + "</code></pre>"


def _asset_uri(rel: str) -> str:
    if rel.startswith(("http://", "https://")):
        return rel
    path = Path(__file__).resolve().parent / rel
    return f"/gradio_api/file={path}"


def _sponsor_group_html(title: str, sponsors: list[dict[str, str]]) -> str:
    if not sponsors:
        return ""
    items = []
    for sp in sponsors:
        name = sp.get("name", "Sponsor")
        image = sp.get("image", "")
        url = sp.get("url", "")
        sponsor_class = sp.get("class", "")
        logo = (
            f"<img src='{_asset_uri(image)}' alt='{name}' loading='lazy'>"
            if image else f"<span>{name}</span>"
        )
        if url:
            logo = f"<a href='{url}' target='_blank' rel='noopener' title='{name}'>{logo}</a>"
        classes = "lra-logo" + (f" lra-logo-{sponsor_class}" if sponsor_class else "")
        items.append(f"<div class='{classes}'>{logo}</div>")
    return (
        "<div class='lra-sponsor-group'>"
        f"<div class='lra-kicker'>{title}</div>"
        f"<div class='lra-logo-row'>{''.join(items)}</div>"
        "</div>"
    )


def _sponsor_strip_html() -> str:
    return (
        "<section class='lra-sponsors'>"
        + _sponsor_group_html("Financial Sponsors", FINANCIAL_SPONSORS)
        + _sponsor_group_html("Technical Sponsors", TECHNICAL_SPONSORS)
        + "</section>"
    )


def _timeline_html() -> str:
    steps = [
        ("Now → Oct 31, 2026", "Warm-up — submissions open",
         f"The public {len(benchmark_names())}-problem development subset is "
         "live and submissions are open now. Tune your pipeline and climb the "
         "practice leaderboard."),
        ("Nov 1, 2026", "Full benchmark",
         f"The full {FULL_BENCH_SIZE}-problem benchmark is released and the "
         "leaderboard is refreshed — entries are evaluated on the full "
         "benchmark (proofs + code here, tech report on OpenReview) from here "
         "on."),
        ("Nov 8, 2026", "Deadline",
         "Submissions close. Organizers reproduce the top entries."),
        ("Nov 22, 2026", "Winners announced",
         f"Each track winner receives {PRIZE_PER_TRACK} and a dedicated "
         f"presentation at the {WORKSHOP_LINK} workshop ({WORKSHOP_VENUE})."),
    ]
    cells = "".join(
        "<div class='lra-tl-step'>"
        f"<div class='lra-tl-when'>{when}</div>"
        f"<div class='lra-tl-name'>{name}</div>"
        f"<p>{desc}</p>"
        "</div>"
        for when, name, desc in steps
    )
    return (
        "<section class='lra-card'>"
        "<div class='lra-kicker'>Timeline</div>"
        "<h2>From warm-up to awards</h2>"
        "<p class='lra-lead'>Submissions are <b>open now</b> on the public "
        f"subset. The full {FULL_BENCH_SIZE}-problem benchmark drops "
        "<b>Nov 1</b> and the leaderboard refreshes; submissions close "
        "<b>Nov 8, 2026</b> and winners are announced "
        "<b>Nov 22, 2026</b>.</p>"
        f"<div class='lra-tl-grid'>{cells}</div>"
        "</section>"
    )


def _tracks_html(compact: bool = True) -> str:
    closed_pts = [
        "Use any <b>closed-source frontier LLM</b> through its API — and build "
        "whatever harness you like around it.",
        f"<b>Budget:</b> {CLOSED_BUDGET}.",
        "<b>Submit here:</b> refactored proofs + the code that produced them, "
        "so organizers can reproduce the run. "
        f"<b>Short tech report on {OPENREVIEW_LINK}.</b>",
    ]
    open_pts = [
        "Use <b>open-source models</b> (publicly available weights). "
        "Post-train them, build a harness around them, or both.",
        f"<b>Budget:</b> must run on {OPEN_BUDGET}.",
        "<b>Submit here:</b> refactored proofs + inference code, so "
        "organizers can reproduce the run. "
        f"<b>Short tech report on {OPENREVIEW_LINK}.</b>",
    ]

    def card(tag, name, pts):
        lis = "".join(f"<li>{p}</li>" for p in pts)
        return (
            "<div class='lra-track'>"
            f"<div class='lra-metric-tag'>{tag}</div>"
            f"<div class='lra-track-name'>{name}</div>"
            f"<ul>{lis}</ul>"
            f"<div class='lra-track-prize'>🏆 Winner: <b>{PRIZE_PER_TRACK}</b> "
            f"+ a dedicated talk at the {WORKSHOP_LINK} workshop</div>"
            "</div>"
        )

    note = (
        "<p class='lra-lead' style='margin-top:14px'>Deliverables, scoring, "
        "the tech report, and the fine print all live in <b>Tracks &amp; "
        f"Rules</b>. <i>{DISCLAIMER}</i></p>"
        if compact else
        f"<p class='lra-lead' style='margin-top:14px'><i>{DISCLAIMER}</i></p>"
    )
    return (
        "<section class='lra-card'>"
        "<div class='lra-kicker'>Two tracks</div>"
        "<h2>Pick your compute, pick your track</h2>"
        "<p class='lra-lead'>The arena runs the same benchmark under two "
        "resource regimes, ranked separately.</p>"
        "<div class='lra-track-grid'>"
        + card("track 1", "Closed-source LLM", closed_pts)
        + card("track 2", "Open-source LLM", open_pts)
        + "</div>"
        + _report_template_html(compact=compact)
        + note
        + "</section>"
    )


def _report_template_html(compact: bool = True) -> str:
    """Callout for the tech report: where it is submitted (OpenReview, not this
    site) and the official LaTeX template it must use.

    Shown in the Home "Two tracks" section and again under Tracks & Rules. The
    compact (Home) variant keeps the single-blind note to one line and points
    at the rules; the non-compact one gives the reason and spells out what
    desk-rejects a report.
    """
    blind = (
        "<p class='lra-tpl-lead' style='margin-top:10px'>Review is "
        "<b>single-blind</b>: the report is <b>not anonymized</b>, so put "
        "your real names, affiliations, and contact information on it. The "
        "organizers may need to contact you about your code and your "
        "submission during review.</p>"
        if compact else
        "<p class='lra-tpl-lead' style='margin-top:10px'>Review is "
        "<b>single-blind</b>: your submission is <b>not anonymized</b>. Give "
        "your real names, affiliations, and contact information, because the "
        "organizers may need to reach you about your code and your submission "
        "while the competition entries are being reviewed.</p>"
    )
    tail = (
        "<p class='lra-tpl-warn'>The report is <b>not</b> uploaded to this "
        "site. Submissions whose reports are not submitted on OpenReview by "
        "the deadline, that do not follow this template, or that exceed the "
        "track budget, are <b>desk-rejected</b>. See <b>Tracks &amp; "
        "Rules</b> for the full list.</p>"
        if compact else
        "<p class='lra-tpl-warn'>The report is <b>not</b> uploaded to this "
        "site. An entry with no OpenReview submission will not be counted. Do "
        "<b>not</b> modify the style files, the margins, or the font sizes, "
        f"and keep the body to <b>{REPORT_PAGE_LIMIT}</b> (references and "
        "appendices excluded).</p>"
    )
    return (
        "<div class='lra-tpl'>"
        "<div class='lra-tpl-head'>"
        "<span class='lra-tpl-icon'>📄</span>"
        "<div>"
        "<div class='lra-tpl-title'>Tech report: submitted on OpenReview</div>"
        "<p class='lra-tpl-lead'>Every entry needs a technical report, "
        f"submitted to the workshop on <b>{OPENREVIEW_LINK}</b> by the final "
        f"deadline (<b>{DEADLINE}</b>), not uploaded here. It must be "
        "written in the official NeurIPS 2026 <i>AI for Verifiable Coding</i> "
        "<b>competition</b> format (see the Overleaf link below): "
        f"<code>{REPORT_TEMPLATE_TEX}</code> with "
        f"<code>{REPORT_TEMPLATE_STY}</code>. The Overleaf project is "
        "read-only and contains the whole bundle: open it and use "
        "<i>Menu → Copy Project</i>.</p>"
        + blind +
        "</div></div>"
        "<div class='lra-tpl-actions'>"
        f"<a class='lra-tpl-btn' href='{OPENREVIEW_URL}' target='_blank' "
        "rel='noopener noreferrer'>Submit the report on OpenReview ↗</a>"
        f"<a class='lra-tpl-btn lra-tpl-btn-alt' href='{REPORT_TEMPLATE_URL}' "
        "target='_blank' rel='noopener noreferrer'>"
        "Open the report template on Overleaf ↗</a>"
        "</div>"
        + tail +
        "</div>"
    )


def _desk_rejection_html() -> str:
    """The rules from the competition template whose breach kills an entry.

    Sourced from neurips_2026_vericode_workshop_competition.tex — kept in sync
    with the template rather than paraphrased loosely.
    """
    rules = [
        ("No report on OpenReview",
         "The report is submitted to the workshop on "
         f"{OPENREVIEW_LINK}. It is <b>not</b> uploaded to this site. An "
         "entry whose report is missing there by the deadline will not be "
         "counted, however well its proofs score."),
        ("A missing required section",
         "All four sections must appear, under those headings, in this "
         "order: <b>Approach</b>, <b>Models</b>, <b>Budget accounting</b>, "
         "<b>Reproduction</b>. None may be deferred to an appendix."),
        ("Exceeding your track's budget",
         "<b>Closed track:</b> the <b>maximum</b> per-problem API spend is "
         "checked against the <b>US$3</b> cap. <b>Open track:</b> the "
         "benchmark run must fit <b>48 hours end-to-end on ≤ 4× A100 "
         "80 GB</b>. Measure before you submit."),
        ("Under-reporting what the run cost",
         "Price at the provider's <b>public list prices</b> and <b>count "
         "every call</b>, including retries and discarded candidates. Give "
         "the total, mean, and maximum per problem; the full per-problem "
         "table goes in an appendix."),
        ("Not disclosing every model",
         "List <b>every</b> model, including embedding models, rerankers, "
         "and judges, with name, version, and provider. Link the weights for "
         "open-weight models, and give the <b>base checkpoint</b> if you "
         "fine-tuned."),
        ("A run the organizers cannot repeat",
         "The code archive needs a <b>top-level README with the exact "
         "reproduction steps</b> and a <b>pinned environment</b> (Lean "
         "toolchain version and dependency revisions). The competition chair "
         "and collaborating Lean repository maintainers will run it."),
    ]
    items = "".join(
        "<li class='lra-dr-item'>"
        f"<div class='lra-dr-name'>{name}</div>"
        f"<p>{body}</p>"
        "</li>"
        for name, body in rules
    )
    return (
        "<section class='lra-card lra-danger'>"
        "<div class='lra-dr-kicker'>⛔ Grounds for desk rejection</div>"
        "<h2 class='lra-dr-h2'>Read this before you write the report</h2>"
        "<p class='lra-dr-lead'>Reviewers are <b>not</b> scoring novelty. They "
        "check that the result is real, honestly accounted for, within budget, "
        "and reproducible from your code archive. Each of the following is, on "
        "its own, grounds for <b>desk rejection from the competition</b> — a "
        "desk-rejected entry is removed from the ranking regardless of its "
        "score.</p>"
        f"<ol class='lra-dr-list'>{items}</ol>"
        "<p class='lra-dr-foot'>These are the highlights. The binding text is "
        f"the template itself: {REPORT_TEMPLATE_LINK}.</p>"
        "</section>"
    )


def _scoring_html() -> str:
    """How a run is scored, spelled out. Rendered in the danger palette
    because the part competitors get wrong — an unsubmitted problem is a zero
    that still counts — costs them the ranking, not just a row."""
    n = len(benchmark_names())
    axes = [
        ("Length reduction %",
         "Token count of your proof body against the reference proof. "
         "Higher is better; negative means your proof got longer."),
        ("Heartbeat reduction %",
         "Lean elaboration cost via <a href='https://lean-lang.org/doc/"
         "reference/latest/IO/Timing/#IO___getNumHeartbeats' target='_blank' "
         "rel='noopener noreferrer'><code>#count_heartbeats</code></a>, "
         "against the reference proof. Higher is better; negative means your "
         "proof got more expensive to compile."),
        ("Zero-shot compatibility %",
         "The share of that problem's listed Lean toolchains "
         "(its <code>version_info</code>) on which your proof compiles "
         "<b>unchanged</b>."),
    ]
    items = "".join(
        f"<li class='lra-dr-item'><div class='lra-dr-name'>{name}</div>"
        f"<p>{body}</p></li>"
        for name, body in axes
    )
    return (
        "<section class='lra-card lra-danger'>"
        "<div class='lra-dr-kicker'>How your score is computed</div>"
        "<h2 class='lra-dr-h2'>Scoring (both tracks)</h2>"
        "<p class='lra-dr-lead'>Every problem is scored on its own, then the "
        "problem scores are averaged. <b>A problem you do not submit scores "
        "zero and is still averaged in</b> — so is one that fails to compile, "
        "changes the statement, or trips the forbidden-pattern filter "
        "(<code>#eval</code>, <code>IO.*</code>, <code>unsafe</code>, "
        "<code>sorry</code>, …). There is no way to raise your score by "
        "leaving out the problems you are least sure of.</p>"
        "<div class='lra-formula'>"
        "<div><span class='lra-f-lhs'>problem score</span>"
        "<span class='lra-f-eq'>=</span>"
        "<span>mean( length reduction % , heartbeat reduction % , "
        "zero-shot compatibility % )</span></div>"
        "<div><span class='lra-f-lhs'>your score</span>"
        "<span class='lra-f-eq'>=</span>"
        f"<span>mean of the problem scores over <b>all {n} problems</b></span>"
        "</div></div>"
        "<p class='lra-dr-lead' style='margin-top:16px'>The three axes a "
        "single problem is measured on:</p>"
        f"<ol class='lra-dr-list'>{items}</ol>"
        "<p class='lra-dr-foot'>The leaderboard ranks by that score, shown as "
        "<b>Combined %</b>. Its other columns are the same three axes averaged "
        f"over all {n} problems the same way, so they average to Combined %. "
        "Per-problem scores for your own runs are under "
        "<b>My submissions</b>.</p>"
        "</section>"
    )


def _sources_html(heading: bool = True) -> str:
    cards = []
    for key, meta in SOURCES.items():
        logo_rel = SOURCE_LOGOS.get(key)
        logo = (
            f"<img class='lra-src-logo' src='{_asset_uri(logo_rel)}' "
            f"alt='{meta['label']}' loading='lazy'>"
            if logo_rel else ""
        )
        cards.append(
            "<div class='lra-src'>"
            f"{logo}"
            "<div class='lra-src-body'>"
            f"<div class='lra-src-name'><a href='{meta['url']}' target='_blank' "
            f"rel='noopener'>{meta['label']}</a></div>"
            f"<p>{meta['blurb']}</p>"
            "</div></div>"
        )
    head = (
        "<div class='lra-kicker'>The benchmark</div>"
        "<h2>Real proofs from real developments</h2>"
        "<p class='lra-lead'>Every problem is a long reference proof taken "
        "verbatim from an active formalization project (plus a slice of "
        "competition mathematics), selected in consultation with the "
        "repository maintainers. Your job: re-prove the same statement "
        "shorter, cheaper, and more robustly. The current set is a "
        "<b>development subset</b> — the <b>full benchmark</b> is released "
        f"on <b>{FULL_BENCH_RELEASE}</b>.</p>"
        if heading else ""
    )
    return (
        "<section class='lra-card'>"
        + head
        + f"<div class='lra-src-grid'>{''.join(cards)}</div>"
        + "</section>"
    )


def _metric_cards_html() -> str:
    metrics = [
        ("length reduction %", "Proof Length",
         "Decrease in proof token counts compared against the original proof "
         "before refactoring. Higher is better."),
        ("heartbeat reduction %", "Compilation Cost",
         "Change in Lean's <a href='https://lean-lang.org/doc/reference/latest/IO/Timing/#IO___getNumHeartbeats' target='_blank' rel='noopener noreferrer'><code>#count_heartbeats</code></a>, "
         "the number of “small” memory allocations performed on the current "
         "execution thread. Positive values indicate cheaper (typically "
         "faster) compilation; negative values indicate costlier compilation."),
        ("zero-shot %", "Version transfer",
         "The fraction of a problem's listed Lean toolchains on which the "
         "accepted proof compiles unchanged."),
    ]
    cards = "".join(
        "<div class='lra-metric'>"
        f"<div class='lra-metric-tag'>{tag}</div>"
        f"<div class='lra-metric-name'>{name}</div>"
        f"<p>{desc}</p>"
        "</div>"
        for tag, name, desc in metrics
    )
    return (
        "<section class='lra-card lra-scoring'>"
        "<div class='lra-kicker'>How scoring works</div>"
        "<h2>Three numbers, one ranking</h2>"
        "<p class='lra-lead'>Every accepted proof is scored on two reduction "
        "axes and a cross-version transfer check. The default rank — "
        "<b>combined %</b> — is the mean of all three; rows that fail to "
        "compile, change the statement, or contain <code>sorry</code> score "
        "zero.</p>"
        f"<div class='lra-metric-grid'>{cards}</div>"
        "</section>"
    )


def _claims_html() -> str:
    shorter_cheap = _lean_highlight(
        "-- 3-line proof · 4,331,226 heartbeats\n"
        "theorem amc12_2001_p21\n"
        "    (a b c d : ℕ)\n"
        "    (h₀ : a * b * c * d = Nat.factorial 8)\n"
        "    (h₁ : a * b + a + b = 524)\n"
        "    (h₂ : b * c + b + c = 146)\n"
        "    (h₃ : c * d + c + d = 104) :\n"
        "    ↑a - ↑d = (10 : ℤ) := by\n"
        "  norm_num [Nat.factorial] at h₀\n"
        "  have : b ≤ 525 := by nlinarith\n"
        "  interval_cases b <;> simp_all <;> nlinarith"
    )
    longer_cheap = _lean_highlight(
        "-- 130+ line proof · 157,079 heartbeats  (27× cheaper)\n"
        "theorem amc12_2001_p21\n"
        "    (a b c d : ℕ) ... :\n"
        "    ↑a - ↑d = (10 : ℤ) := by\n"
        "  -- factor: (x+1)(y+1) = x*y + x + y + 1\n"
        "  have h₄ : (a + 1) * (b + 1) = 525 := by ...\n"
        "  have h₅ : (b + 1) * (c + 1) = 147 := by ...\n"
        "  have h₆ : (c + 1) * (d + 1) = 105 := by ...\n"
        "  -- pin b via gcd, then back-solve each variable\n"
        "  have h₇ : b = 20 := by\n"
        "    have : b + 1 ∣ Nat.gcd 525 147 := Nat.dvd_gcd ‹_› ‹_›\n"
        "    interval_cases b <;> omega\n"
        "  have h₈ : a = 24 := by ...\n"
        "  have h₉ : c = 6  := by ...\n"
        "  have h₁₀ : d = 14 := by ...\n"
        "  exact_mod_cast h₁₁"
    )
    compat_ok = _lean_highlight(
        "-- Lean v4.24.0  ✓ compiles\n"
        "-- a single term ≤ the whole nonneg sum\n"
        "example (f : ℕ → ℝ) (hf : Summable f)\n"
        "    (hpos : ∀ n, 0 ≤ f n) :\n"
        "    f 0 ≤ ∑' n, f n :=\n"
        "  le_tsum hf 0 (fun j _ => hpos j)"
    )
    compat_bad = _lean_highlight(
        "-- Lean v4.28.0  ✗ unknown identifier 'le_tsum'\n"
        "example (f : ℕ → ℝ) (hf : Summable f)\n"
        "    (hpos : ∀ n, 0 ≤ f n) :\n"
        "    f 0 ≤ ∑' n, f n :=\n"
        "  le_tsum hf 0 (fun j _ => hpos j)"
    )
    return (
        "<section class='lra-claims'>"
        "<div class='lra-claim'>"
        "<div class='lra-claim-copy'>"
        "<div class='lra-kicker'>Why it is hard</div>"
        "<h2>Shorter <span class='lra-accent'>≠</span> cheaper</h2>"
        "<p>Two proofs of the same miniF2F theorem, "
        "<code>amc12_2001_p21</code>. The 3-line version leans on a single heavy "
        "cascade — <code>interval_cases</code> over <code>b ≤ 525</code> firing "
        "<code>nlinarith</code> and <code>simp_all</code> across hundreds of "
        "branches — and burns <b>4,331,226 heartbeats</b>. The explicit 130-line "
        "version factors the constraints and pins each variable by hand for just "
        "<b>157,079</b> — over <b>27× cheaper</b> to elaborate. Optimizing only for "
        "shorter text can wreck compilation cost; the arena scores both.</p>"
        "</div>"
        f"<div class='lra-code-pair'>{shorter_cheap}{longer_cheap}</div>"
        "</div>"
        "<div class='lra-claim'>"
        "<div class='lra-claim-copy'>"
        "<div class='lra-kicker'>Why it matters</div>"
        "<h2>Lean ships weekly. Does your proof still <span class='lra-accent'>compile?</span></h2>"
        "<p>The same proof, two toolchains. <code>le_tsum</code> — <i>any single "
        "term of a nonnegative summable series is at most its total</i> — resolves "
        "on one toolchain but a later release answers <code>unknown identifier "
        "'le_tsum'</code>. Lemmas are renamed and removed every release, so a "
        "proof that is flawless today can rot tomorrow. Every benchmark problem "
        "lists the toolchains it is re-checked on, and the transfer rate is a "
        "third of your score.</p>"
        "</div>"
        f"<div class='lra-code-pair'>{compat_ok}{compat_bad}</div>"
        "</div>"
        "</section>"
    )


# ── News ──────────────────────────────────────────────────────────────────────
# Newest first. Each entry is (date, headline, body-html). The rendered box
# shows the top few and scrolls for the rest, so adding an item here never
# pushes the rest of the home page down.
NEWS: list[tuple[str, str, str]] = [
    ("August 17, 2026", "Submissions are open for the warm-up benchmark",
     "You can now submit proofs for the 15 warm-up problems, and submissions "
     "are scored automatically. Your first submission claims your username "
     "and issues a submission key, so keep it: you need that key to submit "
     "again under the same name."),
    ("August 17, 2026", "Join the community Discord",
     f"The <a href='{DISCORD_URL}' target='_blank' rel='noopener'>arena "
     "Discord</a> is open for announcements, rule clarifications, and "
     f"technical questions. There is also a <a href='{ZULIP_URL}' "
     "target='_blank' rel='noopener'>discussion topic</a> on the Lean "
     "community Zulip."),
    ("August 1, 2026", "Warm-up benchmark published",
     "Fifteen long reference proofs drawn from Strata, PhysLib, CSLib, "
     "ArkLib, and PutnamBench are available under the <b>Benchmark</b> tab. "
     f"The full {FULL_BENCH_SIZE}-problem benchmark is released on "
     f"{FULL_BENCH_RELEASE}."),
    ("July 15, 2026", "The arena is announced",
     f"Lean Refactor Arena runs as part of the {WORKSHOP_LINK} workshop at "
     f"{WORKSHOP_VENUE}, with {PRIZE_PER_TRACK} for the winner of each "
     "track. See <b>Tracks &amp; Rules</b> for how entries are judged."),
]


def _news_html() -> str:
    items = "".join(
        "<li class='lra-news-item'>"
        f"<div class='lra-news-date'>{html.escape(date)}</div>"
        f"<div class='lra-news-body'><h3>{html.escape(title)}</h3>"
        f"<p>{body}</p></div>"
        "</li>"
        for date, title, body in NEWS
    )
    return (
        "<section class='lra-card lra-news'>"
        "<div class='lra-news-head'>"
        "<div><div class='lra-kicker'>News</div>"
        "<h2>Latest updates</h2></div>"
        "</div>"
        f"<ol class='lra-news-list'>{items}</ol>"
        "<div class='lra-news-hint'>Scroll for older updates</div>"
        "</section>"
    )


def _community_html() -> str:
    def btn(label, url, icon):
        if url:
            return (
                f"<a class='lra-paper-btn' href='{url}' target='_blank' "
                f"rel='noopener'>{icon} {label}</a>"
            )
        return (
            f"<span class='lra-paper-btn lra-btn-soon' title='Link coming soon'>"
            f"{icon} {label} · coming soon</span>"
        )
    return (
        "<section class='lra-card'>"
        "<div class='lra-kicker'>Community</div>"
        "<h2>Questions? Join the conversation</h2>"
        "<p class='lra-lead'>Announcements, rule clarifications, and technical "
        "Q&amp;A happen in two places: the <b>arena Discord</b>, and our "
        "<b>topic on the Lean community Zulip</b>. Both are open — pick "
        "whichever you already use.</p>"
        "<div class='lra-cite-actions'>"
        + btn("Discord", DISCORD_URL, "💬")
        + " "
        + btn("Lean Zulip", ZULIP_URL, "🗨️")
        + "</div>"
        "</section>"
    )


def _contribute_card_html() -> str:
    return (
        "<section class='lra-card'>"
        "<div class='lra-kicker'>Grow the benchmark</div>"
        "<h2>How to contribute</h2>"
        "<p class='lra-lead'>We are looking for more Lean proofs to refactor — "
        "long ones, expensive to compile, and stable across toolchain "
        "versions. If you maintain or know a development with proofs like "
        "that, we'd love your input!</p>"
        "<div class='lra-cite-actions'>"
        f"<a class='lra-paper-btn' href='{CONTRIB_PAGE_PATH}' target='_blank' "
        "rel='noopener'>📥 Read the contribution guide →</a>"
        "</div>"
        "</section>"
    )


# ── Leaderboard rendering ─────────────────────────────────────────────────────
LB_COLUMNS = [
    ("rank", "#", "", False, False),
    ("user", "Submitter", "", False, False),
    ("model", "Model & reasoning",
     "Optional model and reasoning effort/settings reported by the "
     "participant. These details are not verified and do not affect scoring.",
     False, False),
    ("combined", "Combined %",
     "Each problem scores the mean of its three axes; this is the mean of "
     "those problem scores over the whole benchmark. A problem with no "
     "submission scores 0 and is still averaged in.",
     True, True),
    ("length", "Length reduction %",
     "Decrease in proof token counts compared against the original proof "
     "before refactoring. Higher is better.",
     True, True),
    ("heartbeat", "Heartbeat reduction %",
     "Change in Lean's <a href='https://lean-lang.org/doc/reference/latest/IO/"
     "Timing/#IO___getNumHeartbeats' target='_blank' rel='noopener noreferrer'>"
     "<code>#count_heartbeats</code></a>, the number of “small” memory "
     "allocations performed on the current execution thread. Positive values "
     "indicate cheaper (typically faster) compilation; negative values "
     "indicate costlier compilation.",
     True, True),
    ("zeroshot", "Zero-shot %",
     "Share of a problem's listed Lean toolchains on which the accepted proof "
     "compiles unchanged, averaged over the whole benchmark. A problem that "
     "was not submitted or did not compile counts 0.",
     True, True),
    ("submitted", "Submitted", "", False, False),
]


def _lb_bar_cell(col: str, sort_val, *, display: str, bar_pct: float, negative: bool = False) -> str:
    w = max(0.0, min(100.0, float(bar_pct)))
    cls = "lra-bar neg" if negative else "lra-bar"
    return (
        f"<td data-col='{col}' data-sort='{sort_val}'>"
        f"<div class='lra-cell-num'>{display}</div>"
        f"<div class='{cls}'><span style='width:{w:.1f}%'></span></div>"
        "</td>"
    )


def _lb_na_cell(col: str) -> str:
    return (
        f"<td data-col='{col}' data-sort=''>"
        "<div class='lra-cell-num lra-na'>—</div></td>"
    )


def _lb_pos_cell(col: str, val) -> str:
    if val is None:
        return _lb_na_cell(col)
    return _lb_bar_cell(col, val, display=f"{val}%", bar_pct=val, negative=val < 0)


def _lb_diverging_cell(col: str, val) -> str:
    if val is None:
        return _lb_na_cell(col)
    w = min(100.0, abs(float(val))) / 2.0          # half-track == 100%
    side = "neg" if val < 0 else "pos"
    return (
        f"<td data-col='{col}' data-sort='{val}'>"
        f"<div class='lra-cell-num'>{val}%</div>"
        "<div class='lra-bar diverging'>"
        f"<span class='lra-bar-fill {side}' style='width:{w:.1f}%'></span></div>"
        "</td>"
    )


def _lb_row_html(r: list) -> str:
    (rank, user, len_pct, hb_pct, combined, survival_str, _compiled_str,
     submitted, models, reasoning) = r
    user_e = html.escape(str(user))

    report_bits = []
    if models:
        report_bits.append(
            f"<div class='lra-model-name'>{html.escape(str(models))}</div>"
        )
    if reasoning:
        report_bits.append(
            "<div class='lra-model-settings'><span>Reasoning/settings:</span> "
            f"{html.escape(str(reasoning))}</div>"
        )
    report_html = "".join(report_bits) or "<span class='lra-na'>—</span>"
    report_sort = html.escape(
        f"{models or ''} {reasoning or ''}".strip().lower(), quote=True
    )

    # survival_str comes as e.g. "80.0% (8/10)"; show only the percentage.
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)", survival_str or "")
    surv_val = float(m.group(1)) if m else None

    if surv_val is None:
        zeroshot_cell = _lb_na_cell("zeroshot")
    else:
        zeroshot_cell = _lb_bar_cell(
            "zeroshot", surv_val, display=f"{surv_val:.1f}%",
            bar_pct=surv_val)

    cells = [
        f"<td class='rank' data-col='rank' data-sort='{rank}'>{rank}</td>",
        f"<td class='who' data-col='user' data-sort='{user_e.lower()}'>{user_e}</td>",
        f"<td class='model' data-col='model' data-sort='{report_sort}'>"
        f"{report_html}</td>",
        _lb_pos_cell("combined", combined),
        _lb_pos_cell("length", len_pct),
        _lb_diverging_cell("heartbeat", hb_pct),
        zeroshot_cell,
        f"<td data-col='submitted' data-sort='{html.escape(str(submitted))}'>"
        f"{html.escape(str(submitted))}</td>",
    ]
    return f"<tr data-rank='{rank}'>" + "".join(cells) + "</tr>"


def _lb_header_html() -> str:
    ths = []
    for key, label, tip, _numeric, higher in LB_COLUMNS:
        better = "<span class='lra-better' title='Higher is better'>(↑)</span>" if higher else ""
        has_tip = " has-tip" if tip else ""
        tip_html = f"<div class='lra-tip'>{tip}</div>" if tip else ""
        ths.append(
            f"<th data-col='{key}' data-sortable='1' class='lra-thcell{has_tip}'>"
            "<span class='lra-th'>"
            f"<span class='lra-th-label'>{label}</span>"
            f"{better}"
            "<span class='lra-sort'></span>"
            "</span>"
            f"{tip_html}"
            "</th>"
        )
    return "<thead><tr>" + "".join(ths) + "</tr></thead>"


# Submitters hidden from every public leaderboard display (internal test and
# smoke-test runs made while bringing the arena up). Their records stay in the
# leaderboard file; they are filtered at render time only.
HIDDEN_SUBMITTERS = {
    # warm-up benchmark (the board shown today)
    "lra-smoke-1",
    "lra-golf-1",
    "lra-golf-2",
    "lra-final-golf",
    "lra-endstate-check",
    "lra-uniq-live",
    "lra-sandbox-final",
    "lra-key-demo",
    "test-submission",
    "test-1",
    "test-2",
    "test aug 17",
    "SGTestWater",
    # pre-arena benchmark (leaderboard.json — kept in case it is displayed)
    "Claude Opus 4.8",
    "Gemini 3 Flash",
    "Deepseek V4 Pro",
    "Claude Code - DeepSeek-V4-Pro (Max)",
}


def _rows_for_display(track: str) -> list:
    rows = [
        r for r in LB.leaderboard_rows(track=track)
        if str(r[1]) not in HIDDEN_SUBMITTERS
    ]
    for i, r in enumerate(rows, start=1):
        r[0] = i
        claim = _load_claim(str(r[1])) or {}
        r.extend([
            str(claim.get("models") or ""),
            str(claim.get("reasoning_effort") or ""),
        ])
    return rows


def _clean_self_report(value: str, *, limit: int) -> str:
    """One compact, bounded line suitable for a public leaderboard cell."""
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def save_self_report(
    user: str, submission_key: str, models: str, reasoning_effort: str,
):
    """Save optional, public model details after verifying entry ownership.

    The profile lives alongside the username claim rather than inside a scored
    record, so it is available to existing participants immediately and is not
    erased when the evaluation worker replaces their leaderboard result.
    """
    try:
        display = authorize_viewer(user, submission_key)
    except ValueError as e:
        return (
            f"**Error:** {e}",
            _leaderboard_closed_html(),
            _leaderboard_open_html(),
        )

    models = _clean_self_report(models, limit=200)
    reasoning_effort = _clean_self_report(reasoning_effort, limit=300)
    if not models and not reasoning_effort:
        return (
            "**Error:** enter a model or reasoning effort/settings to save.",
            _leaderboard_closed_html(),
            _leaderboard_open_html(),
        )

    try:
        claim = _load_claim(display)
        if claim is None:
            raise OSError("username claim is unavailable")
        # A blank field leaves its existing value alone, so updating one field
        # never accidentally erases the other.
        if models:
            claim["models"] = models
        if reasoning_effort:
            claim["reasoning_effort"] = reasoning_effort
        claim["self_report_updated"] = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
        path = _claim_path(display)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(claim, ensure_ascii=False))
        os.replace(tmp, path)
    except Exception:
        return (
            "**Error:** could not save your self-reported details just now. "
            "Please try again.",
            _leaderboard_closed_html(),
            _leaderboard_open_html(),
        )

    return (
        f"✅ Saved the self-reported model details for **{html.escape(display)}**.",
        _leaderboard_closed_html(),
        _leaderboard_open_html(),
    )


def _lb_render(rows: list, *, table_id: str) -> str:
    if not rows:
        return (
            "<div class='lra-empty'>No submissions on this track yet — "
            "the first verified run lands here.</div>"
        )
    body_rows = "".join(_lb_row_html(r) for r in rows)
    return (
        f"<div class='lra-lb' id='{table_id}'>"
        "<div class='lra-table-wrap'><table class='lra-table'>"
        f"{_lb_header_html()}"
        f"<tbody>{body_rows}</tbody></table></div></div>"
    )


def _leaderboard_closed_html() -> str:
    LB.reload()
    return _lb_render(_rows_for_display("closed"), table_id="lra-lb-closed")


def _leaderboard_open_html() -> str:
    LB.reload()
    return _lb_render(_rows_for_display("open"), table_id="lra-lb-open")


def _preview_html(limit: int = 5) -> str:
    closed = _rows_for_display("closed")[:limit]
    open_ = _rows_for_display("open")[:limit]
    return (
        "<section class='lra-card lra-preview'>"
        "<div class='lra-kicker'>Leaderboard</div>"
        "<h2>Current front-runners</h2>"
        "<div class='lra-preview-pick'>"
        "<button type='button' class='lra-pickbtn active' data-track='closed'>"
        "Closed-source LLM track</button>"
        "<button type='button' class='lra-pickbtn' data-track='open'>"
        "Open-source LLM track</button>"
        "</div>"
        "<div class='lra-preview-panel' data-track='closed'>"
        + _lb_render(closed, table_id="lra-lb-home-closed")
        + "</div>"
        "<div class='lra-preview-panel' data-track='open' style='display:none'>"
        + _lb_render(open_, table_id="lra-lb-home-open")
        + "</div>"
        "</section>"
    )


# ── My submissions: per-submission history for one submitter ──────────────────
_SUB_STATES = {
    "queued":  ("Queued", "q"),
    "running": ("Scoring", "r"),
    "done":    ("Scored", "d"),
    "error":   ("Failed", "e"),
}

_TRACK_NAMES = {v: k for k, v in TRACK_LABELS.items()}


def _sub_when(sid: str) -> str:
    """`20260828T064523Z` -> `2026-08-28 06:45 UTC` (raw id if unparseable)."""
    try:
        return datetime.strptime(sid, "%Y%m%dT%H%M%SZ").strftime(
            "%Y-%m-%d %H:%M UTC"
        )
    except Exception:
        return sid


def _sub_day(sid: str) -> str:
    try:
        return datetime.strptime(sid, "%Y%m%dT%H%M%SZ").strftime("%Y-%m-%d")
    except Exception:
        return sid[:10]


def _num_html(val, *, suffix: str = "", ref=None) -> str:
    """One numeric cell: the value, optionally over its reference, with
    negatives (a proof that got longer or slower) called out."""
    if val is None:
        return "<span class='lra-cell-num lra-na'>—</span>"
    try:
        num = float(val)
        integral = num.is_integer()
    except (TypeError, ValueError, OverflowError):
        return f"<span class='lra-cell-num'>{html.escape(str(val))}</span>"
    text = f"{num:g}{suffix}" if suffix or not integral else _fmt_int(int(num))
    cls = "lra-cell-num" + (" lra-down" if num < 0 else "")
    ref_html = (
        f"<span class='lra-ref'>of {_fmt_int(ref)}</span>"
        if ref not in (None, 0) else ""
    )
    return f"<span class='{cls}'>{text}</span>{ref_html}"


def _problem_state(res) -> tuple:
    """(label, css modifier) describing what happened to one problem."""
    if not isinstance(res, dict) or res.get("compiled") is None:
        return "Not submitted", "skip"
    if res.get("compiled"):
        return "Compiled", "ok"
    err = str(res.get("error") or "")
    if res.get("rejected") or err.startswith("rejected:"):
        return "Rejected", "bad"
    if res.get("statement_match") is False or err.startswith(
        "submission must be exactly the benchmark statement"
    ):
        return "Statement changed", "warn"
    return "Did not compile", "bad"


_PROBLEM_COLUMNS = (
    "Problem", "Result", "Score", "Length", "Length reduction %",
    "Heartbeats", "Heartbeat reduction %", "Zero-shot", "Notes",
)


def _problem_table_html(results: dict) -> str:
    """Per-problem breakdown of one scored submission, in benchmark order."""
    names = [n for n in benchmark_names() if n in results]
    names += [n for n in results if n not in set(names)]
    if not names:
        return ""
    body = []
    for name in names:
        res = results.get(name) or {}
        label, mod = _problem_state(res)
        compat = res.get("compat") or {}
        n_checks = len(compat)
        n_pass = sum(1 for v in compat.values() if (v or {}).get("passed"))
        zero = (
            f"<span class='lra-cell-num'>{n_pass}/{n_checks}</span>"
            if n_checks else "<span class='lra-cell-num lra-na'>—</span>"
        )
        note = str(res.get("error") or "")
        note_html = (
            f"<span class='lra-hist-note' title='{html.escape(note)}'>"
            f"{html.escape(note[:150])}{'…' if len(note) > 150 else ''}</span>"
            if note else "<span class='lra-na'>—</span>"
        )
        compiled = res.get("compiled") is True
        body.append(
            "<tr>"
            f"<td class='lra-prob'><code>{html.escape(name)}</code></td>"
            f"<td><span class='lra-badge {mod}'>{label}</span></td>"
            f"<td class='lra-score'>{_num_html(Leaderboard.problem_score(res), suffix='%')}</td>"
            f"<td>{_num_html(res.get('length'), ref=original_length(name))}</td>"
            f"<td>{_num_html(res.get('length_reduction_pct') if compiled else None, suffix='%')}</td>"
            f"<td>{_num_html(res.get('heartbeats'), ref=original_heartbeats(name))}</td>"
            f"<td>{_num_html(res.get('heartbeat_reduction_pct') if compiled else None, suffix='%')}</td>"
            f"<td>{zero}</td>"
            f"<td>{note_html}</td>"
            "</tr>"
        )
    head = "".join(f"<th>{c}</th>" for c in _PROBLEM_COLUMNS)
    return (
        "<div class='lra-hist-wrap'><table class='lra-table lra-hist-table'>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


# The worker labels live rows with its own short strings; map them onto the
# same vocabulary the finished table uses so a run reads the same while it is
# in flight as it does when it is done.
_LIVE_STATES = {
    "queued": ("Queued", "skip"),
    "compiling": ("Compiling", "live"),
    "pass": ("Compiled", "ok"),
    "fail": ("Did not compile", "bad"),
    "rejected": ("Rejected", "bad"),
    "statement changed": ("Statement changed", "warn"),
}


def _live_state(raw: str) -> tuple:
    """Strip the worker's leading emoji, then look the status up."""
    key = re.sub(r"^[^A-Za-z]+", "", str(raw or "")).strip().lower()
    return _LIVE_STATES.get(key, (str(raw or "—"), "live"))


def _progress_table_html(rows: list) -> str:
    """Live per-problem rows streamed by the worker for a run in flight.
    Same shape as `lra.worker._progress_row`."""
    body = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 8:
            continue
        name, _scored, state, length, len_pct, hbs, hb_pct, note = row[:8]
        label, mod = _live_state(state)
        if mod != "ok":
            len_pct = hb_pct = None
        # The worker packs the compat tally into the note as "compat N/M";
        # it belongs in the zero-shot column, same as on a finished run.
        note = str(note or "")
        m = re.match(r"compat (\d+)/(\d+)$", note)
        if m:
            zero = f"<span class='lra-cell-num'>{m.group(1)}/{m.group(2)}</span>"
            note = ""
        else:
            zero = "<span class='lra-cell-num lra-na'>—</span>"
        note_html = (
            f"<span class='lra-hist-note' title='{html.escape(note)}'>"
            f"{html.escape(note[:150])}{'…' if len(note) > 150 else ''}</span>"
            if note else "<span class='lra-na'>—</span>"
        )
        # Provisional score from what the worker has reported so far — the
        # same mean of the three axes the finished table shows.
        if mod == "ok":
            compat_pct = (
                float(m.group(1)) / float(m.group(2)) * 100.0
                if m and float(m.group(2)) else 100.0
            )
            score = round(
                ((len_pct or 0.0) + (hb_pct or 0.0) + compat_pct) / 3.0, 2
            )
        else:
            score = 0.0 if mod in ("bad", "warn") else None
        body.append(
            "<tr>"
            f"<td class='lra-prob'><code>{html.escape(str(name))}</code></td>"
            f"<td><span class='lra-badge {mod}'>{html.escape(label)}</span></td>"
            f"<td class='lra-score'>{_num_html(score, suffix='%')}</td>"
            f"<td>{_num_html(length, ref=original_length(str(name)))}</td>"
            f"<td>{_num_html(len_pct, suffix='%')}</td>"
            f"<td>{_num_html(hbs, ref=original_heartbeats(str(name)))}</td>"
            f"<td>{_num_html(hb_pct, suffix='%')}</td>"
            f"<td>{zero}</td>"
            f"<td>{note_html}</td>"
            "</tr>"
        )
    if not body:
        return ""
    head = "".join(f"<th>{c}</th>" for c in _PROBLEM_COLUMNS)
    return (
        "<div class='lra-hist-wrap'><table class='lra-table lra-hist-table'>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def _submission_card_html(rec: dict, *, open_: bool) -> str:
    sid = str(rec.get("submission_id") or "")
    status = str(rec.get("status") or "done")
    label, mod = _SUB_STATES.get(status, ("Scored", "d"))
    track = _TRACK_NAMES.get(str(rec.get("track") or ""), "")
    summary = rec.get("summary") or {}
    results = rec.get("results") or {}

    facts = []
    if track:
        facts.append(html.escape(track))
    if summary.get("avg_combined_pct") is not None:
        facts.append(f"Combined <b>{summary['avg_combined_pct']}%</b>")
    if summary.get("num_compiled") is not None:
        facts.append(
            f"{summary['num_compiled']}/{summary.get('num_benchmark', 0)} compiled"
        )
    elif rec.get("num_scored") is not None:
        n = int(rec["num_scored"])
        noun = "problem" if n == 1 else "problems"
        facts.append(
            f"{n} {noun} to score" if status in ("queued", "running")
            else f"{n} {noun} submitted"
        )

    if results:
        body = _problem_table_html(results)
    elif rec.get("progress_rows"):
        body = _progress_table_html(rec["progress_rows"])
    else:
        body = ""
    if not body:
        if status in ("queued", "running"):
            body = (
                "<div class='lra-empty'>No per-problem results yet — this "
                "submission is still with the evaluation worker. Results "
                "appear here as each proof finishes compiling.</div>"
            )
        else:
            body = (
                "<div class='lra-empty'>This submission was scored before "
                "per-problem history was recorded, so only its summary "
                "survives.</div>"
            )

    message = str(rec.get("message") or "")
    message_html = (
        f"<p class='lra-sub-msg'>{html.escape(message)}</p>" if message else ""
    )
    return (
        f"<details class='lra-sub'{' open' if open_ else ''}>"
        "<summary><span class='lra-sub-when'>"
        f"{html.escape(_sub_when(sid))}</span>"
        f"<span class='lra-badge {mod}'>{label}</span>"
        f"<span class='lra-sub-facts'>{' · '.join(facts)}</span></summary>"
        f"<div class='lra-sub-body'>{message_html}{body}</div>"
        "</details>"
    )


def _history_html(display: str, records: list) -> str:
    if not records:
        return (
            "<div class='lra-empty'>No submissions recorded for "
            f"<b>{html.escape(display)}</b> yet.</div>"
        )
    n_open = sum(
        1 for r in records if str(r.get("status")) in ("queued", "running")
    )
    counts = f"{len(records)} submission{'s' if len(records) != 1 else ''}"
    if n_open:
        counts += f" · {n_open} still being scored"

    by_day: dict = {}
    for rec in records:
        by_day.setdefault(_sub_day(str(rec.get("submission_id") or "")), []).append(rec)

    first = True
    groups = []
    for day in sorted(by_day, reverse=True):
        cards = []
        for rec in by_day[day]:
            cards.append(_submission_card_html(rec, open_=first))
            first = False
        groups.append(
            f"<div class='lra-day'><div class='lra-day-label'>"
            f"{html.escape(day)}</div>{''.join(cards)}</div>"
        )
    return (
        "<section class='lra-hist'>"
        "<div class='lra-hist-head'>"
        f"<div><div class='lra-kicker'>Submitter</div>"
        f"<h3>{html.escape(display)}</h3></div>"
        f"<div class='lra-hist-count'>{counts}</div>"
        "</div>"
        + "".join(groups) +
        "</section>"
    )


def refresh_submissions(user: str, submission_key: str):
    """Timer-driven refresh of an open history view. Silent no-op until a key
    has been entered, so the idle placeholder is never replaced by an error."""
    if not (submission_key or "").strip():
        return gr.skip()
    return view_submissions(user, submission_key)


def view_submissions(user: str, submission_key: str) -> str:
    """Render one submitter's full submission history, newest first.

    Gated on the submission key issued at first submission — the same secret
    that reserves the username — so a submitter's per-problem results and
    compile errors stay visible only to them."""
    try:
        display = authorize_viewer(user, submission_key)
    except ValueError as e:
        return f"<div class='lra-hist-error'><b>Error:</b> {e}</div>"
    return _history_html(display, submission_history(display))


# ── Benchmark tab content ─────────────────────────────────────────────────────
def _bench_details_md() -> str:
    if not BENCHMARK:
        return "_No benchmark loaded._"
    parts = ["### Statements to prove\n"]
    for name in benchmark_names():
        info = BENCHMARK[name]
        src_key = info.get("source") or ""
        label = SOURCES.get(src_key, {}).get("label", src_key)
        link = benchmark_file_link(name)
        link_md = f" · [source file]({link})" if link else ""
        header = (info.get("header") or "").rstrip()
        header_block = (
            f"**Header (imports/options supplied automatically):**\n\n"
            f"```\n{header}\n```\n\n" if header else ""
        )
        versions = ", ".join(benchmark_versions(name)) or "—"
        parts.append(
            f"<details><summary><code>{html.escape(name)}</code> — {label}, "
            f"{_fmt_int(info['original_proof_length'])} reference tokens"
            f"</summary>\n\n"
            f"{header_block}"
            f"**Statement your `proof` must reproduce (then add `:= by ...`):**\n\n"
            f"```\n{info['statement']}\n```\n\n"
            f"**Evaluated on:** {versions}{link_md}\n\n"
            f"</details>"
        )
    return "\n".join(parts)


# ── Page assembly ─────────────────────────────────────────────────────────────
def _hero_html() -> str:
    return (
        "<section class='lra-hero'>"
        "<div class='lra-eyebrow'>Competition · two tracks · "
        f"{PRIZE_PER_TRACK} prize per track</div>"
        "<h1>Can your agent make Lean proofs <span class='lra-accent'>better</span>, "
        "not just correct?</h1>"
        "<p class='lra-hero-lead'>Lean Refactor Arena is a competition for "
        "refactoring Lean&nbsp;4 proofs — from <b>Strata, PhysLib, CSLib, "
        "ArkLib, and PutnamBench</b> — to be <b>shorter</b>, <b>cheaper to "
        "compile</b>, and <b>more robust across toolchain versions</b>. "
        "Compete in the <b>closed-source frontier LLM track</b> or the "
        "<b>open-source model track</b>; each track's winner takes "
        f"<b>{PRIZE_PER_TRACK}</b> and a talk at the {WORKSHOP_LINK} workshop "
        f"({WORKSHOP_VENUE}).</p>"
        "</section>"
    )


ARXIV_URL = "https://arxiv.org/abs/2605.20244"
CITATION_BIBTEX = (
    "@article{lu2026lean,\n"
    "  title={Lean Refactor: Multi-Objective Controllable Proof Optimization "
    "via Agentic Strategy Search},\n"
    "  author={Lu, Jialin and Kong, Soonho and Stehling, Rodrigo and Yang, Kaiyu "
    "and Wang, Zhangyang and Sun, Weiran and Chen, Wuyang},\n"
    "  journal={arXiv preprint arXiv:2605.20244},\n"
    "  year={2026}\n"
    "}"
)


def _cite_html() -> str:
    bib = html.escape(CITATION_BIBTEX)
    return (
        "<section class='lra-card lra-cite'>"
        "<div class='lra-kicker'>Citation</div>"
        "<h2>Cite this work</h2>"
        "<p class='lra-lead'>If you use Lean Refactor Arena or the benchmark in "
        "your research, please cite the paper.</p>"
        "<div class='lra-cite-actions'>"
        f"<a class='lra-paper-btn' href='{ARXIV_URL}' target='_blank' "
        "rel='noopener noreferrer'>📄 Paper</a>"
        "</div>"
        f"<pre class='lra-code lra-bib'><code>{bib}</code></pre>"
        "</section>"
    )


def _home_body_html() -> str:
    return (
        "<div class='lra-home'>"
        + _sponsor_strip_html()
        + _stat_band_html()
        + _news_html()
        + _timeline_html()
        + _tracks_html()
        + _sources_html()
        + _claims_html()
        + _metric_cards_html()
        + _preview_html()
        + _community_html()
        + _contribute_card_html()
        + _cite_html()
        + "</div>"
    )


def refresh_home():
    LB.reload()
    return _home_body_html()


def _select_tab(tab_id: str):
    return gr.Tabs(selected=tab_id)


APP_CSS = """
:root {
  --bg: #f6f7f2;
  --paper: #ffffff;
  --ink: #14201a;
  --muted: #5c6b62;
  --line: rgba(20, 32, 26, 0.10);
  --green: #0f6b50;
  --green-deep: #0a3f30;
  --gold: #b9842b;
  --accent: #d84a3a;
  --danger: #c0261b;
  --danger-ink: #6d1a13;
  --danger-bg: rgba(192, 38, 27, 0.055);
  --danger-line: rgba(192, 38, 27, 0.28);
  --shadow: 0 18px 50px rgba(15, 40, 30, 0.10);
}
.gradio-container {
  background:
    radial-gradient(900px 460px at 14% -8%, rgba(15, 107, 80, 0.10), transparent 70%),
    radial-gradient(720px 380px at 96% 0%, rgba(185, 132, 43, 0.08), transparent 70%),
    linear-gradient(180deg, #fbfcf8 0%, var(--bg) 46%, #ffffff 100%);
  color: var(--ink);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
}
/* Center the content column. Gradio's own `.contain` rule sets margin-right:0,
   which beat a non-!important `margin: 0 auto` and shoved the page right. */
.gradio-container .contain {
  max-width: 1180px !important;
  margin-left: auto !important;
  margin-right: auto !important;
}
footer { display: none !important; }

/* Tab nav: pin readable colours regardless of the viewer's dark mode. */
.tab-container button[role="tab"]:hover:not(.selected),
.tab-nav button:hover:not(.selected) {
  background-color: rgba(15, 107, 80, 0.10) !important;
  color: var(--green) !important;
}
.tab-container button[role="tab"]:not(.selected),
.tab-nav button:not(.selected) { color: var(--ink) !important; }
.tab-container button[role="tab"].selected,
.tab-nav button.selected { color: var(--green) !important; }

/* top bar */
.lra-topbar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; padding: 6px 2px 2px;
}
.lra-brand { display: flex; align-items: center; gap: 14px; font-weight: 800; font-size: 1.6rem; letter-spacing: -0.01em; }
.lra-brand .dot {
  width: 22px; height: 22px; border-radius: 7px;
  background: linear-gradient(135deg, var(--green), var(--green-deep));
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.25);
}
.lra-brand .lra-logo {
  width: 60px; height: 60px; border-radius: 15px; object-fit: cover;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.25);
}
.lra-pill {
  font-size: 0.72rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.10em;
  color: var(--gold); background: rgba(185,132,43,0.12);
  border: 1px solid rgba(185,132,43,0.30); border-radius: 999px; padding: 3px 10px;
}
.lra-statusbar:empty { display: none; }
.lra-statusbar > div, .lra-statusbar { margin: 8px 0 2px; }

/* shared */
.lra-kicker {
  color: var(--green); font-size: 0.74rem; font-weight: 800;
  letter-spacing: 0.14em; text-transform: uppercase;
}
.lra-accent { color: var(--accent); }
.lra-home { display: flex; flex-direction: column; gap: 20px; padding-bottom: 8px; }
.lra-card {
  background: var(--paper); border: 1px solid var(--line);
  border-radius: 16px; padding: 30px; box-shadow: var(--shadow);
}
.lra-card h2, .lra-claim-copy h2 {
  margin: 8px 0 12px; font-size: clamp(1.5rem, 2.6vw, 2.1rem);
  line-height: 1.1; letter-spacing: -0.015em;
}
.lra-lead { color: var(--muted); max-width: 760px; line-height: 1.65; }
code {
  background: rgba(15,107,80,0.08); color: #0c5a44;
  padding: 1px 6px; border-radius: 6px; font-size: 0.86em;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

/* hero */
.lra-hero { padding: 40px 4px 6px; }
.lra-eyebrow {
  color: var(--green); font-size: 0.8rem; font-weight: 800;
  letter-spacing: 0.16em; text-transform: uppercase;
}
.lra-hero h1 {
  margin: 14px 0 18px; max-width: 940px;
  font-size: clamp(2.4rem, 5.2vw, 4rem); line-height: 1.04;
  letter-spacing: -0.025em; font-weight: 800;
}
.lra-hero-lead {
  max-width: 800px; color: var(--muted);
  font-size: clamp(1.02rem, 1.6vw, 1.18rem); line-height: 1.7;
}
.lra-hero-lead b { color: var(--ink); }

/* CTA row (real gradio buttons) — compact + left-aligned */
.lra-cta-row {
  gap: 12px !important; margin: 4px 0 10px !important;
  flex-wrap: wrap; justify-content: flex-start !important;
}
.lra-cta-row > * { flex: 0 0 auto !important; min-width: 0 !important; }
.lra-cta-row button {
  width: auto !important; white-space: nowrap;
  border-radius: 10px !important; font-weight: 700 !important;
  padding: 12px 24px !important; font-size: 0.98rem !important;
  box-shadow: none !important;
}

/* stat band */
.lra-stat-band {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px;
  background: linear-gradient(135deg, var(--green-deep), #0c5340 70%, #0e6149);
  border-radius: 16px; padding: 30px 20px; box-shadow: var(--shadow);
  border: 1px solid rgba(255,255,255,0.08);
}
.lra-stat { text-align: center; padding: 6px 14px; position: relative; }
.lra-stat + .lra-stat::before {
  content: ""; position: absolute; left: 0; top: 14%; height: 72%;
  width: 1px; background: rgba(255,255,255,0.14);
}
.lra-stat-num {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: clamp(1.8rem, 4vw, 2.8rem); font-weight: 600; line-height: 1;
  color: #f4efe6; letter-spacing: -0.02em;
}
.lra-stat-label {
  margin-top: 12px; color: #e8f3ee; font-size: 0.8rem;
  font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase;
}
.lra-stat-note { margin-top: 4px; color: rgba(225,240,233,0.62); font-size: 0.78rem; }

/* timeline */
.lra-tl-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 16px; margin-top: 18px;
}
.lra-tl-step {
  background: #fbfdfb; border: 1px solid var(--line); border-radius: 13px;
  padding: 20px; position: relative;
}
.lra-tl-when {
  display: inline-block; font-family: ui-monospace, Menlo, monospace;
  font-size: 0.8rem; font-weight: 700; color: var(--gold);
  background: rgba(185,132,43,0.10); border-radius: 7px; padding: 3px 9px;
}
.lra-tl-name { margin: 12px 0 6px; font-weight: 800; font-size: 1.05rem; }
.lra-tl-step p { color: var(--muted); font-size: 0.92rem; line-height: 1.55; margin: 0; }

/* tracks */
.lra-track-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 18px; }
.lra-track {
  background: #fbfdfb; border: 1px solid var(--line); border-radius: 13px;
  padding: 22px; display: flex; flex-direction: column;
}
.lra-track-name { margin: 12px 0 8px; font-weight: 800; font-size: 1.25rem; }
.lra-track ul { margin: 0 0 14px 18px; padding: 0; color: var(--muted); line-height: 1.6; }
.lra-track li { margin-bottom: 8px; font-size: 0.95rem; }
.lra-track li b { color: var(--ink); }
.lra-track-prize {
  margin-top: auto; padding: 10px 14px; border-radius: 9px;
  background: rgba(185,132,43,0.10); border: 1px solid rgba(185,132,43,0.25);
  color: #7a5211; font-size: 0.92rem;
}

/* tech report template callout */
.lra-tpl {
  margin-top: 18px; padding: 20px 22px; border-radius: 13px;
  background: linear-gradient(180deg, rgba(15,107,80,0.05), rgba(15,107,80,0.02));
  border: 1px solid rgba(15,107,80,0.22);
}
.lra-tpl-head { display: flex; gap: 14px; align-items: flex-start; }
.lra-tpl-icon { font-size: 1.5rem; line-height: 1.2; flex: 0 0 auto; }
.lra-tpl-title {
  font-weight: 800; font-size: 1.06rem; color: var(--ink); margin-bottom: 6px;
}
.lra-tpl-lead {
  margin: 0; color: var(--muted); line-height: 1.62; font-size: 0.94rem;
  max-width: 820px;
}
.lra-tpl-lead b { color: var(--ink); }
.lra-tpl-actions {
  display: flex; flex-wrap: wrap; gap: 10px; margin: 14px 0 0 38px;
}
.lra-tpl-btn {
  display: inline-block; padding: 10px 18px;
  border-radius: 10px; font-weight: 700; font-size: 0.94rem;
  text-decoration: none !important; color: #ffffff !important;
  background: linear-gradient(135deg, var(--green), var(--green-deep));
  border: 1px solid rgba(10,63,48,0.5);
  box-shadow: 0 6px 16px rgba(15,107,80,0.22);
}
.lra-tpl-btn-alt {
  color: var(--green-deep) !important; background: var(--paper);
  border: 1px solid rgba(15,107,80,0.32); box-shadow: none;
}
.lra-tpl-btn:hover { filter: brightness(1.08); }
.lra-tpl-btn-alt:hover { background: rgba(15,107,80,0.06); filter: none; }
.lra-tpl-warn {
  margin: 14px 0 0 38px; padding: 10px 14px; border-radius: 9px;
  color: var(--danger-ink); background: var(--danger-bg);
  border: 1px solid var(--danger-line);
  border-left: 4px solid var(--danger);
  font-size: 0.9rem; line-height: 1.55; max-width: 820px;
}
.lra-tpl-warn b { color: var(--danger); }
@media (max-width: 700px) {
  .lra-tpl-actions, .lra-tpl-warn { margin-left: 0; }
}

/* news */
.lra-news-head {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 14px; margin-bottom: 6px;
}
.lra-news-head h2 { margin: 4px 0 0; }
/* Height is capped so roughly three entries show and the rest scroll; the
   card keeps its place on the page however many items NEWS holds. */
.lra-news-list {
  list-style: none; margin: 14px 0 0; padding: 0 14px 0 0;
  max-height: 336px; overflow-y: auto; overscroll-behavior: contain;
  scrollbar-width: thin;
}
.lra-news-list::-webkit-scrollbar { width: 8px; }
.lra-news-list::-webkit-scrollbar-thumb {
  background: var(--line); border-radius: 999px;
}
.lra-news-item {
  display: flex; gap: 18px; padding: 15px 0;
  border-bottom: 1px dashed var(--line);
}
.lra-news-item:first-child { padding-top: 2px; }
.lra-news-item:last-child { border-bottom: 0; }
.lra-news-date {
  flex: none; width: 124px; padding-top: 2px;
  font-size: 0.76rem; font-weight: 700; color: var(--green);
  letter-spacing: 0.02em; white-space: nowrap;
}
.lra-news-body h3 {
  margin: 0 0 5px; font-size: 1.02rem; font-weight: 750; line-height: 1.35;
}
.lra-news-body p {
  margin: 0; color: var(--muted); font-size: 0.93rem; line-height: 1.6;
}
.lra-news-body code {
  background: var(--wash); border: 1px solid var(--line);
  border-radius: 5px; padding: 0 4px; font-size: 0.86em;
}
.lra-news-hint {
  margin-top: 12px; padding-top: 11px; border-top: 1px solid var(--line);
  font-size: 0.76rem; color: var(--muted); text-align: center;
}
@media (max-width: 640px) {
  .lra-news-item { flex-direction: column; gap: 4px; }
  .lra-news-date { width: auto; }
  .lra-news-list { max-height: 420px; }
}

/* desk-rejection rules */
.lra-danger {
  border-color: var(--danger-line);
  border-top: 4px solid var(--danger);
  background:
    linear-gradient(180deg, rgba(192,42,31,0.045), rgba(192,42,31,0) 220px),
    var(--paper);
}
.lra-dr-kicker {
  color: var(--danger); font-size: 0.76rem; font-weight: 800;
  letter-spacing: 0.13em; text-transform: uppercase;
}
.lra-danger h2.lra-dr-h2 { color: var(--danger); }
.lra-dr-lead {
  color: var(--muted); max-width: 820px; line-height: 1.65; margin: 0;
}
.lra-dr-lead b { color: var(--danger); }
.lra-dr-list {
  list-style: none; counter-reset: dr; margin: 20px 0 0; padding: 0;
  display: grid; grid-template-columns: 1fr 1fr; gap: 14px;
}
.lra-dr-item {
  counter-increment: dr; position: relative;
  padding: 16px 18px 16px 46px; border-radius: 12px;
  background: var(--danger-bg); border: 1px solid var(--danger-line);
  border-left: 4px solid var(--danger);
}
.lra-dr-item::before {
  content: counter(dr); position: absolute; left: 14px; top: 16px;
  width: 22px; height: 22px; border-radius: 999px;
  background: var(--danger); color: #ffffff;
  font-size: 0.74rem; font-weight: 800;
  display: flex; align-items: center; justify-content: center;
}
.lra-dr-name {
  font-weight: 800; font-size: 1rem; color: var(--danger); margin-bottom: 6px;
}
.lra-dr-item p {
  margin: 0; color: var(--danger-ink); font-size: 0.92rem; line-height: 1.6;
}
.lra-dr-item p b { color: var(--danger); font-weight: 800; }
.lra-dr-item code {
  background: rgba(192,42,31,0.10); color: #8f1f16;
}
.lra-dr-foot {
  margin: 18px 0 0; color: var(--muted); font-size: 0.9rem; line-height: 1.6;
}
.lra-dr-foot a { color: var(--danger); font-weight: 700; }
.lra-formula {
  margin: 16px 0 4px; padding: 14px 18px; border-radius: 12px;
  background: rgba(192,38,27,0.055); border: 1px solid var(--danger-line);
  display: flex; flex-direction: column; gap: 8px;
  font-size: 0.92rem; line-height: 1.5;
}
.lra-formula > div { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; }
.lra-f-lhs { color: var(--danger); font-weight: 800; min-width: 106px; }
.lra-f-eq { color: var(--muted); font-weight: 700; }
.lra-formula b { color: var(--danger); }
@media (max-width: 860px) {
  .lra-dr-list { grid-template-columns: 1fr; }
}

/* benchmark sources */
.lra-src-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 18px; }
.lra-src {
  display: flex; gap: 14px; align-items: flex-start;
  background: #fbfdfb; border: 1px solid var(--line); border-radius: 13px; padding: 18px;
}
.lra-src-logo {
  width: 52px; height: 52px; border-radius: 11px; object-fit: contain;
  background: #ffffff; border: 1px solid var(--line); flex: 0 0 auto; padding: 4px;
}
.lra-src-name { font-weight: 800; font-size: 1.02rem; display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.lra-src-name a { color: var(--ink); text-decoration: none; border-bottom: 1px dotted var(--muted); }
.lra-src-name a:hover { color: var(--green); border-color: var(--green); }
.lra-src-body p { color: var(--muted); font-size: 0.9rem; line-height: 1.55; margin: 6px 0 0; }

/* claims */
.lra-claims { display: flex; flex-direction: column; gap: 20px; }
.lra-claim {
  display: grid; grid-template-columns: 0.82fr 1fr; gap: 26px;
  align-items: center; background: var(--paper); border: 1px solid var(--line);
  border-radius: 16px; padding: 28px 30px; box-shadow: var(--shadow);
}
.lra-claim-copy h2 { font-size: clamp(1.45rem, 2.6vw, 2rem); }
.lra-claim-copy p { color: var(--muted); line-height: 1.65; margin-top: 2px; }
.lra-code-pair { display: grid; gap: 12px; }
.lra-code {
  margin: 0; background: #0e1512; color: #d8e6df;
  border: 1px solid rgba(120,180,150,0.16); border-radius: 12px;
  padding: 16px 18px; overflow-x: auto;
  font-size: 0.82rem; line-height: 1.6;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.04);
}
.lra-code code { background: none; color: inherit; padding: 0; font-size: inherit; }
.lra-code .k { color: #ff8fb3; }
.lra-code .n { color: #e9c07b; }
.lra-code .c { color: #6f8a7e; font-style: italic; }

/* scoring metrics */
.lra-metric-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-top: 18px;
}
.lra-metric {
  background: #fbfdfb; border: 1px solid var(--line); border-radius: 13px; padding: 20px;
}
.lra-metric-tag {
  display: inline-block; font-family: ui-monospace, Menlo, monospace;
  font-size: 0.82rem; font-weight: 700; color: var(--green);
  background: rgba(15,107,80,0.10); border-radius: 7px; padding: 3px 9px;
}
.lra-metric-name { margin: 12px 0 6px; font-weight: 800; font-size: 1.05rem; }
.lra-metric p { color: var(--muted); font-size: 0.92rem; line-height: 1.55; margin: 0; }

/* citation + link-buttons */
.lra-cite-actions { margin: 16px 0; }
.lra-paper-btn {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 10px 18px; border-radius: 10px; font-weight: 800; font-size: 0.95rem;
  color: #ffffff !important; text-decoration: none !important;
  background: linear-gradient(135deg, var(--green), var(--green-deep));
  box-shadow: 0 6px 18px rgba(15,107,80,0.22);
  transition: transform .12s ease, box-shadow .12s ease;
}
.lra-paper-btn:hover { transform: translateY(-1px); box-shadow: 0 10px 24px rgba(15,107,80,0.30); }
.lra-btn-soon {
  background: linear-gradient(135deg, #8aa198, #6d827a); cursor: default;
  box-shadow: none; opacity: 0.85;
}
.lra-btn-soon:hover { transform: none; box-shadow: none; }
.lra-linknote { color: var(--muted); font-size: 0.9rem; margin: 0; max-width: 720px; }
.lra-bib {
  white-space: pre-wrap; word-break: break-word; overflow-x: auto;
  font-size: 0.82rem; margin: 0;
}

/* leaderboard table */
.lra-lb { margin-top: 16px; }

/* home leaderboard-preview track picker */
.lra-preview-pick { display: flex; gap: 10px; margin: 14px 0 4px; flex-wrap: wrap; }
.lra-pickbtn {
  padding: 12px 22px; font-size: 1rem; font-weight: 800; cursor: pointer;
  border: 1px solid var(--line); border-radius: 999px;
  background: var(--paper); color: var(--ink);
  transition: border-color .15s ease, color .15s ease, box-shadow .15s ease;
}
.lra-pickbtn:hover { border-color: var(--green); color: var(--green); }
.lra-pickbtn.active {
  background: linear-gradient(135deg, var(--green), var(--green-deep));
  color: #ffffff; border-color: transparent;
  box-shadow: 0 6px 18px rgba(15,107,80,0.22);
}
.lra-pickbtn.active:hover { color: #ffffff; }
.lra-table-wrap {
  overflow: visible; border: 1px solid var(--line);
  border-radius: 14px; background: var(--paper);
}
.lra-table { width: 100%; table-layout: fixed; border-collapse: separate; border-spacing: 0; font-size: 0.9rem; }
.lra-table th, .lra-table td {
  padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: middle;
  overflow-wrap: anywhere; word-break: break-word;
}
.lra-table th[data-col='rank'] { width: 44px; }
.lra-table th[data-col='user'] { width: 12%; }
.lra-table th[data-col='model'] { width: 22%; }
.lra-table th[data-col='submitted'] { width: 92px; }
.lra-table thead th {
  position: sticky; top: 0; z-index: 5; background: var(--paper);
  color: var(--muted); font-size: 0.76rem; font-weight: 800;
  cursor: pointer; user-select: none; white-space: normal;
  box-shadow: inset 0 -1px 0 var(--line);
}
.lra-table thead th:hover { color: var(--ink); }
.lra-th { display: inline-flex; align-items: baseline; gap: 4px; flex-wrap: wrap; }
.lra-better { color: var(--green); font-weight: 800; font-size: 0.95rem; }
.lra-sort { font-size: 1.05em; color: #2f6fb0; }
.lra-sort::after { content: '▾'; opacity: 0.5; }
.lra-table thead th[data-dir='asc'] .lra-sort::after { content: '▲'; opacity: 1; }
.lra-table thead th[data-dir='desc'] .lra-sort::after { content: '▼'; opacity: 1; }
.lra-table thead th[data-dir] { color: var(--ink); }
.lra-thcell.has-tip .lra-th-label { border-bottom: 1px dotted var(--muted); }
.lra-tip { display: none; }
.lra-tip-float {
  display: none; position: fixed; z-index: 9999; width: 280px; max-width: 76vw;
  background: var(--ink); color: #f2f5f2; text-align: left; font-weight: 500;
  letter-spacing: 0; font-size: 0.8rem; line-height: 1.5;
  padding: 10px 12px; border-radius: 10px; box-shadow: var(--shadow); white-space: normal;
}
.lra-tip-float a { color: #bfe9d3; text-decoration: underline; text-underline-offset: 2px; }
.lra-tip-float code { background: rgba(255,255,255,0.22); color: #ffffff; padding: 1px 5px; border-radius: 4px; font-size: 0.92em; }
.lra-table tbody tr:nth-child(even) { background: rgba(20,32,26,0.025); }
.lra-table tbody tr:hover { background: rgba(15,107,80,0.06); }
.lra-table td.rank { font-family: ui-monospace, Menlo, monospace; color: var(--green); font-weight: 700; white-space: nowrap; }
.lra-table td.who { font-weight: 700; }
.lra-table td.who a { color: var(--ink); text-decoration: none; border-bottom: 1px dotted var(--muted); }
.lra-table td.who a:hover { color: var(--green); border-color: var(--green); }
.lra-table td.model { font-size: 0.82rem; line-height: 1.35; }
.lra-model-name { color: var(--ink); font-weight: 700; }
.lra-model-settings { color: var(--muted); margin-top: 3px; }
.lra-model-settings span { font-weight: 700; }
.lra-cell-num { font-variant-numeric: tabular-nums; }
.lra-cell-num.lra-na { color: var(--muted); opacity: 0.7; }
.lra-bar { margin-top: 5px; height: 5px; border-radius: 3px; background: rgba(20,32,26,0.08); overflow: hidden; }
.lra-bar > span { display: block; height: 100%; border-radius: 3px; background: linear-gradient(90deg, var(--green), var(--green-deep)); }
.lra-bar.neg > span { background: var(--accent); }
.lra-bar.diverging { position: relative; overflow: visible; }
.lra-bar.diverging::before { content: ''; position: absolute; left: 50%; top: -2px; bottom: -2px; width: 1px; background: rgba(20,32,26,0.32); }
.lra-bar.diverging .lra-bar-fill { position: absolute; top: 0; bottom: 0; border-radius: 2px; }
.lra-bar.diverging .lra-bar-fill.pos { left: 50%; background: linear-gradient(90deg, var(--green), var(--green-deep)); }
.lra-bar.diverging .lra-bar-fill.neg { right: 50%; background: var(--accent); }
.lra-table td[data-col='combined'] .lra-cell-num,
.lra-table td[data-col='length'] .lra-cell-num,
.lra-table td[data-col='heartbeat'] .lra-cell-num { font-weight: 600; }
.lra-df table { table-layout: auto !important; }
.lra-df th, .lra-df td { white-space: normal !important; overflow-wrap: anywhere; word-break: break-word; vertical-align: top; }
.lra-df th .header-content, .lra-df th span { white-space: normal !important; }
.lra-empty {
  margin-top: 16px; padding: 26px; text-align: center; color: var(--muted);
  border: 1px dashed var(--line); border-radius: 12px; background: #fbfdfb;
}

/* My submissions: one card per submission, grouped by day */
.lra-hist { display: flex; flex-direction: column; gap: 18px; margin-top: 16px; }
.lra-hist-head {
  display: flex; align-items: flex-end; justify-content: space-between;
  gap: 16px; flex-wrap: wrap;
}
.lra-hist-head h3 { margin: 4px 0 0; font-size: 1.35rem; letter-spacing: -0.015em; }
.lra-hist-count { color: var(--muted); font-size: 0.9rem; }
.lra-hist-error {
  margin-top: 16px; padding: 14px 18px; border-radius: 12px;
  background: var(--danger-bg); border: 1px solid var(--danger-line);
  border-left: 4px solid var(--danger); color: var(--danger-ink);
  line-height: 1.6; max-width: 860px;
}
.lra-hist-error b { color: var(--danger); }
.lra-day { display: flex; flex-direction: column; gap: 10px; }
.lra-day-label {
  color: var(--green); font-size: 0.74rem; font-weight: 800;
  letter-spacing: 0.14em; text-transform: uppercase;
}
.lra-sub {
  background: var(--paper); border: 1px solid var(--line);
  border-radius: 14px; overflow: hidden;
}
.lra-sub[open] { box-shadow: var(--shadow); }
.lra-sub > summary {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  padding: 14px 18px; cursor: pointer; list-style: none;
  font-size: 0.95rem;
}
.lra-sub > summary::-webkit-details-marker { display: none; }
.lra-sub > summary::before {
  content: '▸'; color: var(--muted); font-size: 0.8rem;
  transition: transform 0.15s ease;
}
.lra-sub[open] > summary::before { transform: rotate(90deg); }
.lra-sub > summary:hover { background: rgba(15,107,80,0.05); }
.lra-sub-when { font-weight: 700; font-variant-numeric: tabular-nums; }
.lra-sub-facts { color: var(--muted); margin-left: auto; text-align: right; }
.lra-sub-facts b { color: var(--ink); }
.lra-sub-body { padding: 0 18px 18px; border-top: 1px solid var(--line); }
.lra-sub-msg { color: var(--muted); margin: 12px 0 0; line-height: 1.6; }
.lra-sub-body .lra-empty { margin-top: 14px; }
.lra-badge {
  display: inline-block; padding: 2px 9px; border-radius: 999px;
  font-size: 0.72rem; font-weight: 800; letter-spacing: 0.06em;
  text-transform: uppercase; white-space: nowrap;
  background: rgba(20,32,26,0.07); color: var(--muted);
}
.lra-badge.d, .lra-badge.ok {
  background: rgba(15,107,80,0.12); color: var(--green-deep);
}
.lra-badge.q, .lra-badge.skip { background: rgba(20,32,26,0.07); color: var(--muted); }
.lra-badge.r, .lra-badge.live, .lra-badge.warn {
  background: rgba(185,132,43,0.16); color: #7a5615;
}
.lra-badge.e, .lra-badge.bad {
  background: rgba(192,38,27,0.10); color: var(--danger-ink);
}
.lra-hist-wrap { overflow-x: auto; margin-top: 14px; border-radius: 12px; }
.lra-hist-table { table-layout: auto; min-width: 900px; }
.lra-hist-table thead th {
  color: var(--muted); font-size: 0.72rem; font-weight: 800;
  letter-spacing: 0.08em; text-transform: uppercase; white-space: nowrap;
}
.lra-hist-table tbody tr:last-child td { border-bottom: none; }
.lra-hist-table td.lra-prob code {
  font-size: 0.82rem; color: var(--ink); background: none; padding: 0;
}
.lra-hist-table td.lra-score .lra-cell-num { font-weight: 800; color: var(--green-deep); }
.lra-hist-table td.lra-score .lra-cell-num.lra-down { color: var(--accent); }
.lra-hist-table .lra-ref { display: block; color: var(--muted); font-size: 0.75rem; }
.lra-hist-table .lra-down { color: var(--accent); }
.lra-hist-table .lra-na { color: var(--muted); opacity: 0.7; }
.lra-hist-note { color: var(--muted); font-size: 0.8rem; line-height: 1.45; }
@media (max-width: 720px) {
  .lra-sub-facts { margin-left: 0; text-align: left; width: 100%; }
}

/* sponsors */
.lra-sponsors { text-align: center; padding: 14px 0 6px; }
.lra-sponsor-group + .lra-sponsor-group {
  margin-top: 22px; padding-top: 16px; border-top: 1px solid var(--line);
}
.lra-sponsors .lra-kicker { color: var(--muted); font-size: 1.15rem; margin-bottom: 6px; }
.lra-logo-row {
  display: flex; flex-wrap: wrap; align-items: center; justify-content: center;
  gap: 40px; margin-top: 16px;
}
.lra-logo { display: flex; align-items: center; justify-content: center; }
.lra-logo img {
  height: 62px; max-width: 260px; object-fit: contain;
  filter: grayscale(0.35); opacity: 0.88; transition: filter .2s, opacity .2s;
}
.lra-logo-reasonable { background: #171914; border-radius: 8px; padding: 8px 12px; }
.lra-logo:hover img { filter: grayscale(0); opacity: 1; }

/* leaderboard track selector: large, unmissable pills */
.lra-track-tabs .tab-nav button, .lra-track-tabs button[role="tab"] {
  font-size: 1.12rem !important; font-weight: 800 !important;
  padding: 16px 30px !important;
  border-radius: 12px 12px 0 0 !important;
}
.lra-track-tabs .tab-nav button.selected,
.lra-track-tabs button[role="tab"].selected {
  background: rgba(15,107,80,0.10) !important;
  box-shadow: inset 0 -3px 0 var(--green) !important;
}

/* big benchmark download button */
.lra-download-btn {
  max-width: 420px !important;
  font-size: 1.08rem !important; font-weight: 800 !important;
  padding: 16px 30px !important; border-radius: 12px !important;
  margin: 10px 0 18px !important;
}

/* "coming soon" / caution callout inside a tab */
.lra-note {
  background: rgba(185,132,43,0.10); border: 1px solid rgba(185,132,43,0.32);
  border-left: 4px solid var(--gold); border-radius: 12px;
  padding: 14px 18px; margin: 16px 0 4px;
  color: var(--ink); line-height: 1.65; max-width: 860px;
}
.lra-note b { color: var(--green-deep); }

/* page intros for inner tabs */
.lra-intro {
  background: var(--paper); border: 1px solid var(--line); border-radius: 14px;
  padding: 22px 26px; margin-bottom: 16px; box-shadow: var(--shadow);
}
.lra-intro h2 { margin: 6px 0 8px; font-size: 1.5rem; letter-spacing: -0.015em; }
.lra-intro p { color: var(--muted); line-height: 1.6; margin: 0; max-width: 860px; }
.lra-intro p b { color: var(--ink); }

/* Keep native Gradio text readable regardless of the viewer's light/dark theme. */
.dark {
  --body-text-color: #14201a;
  --body-text-color-subdued: #5c6b62;
  --block-background-fill: #ffffff;
  --block-title-text-color: #14201a;
  --block-label-text-color: #5c6b62;
  --block-info-text-color: #5c6b62;
  --input-background-fill: #ffffff;
  --input-text-color: #14201a;
  --input-placeholder-color: #8a978f;
  --border-color-primary: rgba(20, 32, 26, 0.14);
  --table-even-background-fill: #ffffff;
  --table-odd-background-fill: #fbfdfb;
  --table-text-color: #14201a;
  color-scheme: light;
}

div[data-testid="dataframe"] { border-radius: 12px !important; overflow: hidden; }

@media (max-width: 900px) {
  .lra-claim { grid-template-columns: 1fr; }
  .lra-stat-band { grid-template-columns: repeat(2, 1fr); row-gap: 22px; }
  .lra-stat:nth-child(3)::before { display: none; }
  .lra-metric-grid, .lra-tl-grid, .lra-track-grid, .lra-src-grid { grid-template-columns: 1fr; }
}
@media (max-width: 560px) {
  .lra-stat-band { grid-template-columns: 1fr; }
  .lra-stat::before { display: none !important; }
  .lra-card, .lra-claim { padding: 20px; }
}
"""


# Client-side interactivity for the custom tables (sort/search/columns +
# header tooltips). Attached at the document level so it survives Gradio's
# periodic gr.HTML re-renders.
LB_JS = """
<script>
(function () {
  function num(v) { var n = parseFloat(v); return isNaN(n) ? null : n; }
  // ---- header hover tooltips (fixed-positioned, clip-proof) ----
  var tf = null, hideTimer = null;
  function ensureFloat() {
    if (tf) return tf;
    tf = document.createElement('div');
    tf.className = 'lra-tip-float';
    document.body.appendChild(tf);
    tf.addEventListener('mouseenter', function () { clearTimeout(hideTimer); });
    tf.addEventListener('mouseleave', hideTip);
    return tf;
  }
  function hideTip() { clearTimeout(hideTimer); hideTimer = setTimeout(function () { if (tf) tf.style.display = 'none'; }, 150); }
  document.addEventListener('mouseover', function (e) {
    var th = e.target.closest && e.target.closest('.lra-thcell.has-tip');
    if (!th) return;
    var src = th.querySelector('.lra-tip'); if (!src) return;
    var f = ensureFloat();
    clearTimeout(hideTimer);
    f.innerHTML = src.innerHTML;
    f.style.display = 'block';
    var r = th.getBoundingClientRect();
    var fw = f.offsetWidth, fh = f.offsetHeight;
    var left = Math.max(8, Math.min(r.left + r.width / 2 - fw / 2, window.innerWidth - fw - 8));
    var top = r.bottom + 6;
    if (top + fh > window.innerHeight - 8) top = r.top - fh - 6;   // open upward if no room below
    f.style.left = left + 'px';
    f.style.top = Math.max(8, top) + 'px';
  });
  document.addEventListener('mouseout', function (e) {
    var th = e.target.closest && e.target.closest('.lra-thcell.has-tip');
    if (!th) return;
    var to = e.relatedTarget;
    if (to && to.closest && (to.closest('.lra-thcell.has-tip') === th || to.closest('.lra-tip-float'))) return;
    hideTip();
  });

  document.addEventListener('click', function (e) {
    if (!e.target.closest) return;
    if (e.target.closest('.lra-tip-float')) return;   // let tooltip links work, don't sort
    if (e.target.closest('a')) return;                // let links in cells work, don't sort
    // home leaderboard-preview track picker
    var pk = e.target.closest('.lra-pickbtn');
    if (pk) {
      var sec = pk.closest('.lra-preview');
      var tr = pk.getAttribute('data-track');
      Array.prototype.forEach.call(sec.querySelectorAll('.lra-pickbtn'), function (b) {
        b.classList.toggle('active', b === pk);
      });
      Array.prototype.forEach.call(sec.querySelectorAll('.lra-preview-panel'), function (pl) {
        pl.style.display = pl.getAttribute('data-track') === tr ? '' : 'none';
      });
      return;
    }
    var th = e.target.closest('.lra-table th[data-sortable]');
    if (th) {
      var table = th.closest('table');
      var ths = Array.prototype.slice.call(table.querySelectorAll('th[data-sortable]'));
      var idx = Array.prototype.indexOf.call(th.parentNode.children, th);
      var cur = th.getAttribute('data-dir') || 'none';
      var next = cur === 'desc' ? 'asc' : (cur === 'asc' ? 'none' : 'desc');
      ths.forEach(function (h) { if (h !== th) h.removeAttribute('data-dir'); });
      if (next === 'none') th.removeAttribute('data-dir');
      else th.setAttribute('data-dir', next);
      var tbody = table.querySelector('tbody');
      var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
      rows.sort(function (a, b) {
        if (next === 'none') return (num(a.dataset.rank) || 0) - (num(b.dataset.rank) || 0);
        var av = a.children[idx].dataset.sort, bv = b.children[idx].dataset.sort;
        var an = num(av), bn = num(bv), c;
        if (an !== null && bn !== null) c = an - bn;
        else c = String(av || '').localeCompare(String(bv || ''));
        return next === 'asc' ? c : -c;
      });
      rows.forEach(function (r) { tbody.appendChild(r); });
      return;
    }
  });
})();
</script>
"""

def _topbar_html() -> str:
    """Brand bar shown at the top of every page (main app + /contribute)."""
    return (
        "<div class='lra-topbar'>"
        "<div class='lra-brand'>"
        + (
            f"<img class='lra-logo' src='{APP_ICON_DATA_URI}' alt='Lean Refactor Arena logo'/>"
            if APP_ICON_DATA_URI
            else "<span class='dot'></span>"
        )
        + "Lean Refactor Arena</div>"
        "<span class='lra-pill'>Warm-up phase · full benchmark drops Nov 1</span>"
        "</div>"
    )


# Header shared by the Contribute tab and the standalone /contribute page. The
# "here's what makes a good candidate problem" lead-in only belongs on the page
# that actually follows it with the criteria.
def _contrib_intro_html(with_lead_in: bool) -> str:
    lead_in = (
        " — here's what makes a good candidate problem" if with_lead_in else ""
    )
    return (
        "<div class='lra-intro'>"
        "<div class='lra-kicker'>Grow the benchmark</div>"
        "<h2>Contributing: harvesting long Lean proofs</h2>"
        "<p>The benchmark grows with the community. If you maintain or "
        "know a Lean development with long, expensive proofs, we'd "
        f"love to include them{lead_in}.</p>"
        "</div>"
    )


CONTRIB_PAGE_CSS = """
:root {
  --bg: #f6f7f2; --paper: #ffffff; --ink: #14201a; --muted: #5c6b62;
  --line: rgba(20, 32, 26, 0.10); --green: #0f6b50; --green-deep: #0a3f30;
  --gold: #b9842b; --shadow: 0 18px 50px rgba(15, 40, 30, 0.10);
}
* { box-sizing: border-box; }
body {
  margin: 0; color: var(--ink);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  background:
    radial-gradient(900px 460px at 14% -8%, rgba(15, 107, 80, 0.10), transparent 70%),
    radial-gradient(720px 380px at 96% 0%, rgba(185, 132, 43, 0.08), transparent 70%),
    linear-gradient(180deg, #fbfcf8 0%, var(--bg) 46%, #ffffff 100%);
  background-attachment: fixed;
}
.lra-page { max-width: 1000px; margin: 0 auto; padding: 18px 20px 64px; }
.lra-topbar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; padding: 6px 2px 2px;
}
.lra-brand {
  display: flex; align-items: center; gap: 14px;
  font-weight: 800; font-size: 1.6rem; letter-spacing: -0.01em;
}
.lra-brand .lra-logo { width: 60px; height: 60px; border-radius: 15px; object-fit: cover; }
.lra-brand .dot {
  width: 22px; height: 22px; border-radius: 7px;
  background: linear-gradient(135deg, var(--green), var(--green-deep));
}
.lra-pill {
  font-size: 0.72rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.10em;
  color: var(--gold); background: rgba(185,132,43,0.12);
  border: 1px solid rgba(185,132,43,0.30); border-radius: 999px; padding: 3px 10px;
}
.lra-backlink { margin: 18px 0; }
.lra-backlink a { color: var(--green); font-weight: 700; font-size: 0.92rem; text-decoration: none; }
.lra-backlink a:hover { text-decoration: underline; }
.lra-intro {
  background: var(--paper); border: 1px solid var(--line);
  border-radius: 16px; padding: 22px 26px; box-shadow: var(--shadow);
}
.lra-kicker {
  color: var(--green); font-size: 0.74rem; font-weight: 800;
  letter-spacing: 0.14em; text-transform: uppercase;
}
.lra-intro h2 { margin: 6px 0 8px; font-size: 1.5rem; letter-spacing: -0.015em; }
.lra-intro p { color: var(--muted); line-height: 1.6; margin: 0; max-width: 860px; }
.lra-guide { max-width: 860px; line-height: 1.65; padding: 4px 4px 0; }
.lra-guide h2 {
  margin: 34px 0 10px; font-size: 1.28rem; letter-spacing: -0.01em;
  padding-bottom: 6px; border-bottom: 1px solid var(--line);
}
.lra-guide p { margin: 12px 0; }
.lra-guide ul { margin: 12px 0; padding-left: 22px; }
.lra-guide li { margin: 6px 0; }
.lra-guide hr { border: 0; border-top: 1px solid var(--line); margin: 34px 0; }
.lra-guide a { color: var(--green); }
.lra-guide code {
  font-family: ui-monospace, Menlo, monospace; font-size: 0.88em;
  background: rgba(15,107,80,0.08); border-radius: 6px; padding: 2px 6px;
}
@media (max-width: 640px) {
  .lra-page { padding: 12px 14px 48px; }
  .lra-brand { font-size: 1.25rem; }
  .lra-brand .lra-logo { width: 44px; height: 44px; border-radius: 11px; }
}
"""

_MD = MarkdownIt("commonmark")


def _contribution_page_html() -> str:
    """The standalone /contribute document — plain HTML, no Gradio runtime."""
    return (
        "<!doctype html>\n"
        "<html lang='en'>\n<head>\n"
        "<meta charset='utf-8'>\n"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>\n"
        "<title>Contributing · Lean Refactor Arena</title>\n"
        + (
            f"<link rel='icon' href='{APP_ICON_DATA_URI}'>\n"
            if APP_ICON_DATA_URI
            else ""
        )
        + f"<style>{CONTRIB_PAGE_CSS}</style>\n"
        "</head>\n<body>\n<div class='lra-page'>\n"
        + _topbar_html()
        + "<div class='lra-backlink'><a href='/'>← Back to the arena</a></div>"
        + _contrib_intro_html(with_lead_in=True)
        + "<div class='lra-guide'>"
        + _MD.render(CONTRIBUTION_MD)
        + "</div>\n</div>\n</body>\n</html>\n"
    )


with gr.Blocks(
    title="Lean Refactor Arena",
    theme=gr.themes.Soft(primary_hue="green", neutral_hue="stone"),
    css=APP_CSS,
    head=LB_JS,
) as demo:
    gr.HTML(_topbar_html())

    with gr.Tabs() as app_tabs:
        # ── Home ──────────────────────────────────────────────────────────────
        with gr.Tab("Home", id="home"):
            gr.HTML(value=_hero_html())
            with gr.Row(elem_classes=["lra-cta-row"]):
                home_submit_btn = gr.Button("Submit your proofs", variant="primary")
                home_lb_btn = gr.Button("View the leaderboard", variant="secondary")
                home_rules_btn = gr.Button("Tracks & rules", variant="secondary")
            home_body = gr.HTML(value=_home_body_html())
            gr.Timer(value=60).tick(refresh_home, outputs=home_body)

        # ── Tracks & Rules ────────────────────────────────────────────────────
        with gr.Tab("Tracks & Rules", id="rules"):
            gr.HTML(
                "<div class='lra-intro'>"
                "<div class='lra-kicker'>Competition rules</div>"
                "<h2>Tracks, budgets, and what you must submit</h2>"
                "<p>The arena runs one benchmark under two resource regimes, "
                "ranked separately. Enter either track — or both, with "
                "separate submissions. This competition is part of the "
                f"{WORKSHOP_LINK} workshop at {WORKSHOP_VENUE}.</p>"
                "</div>"
            )
            gr.HTML(value=_tracks_html(compact=False))
            gr.Markdown(
                "### Closed-source LLM track\n\n"
                "- **Models.** Any closed-source frontier LLM accessed through "
                "its API (e.g. GPT, Claude, Gemini). You may build arbitrary "
                "harnesses around the model.\n"
                f"- **Budget.** API spend is capped at **US$3 per problem**, "
                "measured at the provider's list prices. Your tech report "
                "must state the models used and the per-problem spend.\n"
                "- **Deliverables.** The refactored proofs (JSONL) and the "
                "complete harness code, uploaded here, plus a short tech "
                f"report submitted on [OpenReview]({OPENREVIEW_URL}), enough "
                "for the organizers to reproduce your results.\n\n"
                "### Open-source LLM track\n\n"
                "- **Models.** Open-source models only — weights must be "
                "publicly available. You may post-train them, build a harness "
                "around them, or both.\n"
                "- **Budget.** Inference must be deployable on at most "
                "**4× 80 GB A100 GPUs**, and the full benchmark run must "
                "complete within **48 hours** on that hardware.\n"
                "- **Deliverables.** The refactored proofs (JSONL) and the "
                "inference code (harness + how the model is served), uploaded "
                "here, plus a short tech report submitted on "
                f"[OpenReview]({OPENREVIEW_URL}), enough for the organizers "
                "to reproduce your results. Post-training code is not "
                "required.\n\n"
            )
            gr.HTML(value=_scoring_html())
            gr.Markdown(
                "### Prizes\n\n"
                f"- **{PRIZE_PER_TRACK}** for the winner of each track.\n"
                "- A **dedicated presentation slot** at the "
                f"[{WORKSHOP_NAME}]({WORKSHOP_URL}) workshop "
                f"({WORKSHOP_VENUE}) for each track winner.\n\n"
                f"_{DISCLAIMER}_\n\n"
                "### Tech report & code\n\n"
                "Every entry on the full benchmark must be accompanied by a "
                "**short technical report** and the **code** that produced the "
                "proofs. They go to two different places: the **report is "
                f"submitted on [OpenReview]({OPENREVIEW_URL})**, the workshop's "
                "submission venue, and the **code is uploaded here** under "
                "**Submit → Code**. The report must cover:\n\n"
                "- **Approach** — how the refactoring pipeline works, "
                "end to end.\n"
                "- **Models** — every model used, with exact names/versions "
                "(and, for the open track, weight sources).\n"
                "- **Budget accounting** — closed track: per-problem API "
                "spend at the provider's list prices. Open track: the "
                "hardware used and the wall-clock time of the full benchmark "
                "run.\n"
                "The reproduction commands do **not** go in the report: the "
                "code goes in a single archive (`.zip` or `.tar.gz`) with a "
                "**README at the top level listing the exact steps** the "
                "organizers should run to regenerate your submitted JSONL.\n\n"
                "The report itself must be written in the official competition "
                f"template, [`{REPORT_TEMPLATE_TEX}`]({REPORT_TEMPLATE_URL}), "
                f"built with `{REPORT_TEMPLATE_STY}`, and must be "
                f"**{REPORT_PAGE_LIMIT}** including figures, with references "
                "and appendices excluded from that count. At submission time "
                "omit the `final` and `preprint` style options so the PDF "
                "carries line numbers for review.\n\n"
                "**Review is single-blind.** Competition reports are **not "
                "anonymized**: give your real names, affiliations, and "
                "contact information. Reviewers see who you are, and you do "
                "not see who reviews you. The submission is deliberately not "
                "anonymous because the organizers may need to contact you "
                "about your code and your submission while the competition "
                "entries are being reviewed, for example to resolve a failed "
                "reproduction or a question about your budget accounting.\n\n"
                "**Proofs and code are submitted here; the report is "
                f"submitted on [OpenReview]({OPENREVIEW_URL}).** Send proofs "
                "whenever you like — you can add the code at the end, under "
                f"the same username, any time before the {DEADLINE} deadline "
                "(**Submit → Code**). The report goes to the workshop's "
                "OpenReview venue by that same deadline; no part of it is "
                "uploaded to this site.\n"
            )
            gr.HTML(value=_desk_rejection_html())
            gr.Markdown(
                "### Timeline\n\n"
                "| Phase | Dates | What happens |\n"
                "|---|---|---|\n"
                "| Warm-up — submissions open | now – Oct 31, 2026 | Public "
                "development subset live; submissions accepted on the "
                "practice benchmark |\n"
                f"| Full benchmark | {FULL_BENCH_RELEASE} | Full "
                f"{FULL_BENCH_SIZE}-problem benchmark released; leaderboard "
                "refreshed — entries are evaluated on the full benchmark "
                "(proofs + code here, tech report on OpenReview) from here "
                "on |\n"
                f"| Deadline | {DEADLINE} | Proof and code submissions close; "
                "tech reports due on OpenReview |\n"
                f"| Review & awards | {WINNERS_ANNOUNCED} | Organizers "
                "reproduce top entries; winners announced and presented at "
                "the workshop |\n\n"
                "### Fine print\n\n"
                "- Results must be **reproducible** from the submitted code "
                "within the stated budget; organizers will re-run top "
                "entries.\n"
                "- One team may enter **both tracks** with separate "
                "submissions.\n"
                "- Only rows whose `name` matches a benchmark id are scored; "
                "unmatched rows are ignored, and you may submit a subset of "
                "the benchmark.\n"
                "- Proofs may not contain `#eval`, `#reduce`, `IO.*`, "
                "`unsafe`, `extern`, `initialize`, `@[implemented_by]`, or "
                "`@[extern]` — these are rejected at upload, before anything "
                "reaches the evaluation worker.\n"
                "- Proofs also may not contain `sorry` / `admit` (the "
                "theorem must actually be proved), `axiom`, `native_decide` "
                "/ `ofReduceBool` (kernel bypasses), `#count_heartbeats` "
                "(measurement interference), or auxiliary top-level "
                "declarations and syntax extensions (`def`, `instance`, "
                "`attribute`, `macro`, `notation`, …) — a submission is the "
                "benchmark statement plus a proof, nothing else.\n"
                "- You may re-submit as often as you like — each scored run "
                "**replaces** your previous leaderboard entry, so the last "
                "one you send is the one that counts.\n"
                "- **Usernames are unique.** Your first submission claims the "
                "name and issues a **submission key** (shown once — save it). "
                "Re-submitting under that name requires the key, so nobody "
                "else can take your handle or overwrite your entry. Names are "
                "compared ignoring case and spacing, so `Team Alpha` and "
                "`team alpha` are the same entry.\n"
                "- Rule clarifications will be posted on the community "
                f"channels ([Discord]({DISCORD_URL}) and the "
                f"[Lean Zulip topic]({ZULIP_URL})) and "
                f"this page.\n\n_{DISCLAIMER}_\n"
            )

        # ── Leaderboard ───────────────────────────────────────────────────────
        with gr.Tab("Leaderboard", id="leaderboard"):
            gr.HTML(
                "<div class='lra-intro'>"
                "<div class='lra-kicker'>Development subset</div>"
                "<h2>Leaderboard</h2>"
                "<p>Each track is ranked separately — pick a track below. "
                "Every problem is scored on its own as the mean of its three "
                "axes, and a run's <b>combined %</b> is the mean of those "
                "problem scores across the whole benchmark — <b>a problem "
                "with no submission scores 0 and still counts</b>. The other "
                "three columns are those same axes averaged the same way, so "
                "they average to combined %. Negative means the proof got "
                "bigger or slower than the reference. Click a column header "
                "to re-sort; see <b>Tracks &amp; Rules</b> for the full "
                "definition. This board runs on the development subset; it "
                "will be <b>refreshed on Nov 1</b> when the full benchmark is "
                "released.</p>"
                "</div>"
            )
            refresh_btn = gr.Button("↻ Refresh", size="sm")
            with gr.Tabs(elem_classes=["lra-track-tabs"]):
                with gr.Tab("Closed-source LLM track"):
                    lb_closed = gr.HTML(value=_leaderboard_closed_html())
                with gr.Tab("Open-source LLM track"):
                    lb_open = gr.HTML(value=_leaderboard_open_html())
            gr.Markdown(
                "### Self-reported model details (optional)\n\n"
                "Tell others which model(s) produced your entry and the "
                "reasoning effort or other inference settings you used. "
                "These details are public, self-reported, and do not affect "
                "your score. Existing participants can add or update them "
                "with the same submission key used for **My submissions**. "
                "Leave a field blank to keep its current value."
            )
            with gr.Row():
                self_report_user = gr.Textbox(
                    label="Username (optional)",
                    placeholder="leave blank to look up by key alone",
                )
                self_report_key = gr.Textbox(
                    label="Submission key",
                    placeholder="the key issued with your first submission",
                    type="password",
                )
            with gr.Row():
                self_report_models = gr.Textbox(
                    label="Model(s) (optional)",
                    placeholder="e.g. model name and version",
                    max_lines=2,
                )
                self_report_reasoning = gr.Textbox(
                    label="Reasoning effort / settings (optional)",
                    placeholder="e.g. effort level, temperature, sampling setup",
                    max_lines=2,
                )
            self_report_btn = gr.Button("Save model details", variant="primary")
            self_report_status = gr.Markdown("")

        # ── Benchmark ─────────────────────────────────────────────────────────
        with gr.Tab("Benchmark", id="benchmark"):
            gr.HTML(
                "<div class='lra-intro'>"
                "<div class='lra-kicker'>The corpus</div>"
                "<h2>What you are refactoring</h2>"
                "<p>Every problem is a <b>long reference proof</b> lifted "
                "verbatim from an active open-source Lean development, plus a "
                "slice of competition mathematics — selected in consultation "
                "with the repository maintainers. Project problems are "
                "compiled <b>in place inside their repository</b> — the "
                "surrounding imports, notation, and sibling declarations are "
                "all live. PutnamBench problems are self-contained against "
                f"Mathlib. <b>The current {len(benchmark_names())} problems "
                "are a development subset</b>: build your pipeline against "
                f"them now; the <b>full {FULL_BENCH_SIZE}-problem benchmark</b> "
                f"is released on <b>{FULL_BENCH_RELEASE}</b>. "
                f"<i>{DISCLAIMER}</i></p>"
                "</div>"
            )
            gr.HTML(value=_sources_html(heading=False))
            gr.DownloadButton(
                "📥  Download Benchmark Data",
                value=BENCHMARK_JSONL_PATH,
                variant="primary",
                size="lg",
                elem_classes=["lra-download-btn"],
            )
            gr.Markdown(
                "### Data format\n\n"
                "Each line of the JSONL is one problem with these fields:\n\n"
                "| Field | Meaning |\n"
                "|---|---|\n"
                "| `name` | Unique theorem id — the `name` in your submission "
                "must match it exactly. |\n"
                "| `source` | Which corpus the problem comes from: `strata`, "
                "`physlib`, `cslib`, `arklib`, or `putnambench`. |\n"
                "| `statement` | The theorem statement without the proof. "
                "Your refactored proof must keep it unchanged. |\n"
                "| `src` | The original declaration — statement plus the "
                "reference proof you are trying to beat. |\n"
                "| `proof_length` | Token count of the reference proof; the "
                "denominator for length reduction %. |\n"
                "| `num_lines` | Line count of the reference proof. |\n"
                "| `header` | Imports and options for self-contained "
                "PutnamBench problems. Empty for project problems, which are "
                "compiled inside their repository where the imports already "
                "exist. |\n"
                "| `file_path`, `url`, `start_line`, `end_line` | Where the "
                "declaration lives in its source repository. Empty for "
                "PutnamBench problems, which don't belong to a repository. |\n"
                "| `version_info` | The list of `{version: commit}` pairs the "
                "proof is compiled against for the zero-shot transfer score. "
                "|\n\n"
                "**About `version_info`.** For **project problems** (Strata, "
                "PhysLib, CSLib, ArkLib), each entry pins a commit of the "
                "*source repository* corresponding to that Lean toolchain "
                "version. For **PutnamBench problems**, the versions are "
                "**Mathlib release tags** (`v4.25.0`, `v4.26.0`, `v4.27.0`) "
                "and the commit hashes are the corresponding "
                "[mathlib4](https://github.com/leanprover-community/mathlib4) "
                "commits — the proof is compiled against each of those "
                "Mathlib versions.\n"
            )
            gr.Markdown(_bench_details_md())

        # ── Submit ────────────────────────────────────────────────────────────
        with gr.Tab("Submit", id="submit"):
            gr.HTML(
                "<div class='lra-intro'>"
                "<div class='lra-kicker'>Submission</div>"
                "<h2>Two parts here, one on OpenReview</h2>"
                "<p><b>1 · The proofs</b> — a JSONL of refactored Lean "
                "proofs. Compiled and scored on our dedicated evaluation "
                "worker; the leaderboard updates when the run finishes. "
                "<b>2 · The code</b> — the harness that produced those "
                "proofs, so the organizers can reproduce your run.</p>"
                "<p style='margin-top:10px'>They are <b>uploaded "
                "separately</b> and need not arrive together: submit proofs as "
                "often as you like today to see the score, and attach the code "
                f"at the end, any time before {DEADLINE}. Use the <b>same "
                "username</b> everywhere — that is what ties the two parts "
                "together. Results for every run you send land under "
                "<b>My submissions</b>, unlocked with your submission "
                "key.</p>"
                "<p style='margin-top:10px'><b>The tech report is not "
                f"submitted here.</b> It goes to the workshop on "
                f"{OPENREVIEW_LINK}, by the same {DEADLINE} deadline. An "
                "entry with no report there will not be counted. That "
                "submission is <b>single-blind</b> and is <b>not "
                "anonymized</b>, since the organizers may need to contact you "
                "about your code and your submission during review. See "
                "<b>Tracks &amp; Rules</b>.</p>"
                "</div>"
            )
            with gr.Tabs(elem_classes=["lra-track-tabs"]):
                # ── Part 1: proofs ────────────────────────────────────────────
                with gr.Tab("📄 1 · Proofs"):
                    gr.Markdown(
                        "### Steps\n\n"
                        "1. **Download** the benchmark from the **Benchmark** "
                        "tab. See that tab for the problem list and what each "
                        "field means.\n"
                        "2. **Write a shorter / cheaper `proof`** for the "
                        "theorems you want to improve. Keep the statement "
                        "identical; only the proof after `:=` is yours.\n"
                        "3. **Pick your track and a stable username, then "
                        "upload.** You can close the tab; **My submissions** "
                        "shows the progress and score of every run, unlocked "
                        "with your submission key.\n\n"
                        "### JSONL schema\n\n"
                        "```json\n"
                        '{"name": "theorem_id", "proof": "theorem theorem_id ... := by tactic"}\n'
                        "```\n\n"
                        "- `name` must match a benchmark id for the row to be "
                        "scored.\n"
                        "- `proof` is the full declaration; the body after "
                        "`:=` is tokenized for the length metric.\n"
                        "- Compile failure, a changed statement, or `sorry` ⇒ "
                        "0% on all axes.\n"
                    )
                    track_in = gr.Radio(
                        choices=list(TRACK_LABELS.keys()),
                        label="Track",
                        value=None,
                    )
                    with gr.Row():
                        user_in = gr.Textbox(
                            label="Username", placeholder="your-handle"
                        )
                        key_in = gr.Textbox(
                            label="Submission key",
                            placeholder="only if you've submitted before",
                            type="password",
                            info="Leave empty on your first submission — a key "
                                 "is issued then, and it's what reserves your "
                                 "username.",
                        )
                        file_in = gr.File(
                            label="Your JSONL",
                            file_types=[".jsonl", ".json", ".txt"],
                            type="filepath",
                        )
                    with gr.Row():
                        submit_btn = gr.Button(
                            "Verify & Submit", variant="primary"
                        )
                        history_btn = gr.Button(
                            "View my submissions", variant="secondary"
                        )
                    submit_status = gr.Markdown("")
                    gr.HTML(
                        "<div class='lra-note' style='margin-top:10px'>"
                        "Per-problem results — what compiled, what it scored, "
                        "and every compiler error — are under <b>My "
                        "submissions</b>, unlocked with your submission key."
                        "</div>"
                    )

                # ── Part 2: code ──────────────────────────────────────────────
                with gr.Tab("📦 2 · Code"):
                    gr.HTML(
                        "<div class='lra-note'>"
                        "<b>Not open yet.</b> Code intake "
                        f"opens with the full benchmark on "
                        f"<b>{FULL_BENCH_RELEASE}</b>. Submit your proofs "
                        "under <b>Proofs</b> in the meantime — this "
                        "page is here so you know what to prepare."
                        "</div>"
                    )
                    gr.Markdown(
                        "### What to send\n\n"
                        "| | Format | Contents |\n"
                        "|---|---|---|\n"
                        "| **Code** | `.zip` or `.tar.gz` | Everything needed "
                        "to regenerate your JSONL — inference code: harness, "
                        "prompts, and how the model is served. Post-training "
                        "code is not required. A top-level README "
                        "with the exact commands. |\n\n"
                        "### The tech report goes on OpenReview\n\n"
                        "The report is **not uploaded here**. Submit it to the "
                        f"workshop at **[OpenReview]({OPENREVIEW_URL})** "
                        f"by {DEADLINE}: approach, models used, budget "
                        "accounting, and reproduction steps, written in the "
                        f"official [competition template]({REPORT_TEMPLATE_URL}) "
                        f"(`{REPORT_TEMPLATE_TEX}`), "
                        f"{REPORT_PAGE_LIMIT}.\n\n"
                        "**Review is single-blind, so your report is not "
                        "anonymized.** Put your real names, affiliations, and "
                        "contact information on it: the organizers may need to "
                        "contact you about your code and your submission while "
                        "the competition entries are being reviewed.\n\n"
                        f"⚠️ **The template is mandatory.** A score without a "
                        "conforming report on OpenReview will not be counted, "
                        "and an undisclosed or over-budget run is "
                        "desk-rejected. See "
                        "**Tracks & Rules → Grounds for desk rejection**.\n\n"
                        "### How it works\n\n"
                        "- **Same username as your proof submission** — that "
                        "is the only link between the two, so keep it "
                        "identical.\n"
                        f"- **Send it whenever you're ready**, any time before "
                        f"{DEADLINE}. Most teams will do this at the end.\n"
                        "- **Re-upload freely** — the organizers read your "
                        "most recent bundle.\n"
                        "- The code is reviewed by hand, not scored: nothing "
                        "here changes your leaderboard position, but a "
                        "prize-eligible entry needs the code here *and* the "
                        "report on OpenReview.\n"
                    )
                    with gr.Row():
                        art_user_in = gr.Textbox(
                            label="Username",
                            placeholder="same handle as your proofs",
                        )
                        art_key_in = gr.Textbox(
                            label="Submission key",
                            placeholder="the key issued with your proofs",
                            type="password",
                        )
                        art_code_in = gr.File(
                            label="Code archive (.zip / .tar.gz)",
                            file_types=[".zip", ".tar", ".gz", ".tgz",
                                        ".bz2", ".xz"],
                            type="filepath",
                        )
                    art_btn = gr.Button("Submit code", variant="primary")
                    art_status = gr.Markdown("")
                    gr.HTML(
                        "<div class='lra-cite-actions' "
                        "style='margin-top:14px'>"
                        f"<a class='lra-paper-btn' href='{OPENREVIEW_URL}' "
                        "target='_blank' rel='noopener noreferrer'>"
                        "📄 Submit your tech report on OpenReview ↗</a>"
                        "</div>"
                    )

        # ── My submissions ────────────────────────────────────────────────────
        with gr.Tab("My submissions", id="history"):
            gr.HTML(
                "<div class='lra-intro'>"
                "<div class='lra-kicker'>Submission history</div>"
                "<h2>Every run you have sent us</h2>"
                "<p>Paste the <b>submission key</b> you were given on your "
                "first submission to see all of your submissions, newest "
                "first: where each one sits in the evaluation queue, whether "
                "each problem compiled, and what it scored. The username is "
                "optional — the key on its own identifies your entry.</p>"
                "<p style='margin-top:10px'>Nobody else can see this: the "
                "key is the same secret that reserves your username. Lost "
                "it? Ask the organizers on "
                f"<a href='{DISCORD_URL}' target='_blank' "
                "rel='noopener noreferrer'>Discord</a>.</p>"
                "</div>"
            )
            with gr.Row():
                hist_user_in = gr.Textbox(
                    label="Username (optional)",
                    placeholder="leave blank to look up by key alone",
                )
                hist_key_in = gr.Textbox(
                    label="Submission key",
                    placeholder="the key issued with your first submission",
                    type="password",
                )
            hist_btn = gr.Button("View my submissions", variant="primary")
            hist_out = gr.HTML(
                "<div class='lra-empty'>Enter your submission key above to "
                "load your history.</div>"
            )

        # ── Community ─────────────────────────────────────────────────────────
        with gr.Tab("Community", id="community"):
            gr.HTML(
                "<div class='lra-intro'>"
                "<div class='lra-kicker'>Group chat</div>"
                "<h2>Talk to the organizers and other teams</h2>"
                "<p>Reach us on the <b>arena Discord</b> or in our "
                "<b>topic on the Lean community Zulip</b>. Both are open — "
                "use whichever you already follow.</p>"
                "</div>"
            )
            gr.HTML(value=_community_html())

        # ── About ─────────────────────────────────────────────────────────────
        with gr.Tab("About", id="about"):
            gr.Markdown(
                "### What this is\n\n"
                "Lean Refactor Arena asks whether AI systems can make existing "
                "Lean developments **better**, not merely **correct**. Formal "
                "libraries accumulate long, slow, brittle proofs; the arena "
                "measures whether your system can rewrite them — same "
                "statement, better proof — across three axes at once.\n\n"
                "The benchmark draws long reference proofs from four active "
                "formalization projects — "
                "[Strata](https://github.com/strata-org/Strata) (program "
                "verification, AWS), "
                "[PhysLib](https://github.com/leanprover-community/physlib) "
                "(formalized physics), "
                "[CSLib](https://github.com/leanprover/cslib) (computer "
                "science), and "
                "[ArkLib](https://github.com/Verified-zkEVM/ArkLib) (verified "
                "cryptography) — plus "
                "[PutnamBench](https://github.com/trishullab/PutnamBench) "
                "competition problems. Project problems are compiled in place "
                "inside their repositories; PutnamBench problems are "
                "self-contained against Mathlib.\n\n"
                "### The competition\n\n"
                "Two tracks, ranked separately: **closed-source LLM** (API "
                "models + any harness, ≤ US$3 per problem) and **open-source "
                "LLM** (public weights, post-training and/or harness, "
                "4× 80 GB A100 for ≤ 48 h inference budget). Each track's "
                "winner receives "
                f"**{PRIZE_PER_TRACK}** and a dedicated talk at the "
                f"[{WORKSHOP_NAME}]({WORKSHOP_URL}) workshop "
                f"({WORKSHOP_VENUE}), which this competition is part of. See "
                "**Tracks & Rules** for details.\n\n"
                "### Scoring (multi-objective)\n\n"
                "- **Length reduction %** — decrease in proof token count vs "
                "the reference proof.\n"
                "- **Heartbeat reduction %** — change in Lean's "
                "[`#count_heartbeats`](https://lean-lang.org/doc/reference/latest/IO/Timing/#IO___getNumHeartbeats) "
                "elaboration cost vs the reference.\n"
                "- **Zero-shot transfer %** — fraction of the problem's listed "
                "Lean toolchains on which the proof compiles unchanged.\n\n"
                "Each problem scores the **mean of those three**, and a run's "
                "**combined %** — the default ranking — is the mean of the "
                "problem scores over the **whole benchmark**. Compile "
                "failure, a changed statement, or `sorry` scores that problem "
                "zero, and so does not submitting it at all.\n\n"
                "### How evaluation runs\n\n"
                "This Space is the front door: it validates and queues "
                "submissions. Compilation and scoring run on a **dedicated "
                "evaluation worker** with the full Lean toolchains and "
                "repository checkouts pre-built — no compilation happens in "
                "this Space. Progress streams back to the Submit tab and the "
                "leaderboard updates automatically.\n\n"
                "### Built with the support of\n\n"
                "AWS · Simon Fraser University · The University of Texas at "
                "Austin · CSLib · PhysLib · ArkLib."
            )

        # ── Contribute ────────────────────────────────────────────────────────
        with gr.Tab("Contribute", id="contribute"):
            gr.HTML(_contrib_intro_html(with_lead_in=False))
            gr.HTML(
                "<div class='lra-cite-actions'>"
                f"<a class='lra-paper-btn' href='{CONTRIB_PAGE_PATH}' "
                "target='_blank' rel='noopener'>"
                "Read the contribution guide →</a>"
                "</div>"
                "<p class='lra-linknote'>Opens in a new tab: what makes a "
                "proof long enough, why compile cost matters, the "
                "cross-toolchain requirement, and what to send us.</p>"
            )

        # ── Cite ──────────────────────────────────────────────────────────────
        with gr.Tab("Cite", id="cite"):
            gr.HTML(value=_cite_html())

    home_lb_btn.click(lambda: _select_tab("leaderboard"), outputs=app_tabs, api_name=False)
    home_submit_btn.click(lambda: _select_tab("submit"), outputs=app_tabs, api_name=False)
    home_rules_btn.click(lambda: _select_tab("rules"), outputs=app_tabs, api_name=False)

    submit_btn.click(
        verify_and_submit,
        [user_in, key_in, track_in, file_in],
        [gr.State(), submit_status],
        api_name="verify_and_submit",
    )

    art_btn.click(
        submit_artifacts,
        [art_user_in, art_key_in, art_code_in],
        art_status,
        api_name="submit_artifacts",
    )

    history_btn.click(lambda: _select_tab("history"), outputs=app_tabs, api_name=False)
    hist_btn.click(
        view_submissions,
        [hist_user_in, hist_key_in],
        hist_out,
        api_name="view_submissions",
    )
    hist_key_in.submit(
        view_submissions, [hist_user_in, hist_key_in], hist_out, api_name=False
    )

    # Keep an open history view current while a submission is being scored.
    gr.Timer(value=30).tick(
        refresh_submissions, [hist_user_in, hist_key_in], hist_out
    )

    refresh_btn.click(_leaderboard_closed_html, None, lb_closed, api_name="leaderboard")
    refresh_btn.click(_leaderboard_open_html, None, lb_open, api_name=False)
    self_report_btn.click(
        save_self_report,
        [
            self_report_user,
            self_report_key,
            self_report_models,
            self_report_reasoning,
        ],
        [self_report_status, lb_closed, lb_open],
        api_name="save_self_report",
    )

    # Poll the persisted submission status for whatever username is in the box
    # so the submitter sees their run advance without leaving this tab. Only
    # the one-line message is shown here — per-problem results are private to
    # the submitter and live behind the key in "My submissions".
    gr.Timer(value=15).tick(
        lambda user: submission_status(user)[1],
        inputs=[user_in],
        outputs=[submit_status],
    )

    # Auto-refresh the leaderboards so finished submissions appear without
    # the user having to click Refresh.
    gr.Timer(value=60).tick(_leaderboard_closed_html, outputs=lb_closed)
    gr.Timer(value=60).tick(_leaderboard_open_html, outputs=lb_open)

    # Populate the leaderboards + home on every page load (the baked `value=`
    # is only the build-time snapshot; refresh fns re-read the bucket first).
    demo.load(_leaderboard_closed_html, outputs=lb_closed)
    demo.load(_leaderboard_open_html, outputs=lb_open)
    demo.load(refresh_home, outputs=home_body)

    # Hidden admin endpoints — gated by env-var ADMIN_RESET_TOKEN.
    _admin_tok = gr.Textbox(visible=False)
    _admin_out = gr.Textbox(visible=False)
    _admin_btn = gr.Button(visible=False)
    _admin_btn.click(admin_reset, _admin_tok, _admin_out, api_name="admin_reset")

    _cl_tok = gr.Textbox(visible=False)
    _cl_user = gr.Textbox(visible=False)
    _cl_sid = gr.Textbox(visible=False)
    _cl_out = gr.Textbox(visible=False)
    _cl_btn = gr.Button(visible=False)
    _cl_btn.click(
        compat_list, [_cl_tok, _cl_user, _cl_sid], _cl_out,
        api_name="compat_list",
    )

    _log_tok = gr.Textbox(visible=False)
    _log_user = gr.Textbox(visible=False)
    _log_sid = gr.Textbox(visible=False)
    _log_name = gr.Textbox(visible=False)
    _log_ver = gr.Textbox(visible=False)
    _log_out = gr.Textbox(visible=False)
    _log_btn = gr.Button(visible=False)
    _log_btn.click(
        compat_log,
        [_log_tok, _log_user, _log_sid, _log_name, _log_ver],
        _log_out,
        api_name="compat_log",
    )

    # Hidden evaluation-worker endpoints — gated by WORKER_TOKEN.
    _wp_tok = gr.Textbox(visible=False)
    _wp_out = gr.Textbox(visible=False)
    _wp_btn = gr.Button(visible=False)
    _wp_btn.click(worker_poll, _wp_tok, _wp_out, api_name="worker_poll")

    _wu_tok = gr.Textbox(visible=False)
    _wu_payload = gr.Textbox(visible=False)
    _wu_out = gr.Textbox(visible=False)
    _wu_btn = gr.Button(visible=False)
    _wu_btn.click(
        worker_update, [_wu_tok, _wu_payload], _wu_out,
        api_name="worker_update",
    )

    _wr_tok = gr.Textbox(visible=False)
    _wr_payload = gr.Textbox(visible=False)
    _wr_out = gr.Textbox(visible=False)
    _wr_btn = gr.Button(visible=False)
    _wr_btn.click(
        worker_report, [_wr_tok, _wr_payload], _wr_out,
        api_name="worker_report",
    )

    _wh_tok = gr.Textbox(visible=False)
    _wh_payload = gr.Textbox(visible=False)
    _wh_out = gr.Textbox(visible=False)
    _wh_btn = gr.Button(visible=False)
    _wh_btn.click(
        worker_heartbeat, [_wh_tok, _wh_payload], _wh_out,
        api_name="worker_heartbeat",
    )


# ── Serving ───────────────────────────────────────────────────────────────────
# The Gradio UI is mounted at / on a FastAPI app that also serves the standalone
# contribution page at CONTRIB_PAGE_PATH. Doing it this way (rather than as a
# Gradio route) keeps the guide a plain, instantly-rendered HTML document at a
# real URL, which is what the "Read the contribution guide" links open.
app = FastAPI()


@app.get(CONTRIB_PAGE_PATH, response_class=HTMLResponse)
def contribution_page():
    return HTMLResponse(_contribution_page_html())


# ssr_mode=False keeps Gradio on its classic client-rendered SPA. On HF Spaces
# SPACE_ID is set, so Gradio would otherwise auto-enable SSR and serve the
# frontend from /_app/immutable/*, which 404s under a custom mount_gradio_app
# setup and leaves an unstyled, non-interactive page.
app = gr.mount_gradio_app(
    app,
    demo.queue(default_concurrency_limit=None),
    path="/",
    allowed_paths=[
        BENCHMARK_JSONL_PATH,
        str(SPONSOR_ASSETS_DIR),
        str(BENCH_ASSETS_DIR),
    ],
    favicon_path=str(APP_ICON_PATH),
    ssr_mode=False,
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("GRADIO_SERVER_PORT", "7860")),
    )

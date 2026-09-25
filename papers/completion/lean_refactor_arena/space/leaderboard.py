"""Thread-safe leaderboard state with atomic file persistence.

Persistence location:
  - /data/leaderboard.json if /data is mounted (HF Persistent Storage / Bucket).
  - else /home/user/app/leaderboard.json (ephemeral — wiped on Space restart).

Single-user-overwrite model: each new submission from `user` replaces that
user's prior entry. To support "best score retained" semantics, change
`submit()` to merge instead of overwrite.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from benchmark import (
    BENCHMARK,
    benchmark_names,
    original_heartbeats,
    original_length,
)


def _resolve_storage_path(filename: str = "leaderboard.json") -> Path:
    # `LRA_DATA_DIR` lets a local run read a mirror of the bucket (see
    # app.py::_data_root); it must agree with what the rest of the app uses.
    override = os.environ.get("LRA_DATA_DIR")
    if override:
        return Path(override) / filename
    persistent = Path("/data")
    if persistent.is_dir() and os.access(persistent, os.W_OK):
        return persistent / filename
    # Ephemeral fallback (local dev / no bucket): next to this module.
    return Path(__file__).resolve().parent / filename


LB_PATH = _resolve_storage_path()
PERSISTENT = LB_PATH.parent == Path("/data")


class Leaderboard:
    def __init__(self, path: Path | str = LB_PATH) -> None:
        # A bare filename selects that file in the standard storage location
        # (/data when mounted, else next to this module).
        if isinstance(path, str):
            path = _resolve_storage_path(path)
        self.path = path
        self.lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()
        print(
            f"[leaderboard] storage={'persistent' if PERSISTENT else 'ephemeral'} "
            f"path={self.path} users_loaded={len(self.data.get('users', {}))}",
            flush=True,
        )

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except Exception:
                return {"users": {}}
        return {"users": {}}

    def reload(self) -> None:
        """Re-read leaderboard state from disk so the in-memory copy reflects
        writes made since startup — the bucket file may not have been mounted
        yet when the process started, or may have been written by a previous
        container instance. Cheap (small JSON) and safe (writes are atomic via
        os.replace, so a read sees either the old or new complete file)."""
        with self.lock:
            self.data = self._load()

    def _save(self) -> None:
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=".leaderboard.", suffix=".json", dir=self.path.parent
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self.path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @staticmethod
    def problem_axes(r: dict | None) -> tuple[float, float, float]:
        """The three axis percentages for one benchmark problem.

        A problem that was not submitted, did not compile, changed the
        statement, or tripped the forbidden-pattern filter scores 0 on all
        three — including compatibility, which is what stops a competitor
        from raising their score by withholding the problems they are least
        sure of."""
        r = r or {}
        if not r.get("compiled"):
            return 0.0, 0.0, 0.0
        compat = r.get("compat") or {}
        passed = sum(1 for v in compat.values() if (v or {}).get("passed"))
        # `compat` covers every toolchain the problem lists. A problem that
        # lists only its default has nothing left to check, and compiling on
        # that default is all there was to prove.
        compat_pct = (passed / len(compat) * 100.0) if compat else 100.0
        return (
            float(r.get("length_reduction_pct", 0.0)),
            float(r.get("heartbeat_reduction_pct", 0.0)),
            compat_pct,
        )

    @classmethod
    def problem_score(cls, r: dict | None) -> float:
        """One problem's score: the mean of its three axes."""
        return round(sum(cls.problem_axes(r)) / 3.0, 2)

    @classmethod
    def _compute_user_summary(cls, results: dict) -> dict:
        """Aggregate metrics over all benchmark theorems.

        Every axis is a per-problem percentage averaged over the *whole*
        benchmark, so a problem with no submission contributes 0 to each.
        The combined score is the mean of the per-problem scores, which — the
        three axes being averaged the same way — is identical to the mean of
        the three column averages.
        """
        names = benchmark_names()
        if not names:
            return {
                "avg_len_pct": 0.0, "avg_len_abs": 0.0,
                "avg_hb_pct": 0.0, "avg_hb_abs": 0.0,
                "compiled": 0,
                "survival_rate": 0.0,
                "compat_checks": 0, "compat_passed": 0,
            }
        total_len_pct = 0.0
        total_len_abs = 0.0
        total_hb_pct = 0.0
        total_hb_abs = 0.0
        total_compat_pct = 0.0
        compiled = 0
        compat_checks = 0
        compat_passed = 0
        for name in names:
            r = results.get(name) or {}
            len_pct, hb_pct, compat_pct = cls.problem_axes(r)
            total_len_pct += len_pct
            total_hb_pct += hb_pct
            total_compat_pct += compat_pct
            if r.get("compiled"):
                total_len_abs += float(r.get("length_abs_reduction", 0.0))
                total_hb_abs += float(r.get("heartbeat_abs_reduction", 0.0))
                compiled += 1
                for v_res in (r.get("compat") or {}).values():
                    compat_checks += 1
                    if (v_res or {}).get("passed"):
                        compat_passed += 1
        n = len(names)
        return {
            "avg_len_pct": total_len_pct / n,
            "avg_len_abs": total_len_abs / n,
            "avg_hb_pct": total_hb_pct / n,
            "avg_hb_abs": total_hb_abs / n,
            "compiled": compiled,
            "survival_rate": round(total_compat_pct / n, 1),
            "compat_checks": compat_checks,
            "compat_passed": compat_passed,
        }

    def submit(
        self,
        user: str,
        per_theorem_data: dict[str, dict],
        upload_path: str | None = None,
        track: str = "closed",
    ) -> dict:
        """Record a submission for `user` on `track` ("closed" | "open").

        `per_theorem_data` maps benchmark theorem name -> {
            compiled: bool, length: int|None, heartbeats: int|None, error: str
        }. Theorems missing from this dict count as 0 reduction.

        Returns the persisted user record.
        """
        results: dict[str, dict] = {}
        for name in benchmark_names():
            row = per_theorem_data.get(name)
            orig_len = original_length(name) or 0
            orig_hb = original_heartbeats(name) or 0
            if row is None:
                results[name] = {
                    "compiled": None,
                    "length": None,
                    "heartbeats": None,
                    "length_reduction_pct": 0.0,
                    "length_abs_reduction": 0.0,
                    "heartbeat_reduction_pct": 0.0,
                    "heartbeat_abs_reduction": 0.0,
                    "error": "(not in submission)",
                }
                continue
            if not row.get("compiled"):
                results[name] = {
                    "compiled": False,
                    "length": row.get("length"),
                    "heartbeats": row.get("heartbeats"),
                    "length_reduction_pct": 0.0,
                    "length_abs_reduction": 0.0,
                    "heartbeat_reduction_pct": 0.0,
                    "heartbeat_abs_reduction": 0.0,
                    "error": row.get("error", ""),
                }
                continue
            new_len = int(row.get("length") or 0)
            new_hb_raw = row.get("heartbeats")
            new_hb = int(new_hb_raw) if isinstance(new_hb_raw, (int, float)) else None
            len_pct = ((orig_len - new_len) / orig_len * 100.0) if orig_len > 0 else 0.0
            hb_pct = (
                ((orig_hb - new_hb) / orig_hb * 100.0)
                if (orig_hb > 0 and new_hb is not None)
                else 0.0
            )
            hb_abs = float(orig_hb - new_hb) if new_hb is not None else 0.0
            results[name] = {
                "compiled": True,
                "length": new_len,
                "heartbeats": new_hb,
                "length_reduction_pct": round(len_pct, 2),
                "length_abs_reduction": float(orig_len - new_len),
                "heartbeat_reduction_pct": round(hb_pct, 2),
                "heartbeat_abs_reduction": round(hb_abs, 2),
                "error": "",
            }

        # Attach per-theorem compat data from submission (pass/fail per version).
        for name in benchmark_names():
            row = per_theorem_data.get(name)
            if row and row.get("compat"):
                results[name]["compat"] = row["compat"]

        # Each problem's own score, so the UI can show where a run gained or
        # lost ground rather than only the totals.
        for name in benchmark_names():
            results[name]["score"] = self.problem_score(results[name])

        summary = self._compute_user_summary(results)
        # Combined = the mean per-problem score. Averaging the three axes over
        # the whole benchmark first and taking their mean is the same number,
        # and keeps the leaderboard columns consistent with the ranking.
        combined = (
            summary["avg_len_pct"]
            + summary["avg_hb_pct"]
            + summary["survival_rate"]
        ) / 3.0
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "track": track if track in ("closed", "open") else "closed",
            "results": results,
            "avg_length_reduction_pct": round(summary["avg_len_pct"], 2),
            "avg_length_abs_reduction": round(summary["avg_len_abs"], 2),
            "avg_heartbeat_reduction_pct": round(summary["avg_hb_pct"], 2),
            "avg_heartbeat_abs_reduction": round(summary["avg_hb_abs"], 2),
            "avg_combined_pct": round(combined, 2),
            "avg_survival_rate": summary["survival_rate"],
            "num_compiled": summary["compiled"],
            "num_benchmark": len(benchmark_names()),
            "num_compat_passed": summary["compat_passed"],
            "num_compat_checks": summary["compat_checks"],
            "upload_path": upload_path,
        }

        with self.lock:
            self.data.setdefault("users", {})[user] = record
            self._save()
        return record

    def leaderboard_rows(self, track: str | None = None) -> list[list]:
        """Sorted leaderboard rows. Columns:
        [#, user, length reduction %, heartbeat reduction %, combined %,
         zero-shot %, compiled, submitted (day)].
        Ranked by combined % desc. With `track`, only records on that track
        are returned (records with no stored track count as "closed")."""
        with self.lock:
            users = self.data.get("users", {})
            entries = list(users.items())
        if track is not None:
            entries = [
                (u, rec) for u, rec in entries
                if rec.get("track", "closed") == track
            ]
        entries.sort(
            key=lambda kv: (
                -float(kv[1].get("avg_combined_pct") or 0.0),
                -int(kv[1].get("num_compiled") or 0),
                kv[1].get("timestamp", ""),
            )
        )
        rows: list[list] = []
        for rank, (user, rec) in enumerate(entries, start=1):
            n_checks = rec.get("num_compat_checks") or 0
            survival = (
                f"{rec.get('avg_survival_rate', 0.0):.1f}%"
                f" ({rec.get('num_compat_passed', 0)}/{n_checks})"
                if n_checks > 0
                else "—"
            )
            rows.append([
                rank,
                user,
                rec.get("avg_length_reduction_pct", 0.0),
                rec.get("avg_heartbeat_reduction_pct", 0.0),
                rec.get("avg_combined_pct", 0.0),
                survival,
                # `num_compiled` may be null for a record that was never scored
                # on a Lean toolchain (e.g. a locally-seeded demo) — render an em
                # dash rather than "None/N".
                ("—" if rec.get("num_compiled") is None
                 else f"{rec.get('num_compiled')}/{rec.get('num_benchmark', 0)}"),
                rec.get("timestamp", "")[:10],   # day only (YYYY-MM-DD)
            ])
        return rows

    def user_detail(self, user: str) -> Optional[dict]:
        with self.lock:
            return self.data.get("users", {}).get(user)

    def per_theorem_global_avg(self) -> dict[str, dict[str, float]]:
        """For each benchmark theorem, mean length% and heartbeat% across users."""
        with self.lock:
            users = list(self.data.get("users", {}).values())
        if not users:
            return {
                name: {"length_reduction_pct": 0.0, "heartbeat_reduction_pct": 0.0}
                for name in benchmark_names()
            }
        out: dict[str, dict[str, float]] = {}
        for name in benchmark_names():
            len_total = 0.0
            hb_total = 0.0
            for u in users:
                r = (u.get("results") or {}).get(name) or {}
                len_total += float(r.get("length_reduction_pct", 0.0))
                hb_total += float(r.get("heartbeat_reduction_pct", 0.0))
            out[name] = {
                "length_reduction_pct": round(len_total / len(users), 2),
                "heartbeat_reduction_pct": round(hb_total / len(users), 2),
            }
        return out

    def status(self) -> dict:
        with self.lock:
            n_users = len(self.data.get("users", {}))
        return {
            "path": str(self.path),
            "persistent": PERSISTENT,
            "num_users": n_users,
            "num_benchmark": len(benchmark_names()),
        }

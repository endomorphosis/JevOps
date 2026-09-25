"""Injectable, bounded proposal sources for Arena; no verification or training.

Borrowing the ipfs_datasets_py candidate-source/authority-ceiling design, not
its solver trust flags. External commands are explicitly trusted infrastructure,
NOT a sandbox. Only their JSON output is treated as untrusted nominations.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
import time
from collections import deque
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .arena import TOKENIZER_ID, content_hash, intake_error, reference_tokens, source_hash
from .arena_compositions import RULES, draft_batch
from .arena_isolation import capture_process
from .arena_lean import CORPUS
from .arena_trial import Candidate
from .premise_search import Premise, PremiseIndex, PremiseScope, PremiseSignature, bounded_int, premise_name

SCHEMA = "jevops-arena-provider-batch/v1"
UPSTREAM = {"repository": "endomorphosis/ipfs_datasets_py",
            "commit": "ddf6b79467b68159650df81befc288c8553df664",
            "license": "AGPL-3.0", "reuse": "adapted selection and candidate-source design"}
METHODS = ("term", "exact", "apply")
DEFAULT_PATHS = (("port_exact_hyp",), ("port_ctor_pair_exacts",),
                 ("intro_exact_assumption",), ("drop_rename_i",))
LOCAL_RANKING_BYTES = 1_048_576
LOCAL_STRATEGIES = ("baseline-v1", "portfolio-v1")
LOCAL_FAMILIES = ("apply_assumption", "exact", "local_term", "close")
LOCAL_SEARCH = (("max_applications", 2), ("max_terms", 64), ("max_checks", 2048))
LOCAL_CLOSERS = ("assumption", "rfl", "trivial", "solve | simp_all")


@dataclass(frozen=True)
class LocalTemplate:
    """A generated tactic proposal, never a checked application or proof."""
    family: str
    candidate: str
    premise: str | None = None


def _local_portfolio(record, source, capture, index, scope, events, batch):
    """Finite diagonal round-robin over (goal, family) queues.

    Lean performs application/unification only during independent replay; this
    offline generator cannot assert applicability from premise text. Each
    template is emitted separately: no retained mega-`first` search script.
    """
    from .proof_replay import replace_event
    from .scoped_proposals import local_terms, premise_query

    request = batch["request"]
    batch.update(attempted_templates=0, family_drafts={f: 0 for f in LOCAL_FAMILIES})
    eligible, ranking_bytes = [], 0
    for event in events[:request["max_events"]]:
        if event["declaration"] != [["s", part] for part in request["declaration"].split(".")]:
            raise ValueError("foreign captured declaration")
        detail = {"event_id": int(event["id"]), "event_sha256": content_hash(event),
                  "start": event["start"], "end": event["end"], "outcomes": []}
        batch["events"].append(detail)
        try:
            replace_event(source, event, "skip")
        except ValueError:
            detail["status"] = "UNSUPPORTED_SPAN"
            continue
        query = premise_query(event["before"], node_budget=capture["node_budget"],
                              max_query_nodes=request["max_query_nodes"])
        detail.update(status=query["status"], observation=query)
        if query["status"] not in {"READY", "NO_CONSTANTS"}:
            batch["truncated"] |= query["status"] == "QUERY_BUDGET"
            continue
        matches = []
        if query["status"] == "READY":
            ranking = index.rank(query["query"], target=request["declaration"], scope=scope,
                                 top_k=request["top_k"], max_scan=request["max_scan"])
            ranking_bytes += len(json.dumps(ranking, sort_keys=True, allow_nan=False).encode())
            if ranking_bytes > LOCAL_RANKING_BYTES:
                detail.update(status="REPORT_BUDGET", ranking_sha256=content_hash(ranking))
                batch["truncated"] = True
                break
            detail.update(status=ranking["status"], ranking=ranking)
            batch["truncated"] |= ranking["status"] == "SCAN_BUDGET"
            matches = ranking["matches"]
        eligible.append((event, detail, matches))

    def templates(event, detail, matches, family):
        if family in {"apply_assumption", "exact"}:
            for match in matches:
                name = match["name"]
                tactic = (f"solve | apply _root_.{name} <;> assumption" if family == "apply_assumption"
                          else f"exact _root_.{name}")
                yield LocalTemplate(family, tactic, name)
        elif family == "local_term":
            found = local_terms(event["before"], node_budget=capture["node_budget"], **dict(LOCAL_SEARCH))
            detail["local_search"] = {k: v for k, v in found.items() if k != "candidates"}
            batch["truncated"] |= found["truncated"]
            for candidate in found["candidates"]:
                yield LocalTemplate(family, candidate["candidate"])
        else:
            for tactic in LOCAL_CLOSERS:
                yield LocalTemplate(family, tactic)

    # Every pair appears once; later passes consume one more template per pair.
    # Offset the family by goal index so a short budget need not hit one family
    # across all goals. Finite caps do NOT guarantee service to every pair.
    queues = deque((event, detail, iter(templates(event, detail, matches, LOCAL_FAMILIES[
        (i + offset) % len(LOCAL_FAMILIES)])))
        for offset in range(len(LOCAL_FAMILIES)) for i, (event, detail, matches) in enumerate(eligible))
    seen = {source_hash(source), source_hash(record["src"])}
    while queues and len(batch["drafts"]) < request["cap"] and batch["attempted_templates"] < request["max_templates"]:
        event, detail, options = queues.popleft()
        option = next(options, None)
        if option is None:
            continue
        queues.append((event, detail, options))
        batch["attempted_templates"] += 1
        outcome = {"family": option.family, "candidate": option.candidate}
        detail["outcomes"].append(outcome)
        try:
            target = replace_event(source, event, option.candidate)
        except ValueError:
            outcome["status"] = "UNSUPPORTED_SOURCE"
            continue
        identity, tokens = source_hash(target), reference_tokens(target, record["statement"])
        outcome.update(source_sha256=identity, tokens=tokens)
        if intake_error(target, record["statement"]):
            outcome["status"] = "UNSUPPORTED_SOURCE"
        elif identity in seen:
            outcome["status"] = "DUPLICATE"
        elif tokens >= batch["base_tokens"]:
            outcome["status"] = "NOT_SHORTER"
        else:
            seen.add(identity)
            label = f"local-premise-{len(batch['drafts'])}"
            outcome.update(status="DRAFT", label=label)
            batch["family_drafts"][option.family] += 1
            batch["proposals"].append({"event_id": int(event["id"]), "candidate": option.candidate})
            batch["drafts"].append({"name": record["name"], "label": label, "source": target,
                "provenance": f"unverified local {option.family}; request {request['request_sha256']}; event {event['id']}"})
            batch["origins"].append({"label": label, "event_id": int(event["id"]),
                "event_sha256": detail["event_sha256"], "family": option.family,
                "premise": asdict(index.entries[option.premise]) if option.premise is not None else None,
                "ranking_sha256": content_hash(detail["ranking"]) if "ranking" in detail else None})
    batch["truncated"] |= bool(queues)
    if batch["drafts"]:
        batch["status"] = "DRAFTS_ONLY"
    elif queues and batch["attempted_templates"] >= request["max_templates"]:
        batch["status"] = "BUDGET_EXHAUSTED"
    return batch


def strict_json(raw: bytes | str, *, limit: int = 65536):
    if not isinstance(raw, (bytes, str)) or len(raw if isinstance(raw, bytes) else raw.encode()) > limit:
        raise ValueError("JSON byte budget")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON field")
            value[key] = item
        return value

    def nonfinite(_):
        raise ValueError("nonfinite JSON number")

    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
    except RecursionError as exc:
        raise ValueError("JSON nesting budget") from exc


def _fields(value, expected):
    if type(value) is not dict or set(value) != set(expected.split()):
        raise ValueError("unexpected object fields")


def _paths(paths):
    if (type(paths) is not tuple or not 1 <= len(paths) <= 8
            or any(type(p) is not tuple or not 1 <= len(p) <= 3
                   or any(type(r) is not str or r not in RULES for r in p) for p in paths)):
        raise ValueError("bounded allowlisted rule paths required")


def _provider_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", value):
        raise ValueError("bounded provider id required")


@dataclass(frozen=True)
class ProviderLimits:
    per_provider_seconds: int = 5
    total_seconds: int = 20
    request_bytes: int = 262144
    response_bytes: int = 65536

    def __post_init__(self):
        bounded_int(self.per_provider_seconds, 1, 30)
        bounded_int(self.total_seconds, 1, 60)
        bounded_int(self.request_bytes, 1024, 262144)
        bounded_int(self.response_bytes, 1024, 65536)


@dataclass(frozen=True)
class PremiseProvider:
    provider_id: str = "premise-baseline"


@dataclass(frozen=True)
class RuleProvider:
    paths: tuple[tuple[str, ...], ...] = DEFAULT_PATHS
    provider_id: str = "rewrite-baseline"

    def __post_init__(self):
        _paths(self.paths)


@dataclass(frozen=True)
class JsonProvider:
    """Offline model/hammer response; hashes bind it to one proposal request."""
    provider_id: str
    response: str

    def __post_init__(self):
        if not isinstance(self.response, str) or len(self.response.encode()) > 65536:
            raise ValueError("bounded offline response required")


@dataclass(frozen=True)
class CommandProvider:
    """Operator-injected executable: request on stdin, response on stdout.

    No shell, credential inheritance, retries, or dynamic imports from proposals.
    Wall time and combined output bytes are enforced by capture_process. Host
    filesystem/network permissions are NOT restricted; use only trusted adapters.
    """
    provider_id: str
    argv: tuple[str, ...]
    environment: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        if (type(self.argv) is not tuple or not 1 <= len(self.argv) <= 32
                or any(not isinstance(a, str) or not a or "\0" in a or len(a.encode()) > 16384 for a in self.argv)
                or sum(len(a.encode()) for a in self.argv) > 65536
                or not Path(self.argv[0]).is_absolute()):
            raise ValueError("bounded argv with explicit absolute executable required")
        if type(self.environment) is not tuple or len(self.environment) > 32:
            raise ValueError("bounded explicit environment required")
        keys = set()
        for pair in self.environment:
            if (type(pair) is not tuple or len(pair) != 2 or any(not isinstance(s, str) for s in pair)
                    or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", pair[0]) or pair[0] in keys
                    or len(pair[1].encode()) > 8192 or "\0" in pair[1]):
                raise ValueError("invalid environment entry")
            keys.add(pair[0])


Provider = PremiseProvider | RuleProvider | JsonProvider | CommandProvider


def _response(request, proposals):
    return json.dumps({"request_sha256": request["request_sha256"], "proposals": proposals}, allow_nan=False)


def _generate(provider: Provider, request: dict, limits: ProviderLimits, remaining_seconds: float) -> str:
    if type(provider) is PremiseProvider:
        rows = [{"kind": "premise", "name": name, "method": method}
                for method in METHODS for name in request["premises"]]
        return _response(request, rows[:request["proposal_limit"]])
    if type(provider) is RuleProvider:
        return _response(request, [{"kind": "path", "rules": list(p)}
                                  for p in provider.paths[:request["proposal_limit"]]])
    if type(provider) is JsonProvider:
        return provider.response
    if type(provider) is not CommandProvider:
        raise ValueError("use a value adapter or bounded command; arbitrary callbacks are not supported")
    payload = json.dumps(request, sort_keys=True, allow_nan=False).encode()
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
           **dict(provider.environment)}
    # A regular stdin file avoids a pipe writer that could itself block forever.
    with tempfile.TemporaryDirectory(prefix="jevops-provider-") as scratch:
        with tempfile.TemporaryFile(dir=scratch) as stream:
            stream.write(payload)
            stream.seek(0)
            output, _errors, code = capture_process(list(provider.argv), stdin=stream, env=env, cwd=scratch,
                timeout=min(limits.per_provider_seconds, remaining_seconds), output_limit=limits.response_bytes)
    if code:
        raise RuntimeError("provider exit failure")
    return output.decode("utf-8")


def parse_nominations(raw: str, request: dict, *, byte_limit: int = 65536) -> list:
    value = strict_json(raw, limit=byte_limit)
    _fields(value, "request_sha256 proposals")
    if value["request_sha256"] != request["request_sha256"]:
        raise ValueError("stale or foreign proposal request")
    rows = value["proposals"]
    if type(rows) is not list or len(rows) > request["proposal_limit"]:
        raise ValueError("proposal count budget")
    for row in rows:
        if type(row) is not dict:
            raise ValueError("typed nomination required")
        if row.get("kind") == "premise":
            _fields(row, "kind name method")
            if row["name"] not in request["premises"] or row["method"] not in METHODS:
                raise ValueError("unranked premise or unknown application method")
        elif row.get("kind") == "path":
            _fields(row, "kind rules")
            if type(row["rules"]) is not list:
                raise ValueError("rule array required")
            _paths((tuple(row["rules"]),))
        else:
            raise ValueError("unknown nomination kind")
    return rows


def proposal_request(record, index: PremiseIndex, scope: PremiseScope, *, seed: Candidate | None = None,
                     proposal_limit: int = 8, top_k: int = 4, max_scan: int = 512) -> tuple[dict, dict]:
    bounded_int(proposal_limit, 1, 8)
    if type(index) is not PremiseIndex or type(scope) is not PremiseScope:
        raise ValueError("typed premise index and scope required")
    if scope.record_sha256 != content_hash(record):
        raise ValueError("scope/record mismatch")
    premise_name(record["name"])
    Candidate("reference", record["src"], "unverified reference")
    if intake_error(record["src"], record["statement"]):
        raise ValueError("invalid reference envelope")
    if seed is not None and (type(seed) is not Candidate or intake_error(seed.source, record["statement"])):
        raise ValueError("seed must preserve the exact statement")
    base = seed.source if seed else record["src"]
    ranking = index.rank(record["statement"], target=record["name"], scope=scope, top_k=top_k, max_scan=max_scan)
    request = {"schema": "jevops-arena-provider-request/v1", "record_sha256": scope.record_sha256,
        "environment_sha256": scope.environment_sha256, "scope_sha256": ranking["scope_sha256"],
        "index_sha256": index.index_sha256, "ranking_sha256": content_hash(ranking),
        "target": record["name"], "statement": record["statement"], "base_source": base,
        "base_source_sha256": source_hash(base), "premises": [p["name"] for p in ranking["matches"]],
        "rules": list(RULES), "methods": list(METHODS), "proposal_limit": proposal_limit,
        "tokenizer_id": TOKENIZER_ID}
    request["request_sha256"] = content_hash(request)
    return request, ranking


def propose_batch(record, index: PremiseIndex, scope: PremiseScope, *, providers: tuple[Provider, ...] | None = None,
                  seed: Candidate | None = None, cap: int = 8, proposal_limit: int = 8,
                  top_k: int = 4, max_scan: int = 512, limits: ProviderLimits | None = None) -> dict:
    bounded_int(cap, 0, 8)
    limits = ProviderLimits() if limits is None else limits
    if type(limits) is not ProviderLimits:
        raise ValueError("typed provider limits required")
    providers = (PremiseProvider(), RuleProvider()) if providers is None else providers
    if type(providers) is not tuple or len(providers) > 8:
        raise ValueError("at most eight value-type providers required")
    ids = set()
    for provider in providers:
        if type(provider) not in (PremiseProvider, RuleProvider, JsonProvider, CommandProvider):
            raise ValueError("unsupported provider adapter")
        _provider_id(provider.provider_id)
        if provider.provider_id in ids:
            raise ValueError("duplicate provider id")
        ids.add(provider.provider_id)
    request, ranking = proposal_request(record, index, scope, seed=seed, proposal_limit=proposal_limit,
                                       top_k=top_k, max_scan=max_scan)
    if len(json.dumps(request, sort_keys=True, allow_nan=False).encode()) > limits.request_bytes:
        raise ValueError("request byte budget")
    deadline = time.monotonic() + limits.total_seconds
    base_tokens = reference_tokens(request["base_source"], record["statement"])
    seen = {source_hash(record["src"]), request["base_source_sha256"]}
    drafts, attempts = [], []
    for provider in providers:
        if len(drafts) >= cap:
            break
        attempt = {"provider_id": provider.provider_id, "adapter": type(provider).__name__,
                   "request_sha256": request["request_sha256"], "status": "ABSTAINED", "outcomes": []}
        attempts.append(attempt)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            attempt["status"] = "TOTAL_TIMEOUT"
            break
        try:
            raw = _generate(provider, request, limits, remaining)
            attempt["response_sha256"] = source_hash(raw)
            rows = parse_nominations(raw, request, byte_limit=limits.response_bytes)
        except Exception as exc:
            attempt.update(status="TIMEOUT" if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)) else "ERROR",
                           error_type=type(exc).__name__)
            # Exception strings / provider stderr can contain credentials.
            continue
        for row in rows:
            if len(drafts) >= cap:
                break
            outcome = {"nomination": row, "status": "ABSTAINED"}
            attempt["outcomes"].append(outcome)
            if row["kind"] == "path":
                batch = draft_batch(record, [row["rules"]], cap=1, seed=seed)
                source = batch["drafts"][0]["source"] if batch["drafts"] else None
            else:
                name = "_root_." + row["name"]  # Do not resolve through local shadowing.
                body = name if row["method"] == "term" else f"by {row['method']} {name}"
                source = record["statement"] + " := " + body
            if source is None or intake_error(source, record["statement"]):
                continue
            identity = source_hash(source)
            tokens = reference_tokens(source, record["statement"])
            outcome.update(source_sha256=identity, tokens=tokens)
            if identity in seen:
                outcome["status"] = "DUPLICATE"
            elif tokens >= base_tokens:
                outcome["status"] = "NOT_SHORTER"
            else:
                seen.add(identity)
                candidate = Candidate(f"provider-{len(drafts)}", source,
                    f"unverified {provider.provider_id}; request {request['request_sha256']}")
                drafts.append({"name": record["name"], **asdict(candidate)})
                outcome.update(status="DRAFT", label=candidate.label)
        attempt["status"] = "PROPOSED" if any(o["status"] == "DRAFT" for o in attempt["outcomes"]) else "ABSTAINED"
    return {"schema": SCHEMA, "request": request, "ranking": ranking, "upstream": UPSTREAM,
        "limits": asdict(limits), "cap": cap, "base_tokens": base_tokens,
        "reference_tokens": reference_tokens(record["src"], record["statement"]),
        "seed": asdict(seed) if seed else None, "attempts": attempts, "drafts": drafts,
        "external_calls_attempted": sum(a["adapter"] == "CommandProvider" and a["status"] != "TOTAL_TIMEOUT" for a in attempts),
        "proof_verified": False, "native_verifier_calls": 0, "training_enabled": False,
        "promoted": False, "official_score": None,
        "implementation_sha256": {name: source_hash(Path(__file__).with_name(name).read_text())
                                   for name in ("arena_providers.py", "premise_search.py")}}


def _prepare_local_batch(record, capture, index: PremiseIndex, scope: PremiseScope, *,
                        seed: Candidate | None = None, cap: int = 8, top_k: int = 4,
                        max_scan: int = 512, max_events: int = 16,
                        max_query_nodes: int = 256, strategy: str = "baseline-v1",
                        max_templates: int = 128) -> dict:
    """Shared validation/binding only; does not query premises or invoke Lean."""
    from .proof_replay import _check_capture

    bounded_int(cap, 0, 8)
    bounded_int(top_k, 1, 8)
    bounded_int(max_scan, 1, 8192)
    bounded_int(max_events, 0, 64)
    bounded_int(max_query_nodes, 0, 4096)
    bounded_int(max_templates, 0, 512)
    if strategy not in LOCAL_STRATEGIES:
        raise ValueError("unknown local strategy")
    if type(index) is not PremiseIndex or type(scope) is not PremiseScope:
        raise ValueError("typed premise index and scope required")
    if scope.record_sha256 != content_hash(record):
        raise ValueError("scope/record mismatch")
    if scope.environment_sha256 != index.environment_sha256:
        raise ValueError("premise environment mismatch")
    premise_name(record["name"])
    Candidate("reference", record["src"], "unverified reference")
    if intake_error(record["src"], record["statement"]):
        raise ValueError("invalid reference envelope")
    header = re.match(r"(?:theorem|lemma)\s+([^\s(:{]+)(?=\s|[(:{])", record["statement"])
    if header is None:
        raise ValueError("unsupported declaration header")
    declaration_name = premise_name(header[1])
    # Arena problem IDs (e.g. Core.foo) need not equal declaration names (foo).
    # Exclude both, including their aliases and dependent wrappers.
    effective_scope = replace(scope, excluded_names=tuple(dict.fromkeys(
        (*scope.excluded_names, record["name"], declaration_name))))
    if seed is not None and (type(seed) is not Candidate or intake_error(seed.source, record["statement"])):
        raise ValueError("seed must preserve the exact statement")
    source = seed.source if seed else record["src"]
    _check_capture(source, capture, scope.environment_sha256)
    origin = capture.get("origin")
    if origin is not None:
        if (type(origin) is not dict or origin.get("kind") != "arena-project/v1"
                or origin.get("record_sha256") != content_hash(record)
                or origin.get("context_id") != scope.environment_sha256
                or origin.get("target") != record["name"]):
            raise ValueError("foreign project capture origin")
        declaration_name = record["name"]
    request = {"schema": "jevops-local-premise-request/v1", "record_sha256": scope.record_sha256,
        "source_sha256": source_hash(source), "trace_sha256": capture["trace_sha256"],
        "capture_environment": capture["environment"], "environment_sha256": scope.environment_sha256,
        "origin_sha256": capture.get("origin_sha256"),
        "index_sha256": index.index_sha256, "scope_sha256": content_hash(asdict(scope)),
        "effective_scope_sha256": content_hash(asdict(effective_scope)), "declaration": declaration_name,
        "target": record["name"], "methods": ["exact", "apply"], "cap": cap, "top_k": top_k,
        "max_scan": max_scan, "max_events": max_events, "max_query_nodes": max_query_nodes,
        "ranking_bytes": LOCAL_RANKING_BYTES,
        "feature_method": "goal-and-local-type-constants/v1", "tokenizer_id": TOKENIZER_ID}
    if strategy == "portfolio-v1":
        request.update(strategy=strategy, max_templates=max_templates, families=list(LOCAL_FAMILIES),
            local_search=dict(LOCAL_SEARCH), closers=list(LOCAL_CLOSERS),
            schedule="diagonal-goal-family-round-robin/v1")
    request["request_sha256"] = content_hash(request)
    base_tokens = reference_tokens(source, record["statement"])
    batch = {"schema": "jevops-local-premise-batch/v1", "request": request, "events": [],
        "proposals": [], "drafts": [], "origins": [], "base_tokens": base_tokens,
        "policy": "deterministic-lexical-local-premises/v1", "status": "ABSTAINED",
        "truncated": False, "native_verifier_calls": 0, "external_calls_attempted": 0,
        "proof_verified": False, "proof_admitted": False, "whole_source_checked": False,
        "fresh_verification_required": True, "training_enabled": False, "promoted": False,
        "official_score": None}
    if strategy == "portfolio-v1":
        batch.update(policy="deterministic-local-tactic-portfolio/v1", attempted_templates=0,
                     family_drafts={f: 0 for f in LOCAL_FAMILIES})
    return batch, source, effective_scope


def propose_local_batch(record, capture, index: PremiseIndex, scope: PremiseScope, *,
                        seed: Candidate | None = None, cap: int = 8, top_k: int = 4,
                        max_scan: int = 512, max_events: int = 16,
                        max_query_nodes: int = 256, strategy: str = "baseline-v1",
                        max_templates: int = 128) -> dict:
    """Offline library-premise drafts at captured closing spans, never admission.

    ``proposals`` plugs into proof_replay.collect_replay_pairs; ``drafts`` plugs
    into the Arena all-pin selector. Historical default strategy is unchanged.
    """
    from .proof_replay import replace_event
    from .scoped_proposals import premise_query

    batch, source, effective_scope = _prepare_local_batch(record, capture, index, scope,
        seed=seed, cap=cap, top_k=top_k, max_scan=max_scan, max_events=max_events,
        max_query_nodes=max_query_nodes, strategy=strategy, max_templates=max_templates)
    request, base_tokens = batch["request"], batch["base_tokens"]
    declaration_name = request["declaration"]
    if cap == 0 or max_events == 0 or max_query_nodes == 0 or (strategy == "portfolio-v1" and max_templates == 0):
        return {**batch, "status": "BUDGET_EXHAUSTED", "truncated": True}
    events = [e for e in capture["trace"]["events"] if e["status"] == "captured"
              and e["before"]["goals"] and not e["after"]["goals"]
              and e["start"] is not None and e["end"] is not None]
    # Prefer small local obligations over whole-body attempts. Tiny spans that
    # cannot shorten the proof are discarded below, without spending draft slots.
    events.sort(key=lambda e: (int(e["end"]) - int(e["start"]), int(e["id"])))
    batch["truncated"] = len(events) > max_events
    if strategy == "portfolio-v1":
        return _local_portfolio(record, source, capture, index, effective_scope, events, batch)
    seen = {source_hash(source), source_hash(record["src"])}
    ranking_bytes = 0
    for event in events[:max_events]:
        if len(batch["drafts"]) >= cap:
            batch["truncated"] = True
            break
        # Captures are hints, but must still name the exact target declaration.
        declaration = [["s", part] for part in declaration_name.split(".")]
        if event["declaration"] != declaration:
            raise ValueError("foreign captured declaration")
        detail = {"event_id": int(event["id"]), "event_sha256": content_hash(event),
                  "start": event["start"], "end": event["end"], "outcomes": []}
        batch["events"].append(detail)
        try:
            replace_event(source, event, "skip")  # No `by`/declaration wrapper edits.
        except ValueError:
            detail["status"] = "UNSUPPORTED_SPAN"
            continue
        query = premise_query(event["before"], node_budget=capture["node_budget"],
                              max_query_nodes=max_query_nodes)
        detail.update(status=query["status"], observation=query)
        if query["status"] != "READY":
            batch["truncated"] |= query["status"] == "QUERY_BUDGET"
            continue
        ranking = index.rank(query["query"], target=declaration_name, scope=effective_scope,
                             top_k=top_k, max_scan=max_scan)
        ranking_bytes += len(json.dumps(ranking, sort_keys=True, allow_nan=False).encode())
        if ranking_bytes > LOCAL_RANKING_BYTES:
            detail.update(status="REPORT_BUDGET", ranking_sha256=content_hash(ranking))
            batch["truncated"] = True
            break
        detail.update(status=ranking["status"], ranking=ranking)
        batch["truncated"] |= ranking["status"] == "SCAN_BUDGET"
        nominations = [(method, p["name"]) for method in request["methods"] for p in ranking["matches"]]
        for method, name in nominations:
            if len(batch["drafts"]) >= cap:
                batch["truncated"] = True
                break
            candidate = f"{method} _root_.{name}"
            target = replace_event(source, event, candidate)
            identity = source_hash(target)
            tokens = reference_tokens(target, record["statement"])
            outcome = {"candidate": candidate, "source_sha256": identity, "tokens": tokens}
            detail["outcomes"].append(outcome)
            if intake_error(target, record["statement"]):
                outcome["status"] = "UNSUPPORTED_SOURCE"
            elif identity in seen:
                outcome["status"] = "DUPLICATE"
            elif tokens >= base_tokens:
                outcome["status"] = "NOT_SHORTER"
            else:
                seen.add(identity)
                label = f"local-premise-{len(batch['drafts'])}"
                outcome.update(status="DRAFT", label=label)
                batch["proposals"].append({"event_id": int(event["id"]), "candidate": candidate})
                batch["drafts"].append({"name": record["name"], "label": label, "source": target,
                    "provenance": f"unverified local premise; request {request['request_sha256']}; event {event['id']}"})
                batch["origins"].append({"label": label, "event_id": int(event["id"]),
                    "event_sha256": detail["event_sha256"], "premise": asdict(index.entries[name]),
                    "ranking_sha256": content_hash(ranking)})
    if batch["drafts"]:
        batch["status"] = "DRAFTS_ONLY"
    return batch


def plan_local_applications(record, capture, index: PremiseIndex, scope: PremiseScope, *,
                            seed: Candidate | None = None, cap=8, top_k=4, max_scan=512,
                            max_events=16, max_query_nodes=256, max_applications=16,
                            span_order="headroom-v1", retrieval="lexical-v1",
                            search="apply-assumption-v1", max_steps=96, max_depth=4,
                            max_pool=64, max_retrievals=32, retrieval_top_k=4, discharge_window=0,
                            discharge_filter="none", max_discharge_checks=256,
                            cycle_guard="none", max_cycle_checks=256, cycle_key="raw-v1"):
    """Offline bounded nominations for native application/term materialization.

    Lexical retrieval remains a hint. No shortening filter is applied to search
    scripts; native application, term replay and final draft filtering come later.
    Headroom means span token count, NOT inferred heartbeat cost or dependencies.
    """
    from .proof_replay import replace_event
    from .scoped_proposals import premise_query, goal_head

    bounded_int(max_applications, 0, 64)
    if span_order not in {"headroom-v1", "smallest-v1", "matching-head-v1"}:
        raise ValueError("unknown span order")
    if retrieval not in {"lexical-v1", "typed-head-v1"}:
        raise ValueError("unknown retrieval mode")
    if span_order == "matching-head-v1" and retrieval != "typed-head-v1":
        raise ValueError("matching-head order requires typed retrieval")
    if search not in {"apply-assumption-v1", "backward-v1", "subgoal-v1"}:
        raise ValueError("unknown search method")
    bounded_int(max_steps, 0, 256)
    bounded_int(max_depth, 0, 8)
    bounded_int(max_pool, 0, 64)
    bounded_int(max_retrievals, 0, 256)
    bounded_int(retrieval_top_k, 1, 8)
    bounded_int(discharge_window, 0, 16)
    bounded_int(max_discharge_checks, 0, 256)
    bounded_int(max_cycle_checks, 0, 256)
    if type(cycle_guard) is not str or cycle_guard not in {"none", "observe-v1", "prune-v1"}:
        raise ValueError("unknown cycle guard")
    cycling = cycle_guard != "none"
    if type(cycle_key) is not str or cycle_key not in {"raw-v1", "assigned-v1"}:
        raise ValueError("unknown cycle key")
    if cycle_key == "assigned-v1" and not cycling:
        raise ValueError("assigned cycle key requires a cycle guard")
    if cycling and search not in {"backward-v1", "subgoal-v1"}:
        raise ValueError("cycle guard requires backward search")
    if type(discharge_filter) is not str or discharge_filter not in {"none", "observe-all-v1", "propositions-v1"}:
        raise ValueError("unknown discharge filter")
    inspecting = discharge_filter != "none"
    if inspecting and not discharge_window:
        raise ValueError("discharge filter requires a positive window")
    if discharge_window and search != "subgoal-v1":
        raise ValueError("discharge ordering requires subgoal search")
    batch, source, effective_scope = _prepare_local_batch(record, capture, index, scope,
        seed=seed, cap=cap, top_k=top_k, max_scan=max_scan, max_events=max_events,
        max_query_nodes=max_query_nodes)
    request = batch["request"]
    request.pop("request_sha256")
    request.update(schema="jevops-local-application-request/v1", strategy="application-materialization/v1",
        max_applications=max_applications, span_order=span_order, methods=["apply_assumption"],
        final_filter="strictly-fewer-source-tokens/v1")
    if retrieval != "lexical-v1":
        request.update(retrieval=retrieval, head_steps=256)
    if span_order == "matching-head-v1":
        request.update(span_priority="matching-head-and-at-least-three-tokens/v1", fallback_every=4)
    if search in {"backward-v1", "subgoal-v1"}:
        request.update(search=search, methods=["assumption", "apply", "intro", "constructor"],
                       max_steps=max_steps, max_depth=max_depth,
                       primitive_reservation_ceiling=max_applications * max_steps)
    if search == "subgoal-v1":
        request.update(max_pool=max_pool, max_retrievals=max_retrievals, retrieval_top_k=retrieval_top_k,
            subgoal_method="raw-head-with-initial-fallback/v1", head_steps=256,
            retrieval_reservation_ceiling=max_applications * max_retrievals)
    if discharge_window:
        request.update(discharge_window=discharge_window, goal_order="bounded-assumption-first/v1")
    if inspecting:
        request.update(discharge_filter=discharge_filter, max_discharge_checks=max_discharge_checks,
                       discharge_check_reservation_ceiling=max_applications * max_discharge_checks)
    if cycling:
        request.update(cycle_guard=cycle_guard, max_cycle_checks=max_cycle_checks,
                       cycle_check_reservation_ceiling=max_applications * max_cycle_checks)
    if cycle_key == "assigned-v1":
        request["cycle_key"] = cycle_key
    request["request_sha256"] = content_hash(request)
    batch.update(schema="jevops-local-application-plan/v1", policy="lexical-then-native-application/v1",
                 applications=[], status="PLANNED")
    if retrieval == "typed-head-v1":
        batch["policy"] = "typed-head-then-native-application/v1"
    if (not cap or not max_events or not max_query_nodes or not max_applications
            or (search in {"backward-v1", "subgoal-v1"} and (not max_steps or not max_depth))
            or (search == "subgoal-v1" and (not max_pool or not max_retrievals))
            or (inspecting and not max_discharge_checks) or (cycling and not max_cycle_checks)):
        return {**batch, "status": "BUDGET_EXHAUSTED", "truncated": True}
    if search == "subgoal-v1":
        pool = index.scoped_pool(target=request["declaration"], scope=effective_scope, max_pool=max_pool)
        batch["subgoal_pool"] = pool
        if pool["status"] == "POOL_BUDGET":
            return {**batch, "status": "BUDGET_EXHAUSTED", "reason": "subgoal pool overflow", "truncated": True}
    eligible, seen_spans = [], set()
    for event in capture["trace"]["events"]:
        if (event["status"] != "captured" or len(event["before"]["goals"]) != 1
                or event["after"]["goals"] or None in (event["start"], event["end"])):
            continue
        if event["declaration"] != [["s", p] for p in request["declaration"].split(".")]:
            raise ValueError("foreign captured declaration")
        span = event["start"], event["end"]
        if span in seen_spans:
            continue
        seen_spans.add(span)
        try:
            replace_event(source, event, "skip")
        except ValueError:
            continue
        fragment = source.encode()[int(span[0]):int(span[1])].decode()
        # Use the same lexical conventions as final Arena source counting; this
        # synthetic envelope is only a tokenizer input, never a Lean obligation.
        tokens = reference_tokens(record["statement"] + " := " + fragment, record["statement"])
        eligible.append((event, tokens))
    eligible.sort(key=lambda pair: ((-pair[1] if span_order != "smallest-v1" else
                                    int(pair[0]["end"]) - int(pair[0]["start"])), int(pair[0]["id"])))
    batch["truncated"] = len(eligible) > max_events
    ranking_bytes = 0
    for event, tokens in eligible[:max_events]:
        query = premise_query(event["before"], node_budget=capture["node_budget"],
                              max_query_nodes=max_query_nodes)
        detail = {"event_id": int(event["id"]), "event_sha256": content_hash(event),
                  "span_tokens": tokens, "status": query["status"], "observation": query}
        batch["events"].append(detail)
        if query["status"] != "READY":
            batch["truncated"] |= query["status"] == "QUERY_BUDGET"
            continue
        features = {}
        if retrieval == "typed-head-v1":
            head = goal_head(event["before"], node_budget=capture["node_budget"], max_steps=256)
            detail["goal_head"] = asdict(head) if head is not None else None
            if head is not None:
                features["conclusion"] = head
        ranking = index.rank(query["query"], target=request["declaration"], scope=effective_scope,
                             top_k=top_k, max_scan=max_scan, **features)
        ranking_bytes += len(json.dumps(ranking, sort_keys=True, allow_nan=False).encode())
        if ranking_bytes > LOCAL_RANKING_BYTES:
            detail["status"] = "REPORT_BUDGET"
            batch["truncated"] = True
            break
        detail.update(status=ranking["status"], ranking=ranking)
        batch["truncated"] |= ranking["status"] == "SCAN_BUDGET"
    # Round-robin over selected spans; a single span cannot use all applications
    # before another gets its first nominee. Finite caps still limit coverage.
    selected = [e for e in batch["events"] if e.get("ranking", {}).get("matches")]
    if span_order == "matching-head-v1":
        preferred, fallback = deque(), deque()
        for event in selected:
            promising = event["span_tokens"] >= 3 and any(
                m.get("head_priority") == 0 for m in event["ranking"]["matches"])
            event["span_priority"] = "matching-head" if promising else "fallback"
            (preferred if promising else fallback).append(event)
        selected = []
        while preferred or fallback:
            queue = fallback if fallback and (not preferred or len(selected) % 4 == 3) else preferred
            selected.append(queue.popleft())
    options = deque((e, deque(e["ranking"]["matches"])) for e in selected)
    while options and len(batch["applications"]) < max_applications:
        event, matches = options.popleft()
        if search in {"backward-v1", "subgoal-v1"}:
            batch["applications"].append({"event_id": event["event_id"],
                "premises": [m["name"] for m in matches], "max_steps": max_steps, "max_depth": max_depth})
            if cycling:
                batch["applications"][-1].update(cycle_guard=cycle_guard, max_cycle_checks=max_cycle_checks)
            if cycle_key == "assigned-v1":
                batch["applications"][-1]["cycle_key"] = cycle_key
            if search == "subgoal-v1":
                batch["applications"][-1].update(subgoal_pool=pool["entries"],
                    max_retrievals=max_retrievals, retrieval_top_k=retrieval_top_k)
                if discharge_window:
                    batch["applications"][-1]["discharge_window"] = discharge_window
                if inspecting:
                    batch["applications"][-1].update(discharge_filter=discharge_filter,
                        max_discharge_checks=max_discharge_checks)
            continue
        match = matches.popleft()
        if matches:
            options.append((event, matches))
        batch["applications"].append({"event_id": event["event_id"], "premise": match["name"]})
    batch["truncated"] |= bool(options)
    return batch


def _read(path: Path, limit: int):
    with path.open("rb") as stream:
        return strict_json(stream.read(limit + 1), limit=limit)


def load_inventory(index_value: dict, scope_value: dict) -> tuple[PremiseIndex, PremiseScope]:
    typed = type(index_value) is dict and index_value.get("schema") == "jevops-premise-index/v2"
    _fields(index_value, "schema environment_sha256 premises" + (" signatures" if typed else ""))
    _fields(scope_value, "schema record_sha256 environment_sha256 available_names excluded_names excluded_origins")
    if index_value["schema"] not in {"jevops-premise-index/v1", "jevops-premise-index/v2"} or scope_value["schema"] != "jevops-premise-scope/v1":
        raise ValueError("unsupported inventory schema")
    if type(index_value["premises"]) is not list or len(index_value["premises"]) > 8192:
        raise ValueError("bounded premise list required")
    entries = []
    for row in index_value["premises"]:
        _fields(row, "name type_text origin split aliases dependencies")
        if type(row["aliases"]) is not list or type(row["dependencies"]) is not list:
            raise ValueError("alias/dependency arrays required")
        entries.append(Premise(**{**row, "aliases": tuple(row["aliases"]), "dependencies": tuple(row["dependencies"])}))
    values = {k: v for k, v in scope_value.items() if k != "schema"}
    for key in ("available_names", "excluded_names", "excluded_origins"):
        if type(values[key]) is not list:
            raise ValueError("scope arrays required")
        values[key] = tuple(values[key])
    signatures = index_value["signatures"] if typed else []
    if type(signatures) is not list or len(signatures) > 8192:
        raise ValueError("bounded signature list required")
    return PremiseIndex(tuple(entries), environment_sha256=index_value["environment_sha256"],
        signatures=tuple(PremiseSignature.from_dict(s) for s in signatures)), PremiseScope(**values)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    parser.add_argument("--problem", required=True)
    parser.add_argument("--premises", type=Path, required=True)
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--seed", type=Path)
    parser.add_argument("--capture", type=Path, help="source-bound proof-state capture: local premise mode, no native calls")
    parser.add_argument("--max-events", type=int, default=16)
    parser.add_argument("--max-query-nodes", type=int, default=256)
    parser.add_argument("--local-strategy", choices=LOCAL_STRATEGIES, default="baseline-v1")
    parser.add_argument("--max-templates", type=int, default=128)
    parser.add_argument("--proposal-response", type=Path, action="append", default=[])
    parser.add_argument("--cap", type=int, default=8)
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--max-scan", type=int, default=512)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        if len(args.proposal_response) > 6:
            raise ValueError("at most six offline providers plus two baselines")
        with args.corpus.open("rb") as stream:
            raw = stream.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("corpus byte budget")
        records = [strict_json(line, limit=1048576) for line in raw.splitlines() if line.strip()]
        matches = [r for r in records if r["name"] == args.problem]
        if len(matches) != 1:
            raise ValueError("exactly one matching problem required")
        record, seed = matches[0], None
        if args.seed:
            value = _read(args.seed, 1048576)
            _fields(value, "name label source provenance")
            if value["name"] != args.problem:
                raise ValueError("foreign seed")
            seed = Candidate(value["label"], value["source"], value["provenance"])
        index, scope = load_inventory(_read(args.premises, 8 * 1024 * 1024), _read(args.scope, 4 * 1024 * 1024))
        if args.capture:
            if args.proposal_response:
                raise ValueError("local capture mode does not accept whole-proof provider responses")
            batch = propose_local_batch(record, _read(args.capture, 16 * 1024 * 1024), index, scope,
                seed=seed, cap=args.cap, top_k=args.top_k, max_scan=args.max_scan,
                max_events=args.max_events, max_query_nodes=args.max_query_nodes,
                strategy=args.local_strategy, max_templates=args.max_templates)
        else:
            if args.local_strategy != "baseline-v1" or args.max_templates != 128:
                raise ValueError("local strategy/template budget requires --capture")
            providers = tuple(JsonProvider(f"offline-{i}", json.dumps(_read(path, 65536)))
                              for i, path in enumerate(args.proposal_response)) + (PremiseProvider(), RuleProvider())
            batch = propose_batch(record, index, scope, providers=providers, seed=seed, cap=args.cap,
                                  top_k=args.top_k, max_scan=args.max_scan)
        args.output_dir.mkdir(parents=True, exist_ok=False)
        for draft in batch["drafts"]:
            (args.output_dir / (draft["label"] + ".json")).write_text(json.dumps(draft, indent=2) + "\n")
        for name, value in (("manifest", batch), ("request", batch["request"])):
            (args.output_dir / f"{name}.json").write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps({"status": batch["status"] if args.capture else "DRAFTS_ONLY",
                      "count": len(batch["drafts"]), "output_dir": str(args.output_dir),
                      "native_verifier_calls": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

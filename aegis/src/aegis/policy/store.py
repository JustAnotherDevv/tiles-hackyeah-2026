"""PolicyStore implementation (factory `aegis.policy.store:create`, CONTRACTS sections 3.2/3.3/4.1).

Owns the live `PolicySnapshot` and the apply pipeline:
  parse -> validate (line/col) -> profile merge -> self-test gate -> atomic swap (one reference
  assignment under an asyncio.Lock) -> persist (policy_versions row, data/policy/last_good.yaml,
  config/policy.yaml for API sources) -> audit + bus `policy.applied` + metrics + on_change.
Any failure keeps the last-known-good version and emits `policy.rejected` (audit + bus).

Startup chain (lazy, synchronous, on first `snapshot()` or in `start()`):
  AEGIS_POLICY -> data/policy/last_good.yaml -> config/policy.golden.yaml -> PolicyDoc() defaults.
Extras reachable via getattr(rt.policy, ...): reload_from_file, run_selftest, last_selftest,
status, health, effective_controls, snapshot_for_profile, register_validator.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import inspect
import json
import logging
import os
import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aegis.core.policy_schema import (
    ApplyResult,
    ControlConfig,
    PatchOp,
    PolicyChange,
    PolicyDoc,
    PolicySnapshot,
    PolicyVersionInfo,
    ValidationIssue,
    ValidationReport,
)
from aegis.core.types import AuditEvent, Identity, new_id
from aegis.policy import catalog
from aegis.policy.diff import diff_docs, diff_effective, summarize, unified_diff
from aegis.policy.profiles import ProfileSet, effective_controls
from aegis.policy.selftest import (
    MUST_PROTECT,
    BaselineEntry,
    CaseOutcome,
    SelfTestRun,
    SelfTestRunner,
    case_label,
    looser,
)
from aegis.policy.validate import Validated, first_error_message, validate_text

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
GATE_BUDGET_S = 2.5
VALIDATE_BUDGET_S = 8.0
DIFF_CAP = 20_000


class PolicyValidationError(ValueError):
    def __init__(self, errors: list[ValidationIssue]):
        super().__init__(first_error_message(errors) or "invalid policy")
        self.errors = errors


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _who(actor: Identity | None) -> str | None:
    if actor is None:
        return None
    return actor.member_id or actor.agent_id or "anonymous"


def _resolve(p: str | Path) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (REPO_ROOT / path)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        with contextlib.suppress(OSError):
            os.fsync(fh.fileno())
    os.replace(tmp, path)


# ================================================================ persistence
_DDL = (
    "CREATE TABLE IF NOT EXISTS policy_versions (version INTEGER PRIMARY KEY, sha256 TEXT NOT NULL, "
    "yaml TEXT NOT NULL, applied_at TEXT NOT NULL, applied_by TEXT, source TEXT NOT NULL, reason TEXT, "
    "changes_json TEXT NOT NULL DEFAULT '[]', summary TEXT)",
    "CREATE TABLE IF NOT EXISTS policy_proposals (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT, "
    "actor_json TEXT NOT NULL, source TEXT NOT NULL, base_version INTEGER, sha256 TEXT NOT NULL, yaml TEXT, "
    "patch_json TEXT, reason TEXT, changes_json TEXT NOT NULL DEFAULT '[]', decision_id TEXT, approval_id TEXT, "
    "status TEXT NOT NULL, applied_version INTEGER)",
    "CREATE INDEX IF NOT EXISTS ix_policy_proposals_sha ON policy_proposals(sha256)",
    "CREATE INDEX IF NOT EXISTS ix_policy_proposals_dec ON policy_proposals(decision_id)",
)


class VersionRepo:
    """policy_versions + policy_proposals in SQLite via rt.db(); in-memory if no DB."""

    def __init__(self, rt: Any):
        self.rt = rt
        self._ready = False
        self._mem = False
        self._versions: list[dict[str, Any]] = []
        self._proposals: dict[str, dict[str, Any]] = {}

    def _conn(self) -> sqlite3.Connection | None:
        if self._mem:
            return None
        db = getattr(self.rt, "db", None)
        if not callable(db):
            self._mem = True
            return None
        try:
            conn = db()
            if not isinstance(conn, sqlite3.Connection):
                raise TypeError("rt.db() did not return a sqlite3 connection")
            conn.row_factory = sqlite3.Row
        except Exception as exc:
            log.warning("policy versions in memory (db unavailable: %s)", exc)
            self._mem = True
            return None
        if not self._ready:
            for stmt in _DDL:
                conn.execute(stmt)
            conn.commit()
            self._ready = True
        return conn

    def _q(self, sql: str, args: tuple[Any, ...] = (), *, one: bool = False, write: bool = False) -> Any:
        conn = self._conn()
        if conn is None:
            return None
        try:
            cur = conn.execute(sql, args)
            if write:
                conn.commit()
                return cur.rowcount
            rows = cur.fetchall()
            return (dict(rows[0]) if rows else None) if one else [dict(r) for r in rows]
        finally:
            conn.close()

    def ensure(self) -> None:
        conn = self._conn()
        if conn is not None:
            conn.close()

    # -- versions
    def max_version(self) -> int:
        if self._conn_ok():
            row = self._q("SELECT MAX(version) AS v FROM policy_versions", one=True)
            return int(row["v"] or 0) if row else 0
        return max((v["version"] for v in self._versions), default=0)

    def latest(self) -> dict[str, Any] | None:
        if self._conn_ok():
            return self._q("SELECT * FROM policy_versions ORDER BY version DESC LIMIT 1", one=True)
        return max(self._versions, key=lambda v: v["version"]) if self._versions else None

    def insert(self, row: dict[str, Any]) -> None:
        if self._conn_ok():
            self._q("INSERT OR REPLACE INTO policy_versions (version, sha256, yaml, applied_at, applied_by, source, "
                    "reason, changes_json, summary) VALUES (?,?,?,?,?,?,?,?,?)",
                    (row["version"], row["sha256"], row["yaml"], row["applied_at"], row.get("applied_by"),
                     row["source"], row.get("reason"), row.get("changes_json", "[]"), row.get("summary", "")),
                    write=True)
        else:
            self._versions = [v for v in self._versions if v["version"] != row["version"]] + [dict(row)]

    def history(self, limit: int) -> list[dict[str, Any]]:
        if self._conn_ok():
            return self._q("SELECT version, sha256, applied_at, applied_by, source, reason, changes_json, summary "
                           "FROM policy_versions ORDER BY version DESC LIMIT ?", (int(limit),)) or []
        return sorted(self._versions, key=lambda v: -v["version"])[:limit]

    def get_yaml(self, version: int) -> str | None:
        if self._conn_ok():
            row = self._q("SELECT yaml FROM policy_versions WHERE version = ?", (int(version),), one=True)
            return row["yaml"] if row else None
        return next((v["yaml"] for v in self._versions if v["version"] == version), None)

    def _conn_ok(self) -> bool:
        if self._mem:
            return False
        conn = self._conn()
        if conn is None:
            return False
        conn.close()
        return True

    # -- proposals
    def insert_proposal(self, *, id: str, actor: Identity, source: str, base_version: int, sha256: str,
                        yaml: str | None, patch: Any, reason: str | None, changes: list[PolicyChange]) -> None:
        row = {"id": id, "created_at": _now_iso(), "updated_at": _now_iso(),
               "actor_json": actor.model_dump_json(), "source": source, "base_version": base_version,
               "sha256": sha256, "yaml": yaml, "patch_json": json.dumps(patch) if patch is not None else None,
               "reason": reason, "changes_json": json.dumps([c.model_dump(mode="json") for c in changes]),
               "decision_id": None, "approval_id": None, "status": "pending", "applied_version": None}
        try:
            if self._conn_ok():
                cols = ",".join(row)
                self._q(f"INSERT INTO policy_proposals ({cols}) VALUES ({','.join('?' * len(row))})",
                        tuple(row.values()), write=True)
            else:
                self._proposals[id] = row
        except Exception:
            log.exception("policy proposal insert failed id=%s", id)

    def update_proposal(self, id: str | None, **fields: Any) -> None:
        if not id:
            return
        fields = {k: v for k, v in fields.items() if v is not None or k == "status"}
        fields["updated_at"] = _now_iso()
        try:
            if self._conn_ok():
                sets = ", ".join(f"{k} = ?" for k in fields)
                self._q(f"UPDATE policy_proposals SET {sets} WHERE id = ?", (*fields.values(), id), write=True)
            elif id in self._proposals:
                self._proposals[id].update(fields)
        except Exception:
            log.exception("policy proposal update failed id=%s", id)

    def _decode(self, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        out = dict(row)
        if out.get("patch_json"):
            try:
                out["patch"] = json.loads(out["patch_json"])
            except ValueError:
                out["patch"] = None
        return out

    def get_proposal(self, id: str) -> dict[str, Any] | None:
        if self._conn_ok():
            return self._decode(self._q("SELECT * FROM policy_proposals WHERE id = ?", (id,), one=True))
        return self._decode(self._proposals.get(id))

    def find_proposal_by_decision(self, decision_id: str) -> dict[str, Any] | None:
        if self._conn_ok():
            return self._decode(self._q("SELECT * FROM policy_proposals WHERE decision_id = ? ORDER BY created_at DESC "
                                        "LIMIT 1", (decision_id,), one=True))
        return self._decode(next((p for p in self._proposals.values() if p.get("decision_id") == decision_id), None))

    def find_proposal_by_sha_prefix(self, prefix: str) -> dict[str, Any] | None:
        if not prefix:
            return None
        if self._conn_ok():
            return self._decode(self._q("SELECT * FROM policy_proposals WHERE sha256 LIKE ? ORDER BY created_at DESC "
                                        "LIMIT 1", (prefix + "%",), one=True))
        return self._decode(next((p for p in self._proposals.values() if str(p["sha256"]).startswith(prefix)), None))

    def list_proposals(self, limit: int = 50) -> list[dict[str, Any]]:
        if self._conn_ok():
            return self._q("SELECT id, created_at, updated_at, actor_json, source, base_version, sha256, reason, "
                           "decision_id, approval_id, status, applied_version FROM policy_proposals "
                           "ORDER BY created_at DESC LIMIT ?", (int(limit),)) or []
        return sorted(self._proposals.values(), key=lambda p: p["created_at"], reverse=True)[:limit]


# ================================================================ the store
class PolicyStoreImpl:
    """Implements aegis.core.protocols.PolicyStore."""

    def __init__(self, rt: Any):
        self.rt = rt
        self.versions = VersionRepo(rt)
        self.runner = SelfTestRunner(rt)
        self._snap: PolicySnapshot | None = None
        self._text = ""
        self._lock: asyncio.Lock | None = None
        self._callbacks: list[Callable[[PolicySnapshot], Any]] = []
        self._own_writes: set[str] = set()
        self._baseline: dict[tuple[str, str], BaselineEntry] = {}
        self._baseline_version: int | None = None
        self._last_selftest: SelfTestRun | None = None
        self._last_error: str | None = None
        self._state = "ok"
        self._loaded_from = "file"
        self._pending: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = []
        self._started = False
        self._bg: set[asyncio.Task[Any]] = set()
        self._validators: list[Callable[..., list[ValidationIssue]]] = []
        self._profiles: ProfileSet | None = None
        self._org_ids: dict[str, set[str]] | None = None
        self.watcher: Any = None
        self.stats: Any = None
        self._gate_outcomes: tuple[str, dict[tuple[str, str], CaseOutcome]] | None = None

    # ------------------------------------------------------------ settings
    def _setting(self, name: str, env: str, default: Any) -> Any:
        s = getattr(self.rt, "settings", None)
        val = getattr(s, name, None) if s is not None else None
        if val in (None, ""):
            val = os.environ.get(env) or default
        return val

    @property
    def policy_path(self) -> Path:
        return _resolve(self._setting("policy", "AEGIS_POLICY", "config/policy.yaml"))

    @property
    def data_dir(self) -> Path:
        return _resolve(self._setting("data_dir", "AEGIS_DATA_DIR", "data"))

    @property
    def last_good_path(self) -> Path:
        return self.data_dir / "policy" / "last_good.yaml"

    @property
    def golden_path(self) -> Path:
        sib = self.policy_path.parent / "policy.golden.yaml"
        return sib if sib.is_file() else REPO_ROOT / "config" / "policy.golden.yaml"

    @property
    def test_mode(self) -> bool:
        s = getattr(self.rt, "settings", None)
        if s is not None and getattr(s, "test_mode", None) is not None:
            return bool(s.test_mode) or os.environ.get("AEGIS_TEST_MODE") == "1"
        return os.environ.get("AEGIS_TEST_MODE") == "1"

    def _lk(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    # ------------------------------------------------------------ building candidates
    def load_profiles(self) -> ProfileSet:
        self._profiles = ProfileSet.load(policy_path=self.policy_path)
        return self._profiles

    def _kind_lookup(self, cid: str) -> str:
        reg = getattr(self.rt, "controls", None)
        try:
            ctl = reg.get(cid) if reg is not None else None
        except Exception:
            ctl = None
        return str(getattr(ctl, "kind", None) or catalog.kind_of(cid))

    def build_candidate(self, text: str, *, version: int, source: str, actor: Identity | None,
                        profiles: ProfileSet | None = None) -> tuple[PolicySnapshot | None, Validated, ProfileSet]:
        profiles = profiles or self.load_profiles()
        v = validate_text(text, profiles=profiles, org=self._org_ids)
        if v.ok and self._validators:
            for fn in self._validators:
                try:
                    for issue in fn(v.doc) or []:
                        (v.errors if issue.severity == "error" else v.warnings).append(issue)
                except Exception as exc:
                    v.warnings.append(ValidationIssue(message=f"validator {getattr(fn, '__name__', fn)} failed: {exc}",
                                                      severity="warning"))
            if v.errors:
                v.doc = None
        if not v.ok or v.doc is None:
            return None, v, profiles
        eff = effective_controls(v.raw, v.doc, v.doc.profile, profiles, kind_lookup=self._kind_lookup)
        snap = PolicySnapshot(version=version, sha256=_sha(text), doc=v.doc, controls=eff,
                              applied_by=_who(actor), source=source)
        snap.compiled["policy-engine:profiles_sha"] = profiles.sha256
        snap.compiled["policy-engine:raw"] = v.raw
        snap.compiled["policy-engine:index"] = v.index
        snap.compiled["policy-engine:warnings"] = [w.model_dump(mode="json") for w in v.warnings]
        return snap, v, profiles

    def snapshot_for_profile(self, profile: str) -> PolicySnapshot:
        """Current policy evaluated under another profile (CLI --all-profiles, effective endpoint)."""
        cur = self.snapshot()
        raw = cur.compiled.get("policy-engine:raw")
        doc = cur.doc.model_copy(update={"profile": profile})
        profiles = self._profiles or self.load_profiles()
        eff = effective_controls(raw, doc, profile, profiles, kind_lookup=self._kind_lookup)
        snap = PolicySnapshot(version=cur.version, sha256=cur.sha256, doc=doc, controls=eff,
                              applied_by=cur.applied_by, source=cur.source)
        snap.compiled["policy-engine:raw"] = raw
        snap.compiled["policy-engine:index"] = cur.compiled.get("policy-engine:index")
        return snap

    def effective_controls(self, profile: str | None = None) -> dict[str, ControlConfig]:
        if profile is None:
            return dict(self.snapshot().controls)
        return dict(self.snapshot_for_profile(profile).controls)

    # ------------------------------------------------------------ startup
    def _load_initial_sync(self) -> None:
        if self._snap is not None:
            return
        attempts: list[tuple[str, Path]] = [("file", self.policy_path), ("last_good", self.last_good_path),
                                            ("golden", self.golden_path)]
        file_errors: list[ValidationIssue] = []
        chosen: tuple[str, str, PolicySnapshot, Validated] | None = None
        profiles = self.load_profiles()
        for label, path in attempts:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                if label == "file":
                    file_errors = [ValidationIssue(message=f"cannot read {path}: {exc}")]
                continue
            snap, v, _ = self.build_candidate(text, version=0, source="startup", actor=None, profiles=profiles)
            if snap is not None:
                chosen = (label, text, snap, v)
                break
            if label == "file":
                file_errors = v.errors
        if chosen is None:
            doc = PolicyDoc()
            snap = PolicySnapshot(version=0, sha256=_sha(""), doc=doc, controls={}, source="startup")
            chosen = ("defaults", "", snap, Validated(doc=doc, raw={}))
        label, text, snap, v = chosen
        self._loaded_from = label
        # versioning: reuse the newest row if it is the same text
        try:
            latest = self.versions.latest()
            if latest and latest.get("sha256") == snap.sha256:
                version = int(latest["version"])
            else:
                version = self.versions.max_version() + 1
                self.versions.insert({"version": version, "sha256": snap.sha256, "yaml": text,
                                      "applied_at": _now_iso(), "applied_by": None, "source": "startup",
                                      "reason": f"startup ({label})", "changes_json": "[]",
                                      "summary": f"loaded from {label}"})
        except Exception:
            log.exception("policy version bookkeeping failed")
            version = 1
        snap.version = version
        self._snap = snap
        self._text = text
        if label in ("file", "golden") and text:
            try:
                _atomic_write(self.last_good_path, text)
            except OSError:
                log.warning("cannot write last_good.yaml path=%s", self.last_good_path)
        self._state = "ok" if label == "file" else "degraded"
        if label != "file":
            self._last_error = first_error_message(file_errors) or "policy file unavailable"
            msg = (f"policy file invalid ({self._last_error}); serving {label} policy v{version}")
            log.warning("policy startup fallback source=%s error=%s", label, self._last_error)
            self._pending.append(("policy.rejected", {"source": "startup",
                                                      "errors": [e.model_dump(mode="json") for e in file_errors],
                                                      "kept_version": version},
                                  {"sha256_attempted": None}))
            self._pending.append(("system", {"level": "warning", "message": msg, "component": "policy"}, None))
        self._set_gauge(version)
        log.info("policy loaded version=%s source=%s controls=%d profile=%s", version, label,
                 len(snap.controls), snap.doc.profile)

    async def start(self) -> None:
        self.versions.ensure()
        await self._refresh_org_ids()
        if self._snap is None:
            self._load_initial_sync()
        self._started = True
        pending, self._pending = self._pending, []
        for event, data, extra in pending:
            self._publish(event, data)
            if event == "policy.rejected":
                await self._audit("policy.rejected", actor=None, version=data.get("kept_version"),
                                  reason="startup fallback", data={**data, **(extra or {})})
        snap = self._snap
        assert snap is not None
        for cb in list(self._callbacks):
            await self._call(cb, snap)

    async def stop(self) -> None:
        w = self.watcher
        if w is not None:
            with contextlib.suppress(Exception):
                await w.stop()
        for t in list(self._bg):
            t.cancel()
        self._bg.clear()

    async def _refresh_org_ids(self) -> None:
        org = getattr(self.rt, "org", None)
        if org is None:
            return
        try:
            from aegis.core.nulls import is_null

            if is_null(org):
                return
        except Exception:
            pass
        try:
            teams = await org.list_teams()
            members = await org.list_members()
            agents = await org.list_agents()
            if not teams and not members:
                # org not started yet (policy starts first): unknown != empty -> skip id checks
                self._org_ids = None
                return
            self._org_ids = {"teams": {t.id for t in teams}, "members": {m.id for m in members},
                             "agents": {a.id for a in agents}}
        except Exception:
            self._org_ids = None

    async def _ensure_org_ids(self) -> None:
        if self._org_ids is None:
            await self._refresh_org_ids()

    # ------------------------------------------------------------ protocol: reads
    def snapshot(self) -> PolicySnapshot:
        if self._snap is None:
            self._load_initial_sync()
        assert self._snap is not None
        return self._snap

    def control_config(self, control_id: str) -> ControlConfig | None:
        return self.snapshot().controls.get(control_id)

    def current_yaml(self) -> str:
        self.snapshot()
        return self._text

    def history(self, limit: int = 50) -> list[PolicyVersionInfo]:
        self.snapshot()
        out: list[PolicyVersionInfo] = []
        for r in self.versions.history(limit):
            try:
                changes = json.loads(r.get("changes_json") or "[]")
            except ValueError:
                changes = []
            out.append(PolicyVersionInfo(version=r["version"], sha256=r["sha256"], applied_at=r["applied_at"],
                                         applied_by=r.get("applied_by"), source=r.get("source") or "startup",
                                         reason=r.get("reason"), changes_count=len(changes),
                                         summary=r.get("summary") or ""))
        return out

    def get_version_yaml(self, version: int) -> str | None:
        self.snapshot()
        return self.versions.get_yaml(version)

    def on_change(self, callback: Callable[[PolicySnapshot], Any]) -> None:
        self._callbacks.append(callback)
        if self._started and self._snap is not None:
            snap = self._snap
            try:
                res = callback(snap)
                if inspect.isawaitable(res):
                    try:
                        loop = asyncio.get_running_loop()
                        task = loop.create_task(res)  # type: ignore[arg-type]
                        self._bg.add(task)
                        task.add_done_callback(self._bg.discard)
                    except RuntimeError:
                        res.close()  # type: ignore[union-attr]
            except Exception:
                log.exception("policy on_change callback failed")

    def register_validator(self, fn: Callable[..., list[ValidationIssue]]) -> None:
        self._validators.append(fn)

    def status(self) -> dict[str, Any]:
        snap = self.snapshot()
        in_sync = None
        try:
            in_sync = _sha(self.policy_path.read_text(encoding="utf-8")) == snap.sha256
        except OSError:
            in_sync = False
        return {"state": self._state, "version": snap.version, "file_in_sync": in_sync,
                "last_error": self._last_error, "loaded_from": self._loaded_from, "profile": snap.doc.profile,
                "controls": len(snap.controls)}

    def health(self) -> str:
        if self._snap is None:
            return "ok"
        return "ok" if self._state == "ok" else "degraded"

    def last_selftest(self) -> SelfTestRun | None:
        return self._last_selftest

    # ------------------------------------------------------------ protocol: validate / diff
    def diff(self, yaml_text: str) -> list[PolicyChange]:
        cur = self.snapshot()
        v = validate_text(yaml_text, profiles=self._profiles or self.load_profiles(), org=self._org_ids)
        if not v.ok or v.doc is None:
            raise PolicyValidationError(v.errors)
        return diff_docs(cur.doc, v.doc)

    async def validate(self, yaml_text: str) -> ValidationReport:
        await self._ensure_org_ids()
        cur = self.snapshot()
        cand, v, _ = self.build_candidate(yaml_text, version=cur.version + 1, source="validate", actor=None)
        if cand is None:
            return ValidationReport(valid=False, errors=v.errors, warnings=v.warnings, selftest_passed=False)
        changes = diff_docs(cur.doc, cand.doc)
        gate_errors, gate_warnings, run = await self.gate(cand, cur, which="all", budget_s=VALIDATE_BUDGET_S)
        warnings = list(v.warnings) + gate_warnings
        return ValidationReport(valid=not gate_errors, errors=gate_errors, warnings=warnings,
                                selftest=run.results if run else [], selftest_passed=not gate_errors,
                                changes=changes, required_role=None)

    # ------------------------------------------------------------ self-test gate
    def _sandbox(self, snap: PolicySnapshot) -> PolicySnapshot:
        """Self-tests never see the live kill switch (KI-05): evaluate a copy with it released."""
        ks = snap.doc.budgets.kill_switch
        if not (ks.global_ or ks.teams or ks.members or ks.agents or ks.sessions):
            return snap
        budgets = snap.doc.budgets.model_copy(update={"kill_switch": type(ks)()})
        doc = snap.doc.model_copy(update={"budgets": budgets})
        sb = PolicySnapshot(version=snap.version, sha256=snap.sha256, doc=doc, controls=snap.controls,
                            applied_by=snap.applied_by, source=snap.source)
        return sb

    def _issue_for(self, snap: PolicySnapshot, oc: CaseOutcome, message: str, severity: str) -> ValidationIssue:
        line = col = None
        index = snap.compiled.get("policy-engine:index")
        if index is not None:
            with contextlib.suppress(Exception):
                line, col = index.locate(oc.case.loc)
        return ValidationIssue(path=oc.case.path, line=line, col=col, message=message, severity=severity)  # type: ignore[arg-type]

    def _baseline_from(self, outcomes: dict[tuple[str, str], CaseOutcome]) -> dict[tuple[str, str], BaselineEntry]:
        return {k: BaselineEntry(def_hash=o.case.def_hash, passed=o.result.passed, got_control=o.result.got_control)
                for k, o in outcomes.items()}

    async def ensure_baseline(self, cur: PolicySnapshot) -> None:
        if self._baseline_version == cur.version:
            return
        if not self.runner.pipeline_ready():
            return
        run, outcomes = await self.runner.run(self._sandbox(cur), which="gate", budget_s=GATE_BUDGET_S)
        self._baseline = {**self._baseline, **self._baseline_from(outcomes)}
        self._baseline_version = cur.version
        if self._last_selftest is None:
            self._last_selftest = run

    async def gate(self, cand: PolicySnapshot, cur: PolicySnapshot | None, *, which: str = "gate",
                   budget_s: float = GATE_BUDGET_S) -> tuple[list[ValidationIssue], list[ValidationIssue], SelfTestRun | None]:
        """(errors that reject the candidate, warnings, run). Never raises."""
        mode = str((cand.doc.defaults.model_extra or {}).get("selftest_gate") or "enforce")
        if mode == "off":
            return [], [], None
        if not self.runner.pipeline_ready():
            return [], [ValidationIssue(message="self-test skipped: pipeline unavailable", severity="warning")], None
        try:
            if cur is not None:
                await self.ensure_baseline(cur)
            run, outcomes = await self.runner.run(self._sandbox(cand), which=which, budget_s=budget_s)
        except Exception as exc:
            log.exception("self-test run failed")
            return [], [ValidationIssue(message=f"self-test failed to run: {exc}", severity="warning")], None
        errors: list[ValidationIssue] = []
        warnings: list[ValidationIssue] = []
        profile_changed = cur is not None and cand.doc.profile != cur.doc.profile
        for key, oc in outcomes.items():
            res = oc.result
            if res.passed:
                continue
            t = oc.case.test
            base = self._baseline.get(key)
            new_or_changed = base is None or base.def_hash != oc.case.def_hash
            # A deliberate (governed) profile switch changes expected outcomes wholesale: cases that
            # passed under the old profile are reported, not gating (otherwise `profile: permissive`
            # could never be applied). New / edited tests still gate.
            regress = new_or_changed or (base is not None and base.passed and not profile_changed)
            must = t.expect in MUST_PROTECT
            is_looser = looser(t.expect, res.got) or oc.upstream_failed
            deciding_off = False
            if not oc.case.control and base is not None and base.got_control:
                cfg = cand.controls.get(base.got_control)
                deciding_off = cfg is None or not cfg.enabled or cfg.mode == "off"
            label = case_label(oc.case)
            if oc.case.gate and must and is_looser and regress and not deciding_off and mode == "enforce":
                msg = (f"self-test {label}: expected {t.expect}, got {res.got} — update the test, or use "
                       "mode: monitor / enabled: false to loosen this control")
                if oc.detail and oc.upstream_failed:
                    msg += f" ({oc.detail})"
                errors.append(self._issue_for(cand, oc, msg, "error"))
            else:
                why = ("profile change" if profile_changed and not new_or_changed else "pre-existing failure") if not regress else ("stricter than expected" if not is_looser else
                                                                  "would reject (selftest_gate: warn)" if mode == "warn" else "")
                if not oc.case.gate:
                    why = "semantic test (never gates)"
                msg = f"self-test {label}: expected {t.expect}, got {res.got}" + (f" — {why}" if why else "")
                warnings.append(self._issue_for(cand, oc, msg, "warning"))
        run.gate_failures = errors
        self._gate_outcomes = (cand.sha256, outcomes)
        return errors, warnings, run

    async def run_selftest(self, snap: PolicySnapshot | None = None, *, which: str = "all",
                           profile: str | None = None) -> SelfTestRun:
        snap = snap or (self.snapshot_for_profile(profile) if profile else self.snapshot())
        run, outcomes = await self.runner.run(self._sandbox(snap), which=which, budget_s=VALIDATE_BUDGET_S)
        cur = self.snapshot()
        if snap.version == cur.version and snap.doc.profile == cur.doc.profile and which in ("all", "gate"):
            self._baseline = {**self._baseline, **self._baseline_from({k: o for k, o in outcomes.items() if o.case.gate})}
            self._baseline_version = cur.version
        if snap is cur or (snap.version == cur.version and snap.doc.profile == cur.doc.profile):
            self._last_selftest = run
        return run

    async def startup_selftest(self) -> None:
        """Background: establish the regression baseline + warn about semantic failures. Never rejects."""
        try:
            await asyncio.sleep(0)
            run = await self.run_selftest(which="all")
            if run.failed:
                self._publish("system", {"level": "warning", "component": "policy",
                                         "message": f"policy self-test v{run.version}: {run.failed} failing "
                                                    f"test(s) ({', '.join(list(run.details)[:3])})"})
            log.info("policy startup self-test version=%s passed=%d failed=%d skipped=%d ms=%.0f",
                     run.version, run.passed, run.failed, len(run.skipped), run.latency_ms)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("startup self-test failed")

    async def _async_selftests(self, snap: PolicySnapshot) -> None:
        try:
            run, _ = await self.runner.run(self._sandbox(snap), which="async", budget_s=VALIDATE_BUDGET_S)
            if self._last_selftest is not None and self._last_selftest.version == snap.version:
                self._last_selftest.results.extend(run.results)
                self._last_selftest.passed += run.passed
                self._last_selftest.failed += run.failed
                self._last_selftest.details.update(run.details)
            if run.failed:
                self._publish("system", {"level": "warning", "component": "policy",
                                         "message": f"v{snap.version}: {run.failed} semantic self-test(s) failing "
                                                    f"({', '.join(list(run.details)[:3])})"})
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("async self-tests failed")

    def _spawn(self, coro: Any) -> None:
        try:
            task = asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            coro.close()
            return
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    # ------------------------------------------------------------ bus / audit / metrics
    def _publish(self, event: str, data: dict[str, Any]) -> None:
        bus = getattr(self.rt, "bus", None)
        if bus is None:
            return
        try:
            bus.publish(event, data)
        except Exception:
            log.exception("bus publish failed event=%s", event)

    async def _audit(self, event_type: str, *, actor: Identity | None, version: int | None, reason: str | None,
                     data: dict[str, Any]) -> None:
        audit = getattr(self.rt, "audit", None)
        if audit is None:
            return
        try:
            ev = AuditEvent(event_id=new_id("evt"), event_type=event_type, actor=actor,  # type: ignore[arg-type]
                            policy_version=version, reason=reason, data=data)
            res = audit.record(ev)
            if inspect.isawaitable(res):
                await res
        except Exception:
            log.exception("audit record failed event=%s", event_type)

    def _set_gauge(self, version: int) -> None:
        m = getattr(self.rt, "metrics", None)
        if m is None:
            return
        with contextlib.suppress(Exception):
            m.set_gauge("aegis_policy_version", float(version))

    def _inc(self, result: str) -> None:
        m = getattr(self.rt, "metrics", None)
        if m is None:
            return
        with contextlib.suppress(Exception):
            m.inc("aegis_policy_reloads_total", {"result": result})

    def _mask(self, line: str) -> str:
        red = getattr(self.rt, "redactor", None)
        fn = getattr(red, "mask_for_log", None)
        if callable(fn):
            try:
                return str(fn(line, 400))
            except Exception:
                pass
        import re

        return re.sub(r"\d", "#", line)[:400]

    def _masked_diff(self, old: str, new: str, old_v: int, new_v: int) -> str:
        diff = unified_diff(old, new, f"policy v{old_v}", f"policy v{new_v}")
        out: list[str] = []
        size = 0
        for line in diff.splitlines():
            ml = self._mask(line)
            size += len(ml) + 1
            if size > DIFF_CAP:
                out.append("… (diff truncated)")
                break
            out.append(ml)
        return "\n".join(out)

    async def publish_rejected(self, source: str, errors: list[ValidationIssue], sha: str | None,
                               *, proposal_id: str | None = None) -> None:
        cur = self.snapshot()
        data = {"source": source, "errors": [e.model_dump(mode="json") for e in errors], "kept_version": cur.version}
        self._publish("policy.rejected", data)
        self._inc("rejected")
        await self._audit("policy.rejected", actor=None, version=cur.version, reason=first_error_message(errors),
                          data={**data, "sha256_attempted": sha, "proposal_id": proposal_id})
        log.info("policy rejected source=%s errors=%d kept_version=%s", source, len(errors), cur.version)

    def rejected_result(self, errors: list[ValidationIssue], kept: int, latency_ms: float = 0.0) -> ApplyResult:
        first = first_error_message(errors)
        more = f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""
        return ApplyResult(status="rejected", version=kept, previous_version=kept, errors=errors,
                           latency_ms=round(latency_ms, 1),
                           message=f"Rejected: still on v{kept}, {first}{more}" if first else f"Rejected: still on v{kept}")

    async def _call(self, cb: Callable[[PolicySnapshot], Any], snap: PolicySnapshot) -> None:
        try:
            res = cb(snap)
            if inspect.isawaitable(res):
                await res
        except Exception:
            log.exception("policy on_change callback failed cb=%s", getattr(cb, "__qualname__", cb))

    # ------------------------------------------------------------ protocol: apply
    async def apply_yaml(self, yaml_text: str, *, actor: Identity | None, source: str, reason: str | None = None,
                         base_version: int | None = None, _proposal_id: str | None = None,
                         _approval_id: str | None = None) -> ApplyResult:
        await self._ensure_org_ids()
        t0 = time.perf_counter()
        async with self._lk():
            cur = self.snapshot()
            if base_version is not None and base_version != cur.version:
                return ApplyResult(status="conflict", version=cur.version, previous_version=cur.version,
                                   message=f"policy is at v{cur.version}, you edited v{base_version}")
            sha = _sha(yaml_text)
            profiles = self.load_profiles()
            if sha == cur.sha256 and profiles.sha256 == cur.compiled.get("policy-engine:profiles_sha"):
                self._inc("noop")
                return ApplyResult(status="noop", version=cur.version, previous_version=cur.version,
                                   latency_ms=round((time.perf_counter() - t0) * 1000, 1), message="no changes")
            next_v = max(self.versions.max_version(), cur.version) + 1
            cand, v, _ = self.build_candidate(yaml_text, version=next_v, source=source, actor=actor, profiles=profiles)
            if cand is None:
                await self.publish_rejected(source, v.errors, sha, proposal_id=_proposal_id)
                return self.rejected_result(v.errors, cur.version, (time.perf_counter() - t0) * 1000)
            gate_errors: list[ValidationIssue] = []
            gate_warnings: list[ValidationIssue] = []
            run: SelfTestRun | None = None
            if source != "startup":
                gate_errors, gate_warnings, run = await self.gate(cand, cur)
            if gate_errors:
                await self.publish_rejected(source, gate_errors, sha, proposal_id=_proposal_id)
                return self.rejected_result(gate_errors, cur.version, (time.perf_counter() - t0) * 1000)
            changes = diff_docs(cur.doc, cand.doc)
            eff_changes = diff_effective(cur, cand)
            old_text = self._text
            # ---- atomic swap
            self._snap = cand
            self._text = yaml_text
            self._state = "ok"
            self._last_error = None
            if run is not None:
                outs = self._gate_outcomes[1] if self._gate_outcomes and self._gate_outcomes[0] == sha else {}
                self._baseline = {**self._baseline, **self._baseline_from(outs)}
                self._baseline_version = cand.version
                self._last_selftest = run
            latency_ms = (time.perf_counter() - t0) * 1000
            summary = summarize(changes) if changes else (summarize(eff_changes) if eff_changes else "comments only")
            # ---- persist
            try:
                self.versions.insert({"version": cand.version, "sha256": sha, "yaml": yaml_text,
                                      "applied_at": cand.applied_at.isoformat(), "applied_by": _who(actor),
                                      "source": source, "reason": reason,
                                      "changes_json": json.dumps([c.model_dump(mode="json") for c in changes]),
                                      "summary": summary})
            except Exception:
                log.exception("policy_versions insert failed version=%s", cand.version)
            try:
                _atomic_write(self.last_good_path, yaml_text)
            except OSError:
                log.exception("last_good.yaml write failed")
            if source not in ("file", "startup"):
                try:
                    self._own_writes.add(sha)
                    _atomic_write(self.policy_path, yaml_text)
                except OSError:
                    log.exception("policy file write failed path=%s", self.policy_path)
        # ---- outside the lock: audit / bus / metrics / callbacks
        warnings = list(v.warnings) + gate_warnings
        st = {"passed": run.passed if run else 0, "failed": run.failed if run else 0,
              "skipped": len(run.skipped) if run else 0, "deferred": run.deferred if run else 0}
        audit_type = "policy.rollback" if source == "rollback" else "policy.applied"
        await self._audit(audit_type, actor=actor, version=cand.version, reason=reason, data={
            "version": cand.version, "previous_version": cur.version, "sha256": sha, "source": source,
            "profile": cand.doc.profile, "changes": [c.model_dump(mode="json") for c in changes],
            "effective_changes": [c.model_dump(mode="json") for c in eff_changes[:50]],
            "changes_count": len(changes), "selftest": st, "proposal_id": _proposal_id,
            "approval_id": _approval_id, "latency_ms": round(latency_ms, 1),
            "unified_diff": self._masked_diff(old_text, yaml_text, cur.version, cand.version),
        })
        self._publish("policy.applied", {
            "version": cand.version, "previous_version": cur.version, "source": source,
            "actor": actor.model_dump(mode="json") if actor else None,
            "changes": [c.model_dump(mode="json") for c in changes], "latency_ms": round(latency_ms, 1),
            "summary": summary, "profile": cand.doc.profile,
            "effective_changes": [c.model_dump(mode="json") for c in eff_changes[:20]],
            "warnings": [w.message for w in warnings[:10]],
        })
        if warnings:
            self._publish("system", {"level": "warning", "component": "policy",
                                     "message": f"policy v{cand.version}: {len(warnings)} warning(s) — {warnings[0].message}"})
        self._set_gauge(cand.version)
        self._inc("applied")
        log.info("policy applied version=%s source=%s changes=%d ms=%.1f", cand.version, source, len(changes), latency_ms)
        for cb in list(self._callbacks):
            await self._call(cb, cand)
        if not self.test_mode and self.runner.pipeline_ready():
            self._spawn(self._async_selftests(cand))
        return ApplyResult(status="applied", version=cand.version, previous_version=cur.version, changes=changes,
                           latency_ms=round(latency_ms, 1),
                           message=f"applied v{cand.version} in {latency_ms:.0f} ms · {summary}")

    async def apply_patch(self, patch: list[PatchOp], *, actor: Identity | None, source: str,
                          reason: str | None = None) -> ApplyResult:
        from aegis.policy.patch import PatchError, apply_patch_text

        cur = self.snapshot()
        try:
            text = apply_patch_text(self.current_yaml(), patch)
        except PatchError as exc:
            errs = [ValidationIssue(path=exc.path, message=exc.message)]
            await self.publish_rejected(source, errs, None)
            return self.rejected_result(errs, cur.version)
        return await self.apply_yaml(text, actor=actor, source=source, reason=reason)

    async def rollback(self, version: int, *, actor: Identity | None, reason: str | None = None) -> ApplyResult:
        cur = self.snapshot()
        text = self.get_version_yaml(version)
        if text is None:
            return ApplyResult(status="rejected", version=cur.version, message=f"unknown policy version v{version}",
                               errors=[ValidationIssue(message=f"unknown policy version v{version}")])
        return await self.apply_yaml(text, actor=actor, source="rollback", reason=reason or f"rollback to v{version}")

    async def propose(self, actor: Identity, *, yaml_text: str | None = None, patch: list[PatchOp] | None = None,
                      reason: str | None = None, base_version: int | None = None, source: str = "dashboard",
                      apply_source: str = "api") -> ApplyResult:
        await self._ensure_org_ids()
        from aegis.policy.governance import propose as _propose

        return await _propose(self, actor, yaml_text=yaml_text, patch=patch, reason=reason,
                              base_version=base_version, source=source, apply_source=apply_source)

    # ------------------------------------------------------------ file reload (watcher / endpoint)
    def is_own_write(self, sha: str) -> bool:
        return sha in self._own_writes

    async def reload_from_file(self, reason: str | None = None) -> ApplyResult:
        await self._ensure_org_ids()
        cur = self.snapshot()
        try:
            text = self.policy_path.read_text(encoding="utf-8")
        except OSError as exc:
            errs = [ValidationIssue(message=f"cannot read {self.policy_path.name}: {exc}")]
            await self.publish_rejected("file", errs, None)
            return self.rejected_result(errs, cur.version)
        return await self.apply_yaml(text, actor=None, source="file", reason=reason)


def create(rt: Any) -> PolicyStoreImpl:
    """Service factory (cheap, no I/O; the policy loads lazily on first snapshot())."""
    return PolicyStoreImpl(rt)


__all__ = ["PolicyStoreImpl", "PolicyValidationError", "VersionRepo", "create"]

"""Policy self-test: inline `tests:` -> Interactions -> dry-run pipeline -> control-scoped compare.

* Test set: top-level `tests` + every `controls[].tests` (attributed to that control when
  `test.control` is unset). Key = (control or "_top", name); def_hash = sha of canonical JSON.
* Skips: `profiles:` excludes the active profile; attributed control not configured / disabled /
  mode off / not implemented; multi-step (`steps`/`repeat`) or `skip:`; time budget exhausted.
* Sets: GATE = deterministic/stateful (or unattributed) cases, run before the swap (2.5 s budget,
  8 concurrent); ASYNC = semantic/hybrid cases, run after the swap, failures only warn.
* Compare: attributed -> that control's decision in `verdict.decisions` (any mode, so monitor
  controls are tested by their "would" action), else allow. Unattributed -> the strictest
  decision (any mode) excluding live-state controls (budgets, loops, kill switch).
  passed = got == expect, or expect allow and got log.
* `python -m aegis selftest [--profile P | --all-profiles] [--json PATH] [--policy PATH]`.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import random
import re
import string
import sys
import time
import zlib
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from aegis.core.policy_schema import (
    PolicySnapshot,
    PolicyTest,
    SelfTestResult,
    ValidationIssue,
)
from aegis.core.types import (
    ACTION_PRECEDENCE,
    Destination,
    Identity,
    Interaction,
    TextSegment,
    utcnow,
)
from aegis.policy import catalog

log = logging.getLogger(__name__)

MUST_PROTECT = {"redact", "require_approval", "block"}
#: controls whose verdict depends on live counters / kill switch: ignored for unattributed tests
VOLATILE = {"BUD-01", "BUD-02", "EXE-04"}
_IN_SURFACES = {"model.response", "tool.output", "mcp.result", "mcp.list", "egress.response", "a2a.result"}
_TEXT_PATH: dict[str, tuple[str, str, bool]] = {
    "prompt.user": ("prompt", "user", True),
    "model.request": ("messages[0].content", "user", True),
    "model.response": ("content[0].text", "assistant", True),
    "tool.output": ("tool_response", "tool_result", False),
    "mcp.result": ("result.content[0].text", "tool_result", False),
    "mcp.list": ("result.tools[0].description", "tool_description", False),
    "egress.request": ("body", "other", True),
    "egress.response": ("body", "other", False),
    "a2a.message": ("message", "user", True),
    "a2a.result": ("result", "other", False),
    "tool.input": ("tool_input", "tool_args", True),
    "mcp.call": ("params.arguments", "tool_args", True),
}


class SelfTestRun(BaseModel):
    version: int = 0
    profile: str = "balanced"
    ran_at: Any = Field(default_factory=utcnow)
    which: str = "all"
    results: list[SelfTestResult] = Field(default_factory=list)
    skipped: list[dict[str, Any]] = Field(default_factory=list)
    deferred: int = 0
    passed: int = 0
    failed: int = 0
    gate_failures: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0
    details: dict[str, str] = Field(default_factory=dict)  # "<control>/<name>" -> why it failed


@dataclass
class Case:
    key: tuple[str, str]
    test: PolicyTest
    control: str | None
    def_hash: str
    loc: tuple[Any, ...]
    path: str
    gate: bool = True


@dataclass
class CaseOutcome:
    case: Case
    result: SelfTestResult
    detail: str = ""
    upstream_failed: bool = False


@dataclass
class BaselineEntry:
    def_hash: str
    passed: bool
    got_control: str | None = None


@dataclass
class _RunState:
    outcomes: dict[tuple[str, str], CaseOutcome] = field(default_factory=dict)


# ---------------------------------------------------------------- macros
def _rng(name: str) -> random.Random:
    return random.Random(zlib.crc32(name.encode("utf-8")))


def _gen(kind: str, seed: str) -> str:
    r = _rng(f"{kind}:{seed}")
    up32 = string.ascii_uppercase + "234567"
    alnum = string.ascii_letters + string.digits
    if kind == "aws_access_key_id":
        return "AKIA" + "".join(r.choice(up32) for _ in range(16))
    if kind == "aws_secret_access_key":
        return "".join(r.choice(alnum + "/+") for _ in range(40))
    if kind == "github_pat":
        return "ghp_" + "".join(r.choice(alnum) for _ in range(36))
    if kind == "slack_token":
        return "xoxb-" + "".join(r.choice(string.digits) for _ in range(12)) + "-" + "".join(
            r.choice(string.digits) for _ in range(13)) + "-" + "".join(r.choice(alnum) for _ in range(24))
    if kind == "jwt":
        def b64u(b: bytes) -> str:
            return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
        head = b64u(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        body = b64u(json.dumps({"sub": f"u{r.randint(1000, 9999)}", "iat": 1759500000}).encode())
        return f"{head}.{body}.{b64u(bytes(r.getrandbits(8) for _ in range(32)))}"
    if kind == "openssh_private_key":
        raw = bytes(r.getrandbits(8) for _ in range(180))
        b = base64.b64encode(raw).decode()
        lines = [b[i : i + 70] for i in range(0, len(b), 70)]
        return "-----BEGIN OPENSSH PRIVATE KEY-----\n" + "\n".join(lines) + "\n-----END OPENSSH PRIVATE KEY-----"
    return "{{gen:" + kind + "}}"


_MACRO = re.compile(r"\{\{(gen|b64|b64url|tags|zw):(.*?)\}\}", re.S)


def expand_macros(value: str, seed: str = "") -> str:
    def sub(m: re.Match[str]) -> str:
        kind, arg = m.group(1), m.group(2)
        if kind == "gen":
            return _gen(arg.strip(), seed)
        if kind == "b64":
            return base64.b64encode(arg.encode("utf-8")).decode()
        if kind == "b64url":
            return base64.urlsafe_b64encode(arg.encode("utf-8")).rstrip(b"=").decode()
        if kind == "tags":
            return "".join(chr(0xE0000 + ord(c)) if ord(c) < 0x80 else c for c in arg)
        if kind == "zw":
            return "‍".join(arg)
        return m.group(0)

    return _MACRO.sub(sub, value) if "{{" in value else value


def _expand_tree(obj: Any, seed: str) -> Any:
    if isinstance(obj, str):
        return expand_macros(obj, seed)
    if isinstance(obj, dict):
        return {k: _expand_tree(v, seed) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_tree(v, seed) for v in obj]
    return obj


def _string_leaves(obj: Any, prefix: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if isinstance(obj, str):
        out.append((prefix, obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(_string_leaves(v, f"{prefix}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(_string_leaves(v, f"{prefix}[{i}]"))
    return out


# ---------------------------------------------------------------- collection
def _def_hash(t: PolicyTest, control: str | None) -> str:
    data = t.model_dump(mode="json", by_alias=True)
    data["_attributed"] = control
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:16]


def collect(snap: PolicySnapshot) -> list[Case]:
    doc = snap.doc
    cases: list[Case] = []
    for ti, t in enumerate(doc.tests):
        cases.append(Case(key=(t.control or "_top", t.name), test=t, control=t.control,
                          def_hash=_def_hash(t, t.control), loc=("tests", ti),
                          path=f"tests[name={t.name}]"))
    for ci, c in enumerate(doc.controls):
        for ti, t in enumerate(c.tests):
            ctl = t.control or c.id
            cases.append(Case(key=(ctl, t.name), test=t, control=ctl, def_hash=_def_hash(t, ctl),
                              loc=("controls", ci, "tests", ti),
                              path=f"controls[id={c.id}].tests[name={t.name}]"))
    return cases


def case_label(case: Case) -> str:
    return f"{case.control or 'pipeline'}/{case.test.name}"


# ---------------------------------------------------------------- runner
class SelfTestRunner:
    def __init__(self, rt: Any):
        self.rt = rt
        self._ident_cache: dict[str, Identity] = {}

    # -------------------------------------------------------------- helpers
    def pipeline_ready(self) -> bool:
        p = getattr(self.rt, "pipeline", None)
        return p is not None and callable(getattr(p, "evaluate", None)) and callable(getattr(p, "new_context", None))

    def _registry_kind(self, cid: str) -> str:
        reg = getattr(self.rt, "controls", None)
        ctl = None
        try:
            ctl = reg.get(cid) if reg is not None else None
        except Exception:
            ctl = None
        return str(getattr(ctl, "kind", None) or catalog.kind_of(cid))

    def implemented(self, cid: str) -> bool:
        reg = getattr(self.rt, "controls", None)
        if reg is None:
            return False
        try:
            return reg.get(cid) is not None
        except Exception:
            return False

    def skip_reason(self, case: Case, snap: PolicySnapshot) -> str | None:
        t = case.test
        extra = t.model_extra or {}
        profiles = extra.get("profiles")
        if profiles and snap.doc.profile not in profiles:
            return f"not run under profile {snap.doc.profile}"
        if extra.get("skip"):
            return f"skip: {extra.get('skip')}"
        if extra.get("steps") or extra.get("repeat"):
            return "multi-step test (covered by the e2e suite)"
        if case.control:
            cfg = snap.controls.get(case.control)
            if cfg is None:
                return f"{case.control} not configured"
            if not cfg.enabled:
                return f"{case.control} disabled"
            if cfg.mode == "off":
                return f"{case.control} mode off"
            if not self.implemented(case.control):
                return f"{case.control} not implemented in this build"
        return None

    def is_gate(self, case: Case) -> bool:
        if not case.control:
            return True
        return self._registry_kind(case.control) in ("deterministic", "stateful")

    async def _identity(self, t: PolicyTest) -> Identity:
        extra = t.model_extra or {}
        member = extra.get("member")
        agent = t.agent or ("selftest" if not member else None)
        key = f"m:{member}" if member else f"a:{agent}"
        if key in self._ident_cache:
            return self._ident_cache[key]
        org = getattr(self.rt, "org", None)
        ident: Identity
        try:
            if member:
                m = await org.get_member(member) if org is not None else None
                ident = Identity(org_id=m.org_id, team_id=m.team_id, member_id=m.id, role=m.role,
                                 display_name=m.name, authenticated=True) if m else Identity(
                    member_id=member, role="member", authenticated=True)
            else:
                a = await org.get_agent(agent) if org is not None and agent else None
                ident = Identity(org_id=a.org_id, team_id=a.team_id, agent_id=a.id,
                                 member_id=a.owner_member_id, role="agent", authenticated=True,
                                 display_name=a.name) if a else Identity(agent_id=agent, role="agent")
        except Exception:
            ident = Identity(member_id=member, role="member") if member else Identity(agent_id=agent, role="agent")
        self._ident_cache[key] = ident
        return ident

    def build_interaction(self, t: PolicyTest, seed: str) -> Interaction:
        extra = dict(t.model_extra or {})
        kind, surface = t.kind, t.surface
        if kind == "model_call":
            if surface.startswith("egress."):
                kind = "egress"
            elif surface.startswith("mcp."):
                kind = "mcp"
            elif surface.startswith("tool."):
                kind = "tool_call"
            elif surface == "config.change":
                kind = "config_change"
        direction = extra.get("direction") or ("in" if surface in _IN_SURFACES else "out")
        dest = Destination(name=f"selftest:{t.destination}", dest_class=t.destination)
        tool_args = _expand_tree(t.tool_args, seed) if t.tool_args is not None else None
        segments: list[TextSegment] = []
        if extra.get("segments"):
            for s in extra["segments"]:
                if isinstance(s, dict) and "text" in s:
                    seg = dict(s)
                    seg["text"] = expand_macros(str(seg["text"]), seed)
                    seg.setdefault("path", "selftest")
                    segments.append(TextSegment.model_validate(seg))
        elif t.text is not None and surface != "config.change":
            path, role, trusted = _TEXT_PATH.get(surface, ("text", "user", True))
            segments.append(TextSegment(path=path, text=expand_macros(t.text, seed),
                                        role=extra.get("role", role), trusted=extra.get("trusted", trusted)))
        if tool_args:
            for p, v in _string_leaves(tool_args, "tool_args"):
                segments.append(TextSegment(path=p, text=v, role="tool_args",
                                            trusted=bool(extra.get("trusted", True))))
        meta = dict(extra.get("meta") or {})
        if "changes" in extra:
            meta["changes"] = list(extra.get("changes") or [])
        model = extra.get("model")
        if model is None and kind == "model_call":
            model = "aegis-judge" if t.destination == "local" else "mock-echo"
        mcp_server = extra.get("mcp_server")
        if kind == "mcp" and not mcp_server and t.tool_name and "." in t.tool_name:
            mcp_server = t.tool_name.split(".", 1)[0]
        url = extra.get("url")
        resource = extra.get("resource")
        if kind == "config_change" and resource is None:
            resource = f"policy:selftest-{t.name}"
        inter = Interaction(
            kind=kind,  # type: ignore[arg-type]
            surface=surface,
            direction=direction,
            destination=dest,
            model=model,
            tool_name=t.tool_name,
            tool_args=tool_args,
            mcp_server=mcp_server,
            mcp_method=extra.get("mcp_method") or ("tools/call" if surface == "mcp.call" else None),
            http_method=extra.get("http_method"),
            url=expand_macros(url, seed) if isinstance(url, str) else None,
            segments=segments,
            raw=extra.get("raw"),
            action_type=extra.get("action_type"),
            amount_usd=t.amount_usd,
            resource=resource,
            labels={str(k): str(v) for k, v in (extra.get("labels") or {}).items()},
            meta=meta,
        )
        if surface == "model.request":
            inter.est_input_tokens = max(1, len(inter.text()) // 4)
        if extra.get("max_output_tokens"):
            inter.max_output_tokens = int(extra["max_output_tokens"])
        if url and dest.host is None:
            m = re.match(r"^[a-z]+://([^/:?#]+)", str(inter.url or ""))
            if m:
                inter.destination.host = m.group(1)
        return inter

    # -------------------------------------------------------------- one case
    async def _run_case(self, case: Case, snap: PolicySnapshot, run_id: str, idx: int) -> CaseOutcome:
        t = case.test
        t0 = time.perf_counter()
        seed = f"{case.key[0]}/{t.name}"
        try:
            ident = await self._identity(t)
            inter = self.build_interaction(t, seed)
            ctx = self.rt.pipeline.new_context(source="selftest", identity=ident,
                                               session_id=f"ses_selftest_{run_id}_{idx}", dry_run=True)
            verdict = await self.rt.pipeline.evaluate(ctx, inter, policy=snap, dry_run=True)
        except Exception as exc:
            ms = (time.perf_counter() - t0) * 1000
            res = SelfTestResult(name=t.name, control=case.control, expect=t.expect, got="allow",
                                 passed=False, latency_ms=round(ms, 2))
            return CaseOutcome(case, res, detail=f"evaluation error: {type(exc).__name__}: {exc}"[:300])
        ms = (time.perf_counter() - t0) * 1000
        decisions = list(getattr(verdict, "decisions", []) or [])
        if case.control:
            d = next((x for x in decisions if x.control_id == case.control and x.action != "allow"), None)
            d = d or next((x for x in decisions if x.control_id == case.control), None)
            got = d.action if d else "allow"
            got_control = case.control if (d and d.action != "allow") else (
                verdict.primary.control_id if getattr(verdict, "primary", None) else None)
        else:
            relevant = [x for x in decisions if x.control_id not in VOLATILE]
            best = max(relevant, key=lambda x: ACTION_PRECEDENCE.get(x.action, 0), default=None)
            got = best.action if best else "allow"
            got_control = best.control_id if best and best.action != "allow" else None
        passed = got == t.expect or (t.expect == "allow" and got == "log")
        detail = ""
        upstream_failed = False
        extra = t.model_extra or {}
        must = extra.get("upstream_must_contain") or []
        must_not = extra.get("upstream_must_not_contain") or []
        if must or must_not:
            sent = "\n".join(s.text for s in (getattr(verdict, "segments", None) or inter.segments))
            missing = [s for s in must if s not in sent]
            leaked = [s for s in must_not if expand_macros(str(s), seed) in sent]
            if missing or leaked:
                upstream_failed = True
                passed = False
                detail = (f"upstream missing {missing}" if missing else "") + (
                    f" upstream leaked {len(leaked)} value(s)" if leaked else "")
        route_expect = extra.get("expect_route")
        if route_expect and got == "require_approval":
            try:
                route = self.rt.approvals.route(
                    kind="action", action_type=inter.action_type or (inter.tool_name or "unknown"),
                    requester=ident, amount_usd=inter.amount_usd, resource=inter.resource,
                    labels=inter.labels)
                got_route = route.required_role + ("+admin" if route.two_person and route.required_role == "owner" else "")
                if str(route_expect) not in (route.required_role, got_route):
                    passed = False
                    detail = f"route {got_route}, expected {route_expect}"
            except Exception as exc:
                detail = f"route check skipped: {type(exc).__name__}"
        if not passed and not detail:
            reason = ""
            if case.control:
                dd = next((x for x in decisions if x.control_id == case.control), None)
                reason = (dd.reason if dd else "") or ""
            detail = f"expected {t.expect}, got {got}" + (f" ({reason[:120]})" if reason else "")
        res = SelfTestResult(name=t.name, control=case.control, expect=t.expect, got=got,
                             got_control=got_control, passed=passed, latency_ms=round(ms, 2))
        return CaseOutcome(case, res, detail=detail, upstream_failed=upstream_failed)

    # -------------------------------------------------------------- run
    async def run(
        self,
        snap: PolicySnapshot,
        *,
        which: str = "all",
        budget_s: float = 2.5,
        concurrency: int = 8,
    ) -> tuple[SelfTestRun, dict[tuple[str, str], CaseOutcome]]:
        t0 = time.perf_counter()
        run = SelfTestRun(version=snap.version, profile=snap.doc.profile, which=which)
        outcomes: dict[tuple[str, str], CaseOutcome] = {}
        if not self.pipeline_ready():
            run.warnings.append("self-test skipped: pipeline unavailable")
            for c in collect(snap):
                run.skipped.append({"name": c.test.name, "control": c.control, "reason": "pipeline unavailable"})
            return run, outcomes
        selected: list[Case] = []
        for c in collect(snap):
            reason = self.skip_reason(c, snap)
            if reason:
                run.skipped.append({"name": c.test.name, "control": c.control, "reason": reason})
                continue
            c.gate = self.is_gate(c)
            if which == "gate" and not c.gate:
                run.deferred += 1
                continue
            if which == "async" and c.gate:
                continue
            selected.append(c)
        sem = asyncio.Semaphore(max(1, concurrency))
        run_id = f"{snap.version}_{int(time.time() * 1000) % 100000}"

        async def one(i: int, c: Case) -> CaseOutcome:
            async with sem:
                return await self._run_case(c, snap, run_id, i)

        tasks = [asyncio.ensure_future(one(i, c)) for i, c in enumerate(selected)]
        if tasks:
            _done, pending = await asyncio.wait(tasks, timeout=budget_s)
            for p in pending:
                p.cancel()
            for task, c in zip(tasks, selected, strict=True):
                if task in pending or task.cancelled():
                    run.skipped.append({"name": c.test.name, "control": c.control, "reason": "time budget exhausted"})
                    continue
                exc = task.exception()
                if exc is not None:
                    run.skipped.append({"name": c.test.name, "control": c.control, "reason": f"error: {exc}"[:200]})
                    continue
                oc = task.result()
                outcomes[c.key] = oc
                run.results.append(oc.result)
                if oc.result.passed:
                    run.passed += 1
                else:
                    run.failed += 1
                    run.details[case_label(c)] = oc.detail
        run.latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return run, outcomes


def looser(expect: str, got: str) -> bool:
    return ACTION_PRECEDENCE.get(got, 0) < ACTION_PRECEDENCE.get(expect, 0)


# ---------------------------------------------------------------- CLI
def _print_table(runs: list[SelfTestRun]) -> None:
    try:
        from rich.console import Console
        from rich.table import Table
    except Exception:  # pragma: no cover
        for r in runs:
            print(f"profile={r.profile} v{r.version}: {r.passed} passed, {r.failed} failed, "
                  f"{len(r.skipped)} skipped, gate failures {len(r.gate_failures)} ({r.latency_ms} ms)")
        return
    con = Console()
    for r in runs:
        tab = Table(title=f"Aegis policy self-test · profile {r.profile} · v{r.version}", show_lines=False)
        for col in ("test", "control", "expect", "got", "result"):
            tab.add_column(col)
        for res in sorted(r.results, key=lambda x: (x.passed, x.control or "", x.name)):
            mark = "[green]PASS[/green]" if res.passed else "[red]FAIL[/red]"
            tab.add_row(res.name, res.control or "pipeline", res.expect, res.got, mark)
        con.print(tab)
        con.print(f"[bold]{r.passed} passed[/bold], {r.failed} failed, {len(r.skipped)} skipped, "
                  f"gate failures: {len(r.gate_failures)}, {r.latency_ms} ms")
        for k, v in r.details.items():
            con.print(f"  [yellow]{k}[/yellow]: {v}")


def main(argv: list[str] | None = None) -> int:
    """`python -m aegis selftest [--profile P | --all-profiles] [--json PATH] [--policy PATH]`."""
    import argparse
    import os
    from pathlib import Path

    ap = argparse.ArgumentParser(prog="aegis selftest", description="Run the policy's inline tests")
    ap.add_argument("--profile", default=None)
    ap.add_argument("--all-profiles", action="store_true")
    ap.add_argument("--json", dest="json_path", default=None)
    ap.add_argument("--policy", default=None)
    ap.add_argument("--which", default="all", choices=["all", "gate", "async"])
    ap.add_argument("--strict", action="store_true", help="exit 1 on any failing must-protect test")
    args = ap.parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.policy:
        os.environ["AEGIS_POLICY"] = str(Path(args.policy).resolve())
    os.environ.setdefault("AEGIS_TEST_MODE", "1")
    os.environ.setdefault("AEGIS_SEMANTIC", "off")
    os.environ.setdefault("AEGIS_FEED_URL", "disabled")
    if "AEGIS_DATA_DIR" not in os.environ:
        import tempfile

        os.environ["AEGIS_DATA_DIR"] = tempfile.mkdtemp(prefix="aegis-selftest-")
    logging.basicConfig(level=logging.WARNING)
    return asyncio.run(_main_async(args))


async def _main_async(args: Any) -> int:
    from aegis.app import create_app

    try:
        from asgi_lifespan import LifespanManager
    except Exception:  # pragma: no cover
        LifespanManager = None  # type: ignore[assignment]
    from aegis.settings import Settings

    app = create_app(Settings.from_env())
    runs: list[SelfTestRun] = []

    async def go() -> None:
        rt = app.state.rt
        store = getattr(rt, "policy", None)
        if rt is None or store is None:
            print("aegis selftest: runtime unavailable", file=sys.stderr)
            return
        base = store.snapshot()
        profiles = ["permissive", "balanced", "strict", "paranoid"] if args.all_profiles else (
            [args.profile] if args.profile else [base.doc.profile])
        for prof in profiles:
            snap = base if prof == base.doc.profile else _with_profile(store, base, prof)
            run = await store.run_selftest(snap, which=args.which) if hasattr(store, "run_selftest") else None
            if run is not None:
                runs.append(run)

    if LifespanManager is not None:
        async with LifespanManager(app):
            await go()
    else:  # pragma: no cover
        await go()
    _print_table(runs)
    if args.json_path:
        _write_json(args.json_path, [r.model_dump(mode="json") for r in runs])
    if args.strict:  # any failing must-protect deterministic case
        return 1 if any(not r.passed and r.expect in MUST_PROTECT for run in runs for r in run.results) else 0
    return 1 if any(r.gate_failures for r in runs) else 0


def _write_json(path: str, data: Any) -> None:
    from pathlib import Path

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _with_profile(store: Any, base: PolicySnapshot, profile: str) -> PolicySnapshot:
    build = getattr(store, "snapshot_for_profile", None)
    if callable(build):
        return build(profile)
    return base

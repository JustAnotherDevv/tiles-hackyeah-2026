"""Execute a `Case` through its `via` and return a normalized `Observation` (plan 18 §2.5)."""

from __future__ import annotations

import copy
import json
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tests.lib import macros, privacy
from tests.lib.cases import Case
from tests.lib.client import KIND_BY_SURFACE
from tests.lib.identities import OWNER
from tests.lib.mcp_client import McpClient

HOOK_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "hooks"
_CTRL = re.compile(r"\b([A-Z]{2,3}-\d{2})\b")


@dataclass
class Observation:
    action: str | None = None
    control: str | None = None  # primary
    decisions: list[dict[str, Any]] = field(default_factory=list)  # enforce + monitor decisions
    entities: list[str] = field(default_factory=list)
    redaction_controls: list[str] = field(default_factory=list)
    mutations: int = 0
    status: int | None = None
    error_type: str | None = None
    jsonrpc_code: int | None = None
    decision_id: str | None = None
    approval_id: str | None = None
    route: dict[str, Any] | None = None
    text_out: str | None = None  # redacted outbound text (guard) / upstream request text (proxies)
    response_text: str | None = None
    upstream_texts: list[str] = field(default_factory=list)
    upstream_calls: int | None = None
    sink_delta: int | None = None
    tools_listed: list[str] | None = None
    latency_ms: float | None = None
    reason: str = ""
    skip: str | None = None
    raw: Any = None

    def controls_with(self, actions: set[str], mode: str = "enforce") -> list[str]:
        return [
            d.get("control_id")
            for d in self.decisions
            if d.get("action") in actions and (d.get("mode") or "enforce") == mode
        ]


def _session(case: Case) -> str:
    return f"t-{case.id.lower()}-{secrets.token_hex(2)}"


def _interaction(case: Case, step: dict[str, Any] | None = None) -> dict[str, Any]:
    s = {**case.model_dump(by_alias=False, exclude_none=True), **(step or {})}
    surface = s.get("surface") or ("tool.input" if s.get("tool") else "model.request")
    i: dict[str, Any] = {
        "surface": surface,
        "kind": s.get("kind") or KIND_BY_SURFACE.get(surface, "model_call"),
    }
    dest = s.get("dest")
    if dest:
        i["destination"] = dest
    elif surface.startswith("mcp.") or surface.startswith("egress."):
        i["destination"] = "third_party"
    elif surface.startswith("tool."):
        i["destination"] = "local"
    else:
        i["destination"] = "remote"
    if s.get("input") is not None:
        i["text"] = macros.expand(s["input"])
    if s.get("segments"):
        i["segments"] = macros.expand_obj(s["segments"])
    if s.get("tool"):
        i["tool_name"] = s["tool"]
        if surface.startswith("mcp.") and "." in s["tool"]:
            i["mcp_server"] = s["tool"].split(".", 1)[0]
    if s.get("args") is not None:
        i["tool_args"] = macros.expand_obj(s["args"])
    if s.get("url"):
        i["url"] = macros.expand(s["url"])
        i["http_method"] = (s.get("method") or "GET").upper()
    for k in ("amount_usd", "model", "action_type", "resource"):
        if s.get(k) is not None:
            i[k] = s[k]
    if s.get("meta"):
        i["meta"] = macros.expand_obj(s["meta"])
    if s.get("labels"):
        i["labels"] = {k: str(v) for k, v in s["labels"].items()}
    _mcp_shapes(i)
    if i.get("amount_usd") is None and isinstance(i.get("tool_args"), dict):
        amt = i["tool_args"].get("amount_usd")
        if isinstance(amt, (int, float)):
            i["amount_usd"] = amt
    return i


def _mcp_shapes(i: dict[str, Any]) -> None:
    """Staging-style `mcp.list` args → contract interactions (A-12/A-13).

    - `{server, tools: [{name, description, ...}]}` → one `mcp.list` interaction for the first tool
      (`tool_name=<server>.<name>`, description as text, `meta.raw_result` = the definition)
    - `{server, transport, command|url}` → `mcp.init` with `tool_args.command` argv
    """
    args = i.get("tool_args")
    if i.get("surface") not in ("mcp.list", "mcp.init") or not isinstance(args, dict):
        return
    server = str(args.get("server") or "unknown")
    i["mcp_server"] = server
    tools = args.get("tools")
    if isinstance(tools, list) and tools:
        t = tools[0] if isinstance(tools[0], dict) else {"name": str(tools[0])}
        i["surface"], i["kind"] = "mcp.list", "mcp"
        i["tool_name"] = f"{server}.{t.get('name')}"
        i["text"] = str(t.get("description") or "")
        i["tool_args"] = None
        i["meta"] = {**(i.get("meta") or {}), "raw_result": t}
        i.pop("tool_args", None)
        return
    if args.get("command") or args.get("url"):
        import shlex

        i["surface"], i["kind"] = "mcp.init", "mcp"
        cmd = args.get("command")
        argv = shlex.split(cmd) if isinstance(cmd, str) else (cmd or [])
        i["tool_args"] = {"command": argv} if argv else {"url": args.get("url")}
        if args.get("url"):
            i["url"] = args["url"]
        i["meta"] = {
            **(i.get("meta") or {}),
            "mcp.command": argv,
            "mcp.transport": args.get("transport"),
        }


def _from_verdict(obs: Observation, v: dict[str, Any]) -> None:
    obs.action = v.get("action")
    prim = v.get("primary") or {}
    obs.control = prim.get("control_id")
    obs.reason = prim.get("reason") or ""
    obs.decisions = [
        {
            "control_id": d.get("control_id"),
            "action": d.get("action"),
            "mode": d.get("mode"),
            "reason": d.get("reason"),
            "mutations": len(d.get("mutations") or []),
            "findings": len(d.get("findings") or []),
        }
        for d in v.get("decisions") or []
    ]
    reds = v.get("redactions") or []
    obs.entities = sorted({r.get("entity") for r in reds if r.get("entity")})
    obs.redaction_controls = sorted({r.get("control_id") for r in reds if r.get("control_id")})
    obs.mutations = len(v.get("mutations") or []) + len(reds)
    obs.latency_ms = v.get("latency_ms")
    appr = v.get("approval") or {}
    obs.approval_id = appr.get("id") or prim.get("approval_id")


def _from_detail(obs: Observation, gw: Any, decision_id: str | None) -> None:
    det = gw.decision(decision_id) if decision_id else None
    if not det:
        return
    obs.control = obs.control or det.get("control_id")
    if not obs.decisions:
        obs.decisions = [
            {
                "control_id": d.get("control_id"),
                "action": d.get("action"),
                "mode": d.get("mode"),
                "reason": d.get("reason"),
                "mutations": len(d.get("mutations") or []),
            }
            for d in det.get("decisions") or []
        ]
    reds = det.get("redactions") or []
    obs.entities = sorted(
        set(obs.entities)
        | {r.get("entity") for r in reds if r.get("entity")}
        | set(det.get("entities") or [])
    )
    obs.redaction_controls = sorted(
        set(obs.redaction_controls) | {r.get("control_id") for r in reds if r.get("control_id")}
    )
    obs.mutations = max(
        obs.mutations,
        len(reds) + len(det.get("mutations") or []),
        int(det.get("redaction_count") or 0),
    )
    obs.reason = obs.reason or det.get("reason") or ""
    if obs.latency_ms is None:
        obs.latency_ms = det.get("latency_ms")


def _upstream_text(req: dict[str, Any]) -> str:
    return json.dumps(
        {"headers": req.get("headers") or {}, "body": req.get("body") or {}}, ensure_ascii=False
    )


def _complete(stack: Any, data: dict[str, Any], dry_run: bool) -> None:
    """Report the outcome of an allowed guard check (releases reservations, e.g. BUD-02 slots)."""
    v = data.get("verdict") or {}
    if dry_run or v.get("action") not in ("allow", "log", "redact"):
        return
    did = data.get("decision_id") or v.get("id")
    if did:
        stack.gw.request(
            "POST",
            "/v1/guard/complete",
            json={"decision_id": did, "status_code": 200, "usage": {"requests": 1}},
        )


def run_guard(case: Case, stack: Any, dry_run: bool = False) -> Observation:
    obs = Observation()
    session = _session(case)
    steps = case.steps or [None]
    reps = max(1, case.repeat)
    data: dict[str, Any] = {}
    for _ in range(reps):
        for step in steps:
            inter = _interaction(case, step)
            who = (step or {}).get("as") or case.as_
            r = stack.gw.guard(
                inter, who=who, session=session, dry_run=dry_run, headers=case.headers
            )
            obs.status = r.status_code
            if r.status_code != 200:
                obs.error_type = _err_type(r)
                obs.reason = r.text[:300]
                return obs
            data = r.json()
            _complete(stack, data, dry_run)
    v = data.get("verdict") or {}
    _from_verdict(obs, v)
    obs.decision_id = data.get("decision_id") or v.get("id")
    obs.text_out = data.get("text")
    if obs.text_out is None and data.get("segments"):
        obs.text_out = "\n".join(s.get("text", "") for s in data["segments"] if isinstance(s, dict))
    obs.raw = {"action": obs.action, "control": obs.control}
    return obs


def _err_type(r: Any) -> str | None:
    try:
        d = r.json()
    except ValueError:
        return None
    err = d.get("error") if isinstance(d, dict) else None
    if isinstance(err, dict):
        return err.get("type")
    if isinstance(d, dict) and isinstance(d.get("aegis"), dict):
        return d["aegis"].get("type")
    return None


def run_proxy(case: Case, stack: Any) -> Observation:
    obs = Observation()
    session = _session(case)
    stack.llm_clear()
    text = macros.expand(case.input or "")
    kw = {
        "model": case.model or "mock-echo",
        "who": case.as_,
        "session": session,
        "stream": case.stream,
        "headers": case.headers,
    }
    if case.max_tokens:
        kw["max_tokens"] = case.max_tokens
    t0 = time.perf_counter()
    r = (stack.gw.anthropic if case.via == "anthropic" else stack.gw.openai)(text, **kw)
    obs.latency_ms = (time.perf_counter() - t0) * 1000
    obs.status = r.status_code
    obs.action = r.headers.get("x-aegis-decision")
    obs.decision_id = r.headers.get("x-aegis-decision-id")
    if r.status_code >= 400:
        obs.error_type = _err_type(r)
    obs.response_text = r.text
    _from_detail(obs, stack.gw, obs.decision_id)
    resp_id = r.headers.get("x-aegis-response-decision-id")
    if resp_id and resp_id != obs.decision_id:
        det = stack.gw.decision(resp_id) or {}
        for d in det.get("decisions") or []:
            obs.decisions.append(
                {
                    "control_id": d.get("control_id"),
                    "action": d.get("action"),
                    "mode": d.get("mode"),
                    "reason": d.get("reason"),
                }
            )
        if det.get("action") and det.get("action") not in ("allow", "log"):
            obs.action = det.get("action") if obs.action in (None, "allow", "log") else obs.action
            obs.control = obs.control if obs.action != det.get("action") else det.get("control_id")
    m = _CTRL.search(r.text or "") if "[Aegis]" in (r.text or "") else None
    if m and not obs.control:
        obs.control = m.group(1)
    reqs = stack.llm_requests()
    obs.upstream_calls = len(reqs)
    obs.upstream_texts = [_upstream_text(x) for x in reqs]
    obs.text_out = obs.upstream_texts[-1] if obs.upstream_texts else None
    return obs


def _hook_payload(case: Case) -> dict[str, Any]:
    event = case.hook_event or "PreToolUse"
    p = HOOK_DIR / f"{event}.json"
    payload: dict[str, Any] = (
        json.loads(p.read_text()) if p.exists() else {"hook_event_name": event}
    )
    payload["session_id"] = f"00000000-0000-4000-8000-{secrets.token_hex(6)}"
    payload["hook_event_name"] = event
    if case.tool:
        payload["tool_name"] = case.tool
    if case.args is not None:
        payload["tool_input"] = macros.expand_obj(case.args)
    if case.input is not None:
        if event == "UserPromptSubmit":
            payload["prompt"] = macros.expand(case.input)
        elif event in ("PostToolUse", "PostToolUseFailure"):
            payload["tool_response"] = macros.expand(case.input)
        elif event == "ConfigChange":
            payload["file_path"] = case.input
    if case.meta:
        payload.update(macros.expand_obj(case.meta))
    return payload


def run_hook(case: Case, stack: Any) -> Observation:
    obs = Observation()
    payload = _hook_payload(case)
    r = stack.gw.hook(payload, who=case.as_ or "claude-code@platform")
    obs.status = r.status_code
    obs.decision_id = r.headers.get("x-aegis-decision-id")
    try:
        out = r.json()
    except ValueError:
        out = {}
    hso = out.get("hookSpecificOutput") or {}
    perm = hso.get("permissionDecision")
    reason = hso.get("permissionDecisionReason") or out.get("reason") or ""
    obs.reason = reason
    if perm == "deny" or out.get("decision") == "block":
        obs.action = "block"
    elif (
        hso.get("updatedInput") is not None
        or hso.get("updatedToolOutput") is not None
        or out.get("updatedToolOutput") is not None
    ):
        obs.action = "redact"
        obs.mutations = 1
    else:
        obs.action = "allow"
    hdr = r.headers.get("x-aegis-decision")
    _from_detail(obs, stack.gw, obs.decision_id)
    if hdr == "require_approval" or "apr_" in reason:
        obs.action = "require_approval" if obs.action == "block" else obs.action
        m = re.search(r"apr_[0-9a-z]+", reason)
        obs.approval_id = m.group(0) if m else None
    if not obs.control:
        m = _CTRL.search(reason)
        obs.control = m.group(1) if m else None
    if obs.control and not any(d.get("control_id") == obs.control for d in obs.decisions):
        obs.decisions.append({"control_id": obs.control, "action": obs.action, "mode": "enforce"})
    obs.text_out = json.dumps(out)
    return obs


def run_mcp(case: Case, stack: Any) -> Observation:
    obs = Observation()
    if not stack.mcp_url and stack.mode == "hermetic":
        obs.skip = "via mcp unavailable (no MCP upstream in this stack)"
        return obs
    server, _, tool = (case.tool or "").partition(".")
    mc = McpClient(stack.gw, server, who=case.as_, session=_session(case))
    init = mc.initialize()
    obs.status = init["status"]
    err = (init["message"] or {}).get("error")
    if err:
        obs.jsonrpc_code = err.get("code")
        obs.action = "block"
        m = _CTRL.search(err.get("message") or "")
        obs.control = m.group(1) if m else ("MCP-01" if err.get("code") == -32001 else None)
        return obs
    if case.surface == "mcp.list" or not tool:
        res = mc.list_tools()
        tools = ((res["message"] or {}).get("result") or {}).get("tools") or []
        obs.tools_listed = [t.get("name") for t in tools]
        obs.action = "allow"
        return obs
    res = mc.call(tool, macros.expand_obj(case.args or {}))
    msg = res["message"] or {}
    obs.decision_id = res["headers"].get("x-aegis-decision-id")
    if msg.get("error"):
        obs.jsonrpc_code = msg["error"].get("code")
        obs.action = "block"
        m = _CTRL.search(msg["error"].get("message") or "")
        obs.control = m.group(1) if m else None
        return obs
    result = msg.get("result") or {}
    text = " ".join(c.get("text", "") for c in result.get("content") or [] if isinstance(c, dict))
    obs.response_text = text
    hdr = res["headers"].get("x-aegis-decision")
    if result.get("isError") and "[Aegis]" in text:
        obs.action = (
            "require_approval"
            if ("approval" in text.lower() or hdr == "require_approval")
            else "block"
        )
        m = _CTRL.search(text)
        obs.control = m.group(1) if m else None
    else:
        obs.action = hdr or "allow"
    _from_detail(obs, stack.gw, obs.decision_id)
    return obs


def run_egress(case: Case, stack: Any) -> Observation:
    obs = Observation()
    before = stack.sink_count()
    r = stack.gw.egress(
        (case.method or "GET").upper(),
        macros.expand(case.url or ""),
        json_body=macros.expand_obj(case.json_body),
        tool_name=case.tool,
        who=case.as_,
        session=_session(case),
    )
    obs.status = r.status_code
    try:
        d = r.json()
    except ValueError:
        d = {}
    err = d.get("error") if isinstance(d, dict) else None
    if r.status_code == 200:
        obs.action = "redact" if d.get("redactions") else "allow"
        obs.decision_id = d.get("decision_id")
    elif isinstance(err, dict):
        obs.error_type = err.get("type")
        obs.control = err.get("control_id")
        obs.decision_id = err.get("decision_id")
        obs.approval_id = err.get("approval_id")
        obs.action = {"approval_required": "require_approval", "policy_blocked": "block"}.get(
            err.get("type") or "", "block"
        )
        obs.reason = err.get("message") or ""
    _from_detail(obs, stack.gw, obs.decision_id)
    after = stack.sink_count()
    if before is not None and after is not None:
        obs.sink_delta = after - before
    return obs


def run_playground(case: Case, stack: Any) -> Observation:
    obs = Observation()
    body = {
        "text": macros.expand(case.input or ""),
        "surface": case.surface or "model.request",
        "destination": case.dest or "remote",
        "agent_id": case.as_,
        "send": False,
    }
    r = stack.gw.api("POST", "/api/playground", json=body)
    obs.status = r.status_code
    if r.status_code != 200:
        obs.error_type = _err_type(r)
        return obs
    d = r.json()
    _from_verdict(obs, d.get("verdict") or {})
    obs.text_out = (
        d.get("outbound") if isinstance(d.get("outbound"), str) else json.dumps(d.get("outbound"))
    )
    return obs


def run_simulate(case: Case, stack: Any) -> Observation:
    obs = Observation()
    body: dict[str, Any] = {
        "kind": case.kind or "action",
        "action_type": case.action_type or "",
        "amount_usd": case.amount_usd,
        "resource": case.resource,
    }
    if case.labels:
        body["labels"] = {k: str(v) for k, v in case.labels.items()}
    if case.changes:
        body["changes"] = case.changes
    if case.profiles:
        body["profile"] = case.profiles[0]
    if case.as_ and case.as_.startswith("u_"):
        body["requester_member_id"] = case.as_
    elif case.as_:
        body["requester_agent_id"] = case.as_
    r = stack.gw.api("POST", "/api/approvals/simulate", json=body)
    obs.status = r.status_code
    if r.status_code != 200:
        obs.error_type = _err_type(r)
        return obs
    route = r.json()
    obs.route = route
    role = route.get("required_role")
    obs.action = {"auto": "allow", "deny": "block"}.get(role, "require_approval")
    return obs


def run_api(case: Case, stack: Any) -> Observation:
    obs = Observation()
    r = stack.gw.api(
        (case.method or "GET").upper(),
        case.path or "/",
        view_as=case.view_as or case.as_ or OWNER,
        json=macros.expand_obj(case.json_body),
    )
    obs.status = r.status_code
    obs.error_type = _err_type(r) if r.status_code >= 400 else None
    try:
        d = r.json()
    except ValueError:
        d = {}
    status = d.get("status") if isinstance(d, dict) else None
    if r.status_code >= 400:
        obs.action = "block"
    elif status == "pending_approval":
        obs.action = "require_approval"
    else:
        obs.action = "allow"
    obs.raw = d
    return obs


def run_ollama(case: Case, stack: Any) -> Observation:
    obs = Observation()
    path = case.path or "api/chat"
    body = (
        macros.expand_obj(case.json_body)
        if case.json_body is not None
        else {
            "model": case.model or "aegis-judge",
            "stream": False,
            "messages": [{"role": "user", "content": macros.expand(case.input or "")}],
        }
    )
    r = stack.gw.ollama(path, body, who=case.as_, session=_session(case))
    obs.status = r.status_code
    obs.action = r.headers.get("x-aegis-decision")
    obs.decision_id = r.headers.get("x-aegis-decision-id")
    obs.error_type = _err_type(r) if r.status_code >= 400 else None
    _from_detail(obs, stack.gw, obs.decision_id)
    if not obs.control:
        m = _CTRL.search(r.text or "")
        obs.control = m.group(1) if (m and "[Aegis]" in r.text) else None
    return obs


RUNNERS = {
    "guard": run_guard,
    "anthropic": run_proxy,
    "openai": run_proxy,
    "hook": run_hook,
    "mcp": run_mcp,
    "egress": run_egress,
    "playground": run_playground,
    "simulate": run_simulate,
    "api": run_api,
    "ollama": run_ollama,
}


def run_case(case: Case, stack: Any) -> Observation:
    for v in case.assert_.audit_must_not_contain:
        privacy.register(macros.expand(v), f"audit_must_not_contain:{case.id}")
    fn = RUNNERS[case.via]
    if case.via == "guard":
        return run_guard(copy.deepcopy(case), stack, dry_run=(stack.mode == "live"))
    return fn(case, stack)


__all__ = ["RUNNERS", "Observation", "run_case"]

"""Semantic policy diff (public surface: `diff_docs`, CONTRACTS section 3.3).

`diff_docs(old, new)` walks both documents (`model_dump(mode="json", by_alias=True)`) with keyed
list identity (controls/rules by id, tests by name, budget limits by (scope, window), downgrade
by from) and classifies every difference into a `PolicyChange` (kind, loosening, summary) that
GOV-05 / approvals routing understand. Also: `unified_diff`, `summarize`, `primary_kind`,
`diff_effective` (profile-induced effective changes, for toasts and audit only).
"""

from __future__ import annotations

import difflib
from typing import Any

from aegis.core.policy_schema import PolicyChange, PolicyDoc
from aegis.core.types import ACTION_PRECEDENCE, APPROVER_RANK

PROFILE_RANK = {"permissive": 0, "balanced": 1, "strict": 2, "paranoid": 3}
MODE_RANK = {"off": 0, "monitor": 1, "enforce": 2}
FAIL_RANK = {"open": 0, "deterministic_only": 1, "closed": 2}
DEST_RANK = {"local": 0, "remote": 1, "third_party": 2}
_KS_SCOPE = {"teams": "team", "members": "member", "agents": "agent", "sessions": "session"}
_DIMS = ("usd", "tokens", "compute_s", "requests", "tool_calls", "spend_usd")

# known params: higher value = looser
_PARAM_UP_LOOSENS = ("_max_usd", "hard_block_above_usd", "redaction_ratio_block", "entropy_min",
                     "min_len", "max_encoded_len", "overlap_threshold", "query_max_len",
                     "dns_label_max", "max_description_len", "collision_distance", "untrusted_threshold",
                     "max_concurrency", "max_model_gb", "max_recipients")
_BOOL_TRUE_PROTECTS = ("block_private_ranges", "strip_ansi", "fuzzy", "price_check",
                       "block_bypass_permissions", "pinned")


def _fmt(v: Any) -> str:
    if v is None:
        return "none"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() and abs(v) < 1e15 else f"{v:g}"
    if isinstance(v, list | dict):
        s = str(v)
        return s if len(s) <= 60 else s[:57] + "..."
    return str(v)


def _fmt_threshold(v: Any) -> str:
    if isinstance(v, int | float) and not isinstance(v, bool):
        return f"{v:.2f}"
    return _fmt(v)


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int | float):
        return float(v)
    return None


# ---------------------------------------------------------------- generic keyed walk
def _key_for(path: tuple[str, ...]) -> tuple[str, ...] | None:
    """Identity keys for lists of mappings at this (normalized) path; None = by index."""
    last = path[-1] if path else ""
    if last in ("controls",) and len(path) == 1:
        return ("id",)
    if last == "tests":
        return ("name",)
    if path == ("approvals", "rules") or path == ("approvals", "config_rules") or path == ("feeds", "sources"):
        return ("id",)
    if path == ("budgets", "limits"):
        return ("scope", "window")
    if path == ("models", "downgrade"):
        return ("from",)
    return None


def _sel_str(keys: tuple[str, ...], item: dict[str, Any]) -> str:
    return "[" + ",".join(f"{k}={item.get(k)}" for k in keys) + "]"


class _Ev:
    __slots__ = ("after", "before", "op", "parts", "path")

    def __init__(self, op: str, parts: list[Any], path: str, before: Any = None, after: Any = None):
        self.op = op  # change | add | remove | list_add | list_remove
        self.parts = parts  # normalized parts: str keys, ("sel", {k: v}) for keyed items, int index
        self.path = path
        self.before = before
        self.after = after


def _walk(a: Any, b: Any, parts: list[Any], path: str, norm: tuple[str, ...], out: list[_Ev]) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        for k in list(a.keys()) + [k for k in b.keys() if k not in a]:
            sub = f"{path}.{k}" if path else str(k)
            if k not in b:
                out.append(_Ev("remove", [*parts, k], sub, before=a[k]))
            elif k not in a:
                out.append(_Ev("add", [*parts, k], sub, after=b[k]))
            elif a[k] != b[k]:
                _walk(a[k], b[k], [*parts, k], sub, (*norm, str(k)), out)
        return
    if isinstance(a, list) and isinstance(b, list):
        keys = _key_for(norm)
        dict_list = all(isinstance(x, dict) for x in a + b) and (a or b)
        if keys and dict_list:
            def ident(item: dict[str, Any]) -> tuple[Any, ...]:
                return tuple(str(item.get(k)) for k in keys)

            amap = {ident(x): x for x in a}
            bmap = {ident(x): x for x in b}
            for x in a:
                ix = ident(x)
                sub = f"{path}{_sel_str(keys, x)}"
                if ix not in bmap:
                    out.append(_Ev("remove", [*parts, ("sel", {k: x.get(k) for k in keys})], sub, before=x))
                elif bmap[ix] != x:
                    _walk(x, bmap[ix], [*parts, ("sel", {k: x.get(k) for k in keys})], sub, norm, out)
            for x in b:
                if ident(x) not in amap:
                    sub = f"{path}{_sel_str(keys, x)}"
                    out.append(_Ev("add", [*parts, ("sel", {k: x.get(k) for k in keys})], sub, after=x))
            return
        if not dict_list and all(not isinstance(x, dict | list) for x in a + b):
            # scalar list: set semantics
            for x in a:
                if x not in b:
                    out.append(_Ev("list_remove", parts, path, before=x))
            for x in b:
                if x not in a:
                    out.append(_Ev("list_add", parts, path, after=x))
            if not any(x not in b for x in a) and not any(x not in a for x in b) and a != b:
                out.append(_Ev("change", parts, path, before=a, after=b))  # reorder only
            return
        # index-wise
        n = max(len(a), len(b))
        for i in range(n):
            sub = f"{path}[{i}]"
            if i >= len(b):
                out.append(_Ev("remove", [*parts, i], sub, before=a[i]))
            elif i >= len(a):
                out.append(_Ev("add", [*parts, i], sub, after=b[i]))
            elif a[i] != b[i]:
                _walk(a[i], b[i], [*parts, i], sub, norm, out)
        return
    if a != b:
        out.append(_Ev("change", parts, path, before=a, after=b))


# ---------------------------------------------------------------- classification
def _change(kind: str, ev: _Ev, *, loosening: bool = False, summary: str = "", **kw: Any) -> PolicyChange:
    return PolicyChange(kind=kind, path=ev.path, before=ev.before, after=ev.after, loosening=loosening,
                        summary=summary or f"{ev.path}: {_fmt(ev.before)} → {_fmt(ev.after)}", **kw)  # type: ignore[arg-type]


def _classify_control(ev: _Ev, cid: str, sub: list[Any]) -> PolicyChange:
    field = sub[0] if sub else None
    if ev.op in ("add", "remove") and field is None:
        if ev.op == "add":
            return _change("control.add", ev, control_id=cid, summary=f"{cid} added")
        return _change("control.remove", ev, control_id=cid, loosening=True, summary=f"{cid} removed")
    b, a = ev.before, ev.after
    if field == "enabled":
        if a is False or (ev.op == "add" and a is False):
            return _change("control.disable", ev, control_id=cid, loosening=True, summary=f"{cid} disabled")
        if a is True or ev.op == "remove":
            return _change("control.enable", ev, control_id=cid, summary=f"{cid} enabled")
    if field == "mode":
        rb, ra = MODE_RANK.get(str(b or "enforce"), 2), MODE_RANK.get(str(a or "enforce"), 2)
        return _change("control.mode", ev, control_id=cid, loosening=ra < rb,
                       summary=f"{cid} mode {_fmt(b or 'enforce')} → {_fmt(a or 'enforce')}")
    if field == "action":
        pb, pa = ACTION_PRECEDENCE.get(str(b), 4), ACTION_PRECEDENCE.get(str(a), 4)
        kind = "control.action.loosen" if pa < pb else "control.action.tighten"
        return _change(kind, ev, control_id=cid, loosening=pa < pb, summary=f"{cid} action {_fmt(b)} → {_fmt(a)}")
    if field == "threshold":
        nb, na = _num(b), _num(a)
        loosen = (na is None and nb is not None) or (nb is not None and na is not None and na > nb)
        kind = "control.threshold.loosen" if loosen else "control.threshold.tighten"
        return _change(kind, ev, control_id=cid, loosening=loosen,
                       summary=f"{cid} threshold {_fmt_threshold(b)} → {_fmt_threshold(a)}")
    if field == "adherence_pct":
        nb, na = _num(b), _num(a)
        loosen = (na is None and nb is not None) or (nb is not None and na is not None and na < nb)
        kind = "control.threshold.loosen" if loosen else "control.threshold.tighten"
        return _change(kind, ev, control_id=cid, loosening=loosen,
                       summary=f"{cid} adherence {_fmt(b)}% → {_fmt(a)}%")
    if field == "fail_mode":
        loosen = FAIL_RANK.get(str(a), 2) < FAIL_RANK.get(str(b), 2)
        return _change("control.params", ev, control_id=cid, loosening=loosen,
                       summary=f"{cid} fail_mode {_fmt(b)} → {_fmt(a)}")
    if field == "scope":
        lst = str(sub[1]) if len(sub) > 1 else ""
        if lst in ("orgs", "teams", "members", "agents"):
            loosen = ev.op in ("list_remove", "remove")
        else:  # kinds / surfaces / destinations: empty = all, adding entries narrows the control
            loosen = ev.op in ("list_add", "add")
        return _change("control.params", ev, control_id=cid, loosening=loosen,
                       summary=f"{cid} scope.{lst}: {_fmt(b)} → {_fmt(a)}")
    if field == "params":
        return _change("control.params", ev, control_id=cid, loosening=_param_loosening(ev, sub[1:]),
                       summary=f"{cid} {'.'.join(str(s) for s in sub[1:] if not isinstance(s, tuple)) or 'params'}: "
                               f"{_fmt(b)} → {_fmt(a)}")
    if field == "tests":
        loosen = ev.op == "remove" and len(sub) <= 2
        return _change("other", ev, control_id=cid, loosening=loosen,
                       summary=f"{cid} tests changed" if not loosen else f"{cid} test removed")
    return _change("other", ev, control_id=cid, summary=f"{cid} {field}: {_fmt(b)} → {_fmt(a)}")


def _param_loosening(ev: _Ev, sub: list[Any]) -> bool:
    name = str(sub[0]) if sub else ""
    leaf = str(sub[-1]) if sub and not isinstance(sub[-1], tuple) else name
    b, a = ev.before, ev.after
    if ev.op == "list_add":
        return name.startswith("allow") or name in ("allow_hosts", "allowlist_values", "allowlist_patterns",
                                                    "allowed_formats", "pickle_global_allow")
    if ev.op == "list_remove":
        return name.startswith("deny") or name in ("fs_deny", "keywords", "canaries", "entities",
                                                   "approve_tools", "forbidden_scopes", "rules")
    if ev.op == "remove" and name == "rules":
        return True
    nb, na = _num(b), _num(a)
    if nb is not None and na is not None:
        if any(leaf.endswith(s) or leaf == s.strip("_") for s in _PARAM_UP_LOOSENS):
            return na > nb
        return False
    if isinstance(b, bool) and isinstance(a, bool):
        if leaf in _BOOL_TRUE_PROTECTS:
            return b and not a
        if leaf.startswith("allow"):
            return a and not b
        return False
    if leaf.endswith("action") and isinstance(b, str) and isinstance(a, str):
        return ACTION_PRECEDENCE.get(a, 4) < ACTION_PRECEDENCE.get(b, 4)
    return False


def _classify(ev: _Ev, old: dict[str, Any], new: dict[str, Any]) -> PolicyChange | None:
    p = ev.parts
    top = p[0] if p else ""
    b, a = ev.before, ev.after

    if top == "profile":
        loosen = PROFILE_RANK.get(str(a), 1) < PROFILE_RANK.get(str(b), 1)
        return _change("profile.change", ev, loosening=loosen, summary=f"profile {_fmt(b)} → {_fmt(a)}")

    if top == "defaults":
        key = p[1] if len(p) > 1 else ""
        if key == "mode":
            loosen = MODE_RANK.get(str(a), 2) < MODE_RANK.get(str(b), 2)
            return _change("control.mode", ev, loosening=loosen, summary=f"global mode {_fmt(b)} → {_fmt(a)}")
        if key == "fail_mode":
            loosen = FAIL_RANK.get(str(a), 2) < FAIL_RANK.get(str(b), 2)
            return _change("control.params", ev, loosening=loosen, summary=f"default fail_mode {_fmt(b)} → {_fmt(a)}")
        loosen = (key == "require_auth" and b is True and a is False) or (
            key == "audit_content" and b is False and a is True) or (
            key == "selftest_gate" and str(a) in ("warn", "off") and str(b or "enforce") == "enforce")
        return _change("other", ev, loosening=loosen, summary=f"defaults.{key}: {_fmt(b)} → {_fmt(a)}")

    if top == "destinations":
        key = p[1] if len(p) > 1 else ""
        if key == "matrix" and len(p) >= 4:
            cls, dest = p[2], p[3]
            pb, pa = ACTION_PRECEDENCE.get(str(b), 0), ACTION_PRECEDENCE.get(str(a), 0)
            kind = "control.action.loosen" if pa < pb else "control.action.tighten"
            return _change(kind, ev, loosening=pa < pb, control_id="DLP-01",
                           summary=f"matrix {cls}→{dest}: {_fmt(b)} → {_fmt(a)}")
        if key == "matrix" and len(p) == 3:  # whole class row added/removed
            return _change("control.action.tighten" if ev.op == "add" else "control.action.loosen", ev,
                           loosening=ev.op == "remove", control_id="DLP-01", summary=f"matrix row {p[2]} {ev.op}")
        loosen = ev.op == "list_add" and key in ("internal_domains", "allowed_link_domains", "egress_allowlist", "local_tools")
        return _change("other", ev, loosening=loosen,
                       summary=f"destinations.{key}: {'+' if ev.op == 'list_add' else '-' if ev.op == 'list_remove' else ''}"
                               f"{_fmt(a if ev.op != 'list_remove' else b)}")

    if top == "providers":
        name = p[1] if len(p) > 1 else "?"
        if ev.op == "add" and len(p) == 2:
            return _change("provider.change", ev, loosening=True, summary=f"provider {name} added")
        if ev.op == "remove" and len(p) == 2:
            return _change("provider.change", ev, summary=f"provider {name} removed")
        loosen = len(p) > 2 and p[2] == "destination" and DEST_RANK.get(str(a), 1) > DEST_RANK.get(str(b), 1)
        return _change("provider.change", ev, loosening=loosen, summary=f"provider {name}.{'.'.join(str(x) for x in p[2:])}: {_fmt(b)} → {_fmt(a)}")

    if top == "models":
        key = p[1] if len(p) > 1 else ""
        if key in ("allowed", "denied") and ev.op in ("list_add", "list_remove"):
            val = a if ev.op == "list_add" else b
            allow = (key == "allowed") == (ev.op == "list_add")
            if allow:
                return _change("model.allow", ev, loosening=True,
                               summary=f"models.{key} {'+' if ev.op == 'list_add' else '-'} {val}")
            return _change("model.disallow", ev, summary=f"models.{key} {'+' if ev.op == 'list_add' else '-'} {val}")
        if key in ("allowed", "denied"):
            return _change("other", ev, summary=f"models.{key} reordered")
        return _change("route.change", ev, summary=f"models.{key} changed")

    if top == "budgets":
        return _classify_budget(ev, p)

    if top == "approvals":
        return _classify_approval(ev, p)

    if top == "mcp":
        key = p[1] if len(p) > 1 else ""
        if key == "servers":
            name = p[2] if len(p) > 2 else "?"
            if len(p) == 3:
                return _change("mcp.server", ev, loosening=ev.op == "add",
                               summary=f"MCP server {name} {'added' if ev.op == 'add' else 'removed'}")
            field = p[3]
            loosen = (field == "allowed_tools" and ev.op == "list_add") or (field == "pinned" and b is True and a is False) or (
                field == "destination" and DEST_RANK.get(str(a), 2) > DEST_RANK.get(str(b), 2))
            return _change("mcp.server", ev, loosening=loosen, summary=f"MCP {name}.{field}: {_fmt(b if ev.op != 'list_add' else '')}{' → ' if ev.op == 'change' else ' +'}{_fmt(a)}")
        if key in ("unknown_server_action", "on_tool_change"):
            loosen = ACTION_PRECEDENCE.get(str(a), 4) < ACTION_PRECEDENCE.get(str(b), 4)
            return _change("mcp.server", ev, loosening=loosen, summary=f"mcp.{key}: {_fmt(b)} → {_fmt(a)}")
        loosen = key == "max_description_len" and (_num(a) or 0) > (_num(b) or 0)
        return _change("other", ev, loosening=loosen, summary=f"mcp.{key}: {_fmt(b)} → {_fmt(a)}")

    if top == "feeds":
        key = p[1] if len(p) > 1 else ""
        if key == "overrides":
            sig = p[2] if len(p) > 2 else "?"
            ov_b = b if len(p) == 3 else None
            ov_a = a if len(p) == 3 else None
            field = p[3] if len(p) > 3 else None
            loosen = False
            if len(p) == 3 and ev.op == "add" and isinstance(ov_a, dict):
                loosen = ov_a.get("enabled") is False or ov_a.get("mode") in ("monitor", "off") or (
                    ov_a.get("action") is not None and ov_a.get("action") != "block")
            elif field == "enabled":
                loosen = a is False
            elif field == "action":
                loosen = ACTION_PRECEDENCE.get(str(a), 4) < ACTION_PRECEDENCE.get(str(b or "block"), 4)
            elif field == "mode":
                loosen = MODE_RANK.get(str(a), 2) < MODE_RANK.get(str(b or "enforce"), 2)
            _ = ov_b
            return _change("feed.override", ev, loosening=loosen,
                           summary=f"feed override {sig}{('.' + str(field)) if field else ''}: {_fmt(b)} → {_fmt(a)}")
        return _change("other", ev, summary=f"feeds.{key} changed")

    if top == "controls":
        sel = p[1] if len(p) > 1 else None
        cid = sel[1].get("id") if isinstance(sel, tuple) else (str(ev.before.get("id")) if isinstance(ev.before, dict) else "?")
        if isinstance(sel, tuple) and len(p) == 2:
            return _classify_control(ev, str(cid), [])
        return _classify_control(ev, str(cid), list(p[2:]))

    if top == "tests":
        loosen = ev.op == "remove" and len(p) == 2
        name = p[1][1].get("name") if len(p) > 1 and isinstance(p[1], tuple) else "?"
        return _change("other", ev, loosening=loosen,
                       summary=f"test {name} {'removed' if loosen else 'added' if ev.op == 'add' and len(p) == 2 else 'changed'}")

    if top == "actions":
        loosen = ev.op == "remove" and len(p) == 2
        return _change("other", ev, loosening=loosen, summary="actions table changed")

    return _change("other", ev, summary=f"{ev.path}: {_fmt(b)} → {_fmt(a)}")


def _classify_budget(ev: _Ev, p: list[Any]) -> PolicyChange:
    key = p[1] if len(p) > 1 else ""
    b, a = ev.before, ev.after
    if key == "limits":
        sel = p[2] if len(p) > 2 else None
        ident = sel[1] if isinstance(sel, tuple) else {}
        scope = str(ident.get("scope")) if ident else None
        window = ident.get("window") if ident else None
        if len(p) == 3 and ev.op in ("add", "remove"):
            item = a if ev.op == "add" else b
            dims = [d for d in _DIMS if isinstance(item, dict) and item.get(d) is not None]
            dim = dims[0] if dims else None
            txt = ", ".join(f"{d} {_fmt(item.get(d))}" for d in dims) if isinstance(item, dict) else ""
            if ev.op == "add":
                return _change("budget.add", ev, scope=scope, dimension=dim, summary=f"budget {scope} {window} added ({txt})")
            return _change("budget.remove", ev, scope=scope, dimension=dim, loosening=True,
                           summary=f"budget {scope} {window} removed")
        field = str(p[3]) if len(p) > 3 else ""
        if field in _DIMS:
            nb, na = _num(b), _num(a)
            if nb is None and na is not None:
                return _change("budget.add", ev, scope=scope, dimension=field,
                               summary=f"{scope} {window} {field} limit {_fmt(na)} added")
            if na is None and nb is not None:
                return _change("budget.remove", ev, scope=scope, dimension=field, loosening=True,
                               summary=f"{scope} {window} {field} limit removed")
            if nb is not None and na is not None:
                pct = ((na - nb) / nb * 100.0) if nb else (100.0 if na > 0 else 0.0)
                pct = round(pct, 2)
                if na > nb:
                    return _change("budget.raise", ev, scope=scope, dimension=field, increase_pct=pct, loosening=True,
                                   summary=f"{scope} {window} {field} {_fmt(nb)} → {_fmt(na)} (+{_fmt(round(pct, 1))}%)")
                return _change("budget.lower", ev, scope=scope, dimension=field, increase_pct=pct,
                               summary=f"{scope} {window} {field} {_fmt(nb)} → {_fmt(na)} ({_fmt(round(pct, 1))}%)")
        loosen = (field == "soft_pct" and (_num(a) or 0) > (_num(b) or 0)) or (
            field == "on_hard" and str(a) in ("require_approval", "downgrade") and str(b) in ("block", "None"))
        return _change("other", ev, scope=scope, loosening=loosen, summary=f"{scope} {window} {field}: {_fmt(b)} → {_fmt(a)}")
    if key == "kill_switch":
        sub = p[2] if len(p) > 2 else ""
        if sub == "global":
            if a is True:
                return _change("killswitch.on", ev, scope="global", summary="kill switch on: global")
            return _change("killswitch.off", ev, scope="global", loosening=True, summary="kill switch off: global")
        stype = _KS_SCOPE.get(str(sub), str(sub))
        if ev.op == "list_add":
            return _change("killswitch.on", ev, scope=f"{stype}:{a}", summary=f"kill switch on: {stype} {a}")
        if ev.op == "list_remove":
            return _change("killswitch.off", ev, scope=f"{stype}:{b}", loosening=True, summary=f"kill switch off: {stype} {b}")
        return _change("other", ev, summary=f"kill switch {sub} reordered")
    # defaults / loops / rate
    field = str(p[-1]) if p else ""
    nb, na = _num(b), _num(a)
    loosen = False
    if key in ("rate", "loops") and nb is not None and na is not None:
        loosen = na > nb
    if key == "defaults":
        if field == "soft_pct" and nb is not None and na is not None:
            loosen = na > nb
        if field == "on_hard":
            loosen = str(a) in ("require_approval", "downgrade") and str(b) == "block"
        if field == "max_output_tokens":
            loosen = na is None or (nb is not None and na > nb)
    if key == "loops" and field == "ladder":
        loosen = ev.op == "list_remove"
    return _change("other", ev, loosening=loosen, summary=f"budgets.{key}.{field}: {_fmt(b)} → {_fmt(a)}")


def _classify_approval(ev: _Ev, p: list[Any]) -> PolicyChange:
    b, a = ev.before, ev.after
    key = p[1] if len(p) > 1 else ""
    loosen = False
    summary = f"approvals.{key} changed"
    if key in ("rules", "config_rules"):
        sel = p[2] if len(p) > 2 else None
        rid = sel[1].get("id") if isinstance(sel, tuple) else "?"
        if len(p) == 3 and ev.op == "remove":
            loosen, summary = True, f"approval rule {rid} removed"
        elif len(p) == 3 and ev.op == "add":
            appr = a.get("approver", "admin") if isinstance(a, dict) else "admin"
            loosen = APPROVER_RANK.get(str(appr), 2) < 2
            summary = f"approval rule {rid} added (approver {appr})"
        else:
            field = str(p[3]) if len(p) > 3 else ""
            if field == "approver":
                loosen = APPROVER_RANK.get(str(a), 2) < APPROVER_RANK.get(str(b), 2)
            elif field == "two_person":
                loosen = b is True and a is not True
            summary = f"approval rule {rid}.{'.'.join(str(x) for x in p[3:] if not isinstance(x, tuple))}: {_fmt(b)} → {_fmt(a)}"
        if not loosen and ev.op == "change" and len(p) == 2:
            summary = f"approvals.{key} reordered"
    elif key == "defaults":
        field = str(p[2]) if len(p) > 2 else ""
        if field in ("default_approver", "default_config_approver"):
            loosen = APPROVER_RANK.get(str(a), 2) < APPROVER_RANK.get(str(b), 2)
        summary = f"approvals.defaults.{field}: {_fmt(b)} → {_fmt(a)}"
    return _change("approval.rule", ev, loosening=loosen, summary=summary)


# ---------------------------------------------------------------- public API
def _dump(doc: PolicyDoc) -> dict[str, Any]:
    return doc.model_dump(mode="json", by_alias=True)


def diff_docs(old: PolicyDoc, new: PolicyDoc) -> list[PolicyChange]:
    """Classified changes old -> new (empty list = semantically identical)."""
    a, b = _dump(old), _dump(new)
    events: list[_Ev] = []
    _walk(a, b, [], "", (), events)
    out: list[PolicyChange] = []
    for ev in events:
        try:
            ch = _classify(ev, a, b)
        except Exception:  # never let a classifier bug break a policy apply
            ch = PolicyChange(kind="other", path=ev.path, before=ev.before, after=ev.after,
                              summary=f"{ev.path} changed")
        if ch is not None:
            out.append(ch)
    return out


def unified_diff(old_text: str, new_text: str, old_label: str = "a/policy.yaml",
                 new_label: str = "b/policy.yaml", context: int = 3) -> str:
    return "".join(difflib.unified_diff(
        old_text.splitlines(keepends=True), new_text.splitlines(keepends=True),
        fromfile=old_label, tofile=new_label, n=context))


def primary_kind(changes: list[PolicyChange]) -> str:
    """Kind of the first loosening change, else of the first change, else 'other'."""
    for c in changes:
        if c.loosening:
            return c.kind
    return changes[0].kind if changes else "other"


def summarize(changes: list[PolicyChange], limit: int = 3) -> str:
    if not changes:
        return "no semantic changes"
    parts = [c.summary or c.path for c in changes[:limit]]
    more = len(changes) - limit
    return " · ".join(parts) + (f" · +{more} more" if more > 0 else "")


def diff_effective(old_snap: Any, new_snap: Any) -> list[PolicyChange]:
    """Effective (profile-merged) control differences: enabled/mode/action/threshold/
    adherence_pct/fail_mode/params. For toasts and audit only (never routed to approval)."""
    out: list[PolicyChange] = []
    old_c = getattr(old_snap, "controls", {}) or {}
    new_c = getattr(new_snap, "controls", {}) or {}
    for cid in sorted(set(old_c) | set(new_c)):
        oc, nc = old_c.get(cid), new_c.get(cid)
        if oc is None or nc is None:
            continue
        for field in ("enabled", "mode", "action", "threshold", "adherence_pct", "fail_mode"):
            bv, av = getattr(oc, field), getattr(nc, field)
            if bv != av:
                ev = _Ev("change", ["controls", ("sel", {"id": cid}), field], f"controls[id={cid}].{field}", bv, av)
                out.append(_classify_control(ev, cid, [field]))
        if oc.params != nc.params:
            ev = _Ev("change", ["controls", ("sel", {"id": cid}), "params"], f"controls[id={cid}].params",
                     oc.params, nc.params)
            out.append(PolicyChange(kind="control.params", path=ev.path, before=oc.params, after=nc.params,
                                    control_id=cid, summary=f"{cid} params (effective) changed"))
    return out

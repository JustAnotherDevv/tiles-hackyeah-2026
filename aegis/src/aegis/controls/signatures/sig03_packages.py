"""SIG-03 · Package-install & slopsquatting guard.

Parses install commands (pip/uv/poetry/pdm/pipx, npm/pnpm/yarn/bun, npx/bunx/dlx,
`code --install-extension`, MCP `{command, args}` launch lines) and looks every package up in
the signed feed's `lists`:

- `malicious_versions` exact version (or an entry with no versions)  -> block
- known-bad name but unpinned install                                -> log ("unpinned")
- `hallucinated_packages`                                            -> require_approval
- `known_good_packages`                                              -> allow
- anything else                                                      -> params.unknown_action
  (`require_approval`, signal `unknown_package`; `mcp.init` -> `unknown_action_mcp_init`)

No lists (empty feed) -> None + degraded. This control never blocks blindly.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from aegis.controls.signatures import _common as C
from aegis.core.protocols import BaseControl
from aegis.core.types import AppliesTo, ApprovalDraft, Decision, Finding
from aegis.feed.matchers.structured import norm_pkg, parse_install_commands

log = logging.getLogger(__name__)

Act = Literal["allow", "log", "require_approval", "block"]


class SIG03Params(C.Params):
    unknown_action: Act = "require_approval"
    unknown_action_mcp_init: Act = "log"
    ecosystems: list[str] = ["pypi", "npm", "vscode"]


def _texts(i: Any) -> str:
    parts = [str(getattr(s, "text", "") or "") for s in (getattr(i, "segments", None) or [])]
    args = getattr(i, "tool_args", None) or {}
    if isinstance(args, dict) and isinstance(args.get("command"), str):
        cmd = args["command"]
        rest = args.get("args")
        if isinstance(rest, list):  # MCP stdio launch {command, args}
            cmd = " ".join([cmd, *[str(a) for a in rest]])
        parts.append(cmd)
    return "\n".join(dict.fromkeys(p for p in parts if p))


def _index(lists: dict) -> tuple[dict, set, dict]:
    bad: dict[tuple[str, str], set[str]] = {}
    for e in lists.get("malicious_versions") or []:
        if isinstance(e, dict) and e.get("name"):
            eco = str(e.get("ecosystem", "pypi"))
            bad.setdefault((eco, norm_pkg(eco, str(e["name"]))), set()).update(
                str(v) for v in (e.get("versions") or [])
            )
    halluc = {
        (str(e.get("ecosystem", "pypi")), norm_pkg(str(e.get("ecosystem", "pypi")), str(e["name"])))
        for e in lists.get("hallucinated_packages") or []
        if isinstance(e, dict) and e.get("name")
    }
    good = {
        eco: {norm_pkg(eco, str(n)) for n in names or []}
        for eco, names in (lists.get("known_good_packages") or {}).items()
    }
    return bad, halluc, good


class PackageInstallGuard(BaseControl):
    id, family, name, kind = (
        "SIG-03",
        "SIG",
        "Package-install & slopsquatting guard",
        "deterministic",
    )
    applies_to = AppliesTo(surfaces={"tool.input", "mcp.call", "mcp.init"})
    owasp = ["LLM04:2026", "ASI04", "MCP04:2025"]
    priority = 100

    async def evaluate(self, ctx: Any, interaction: Any, cfg: Any) -> Decision | None:
        text = _texts(interaction)
        if not text:
            return None
        pkgs = parse_install_commands(text)
        if not pkgs:
            return None
        p = C.params(self.id, SIG03Params, cfg)
        feed = C.feed()
        lists = feed.lists() if feed is not None and hasattr(feed, "lists") else {}
        if not lists:
            return Decision(
                action="allow",
                control_id=self.id,
                degraded=True,
                reason="package lists unavailable (no feed bundle)",
            )
        bad, halluc, good = _index(lists)
        surface = str(getattr(interaction, "surface", ""))
        unknown = p.unknown_action_mcp_init if surface == "mcp.init" else p.unknown_action
        rows: list[tuple[str, str, str, str]] = []  # (action, detector, label, why)
        res: dict[str, str] = {}
        for eco, name, ver in pkgs:
            eco_l = "npm" if eco == "npm-exec" else eco
            if eco_l not in p.ecosystems:
                continue
            key = (eco_l, name)
            label = f"{eco_l}:{name}" + (f"@{ver}" if ver else "")
            res[label] = f"pkg:{eco_l}/{name}"
            if key in bad:
                versions = bad[key]
                if not versions or (ver and ver in versions):
                    rows.append(
                        (
                            "block",
                            "sig03.malicious_version",
                            label,
                            f"known-compromised package {label}",
                        )
                    )
                    continue
                if not ver:
                    rows.append(
                        (
                            "log",
                            "sig03.unpinned_known_bad",
                            label,
                            f"{label} unpinned; known-bad versions exist ({', '.join(sorted(versions))})",
                        )
                    )
                    continue
            if key in halluc:
                rows.append(
                    (
                        "require_approval",
                        "sig03.hallucinated",
                        label,
                        f"{label} is a known hallucinated / slopsquatted package name",
                    )
                )
                continue
            if name in good.get(eco_l, set()):
                continue
            if unknown != "allow":
                rows.append(
                    (
                        unknown,
                        "sig03.unknown",
                        label,
                        f"{label} is not on the known-good list (possible slopsquatting)",
                    )
                )
        if not rows:
            return Decision(
                action="allow", control_id=self.id, severity="info", reason="known-good packages"
            )
        action = C.strongest([r[0] for r in rows])
        primary = next(r for r in rows if r[0] == action)
        sev = {"block": "critical", "require_approval": "high"}.get(action, "low")
        findings = [
            Finding(
                control_id=self.id,
                detector=r[1],
                category="supply_chain",
                severity=sev if r[0] == action else "low",  # type: ignore[arg-type]
                excerpt=r[2],
                meta={"package": r[2], "action": r[0]},
            )
            for r in rows
        ]
        approval = None
        if action == "require_approval":
            approval = ApprovalDraft(
                kind="action",
                action_type="package.install",
                title=f"Install package {primary[2]}",
                summary=primary[3],
                resource=res.get(primary[2]),
                labels={
                    "signals": "unknown_package",
                    "pattern": "pkg_install",
                    "capability": "code_exec",
                },
                payload={
                    "facts": {"packages": [r[2] for r in rows], "surface": surface},
                    "checks": [
                        {"name": r[2], "ok": r[0] in ("allow", "log"), "detail": r[3]} for r in rows
                    ],
                },
            )
        return Decision(
            action=action,
            control_id=self.id,
            reason=primary[3],  # type: ignore[arg-type]
            severity=sev,
            findings=findings,
            approval=approval,  # type: ignore[arg-type]
            owasp=list(getattr(cfg, "owasp", None) or self.owasp),
            meta={"packages": [r[2] for r in rows]},
        )


CONTROLS = [PackageInstallGuard()]

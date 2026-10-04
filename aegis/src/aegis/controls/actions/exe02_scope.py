"""ctl EXE-02 - Filesystem & network scope (SSRF) (action-guards).

FS: paths from ``params.path_args`` and Bash path tokens; ``~``/``$HOME`` expansion, ``meta.cwd``,
lexical ``..``, symlinks, darwin casefold. Order: ``fs_allow_exceptions`` (``.env.example``) ->
``fs_deny`` -> ``fs_write_deny`` (writes) -> ``fs_allow`` (when non-empty).
Network: URLs from ``interaction.url`` (egress), ``params.url_args`` and Bash tokens; scheme check,
host canonicalization (decimal/octal/hex/short IPv4, IPv6, IPv4-mapped, userinfo tricks),
loopback/private/link-local/metadata -> block unless ``allow_hosts``; ``deny_hosts``;
``destinations.egress_allowlist``. The gateway itself (:8787) is deliberately not allowed.
"""

from __future__ import annotations

from typing import ClassVar

from aegis.actions import catalog as catmod
from aegis.actions import runtime as art
from aegis.actions.argpath import get_arg, get_path
from aegis.actions.base import ActionGuardBase
from aegis.actions.commands import analysis_for, matches_any
from aegis.actions.explain import Explain, mask
from aegis.actions.fs import check_path
from aegis.actions.net import check_url, extract_urls, parse_url
from aegis.actions.params import Exe02Params
from aegis.core.policy_schema import ControlConfig
from aegis.core.types import AppliesTo, ControlKind, Decision, Interaction, RequestContext

P = "controls[EXE-02].params"
SUFFIX = "Do not retry or work around this."
_NET_LABEL = {
    "metadata": "cloud metadata endpoint (SSRF)",
    "loopback": "loopback address (SSRF)",
    "private": "private network address (SSRF)",
    "link-local": "link-local address (SSRF)",
    "scheme": "disallowed URL scheme",
    "deny_host": "denied host",
    "not_allowlisted": "host outside the egress allowlist",
}


class ScopeGuard(ActionGuardBase):
    id: ClassVar[str] = "EXE-02"
    family: ClassVar[str] = "EXE"
    name: ClassVar[str] = "Filesystem & network scope (SSRF)"
    kind: ClassVar[ControlKind] = "deterministic"
    applies_to: ClassVar[AppliesTo] = AppliesTo(
        surfaces={"tool.input", "mcp.call", "egress.request"}, directions={"out"}
    )
    owasp: ClassVar[list[str]] = ["ASI02", "MCP05:2025", "MCP10:2025", "LLM03:2026"]
    priority: ClassVar[int] = 21
    params_model = Exe02Params
    default_levers: ClassVar[list[str]] = [
        f"{P}.fs_deny",
        f"{P}.allow_hosts",
        "destinations.egress_allowlist",
    ]

    # ------------------------------------------------------------------ extraction
    @staticmethod
    def _paths(i: Interaction, p: Exe02Params) -> list[tuple[str, str]]:
        if i.surface == "egress.request":
            return []
        op = "write" if matches_any(i.tool_name, p.write_tools) else "read"
        out: list[tuple[str, str]] = []
        args = i.tool_args or {}
        for key in p.path_args:
            val = args.get(key)
            vals = val if isinstance(val, list) else [val]
            for v in vals:
                if isinstance(v, str) and v.strip() and "://" not in v and len(v) < 4096:
                    out.append((v.strip(), op))
        a = analysis_for(i, max_chars=p.max_scan_chars)
        if a is not None:
            out.extend(a.all_paths())
        return list(dict.fromkeys(out))[:50]

    @staticmethod
    def _urls(i: Interaction, p: Exe02Params) -> list[str]:
        urls: list[str] = []
        if i.surface == "egress.request" and i.url:
            urls.append(i.url)
        args = i.tool_args or {}
        for key in p.url_args:
            # tool arguments only: on mcp.call/mcp.init ``interaction.url`` is the registered MCP
            # upstream (MCP-01 governs the registry), never an agent-chosen destination
            val = get_arg(i, key) if i.surface == "egress.request" else get_path(args, key)
            if isinstance(val, str) and "://" in val:
                urls.append(val.strip())
        a = analysis_for(i, max_chars=p.max_scan_chars)
        if a is not None:
            urls.extend(a.all_urls())
            for seg in a.all_segments():  # nc host port / telnet host port
                if seg.prog in ("nc", "ncat", "netcat", "telnet"):
                    pos = [x for x in seg.args if not x.startswith("-")]
                    if len(pos) >= 2 and pos[1].isdigit():
                        urls.append(f"tcp://{pos[0]}:{pos[1]}")
        if i.surface != "egress.request" and not urls:
            # free-text URLs in other string args (e.g. web.fetch_url {target: "..."})
            for key in ("target", "q"):
                val = (i.tool_args or {}).get(key)
                if isinstance(val, str):
                    urls.extend(extract_urls(val)[:3])
        return list(dict.fromkeys(urls))[:20]

    # ------------------------------------------------------------------ evaluate
    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        p: Exe02Params = self.params(cfg)
        cwd = interaction.meta.get("cwd")
        ex = Explain()
        # ---- filesystem
        for path, op in self._paths(interaction, p):
            res = check_path(
                path,
                op,
                deny=p.fs_deny,
                write_deny=p.fs_write_deny,
                exceptions=p.fs_allow_exceptions,
                allow=p.fs_allow or None,
                cwd=cwd if isinstance(cwd, str) else None,
                resolve_symlinks=p.resolve_symlinks,
            )
            if res.ok:
                if res.exception:
                    ex.check(
                        "fs_exception",
                        f"{op} {res.path}",
                        res.exception,
                        None,
                        "pass",
                        f"{P}.fs_allow_exceptions",
                    )
                continue
            what = {
                "fs_deny": "credential / sensitive file",
                "fs_write_deny": "protected file (write)",
                "fs_allow": "path outside the allowed workspace",
            }.get(res.rule, "protected path")
            ex.facts.update(
                {"path": res.path, "operation": op, "rule": res.rule, "pattern": res.pattern}
            )
            ex.check(
                res.rule,
                f"{op} {res.path}",
                res.pattern or "outside fs_allow",
                None,
                "fail",
                f"{P}.{res.rule}",
            )
            resource = f"file:{res.path}"
            if interaction.resource is None:
                interaction.resource = resource
            return self.hard(
                cfg,
                interaction,
                core=f"{what} — {op} of {res.path} is out of scope for agents",
                explain=ex,
                action_type="file.sensitive",
                suffix=SUFFIX,
                resource=resource,
                findings=[
                    self.finding(
                        f"exe.scope.{res.rule}",
                        category="scope",
                        severity="high",
                        excerpt=f"{op} {res.path}",
                        pattern=res.pattern,
                    )
                ],
            )
        # ---- network
        urls = self._urls(interaction, p)
        if urls:
            snap = art.policy_of(ctx)
            dest = getattr(getattr(snap, "doc", None), "destinations", None)
            allowlist = list(getattr(dest, "egress_allowlist", []) or [])
            deny = list(p.deny_hosts)
            internal: list[str] = []
            if allowlist or p.use_catalog_denylist:
                cat = await catmod.get_catalog()
                internal = catmod.internal_domains(snap, cat)
                if p.use_catalog_denylist:
                    deny.extend(h for h, m in cat.external_hosts.items() if m.get("denylisted"))
            upstreams = _mcp_upstreams(snap)
            for url in urls:
                if _is_upstream(url, upstreams):
                    ex.check(
                        "mcp_upstream",
                        "configured MCP server upstream",
                        mask(url, 80),
                        None,
                        "pass",
                        "mcp.servers[*].url",
                    )
                    continue
                schemes = list(p.allowed_schemes) + (["tcp"] if url.startswith("tcp://") else [])
                res = check_url(
                    url,
                    allowed_schemes=schemes,
                    block_private_ranges=p.block_private_ranges,
                    metadata_hosts=p.metadata_hosts,
                    allow_hosts=p.allow_hosts,
                    deny_hosts=deny,
                    egress_allowlist=allowlist,
                    internal_domains=internal,
                )
                if res.ok:
                    continue
                label = _NET_LABEL.get(res.rule, res.rule)
                host = res.host or "?"
                shown = f"{host}:{res.port}" if res.port and res.port not in (80, 443) else host
                ex.facts.update(
                    {
                        "url": mask(url, 120),
                        "host": host,
                        "port": res.port,
                        "ip": res.ip,
                        "rule": res.rule,
                    }
                )
                ex.check(
                    res.rule,
                    f"request to {shown}",
                    res.detail,
                    None,
                    "fail",
                    f"{P}.allow_hosts"
                    if res.rule in ("loopback", "private", "link-local", "metadata")
                    else "destinations.egress_allowlist"
                    if res.rule == "not_allowlisted"
                    else f"{P}.deny_hosts",
                )
                resource = f"host:{host}"
                return self.hard(
                    cfg,
                    interaction,
                    core=f"{label} — {shown}: {res.detail}",
                    explain=ex,
                    action_type=interaction.action_type or "egress.get",
                    suffix=SUFFIX,
                    resource=resource,
                    findings=[
                        self.finding(
                            f"exe.scope.{res.rule}",
                            category="scope",
                            severity="high",
                            excerpt=mask(url, 100),
                            host=host,
                        )
                    ],
                )
        return None


def _hp(url: str) -> tuple[str | None, int | None]:
    parsed = parse_url(url)
    if parsed is None or not parsed.hosts:
        return None, None
    return (parsed.host or "").lower(), parsed.port


def _mcp_upstreams(snap: object) -> set[tuple[str | None, int | None]]:
    """(host, port) of every configured ``mcp.servers[*].url`` (exempt from SSRF checks; B12)."""
    servers = getattr(getattr(getattr(snap, "doc", None), "mcp", None), "servers", None) or {}
    out: set[tuple[str | None, int | None]] = set()
    for srv in servers.values():
        url = getattr(srv, "url", None)
        if isinstance(url, str) and url:
            hp = _hp(url)
            if hp[0]:
                out.add(hp)
    return out


def _is_upstream(url: str, upstreams: set[tuple[str | None, int | None]]) -> bool:
    return bool(upstreams) and _hp(url) in upstreams


CONTROLS = [ScopeGuard()]

"""Org seed loader + `python -m aegis seed` CLI (CONTRACTS section 4.5, plan 08 section 2.3).

`load_seed(path)` parses YAML into `SeedDoc`; `map_seed(doc)` maps it onto the frozen models
(validating ids, sponsors, teams and key principals); `main(argv)` is the CLI
(`--check`, `--reset`, `--path`). The DB side lives in `aegis.org.store`.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from aegis.core.types import Agent, Member, Org, Team, utcnow
from aegis.org.models import SeedBundle, SeedDoc, SeedKey

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SEED = Path("config/org.seed.yaml")

KIND_MAP = {
    "coding_agent": "claude-code",
    "local_agent": "scripted",
    "remote_agent": "sdk",
    "mcp_client": "mcp-client",
}
CONTRACT_KINDS = {"claude-code", "scripted", "sdk", "mcp-client", "other"}
TIER_MAP = {"T0": "local", "T1": "remote", "T2": "third_party"}
DEST_CLASSES = {"local", "remote", "third_party"}
ROLES = {"owner", "admin", "member"}
PROVIDER_PREFIXES = ("anthropic/", "openai/", "ollama/", "openrouter/", "mock/")
MODEL_ALIASES = {"echo-llm": ["mock-echo"], "mock-echo-llm": ["mock-echo"]}
_MCP_TOOL = re.compile(r"^mcp__(.+?)__(.+)$")


class SeedError(ValueError):
    """Seed validation failure; `errors` holds `(path, message)` pairs."""

    def __init__(self, errors: list[tuple[str, str]]):
        self.errors = errors
        super().__init__("; ".join(f"{p}: {m}" for p, m in errors) or "invalid seed")


# ---------------------------------------------------------------- loading


def resolve_seed_path(path: str | Path | None = None) -> Path:
    """Relative paths: CWD first, then the repo root."""
    p = Path(path) if path else DEFAULT_SEED
    if p.is_absolute():
        return p
    if p.exists():
        return p.resolve()
    return (REPO_ROOT / p).resolve()


def load_seed(path: str | Path | None = None) -> tuple[SeedDoc, str]:
    """Parse the seed file -> (SeedDoc, sha256 of the file bytes). Raises SeedError."""
    p = resolve_seed_path(path)
    try:
        raw = p.read_bytes()
    except OSError as exc:
        raise SeedError([("", f"cannot read seed {p}: {exc}")]) from exc
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise SeedError([("", f"invalid YAML: {exc}")]) from exc
    if not isinstance(data, dict):
        raise SeedError([("", "seed must be a mapping")])
    try:
        doc = SeedDoc.model_validate(data)
    except ValidationError as exc:
        errs = [(_loc(e["loc"]), e["msg"]) for e in exc.errors()]
        raise SeedError(errs) from exc
    return doc, hashlib.sha256(raw).hexdigest()


def _loc(loc: tuple[Any, ...]) -> str:
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else str(part)
    return out


# ---------------------------------------------------------------- mapping helpers


def parse_dt(value: Any) -> datetime | None:
    """ISO string / datetime / date -> aware UTC datetime (naive = UTC)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            try:
                from datetime import date

                d = date.fromisoformat(text)
                dt = datetime(d.year, d.month, d.day)
            except ValueError as exc:
                raise ValueError(f"invalid datetime {value!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def map_models(allowed: list[str] | None) -> list[str]:
    """Provider-prefixed ids -> wire globs (CONTRACTS section 1.4 translation table)."""
    out: list[str] = []
    for raw in allowed or ["*"]:
        name = str(raw).strip()
        extra: list[str] = []
        for prefix in PROVIDER_PREFIXES:
            if name.startswith(prefix):
                name = name[len(prefix) :]
                break
        if name in MODEL_ALIASES:
            extra = MODEL_ALIASES[name]
            name = extra[0]
            extra = extra[1:]
        if name.startswith("qwen3.5:0.8b"):
            extra.append("aegis-judge*")
        for n in [name, *extra]:
            if n and n not in out:
                out.append(n)
    return out


def map_tool(name: str) -> str:
    """`mcp__<server>__<tool>` -> `<server>.<tool>` (globs preserved)."""
    m = _MCP_TOOL.match(str(name).strip())
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    return str(name).strip()


def map_dest(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    v = str(value).strip()
    v = TIER_MAP.get(v.upper(), v) if v.upper() in TIER_MAP else v
    return v


def principal_of(raw: str, member_ids: set[str], agent_ids: set[str]) -> str | None:
    """Seed key principal -> 'agent:<id>' | 'member:<id>' (None when unknown)."""
    p = str(raw).strip()
    if p.startswith(("agent:", "member:")):
        kind, _, ident = p.partition(":")
        ok = ident in (agent_ids if kind == "agent" else member_ids)
        return p if ok else None
    if p in agent_ids:
        return f"agent:{p}"
    if p in member_ids:
        return f"member:{p}"
    return None


_MEMBER_CORE = {
    "id",
    "name",
    "email",
    "role",
    "title",
    "teams",
    "team",
    "avatar_url",
    "active",
    "status",
}
_AGENT_CORE = {
    "id",
    "display_name",
    "name",
    "kind",
    "team",
    "sponsor",
    "description",
    "models",
    "tools",
    "max_destination",
    "max_destination_tier",
    "profile_override",
    "profile",
    "status",
    "active",
}
_TEAM_CORE = {"id", "name", "description", "color"}


def _extras(model: Any, core: set[str]) -> dict[str, Any]:
    extra = dict(getattr(model, "model_extra", None) or {})
    for name in type(model).model_fields:
        if name not in core:
            val = getattr(model, name)
            if val is not None and val != [] and val != {}:
                extra[name] = val
    return {k: v for k, v in extra.items() if k not in core}


# ---------------------------------------------------------------- mapping


def map_seed(doc: SeedDoc, *, sha256: str = "", now: datetime | None = None) -> SeedBundle:
    """Map + validate. Raises SeedError listing every problem with its YAML path."""
    now = now or utcnow()
    errors: list[tuple[str, str]] = []
    org_id = doc.org.id
    org = Org(id=org_id, name=doc.org.name)
    org_meta = {
        "description": (doc.org.description or "").strip() or None,
        "timezone": doc.org.timezone,
        "email_domain": doc.org.email_domain,
        "seed_version": doc.seed_version,
        "policy_profile": doc.org.initial_profile,
    }
    for k, v in (doc.org.model_extra or {}).items():
        org_meta.setdefault(k, v)

    team_ids: set[str] = set()
    teams: list[Team] = []
    for i, t in enumerate(doc.teams):
        if t.id in team_ids:
            errors.append((f"teams[{i}].id", f"duplicate team id {t.id!r}"))
        team_ids.add(t.id)
        meta = _extras(t, _TEAM_CORE)
        teams.append(
            Team(
                id=t.id,
                org_id=org_id,
                name=t.name,
                description=_strip(t.description),
                color=t.color,
                meta=meta,
            )
        )

    member_ids: set[str] = set()
    members: list[Member] = []
    for i, m in enumerate(doc.members):
        path = f"members[{i}]"
        if m.id in member_ids:
            errors.append((f"{path}.id", f"duplicate member id {m.id!r}"))
        member_ids.add(m.id)
        role = str(m.role).strip().lower()
        if role not in ROLES:
            errors.append((f"{path}.role", f"role must be owner|admin|member, got {m.role!r}"))
            role = "member"
        m_teams = list(m.teams) or ([m.team] if m.team else [])
        for j, tid in enumerate(m_teams):
            if tid not in team_ids:
                errors.append((f"{path}.teams[{j}]", f"unknown team {tid!r}"))
        active = _active(m.active, m.status)
        meta = _extras(m, _MEMBER_CORE)
        meta["teams"] = m_teams
        meta.pop("sponsor_of", None)  # informational; the binding link is agents[].sponsor
        members.append(
            Member(
                id=m.id,
                org_id=org_id,
                team_id=m_teams[0] if m_teams else None,
                name=m.name,
                email=m.email,
                role=role,
                title=m.title,
                avatar_url=m.avatar_url,
                active=active,
                created_at=now,
                meta=meta,
            )  # type: ignore[arg-type]
        )

    agent_ids: set[str] = set()
    agents: list[Agent] = []
    for i, a in enumerate(doc.agents):
        path = f"agents[{i}]"
        if a.id in agent_ids or a.id in member_ids:
            errors.append((f"{path}.id", f"duplicate id {a.id!r}"))
        agent_ids.add(a.id)
        if a.sponsor and a.sponsor not in member_ids:
            errors.append((f"{path}.sponsor", f"unknown member {a.sponsor!r}"))
        if a.team and a.team not in team_ids:
            errors.append((f"{path}.team", f"unknown team {a.team!r}"))
        raw_kind = (a.kind or "other").strip()
        kind = KIND_MAP.get(raw_kind, raw_kind if raw_kind in CONTRACT_KINDS else "other")
        dest = map_dest(a.max_destination or a.max_destination_tier)
        if dest is not None and dest not in DEST_CLASSES:
            errors.append(
                (f"{path}.max_destination", f"must be local|remote|third_party: {dest!r}")
            )
            dest = None
        meta = _extras(a, _AGENT_CORE)
        meta["seed_kind"] = raw_kind
        if a.models.default:
            meta["default_model"] = a.models.default
        for k, v in (a.models.model_extra or {}).items():
            meta.setdefault(f"models_{k}", v)
        agents.append(
            Agent(
                id=a.id,
                org_id=org_id,
                team_id=a.team,
                owner_member_id=a.sponsor,
                name=a.display_name or a.name or a.id,
                kind=kind,  # type: ignore[arg-type]
                description=_strip(a.description),
                profile=a.profile_override or a.profile,
                allowed_models=map_models(a.models.allowed),
                allowed_tools=[map_tool(t) for t in a.tools.allow],
                denied_tools=[map_tool(t) for t in a.tools.deny],
                max_destination=dest,  # type: ignore[arg-type]
                active=_active(a.active, a.status),
                created_at=now,
                meta=meta,
            )
        )

    keys: list[SeedKey] = []
    key_ids: set[str] = set()
    plaintexts: set[str] = set()
    for i, k in enumerate(doc.api_keys):
        path = f"api_keys[{i}]"
        if k.key_id in key_ids:
            errors.append((f"{path}.key_id", f"duplicate key id {k.key_id!r}"))
        key_ids.add(k.key_id)
        if not str(k.key).startswith("aegis_"):
            errors.append((f"{path}.key", "keys must start with 'aegis_'"))
        if k.key in plaintexts:
            errors.append((f"{path}.key", "duplicate key value"))
        plaintexts.add(k.key)
        principal = principal_of(k.principal, member_ids, agent_ids)
        if principal is None:
            errors.append((f"{path}.principal", f"unknown principal {k.principal!r}"))
            continue
        try:
            created, expires, revoked = (
                parse_dt(k.created_at),
                parse_dt(k.expires_at),
                parse_dt(k.revoked_at),
            )
        except ValueError as exc:
            errors.append((path, str(exc)))
            continue
        keys.append(
            SeedKey(
                key_id=k.key_id,
                principal=principal,
                plaintext=k.key,
                scopes=list(k.scopes),
                created_by=k.created_by,
                created_at=created,
                expires_at=expires,
                revoked_at=revoked,
            )
        )

    if not any(m.role == "owner" and m.active for m in members):
        errors.append(("members", "at least one active owner is required"))

    cp = doc.control_plane
    aliases: dict[str, str] = {}
    for alias, target in (cp.view_as_aliases or {}).items():
        if target not in member_ids:
            errors.append((f"control_plane.view_as_aliases.{alias}", f"unknown member {target!r}"))
        else:
            aliases[str(alias).lower()] = target
    if cp.default_viewer and cp.default_viewer not in member_ids:
        errors.append(("control_plane.default_viewer", f"unknown member {cp.default_viewer!r}"))

    if errors:
        raise SeedError(errors)
    return SeedBundle(
        org=org,
        org_meta=org_meta,
        teams=teams,
        members=members,
        agents=agents,
        keys=keys,
        resources=normalize_resources(
            doc.resources, internal_domains=(doc.org.model_extra or {}).get("internal_domains")
        ),
        view_as_aliases=aliases,
        default_viewer=cp.default_viewer,
        admin_token=cp.admin_token,
        seed_version=doc.seed_version,
        sha256=sha256,
    )


def _strip(text: str | None) -> str | None:
    return " ".join(text.split()) if text else text


def _active(active: bool | None, status: str | None) -> bool:
    if active is False:
        return False
    if status and str(status).strip().lower() in {"disabled", "inactive", "revoked", "retired"}:
        return False
    return True


def normalize_resources(
    res: dict[str, Any] | None, *, internal_domains: list[str] | None = None
) -> dict[str, Any]:
    """`resources` section in contract form (CONTRACTS A-37: mcp_server, dest_class,
    internal_domains)."""
    out: dict[str, Any] = dict(res or {})
    out.setdefault("internal_domains", list(internal_domains or []))
    dbs = []
    for db in out.get("databases") or []:
        db = dict(db)
        if "mock" in db and "mcp_server" not in db:
            db["mcp_server"] = db.pop("mock")
        tables = []
        for t in db.get("tables") or []:
            t = dict(t)
            t.setdefault("sensitivity", "INTERNAL")
            t.setdefault("categories", [])
            t.setdefault("contains", [])
            tables.append(t)
        db["tables"] = tables
        dbs.append(db)
    out["databases"] = dbs
    out["vendors"] = [dict(v) for v in out.get("vendors") or []]
    hosts = []
    for h in out.get("external_hosts") or []:
        h = dict(h)
        if "dest_class" not in h and h.get("tier"):
            h["dest_class"] = TIER_MAP.get(str(h["tier"]).upper(), "third_party")
        hosts.append(h)
    out["external_hosts"] = hosts
    return out


def load_bundle(path: str | Path | None = None) -> SeedBundle:
    doc, sha = load_seed(path)
    return map_seed(doc, sha256=sha)


# ---------------------------------------------------------------- CLI


def _settings() -> Any:
    try:
        from aegis.settings import get_settings

        return get_settings()
    except Exception:  # pragma: no cover - core-gateway always ships settings
        return None


def main(argv: list[str] | None = None) -> int:
    """`python -m aegis seed [--check] [--reset] [--path FILE]`."""
    parser = argparse.ArgumentParser(prog="aegis seed", description="Seed the Acme Capital org")
    parser.add_argument("--check", action="store_true", help="validate only (no DB access)")
    parser.add_argument("--reset", action="store_true", help="wipe org tables and reseed")
    parser.add_argument("--path", default=None, help="seed file (default AEGIS_ORG_SEED)")
    parser.add_argument("--no-demo-state", action="store_true", help="accepted (no-op here)")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    settings = _settings()
    path = args.path or (getattr(settings, "org_seed", None) if settings else None)
    try:
        bundle = load_bundle(path)
    except SeedError as exc:
        print(f"seed invalid ({resolve_seed_path(path)}):", file=sys.stderr)
        for p, msg in exc.errors:
            print(f"  {p or '<root>'}: {msg}", file=sys.stderr)
        return 1
    if args.check:
        print(bundle.summary())
        return 0

    from aegis.org import store

    data_dir = Path(getattr(settings, "data_dir", None) or "data")
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = store.connect(data_dir / "aegis.db")
    try:
        store.create_tables(conn)
        if not args.reset and store.org_count(conn) > 0:
            print(f"org already seeded ({data_dir / 'aegis.db'}); use --reset to reseed")
            return 0
        store.apply_seed(conn, bundle, reset=args.reset)
    finally:
        conn.close()
    print(("reseeded " if args.reset else "seeded ") + bundle.summary())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

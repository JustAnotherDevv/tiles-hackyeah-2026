"""ctl ACT-02 - Data access guard (tables by sensitivity & environment) (action-guards).

enrich: ``analyze_sql`` + catalog (``rt.org.resources()``) + standing grants -> refines
``action_type`` (db.read | db.write | db.schema), ``resource db:<most sensitive table>`` and labels
``sensitivity``, ``env``, ``operation`` (+ ``bulk``/``unbounded``, ``grant``).
evaluate ladder: unparseable -> prod DDL block -> RESTRICTED block -> standing grant -> low
sensitivity read -> single-row read -> soft (require_approval + draft with facts).
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Any, ClassVar

from aegis.actions import catalog as catmod
from aegis.actions import runtime as art
from aegis.actions.argpath import first_arg
from aegis.actions.base import ActionGuardBase
from aegis.actions.catalog import SENSITIVITY_RANK
from aegis.actions.classify import glob_match, normalize_tool_name, refine
from aegis.actions.commands import matches_any
from aegis.actions.explain import Explain
from aegis.actions.params import Act02Params
from aegis.actions.sql import SqlAnalysis, analyze_sql
from aegis.core.policy_schema import ControlConfig
from aegis.core.types import AppliesTo, ControlKind, Decision, Interaction, RequestContext

META = "act.data"
P = "controls[ACT-02].params"
_OP_TYPE = {
    "read": "db.read",
    "write": "db.write",
    "delete": "db.write",
    "ddl": "db.schema",
    "dcl": "db.schema",
}
_GRANT_OP = {"read": "read", "write": "write", "delete": "write", "ddl": "schema", "dcl": "schema"}


def _rank(s: str | None) -> int:
    return SENSITIVITY_RANK.get((s or "").upper(), SENSITIVITY_RANK["CONFIDENTIAL"])


def _max_sens(values: list[str]) -> str:
    return max(values, key=_rank) if values else "PUBLIC"


class DataAccessGuard(ActionGuardBase):
    id: ClassVar[str] = "ACT-02"
    family: ClassVar[str] = "ACT"
    name: ClassVar[str] = "Data access guard (tables by sensitivity & environment)"
    kind: ClassVar[ControlKind] = "deterministic"
    applies_to: ClassVar[AppliesTo] = AppliesTo(
        surfaces={"tool.input", "mcp.call"}, directions={"out"}
    )
    owasp: ClassVar[list[str]] = ["LLM02:2026", "LLM03:2026", "ASI02", "ASI03", "MCP02:2025"]
    priority: ClassVar[int] = 31
    params_model = Act02Params
    default_levers: ClassVar[list[str]] = [
        f"{P}.tables.<table>.sensitivity",
        f"{P}.auto_allow_max_sensitivity",
        "approvals.rules[db-*]",
    ]

    def _applies(self, i: Interaction, p: Act02Params) -> bool:
        at = i.action_type or ""
        return (
            at.startswith("db.")
            or matches_any(i.tool_name, p.db_tools)
            or self._mapped(i, p) is not None
        )

    @staticmethod
    def _mapped(i: Interaction, p: Act02Params) -> dict[str, Any] | None:
        name = normalize_tool_name(i.tool_name)
        for pat, spec in p.tool_tables.items():
            if name and glob_match(pat, name) and isinstance(spec, dict):
                return spec
        return None

    # ------------------------------------------------------------------ analysis
    async def _analyze(
        self, ctx: RequestContext, i: Interaction, p: Act02Params
    ) -> dict[str, Any] | None:
        mapped = self._mapped(i, p)
        sql_path, sql = first_arg(i, p.sql_args)
        if isinstance(sql, str) and sql.strip():
            a = analyze_sql(sql)
        elif mapped is not None:
            rows = mapped.get("rows")
            a = SqlAnalysis(
                ok=True,
                operation=str(mapped.get("operation", "read")),
                verbs=["LOOKUP"],
                tables=[str(mapped.get("table", "?"))],
                rows=None if rows in (None, "all") else int(rows),
            )  # type: ignore[arg-type]
        else:
            return None
        cat = await catmod.get_catalog(overrides=p.tables)
        _, db_arg = first_arg(i, ["database", "db", "database_id"])
        server = i.mcp_server or ((normalize_tool_name(i.tool_name) or "").split(".", 1)[0] or None)
        db_id = (
            (str(db_arg) if db_arg else None)
            or p.server_databases.get(server or "")
            or p.default_database
        )
        db = cat.database(db_id)
        env = db.environment if db else "prod"
        tables: list[dict[str, Any]] = []
        for t in a.tables:
            tbl = cat.table(db_id, t)
            tables.append(
                {
                    "name": t,
                    "sensitivity": tbl.sensitivity if tbl else p.unknown_table_sensitivity,
                    "categories": list(tbl.categories) if tbl else ["unknown"],
                    "known": tbl is not None,
                }
            )
        col_hits: list[dict[str, str]] = []
        for col in a.columns:
            short = col.rsplit(".", 1)[-1].strip('"`[]').lower()
            for pat, sens in p.sensitive_columns.items():
                if fnmatchcase(short, pat.lower()):
                    col_hits.append({"column": short, "sensitivity": sens})
                    break
        table_sens = _max_sens([t["sensitivity"] for t in tables])
        col_sens = _max_sens([c["sensitivity"] for c in col_hits])
        eff = (
            _max_sens([table_sens, col_sens])
            if (tables or col_hits)
            else p.unknown_table_sensitivity
        )
        if (
            a.operation == "read"
            and a.aggregate_only
            and _rank(eff) < SENSITIVITY_RANK["RESTRICTED"]
        ):
            cap = p.aggregate_max_sensitivity
            if _rank(eff) > _rank(cap):
                eff = cap
        most = max(tables, key=lambda t: _rank(t["sensitivity"]))["name"] if tables else None
        unbounded = a.unbounded_write
        grant = await self._grant(ctx, db_id, a, eff, unbounded)
        return {
            "database": db_id,
            "environment": env,
            "operation": a.operation,
            "statements": len(a.statements),
            "verbs": a.verbs,
            "ddl_verbs": a.ddl_verbs,
            "tables": tables,
            "columns": a.columns[:12],
            "sensitive_columns": col_hits,
            "select_star": a.select_star,
            "aggregate_only": a.aggregate_only,
            "rows": a.rows,
            "limit": a.limit,
            "has_where": a.has_where,
            "unbounded": unbounded,
            "sensitivity": eff,
            "resource_table": most,
            "grant": grant,
            "parsed": a.ok,
            "parse_error": a.error,
            "summary": a.summary(),
            "catalog": cat.source,
            "sql_arg": sql_path,
        }

    async def _grant(
        self, ctx: RequestContext, db_id: str, a: SqlAnalysis, sens: str, unbounded: bool
    ) -> str | None:
        agent = await art.agent_for(ctx)
        if agent is None or not a.ok or not a.tables:
            return None
        if unbounded or (a.select_star and _rank(sens) >= SENSITIVITY_RANK["CONFIDENTIAL"]):
            return None
        op = _GRANT_OP.get(a.operation)
        if op is None:
            return None
        for g in (agent.meta or {}).get("data_grants") or []:
            if not isinstance(g, dict):
                continue
            if g.get("database") not in (db_id, "*"):
                continue
            ops = [str(o).lower() for o in g.get("operations") or []]
            if op not in ops:
                continue
            globs = [str(t).lower() for t in g.get("tables") or []]
            if all(
                any(fnmatchcase(t.lower().rsplit(".", 1)[-1], gl) for gl in globs) for t in a.tables
            ):
                return "standing"
        return None

    # ------------------------------------------------------------------ enrich
    async def enrich(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> None:
        await super().enrich(ctx, interaction, cfg)
        p: Act02Params = self.params(cfg)
        if not self._applies(interaction, p):
            return
        f = await self._analyze(ctx, interaction, p)
        if f is None:
            return
        interaction.meta[META] = f
        labels: dict[str, Any] = {
            "sensitivity": f["sensitivity"],
            "env": f["environment"],
            "operation": f["operation"],
        }
        if f["unbounded"]:
            labels["unbounded"] = "true"
            if f["environment"] == "prod":
                labels["bulk"] = "true"
        if f["grant"]:
            labels["grant"] = f["grant"]
        refine(
            interaction,
            action_type=_OP_TYPE.get(f["operation"]) if f["parsed"] else None,
            resource=f"db:{f['resource_table']}" if f["resource_table"] else None,
            labels=labels,
        )

    # ------------------------------------------------------------------ evaluate
    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        p: Act02Params = self.params(cfg)
        if not self._applies(interaction, p):
            return None
        f = interaction.meta.get(META)
        if not isinstance(f, dict):
            f = await self._analyze(ctx, interaction, p)
            if f is None:
                return None
        at = interaction.action_type or _OP_TYPE.get(f["operation"], "db.read")
        ex = Explain(
            facts={
                k: f[k]
                for k in (
                    "database",
                    "environment",
                    "operation",
                    "tables",
                    "columns",
                    "select_star",
                    "rows",
                    "unbounded",
                    "grant",
                    "sensitivity",
                    "catalog",
                )
                if k in f
            }
        )
        ex.facts["query"] = f["summary"]
        tables = ", ".join(t["name"] for t in f["tables"]) or "?"
        sens, env, op = f["sensitivity"], f["environment"], f["operation"]
        agent = ctx.identity.agent_id or ctx.identity.member_id or "someone"
        common = {
            "action_type": at,
            "resource": interaction.resource,
            "title": f"{agent} wants to {op} {tables} ({sens}, {env})",
        }
        # 1. unparseable
        if not f["parsed"]:
            ex.check(
                "parse",
                "SQL parsed",
                f.get("parse_error") or "error",
                None,
                "fail",
                f"{P}.unparseable",
            )
            if p.unparseable == "block":
                return self.hard(
                    cfg,
                    interaction,
                    core="could not parse the SQL statement",
                    explain=ex,
                    action_type=at,
                )
            if p.unparseable in ("allow", "log"):
                return self.note(
                    cfg,
                    interaction,
                    core="could not parse the SQL statement",
                    action=p.unparseable,
                    explain=ex,
                    action_type=at,
                )
            return await self.soft(
                ctx,
                interaction,
                cfg,
                core="could not parse the SQL statement",
                explain=ex,
                **common,
            )
        # 2. prod DDL / DCL
        blocked_verbs = [
            v
            for v in f["ddl_verbs"]
            if v.upper() in {b.upper() for b in p.block_statements_in_prod}
        ]
        ex.check(
            "prod_ddl",
            "schema change in prod",
            ",".join(f["ddl_verbs"]) or "none",
            env,
            "fail" if blocked_verbs and env == "prod" else "pass",
            f"{P}.block_statements_in_prod",
        )
        if blocked_verbs and env == "prod":
            stacked = " (stacked statement)" if f["statements"] > 1 else ""
            return self.hard(
                cfg,
                interaction,
                explain=ex,
                action_type="db.schema",
                findings=[
                    self.finding(
                        "act.data.prod_ddl",
                        severity="critical",
                        excerpt=f"{blocked_verbs[0]} on {tables}",
                    )
                ],
                core=f"{blocked_verbs[0]} on {tables} in prod{stacked} — schema changes to production are not allowed",
            )
        # 3. RESTRICTED
        restricted = _rank(sens) >= SENSITIVITY_RANK["RESTRICTED"]
        ex.check(
            "restricted",
            "data sensitivity",
            sens,
            "RESTRICTED",
            "fail" if restricted else "pass",
            f"{P}.restricted_action",
        )
        if restricted:
            cats = sorted({c for t in f["tables"] for c in t["categories"]})
            fnd = [
                self.finding(
                    "act.data.restricted",
                    severity="critical",
                    data_class=sens if sens in ("RESTRICTED", "SECRET") else None,
                    excerpt=f"{op} {tables}",
                )
            ]
            core = (
                f"{op} of {tables} ({sens}{' · ' + ', '.join(cats) if cats else ''}) — "
                "no agent may read raw card data or secrets"
            )
            if p.restricted_action == "block":
                return self.hard(
                    cfg, interaction, core=core, findings=fnd, explain=ex, action_type=at
                )
            return await self.soft(
                ctx, interaction, cfg, core=core, findings=fnd, explain=ex, **common
            )
        # 4. standing grant
        ex.check(
            "grant",
            "standing data grant",
            f["grant"] or "none",
            None,
            "pass" if f["grant"] else "info",
            "org agents[].data_grants",
        )
        if f["grant"]:
            return self.note(
                cfg,
                interaction,
                explain=ex,
                action_type=at,
                core=f"{op} of {tables} covered by {agent}'s standing grant on {f['database']}",
            )
        # 5. low-sensitivity read
        low = op == "read" and _rank(sens) <= _rank(p.auto_allow_max_sensitivity)
        ex.check(
            "sensitivity",
            "read sensitivity vs auto-allow",
            sens,
            p.auto_allow_max_sensitivity,
            "pass" if low else "info",
            f"{P}.auto_allow_max_sensitivity",
        )
        if low:
            return self.note(
                cfg, interaction, explain=ex, action_type=at, core=f"read of {tables} ({sens})"
            )
        # 6. single-record read
        rows = f["rows"]
        small = (
            op == "read"
            and rows is not None
            and rows <= p.auto_allow_max_rows
            and not f["select_star"]
        )
        ex.check(
            "rows",
            "rows returned",
            rows if rows is not None else "unbounded",
            p.auto_allow_max_rows,
            "pass" if small else "info",
            f"{P}.auto_allow_max_rows",
        )
        if small:
            return self.note(
                cfg,
                interaction,
                action="log",
                explain=ex,
                action_type=at,
                core=f"single-record read of {tables} ({sens})",
            )
        # 7. soft
        bits = [sens, env]
        if f["select_star"]:
            bits.append("SELECT *")
        bits.append(
            "unbounded rows"
            if (rows is None and op == "read") or f["unbounded"]
            else f"{rows} rows"
        )
        fnd = [self.finding("act.data.sensitive_access", severity="high", excerpt=f["summary"])]
        return await self.soft(
            ctx,
            interaction,
            cfg,
            core=f"{op} of {tables} ({', '.join(bits)})",
            findings=fnd,
            explain=ex,
            **common,
        )


CONTROLS = [DataAccessGuard()]

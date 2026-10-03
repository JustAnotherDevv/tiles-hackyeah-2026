"""ctl ACT-01 - Spend guard (purchases, subscriptions, top-ups) (action-guards).

enrich: amount -> USD (``fx_to_usd``), vendor/plan from the resource catalog, catalog price check
(an understated ``$5`` for the ``$4,800`` plan is routed as ``$4,800``), sets
``interaction.amount_usd`` (BUD-01 reserves it) + labels ``vendor_approved``, ``recurring``,
``amount_unknown``.
evaluate ladder: missing amount -> hard cap -> unapproved vendor -> auto-allow -> soft
(``require_approval`` + ApprovalDraft; approvals-engine decides self/admin/owner/two-person).
"""

from __future__ import annotations

from typing import Any, ClassVar

from aegis.actions import catalog as catmod
from aegis.actions.argpath import first_arg, url_of
from aegis.actions.base import ActionGuardBase
from aegis.actions.classify import caller_supplied, render_title
from aegis.actions.explain import Explain, mask
from aegis.actions.money import fmt_usd, normalize_currency, parse_amount, to_usd
from aegis.actions.net import host_of
from aegis.actions.params import Act01Params
from aegis.core.policy_schema import ControlConfig
from aegis.core.types import AppliesTo, ControlKind, Decision, Interaction, RequestContext

META = "act.spend"
P = "controls[ACT-01].params"


def _agent_label(ctx: RequestContext) -> str:
    ident = ctx.identity
    return ident.agent_id or ident.display_name or ident.member_id or "someone"


class SpendGuard(ActionGuardBase):
    id: ClassVar[str] = "ACT-01"
    family: ClassVar[str] = "ACT"
    name: ClassVar[str] = "Spend guard (purchases, subscriptions, top-ups)"
    kind: ClassVar[ControlKind] = "deterministic"
    applies_to: ClassVar[AppliesTo] = AppliesTo(
        surfaces={"tool.input", "mcp.call", "egress.request"}, directions={"out"}
    )
    owasp: ClassVar[list[str]] = ["LLM03:2026", "ASI02", "ASI09", "LLM06:2026"]
    priority: ClassVar[int] = 30
    params_model = Act01Params
    default_levers: ClassVar[list[str]] = [
        f"{P}.auto_allow_max_usd",
        f"{P}.hard_block_above_usd",
        "approvals.rules[spend-*]",
    ]

    # ------------------------------------------------------------------ enrich
    async def enrich(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> None:
        await super().enrich(ctx, interaction, cfg)
        if not (interaction.action_type or "").startswith("spend."):
            return
        p: Act01Params = self.params(cfg)
        cat = await catmod.get_catalog()
        facts = self._analyze(interaction, p, cat)
        interaction.meta[META] = facts
        amount = facts["amount_usd"]
        if amount is not None:
            interaction.amount_usd = amount  # price check may raise a caller-supplied amount
        if facts["vendor"] and interaction.resource is None:
            interaction.resource = f"vendor:{facts['vendor']}"
        if facts["vendor"]:
            interaction.labels["vendor_approved"] = "true" if facts["vendor_approved"] else "false"
        interaction.labels["recurring"] = facts.get("recurring") or "none"
        if amount is None:
            interaction.labels["amount_unknown"] = "true"
        interaction.labels["capability"] = "spend"

    def _analyze(
        self, i: Interaction, p: Act01Params, cat: catmod.ResourceCatalog
    ) -> dict[str, Any]:
        # ---- declared amount (USD)
        original: float | None = None
        currency: str | None = None
        source = "args"
        declared: float | None = None
        if caller_supplied(i, "amount_usd") and i.amount_usd is not None:
            declared, currency, source = float(i.amount_usd), "USD", "caller"
            original = declared
        else:
            path, val = first_arg(i, p.amount_args)
            if path is not None:
                original, currency = parse_amount(val)
                if currency is None:
                    if path.endswith(("_usd", ".usd")):
                        currency = "USD"
                    else:
                        _, cval = first_arg(i, p.currency_args)
                        currency = normalize_currency(cval) if cval is not None else "USD"
                if original is not None:
                    fx = {k.upper(): v for k, v in p.fx_to_usd.items()}
                    declared = to_usd(original, currency, fx) if (currency or "USD") in fx else None
                    if declared is None:
                        source = "unknown_currency"
            elif i.amount_usd is not None:
                declared, currency, source, original = (
                    float(i.amount_usd),
                    "USD",
                    "rule",
                    float(i.amount_usd),
                )
            if declared is None and p.amount_from_text:
                from aegis.actions.money import amount_from_text

                _, tval = first_arg(i, p.text_args)
                if isinstance(tval, str):
                    amt, ccy = amount_from_text(tval)
                    if amt is not None:
                        original, currency, source = amt, ccy or "USD", "text"
                        declared = to_usd(
                            amt, currency, {k.upper(): v for k, v in p.fx_to_usd.items()}
                        )
        # ---- vendor / plan
        vendor = None
        if i.resource and i.resource.startswith("vendor:"):
            vendor = cat.vendor(i.resource)
        vendor_ref = None
        if vendor is None:
            _, vendor_ref = first_arg(i, p.vendor_args)
            vendor = cat.vendor(vendor_ref) if vendor_ref is not None else None
        if vendor is None:
            server = i.mcp_server or (
                (i.tool_name or "").split(".", 1)[0] if "." in (i.tool_name or "") else None
            )
            vendor = cat.vendor_for_server(server) or cat.vendor_for_host(host_of(url_of(i)))
        _, plan_ref = first_arg(i, p.plan_args)
        pv, plan = cat.plan(plan_ref, vendor)
        if vendor is None and pv is not None:
            vendor = pv
        catalog_price = plan.usd if plan is not None else None
        amount = declared
        mismatch = False
        if p.price_check and catalog_price is not None:
            if declared is None:
                amount, source = catalog_price, "catalog"
            elif catalog_price > declared + 0.005:
                amount, source, mismatch = catalog_price, "catalog_price_check", True
        amount = round(amount, 2) if amount is not None else None
        return {
            "vendor": vendor.id if vendor else None,
            "vendor_name": vendor.name
            if vendor
            else (mask(str(vendor_ref), 60) if vendor_ref else None),
            "vendor_approved": bool(vendor.approved) if vendor else False,
            "vendor_known": vendor is not None,
            "plan": plan.id if plan else (mask(str(plan_ref), 60) if plan_ref else None),
            "recurring": plan.recurring if plan else "none",
            "amount_usd": amount,
            "amount_declared_usd": round(declared, 2) if declared is not None else None,
            "amount_original": original,
            "currency": currency,
            "catalog_price_usd": catalog_price,
            "amount_source": source,
            "amount_mismatch": mismatch,
            "catalog": cat.source,
        }

    # ------------------------------------------------------------------ evaluate
    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        at = interaction.action_type or ""
        if not at.startswith("spend."):
            return None
        p: Act01Params = self.params(cfg)
        f = interaction.meta.get(META)
        if not isinstance(f, dict):
            f = self._analyze(interaction, p, await catmod.get_catalog())
        amount = f["amount_usd"]
        ex = Explain(facts={k: v for k, v in f.items() if k not in ("vendor_known",)})
        findings = []
        if f["amount_mismatch"]:
            findings.append(
                self.finding(
                    "act.spend.amount_mismatch",
                    severity="high",
                    excerpt=f"declared {fmt_usd(f['amount_declared_usd'])}, catalog {fmt_usd(f['catalog_price_usd'])}",
                )
            )
            ex.check(
                "price_check",
                "declared amount vs catalog price",
                f["amount_declared_usd"],
                f["catalog_price_usd"],
                "fail",
                f"{P}.price_check",
            )
        elif f["catalog_price_usd"] is not None:
            ex.check(
                "price_check",
                "declared amount vs catalog price",
                f["amount_declared_usd"],
                f["catalog_price_usd"],
                "pass",
                f"{P}.price_check",
            )
        what = self._what(f)
        values = {
            "agent": _agent_label(ctx),
            "member": ctx.identity.member_id or "",
            "amount": f"{amount:,.2f}" if amount is not None else "?",
            "resource": interaction.resource or "",
            "tool": interaction.tool_name or "",
            "vendor": f.get("vendor_name") or f.get("vendor") or "",
            "plan": f.get("plan") or "",
        }
        rule = self._rule(ctx, interaction)
        title = render_title(getattr(rule, "title", None), values, interaction, mask) or (
            f"{values['agent']} wants to spend {fmt_usd(amount) if amount is not None else 'an unknown amount'} on {what}"
        )
        common = {
            "action_type": at,
            "title": title,
            "amount_usd": amount,
            "resource": interaction.resource,
        }

        # 1. unknown amount
        if amount is None:
            ex.check("amount", "amount known", None, None, "fail", f"{P}.missing_amount")
            if p.missing_amount == "block":
                return self.hard(
                    cfg,
                    interaction,
                    core=f"spending on {what} with no verifiable amount",
                    findings=findings,
                    explain=ex,
                    action_type=at,
                )
            return await self.soft(
                ctx,
                interaction,
                cfg,
                core=f"spending an unknown amount on {what} (routed to owner)",
                findings=findings,
                explain=ex,
                labels={"amount_unknown": "true"},
                **common,
            )
        # 2. hard cap
        over = amount > p.hard_block_above_usd
        ex.check(
            "hard_cap",
            "amount vs hard cap",
            amount,
            p.hard_block_above_usd,
            "fail" if over else "pass",
            f"{P}.hard_block_above_usd",
        )
        if over:
            findings.append(
                self.finding(
                    "act.spend.hard_cap",
                    severity="critical",
                    excerpt=f"{fmt_usd(amount)} > {fmt_usd(p.hard_block_above_usd)}",
                )
            )
            return self.hard(
                cfg,
                interaction,
                findings=findings,
                explain=ex,
                action_type=at,
                core=(
                    f"spending {fmt_usd(amount)} on {what} exceeds the hard cap of "
                    f"{fmt_usd(p.hard_block_above_usd)}; no approval path"
                ),
            )
        # 3. vendor
        vendor_ok = f["vendor_known"] and f["vendor_approved"]
        ex.check(
            "vendor",
            "vendor approved",
            f.get("vendor") or "unknown",
            None,
            "pass" if vendor_ok else "fail",
            f"{P}.unapproved_vendor",
        )
        if not vendor_ok:
            findings.append(
                self.finding(
                    "act.spend.unapproved_vendor",
                    severity="high",
                    excerpt=str(f.get("vendor_name") or "unknown vendor"),
                )
            )
            if p.unapproved_vendor == "block":
                return self.hard(
                    cfg,
                    interaction,
                    core=f"{what} is not an approved vendor",
                    findings=findings,
                    explain=ex,
                    action_type=at,
                )
            if p.unapproved_vendor == "require_approval":
                return await self.soft(
                    ctx,
                    interaction,
                    cfg,
                    findings=findings,
                    explain=ex,
                    core=f"spending {fmt_usd(amount)} on {what} (vendor not approved)",
                    labels={"vendor_approved": "false"},
                    **common,
                )
        # 4. auto-allow band
        auto = amount <= p.auto_allow_max_usd
        ex.check(
            "auto_allow",
            "amount vs auto-allow limit",
            amount,
            p.auto_allow_max_usd,
            "pass" if auto else "info",
            f"{P}.auto_allow_max_usd",
        )
        if auto:
            return self.note(
                cfg,
                interaction,
                core=f"spending {fmt_usd(amount)} on {what} is within the auto-allow limit",
                explain=ex,
                action_type=at,
                findings=findings,
            )
        # 5. soft (approvals-engine routes by amount)
        return await self.soft(
            ctx,
            interaction,
            cfg,
            core=f"spending {fmt_usd(amount)} on {what}",
            findings=findings,
            explain=ex,
            **common,
        )

    @staticmethod
    def _what(f: dict[str, Any]) -> str:
        name = f.get("vendor_name") or f.get("vendor") or "an unknown vendor"
        extra = [
            x
            for x in (
                f.get("plan"),
                f.get("recurring") if f.get("recurring") not in (None, "none") else None,
            )
            if x
        ]
        return f"{name} ({', '.join(extra)})" if extra else str(name)

    @staticmethod
    def _rule(ctx: RequestContext, interaction: Interaction) -> Any:
        from aegis.actions import runtime as art

        rid = interaction.meta.get("act.rule")
        if not rid:
            return None
        return next((r for r in art.action_rules(ctx) if r.id == rid), None)


CONTROLS = [SpendGuard()]

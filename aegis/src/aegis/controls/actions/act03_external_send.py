"""ctl ACT-03 - External send guard (email, webhooks, uploads) (action-guards).

Recipients from ``to/cc/bcc/recipient(s)`` (split on ``,;``) or the URL host (egress). A recipient
is internal when it matches ``destinations.internal_domains`` ∪ catalog ``internal_domains``.
Denylisted recipients/hosts -> block. All internal -> allow (refined to ``email.internal``).
Payload data class = max over ``rt.redactor.detect`` spans, vault placeholders (``[PESEL_1]``
counts as its entity's class, SF-04) and a built-in Luhn PAN check. RESTRICTED/SECRET to an
external recipient -> block; otherwise soft ``require_approval`` with labels ``data_class``,
``recipients``, ``dest_host`` (+ ``bulk`` above ``max_recipients``).
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from aegis.actions import catalog as catmod
from aegis.actions import runtime as art
from aegis.actions.argpath import get_arg, string_leaves, url_of
from aegis.actions.base import ActionGuardBase
from aegis.actions.catalog import SENSITIVITY_RANK
from aegis.actions.classify import refine
from aegis.actions.commands import matches_any
from aegis.actions.explain import Explain, mask_email
from aegis.actions.net import domain_match, host_of
from aegis.actions.params import Act03Params
from aegis.core.policy_schema import ControlConfig
from aegis.core.types import AppliesTo, ControlKind, Decision, Interaction, RequestContext

P = "controls[ACT-03].params"
META = "act.send"
_EMAIL_RX = re.compile(r"[A-Za-z0-9._%+\-]+@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})")
_PLACEHOLDER_RX = re.compile(r"\[([A-Z][A-Z0-9_]*?)_\d+\]")
_PAN_RX = re.compile(r"(?<!\d)(?:\d[ \-]?){13,19}(?!\d)")
ENTITY_CLASS: dict[str, str] = {
    "PAN": "RESTRICTED",
    "CREDIT_CARD": "RESTRICTED",
    "CARD_EXPIRY": "RESTRICTED",
    "CVV": "RESTRICTED",
    "SECRET": "SECRET",
    "API_KEY": "SECRET",
    "AWS_ACCESS_KEY": "SECRET",
    "PASSWORD": "SECRET",
    "PRIVATE_KEY": "SECRET",
    "JWT": "SECRET",
    "TOKEN": "SECRET",
    "PERSON": "CONFIDENTIAL",
    "EMAIL": "CONFIDENTIAL",
    "PHONE": "CONFIDENTIAL",
    "PESEL": "CONFIDENTIAL",
    "NIP": "CONFIDENTIAL",
    "REGON": "CONFIDENTIAL",
    "IBAN": "CONFIDENTIAL",
    "ADDRESS": "CONFIDENTIAL",
    "DOB": "CONFIDENTIAL",
    "ID_CARD": "CONFIDENTIAL",
    "PASSPORT": "CONFIDENTIAL",
    "ACCOUNT": "CONFIDENTIAL",
    "IP_ADDRESS": "INTERNAL",
    "HOSTNAME": "INTERNAL",
    "INTERNAL_URL": "INTERNAL",
    "USERNAME": "INTERNAL",
    "PATH": "INTERNAL",
}
SEND_TYPES = ("email.external", "email.internal", "egress.post")


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def _card_ok(digits: str) -> bool:
    try:
        from aegis.redaction.validators import card_ok  # type: ignore[import-not-found]

        return bool(card_ok(digits))
    except Exception:  # TODO(integration): redaction-engine validators not importable
        return 13 <= len(digits) <= 19 and _luhn(digits)


def _rank(c: str | None) -> int:
    return SENSITIVITY_RANK.get((c or "PUBLIC").upper(), 0)


def _split(val: Any) -> list[str]:
    if isinstance(val, str):
        return [x.strip() for x in re.split(r"[,;]", val) if x.strip()]
    if isinstance(val, list | tuple):
        out: list[str] = []
        for v in val:
            if isinstance(v, dict):
                v = v.get("email") or v.get("address")
            out.extend(_split(v))
        return out
    if isinstance(val, dict):
        return _split(val.get("email") or val.get("address"))
    return []


class ExternalSendGuard(ActionGuardBase):
    id: ClassVar[str] = "ACT-03"
    family: ClassVar[str] = "ACT"
    name: ClassVar[str] = "External send guard (email, webhooks, uploads)"
    kind: ClassVar[ControlKind] = "deterministic"
    applies_to: ClassVar[AppliesTo] = AppliesTo(
        surfaces={"tool.input", "mcp.call", "egress.request"}, directions={"out"}
    )
    owasp: ClassVar[list[str]] = ["LLM02:2026", "ASI01", "ASI02", "MCP10:2025"]
    priority: ClassVar[int] = 32
    params_model = Act03Params
    default_levers: ClassVar[list[str]] = [
        "destinations.internal_domains",
        f"{P}.max_recipients",
        "approvals.rules[send-*]",
    ]

    def _applies(self, i: Interaction, p: Act03Params) -> bool:
        at = i.action_type or ""
        if at.startswith(("spend.", "db.")):
            return False  # ACT-01 / ACT-02 govern these (e.g. POST pay.saas.test/payments/*)
        return at in SEND_TYPES or matches_any(i.tool_name, p.send_tools)

    # ------------------------------------------------------------------ analysis
    def _data_class(self, i: Interaction, p: Act03Params) -> tuple[str, list[str]]:
        texts: list[str] = []
        args = i.tool_args or {}
        for key in p.body_args:
            val = get_arg(i, key) if key != "json" else args.get("json")
            if isinstance(val, str):
                texts.append(val)
            elif isinstance(val, dict | list):
                texts.extend(v for _, v in string_leaves(val, limit=100))
        text = "\n".join(texts)[:20_000]
        best, entities = "PUBLIC", []
        if not text:
            return best, entities
        for m in _PLACEHOLDER_RX.finditer(text):
            ent = m.group(1)
            cls = ENTITY_CLASS.get(ent, "CONFIDENTIAL")
            entities.append(ent)
            if _rank(cls) > _rank(best):
                best = cls
        for m in _PAN_RX.finditer(text):
            digits = re.sub(r"\D", "", m.group(0))
            if _card_ok(digits):
                entities.append("PAN")
                best = "RESTRICTED" if _rank("RESTRICTED") > _rank(best) else best
        rt = art.current_rt()
        red = getattr(rt, "redactor", None) if rt is not None else None
        if red is not None:
            try:
                for span in red.detect(text):
                    entities.append(span.entity)
                    if _rank(span.data_class) > _rank(best):
                        best = str(span.data_class)
            except Exception:
                pass
        return best, list(dict.fromkeys(entities))[:12]

    async def _analyze(self, ctx: RequestContext, i: Interaction, p: Act03Params) -> dict[str, Any]:
        cat = await catmod.get_catalog()
        internal = catmod.internal_domains(art.policy_of(ctx), cat, p.internal_domains)
        recips: list[dict[str, Any]] = []
        for key in p.recipient_args:
            for r in _split(get_arg(i, key)):
                m = _EMAIL_RX.search(r)
                dom = m.group(1).lower() if m else None
                if dom is None:
                    continue  # channel names etc. are not external recipients
                recips.append(
                    {
                        "masked": mask_email(r),
                        "domain": dom,
                        "internal": any(domain_match(d, dom) for d in internal),
                        "denied": any(domain_match(d, dom) for d in p.deny_recipients)
                        or cat.denylisted(dom),
                    }
                )
        host = host_of(url_of(i))
        host_internal = bool(host) and any(domain_match(d, host) for d in internal)
        host_denied = bool(host) and (
            cat.denylisted(host) or any(domain_match(d, host) for d in p.deny_hosts)
        )
        data_class, entities = self._data_class(i, p)
        return {
            "recipients": recips,
            "host": host,
            "host_internal": host_internal,
            "host_denied": host_denied,
            "data_class": data_class,
            "entities": entities,
            "catalog": cat.source,
        }

    # ------------------------------------------------------------------ enrich
    async def enrich(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> None:
        await super().enrich(ctx, interaction, cfg)
        p: Act03Params = self.params(cfg)
        if not self._applies(interaction, p):
            return
        f = await self._analyze(ctx, interaction, p)
        interaction.meta[META] = f
        recips = f["recipients"]
        labels: dict[str, Any] = {"data_class": f["data_class"]}
        if recips:
            labels["recipients"] = str(len(recips))
            all_internal = all(r["internal"] for r in recips)
            if (interaction.action_type or "").startswith(
                "email."
            ) or interaction.action_type is None:
                refine(
                    interaction, action_type="email.internal" if all_internal else "email.external"
                )
            if len(recips) > p.max_recipients:
                labels["bulk"] = "true"
        elif f["host"]:
            labels["dest_host"] = f["host"]
            if interaction.action_type is None:
                refine(interaction, action_type="egress.post")
        if f["host"]:
            labels["dest_host"] = f["host"]
        refine(interaction, labels=labels)
        if interaction.resource is None and f["host"]:
            interaction.resource = f"host:{f['host']}"

    # ------------------------------------------------------------------ evaluate
    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        p: Act03Params = self.params(cfg)
        if not self._applies(interaction, p):
            return None
        f = interaction.meta.get(META)
        if not isinstance(f, dict):
            f = await self._analyze(ctx, interaction, p)
        recips = f["recipients"]
        at = interaction.action_type or ("email.external" if recips else "egress.post")
        ext = [r for r in recips if not r["internal"]]
        dest = ", ".join(r["masked"] for r in recips[:3]) + (
            f" +{len(recips) - 3}" if len(recips) > 3 else ""
        )
        if not recips:
            dest = f["host"] or "an external destination"
        ex = Explain(
            facts={
                "recipients": [
                    {"masked": r["masked"], "internal": r["internal"]} for r in recips[:10]
                ],
                "hosts": [f["host"]] if f["host"] else [],
                "data_class": f["data_class"],
                "entities": f["entities"],
            }
        )
        agent = ctx.identity.agent_id or ctx.identity.member_id or "someone"
        # 1. denylisted
        denied = [r for r in recips if r["denied"]]
        if denied or f["host_denied"]:
            ex.check(
                "denylist", "destination denylisted", dest, None, "fail", f"{P}.deny_recipients"
            )
            core = f"sending to {', '.join(r['masked'] for r in denied) or f['host']} — destination is denylisted"
            fnd = [
                self.finding("act.send.denylisted", category="exfil", severity="high", excerpt=dest)
            ]
            if p.denylisted_hosts_action == "block":
                return self.hard(
                    cfg, interaction, core=core, findings=fnd, explain=ex, action_type=at
                )
            return await self.soft(
                ctx,
                interaction,
                cfg,
                core=core,
                findings=fnd,
                explain=ex,
                action_type=at,
                title=f"{agent} wants to send data to {dest}",
            )
        # 2. internal only
        internal_only = (recips and not ext) or (not recips and f["host_internal"])
        ex.check(
            "internal",
            "all recipients internal",
            len(recips) - len(ext),
            len(recips),
            "pass" if internal_only else "info",
            "destinations.internal_domains",
        )
        if internal_only:
            return self.note(
                cfg, interaction, core=f"internal send to {dest}", explain=ex, action_type=at
            )
        # 3. data class to external
        cls = f["data_class"]
        bad = cls in {c.upper() for c in p.block_data_classes}
        ex.check(
            "data_class",
            "payload data class",
            cls,
            ",".join(p.block_data_classes),
            "fail" if bad else "pass",
            f"{P}.block_data_classes",
        )
        if bad:
            return self.hard(
                cfg,
                interaction,
                explain=ex,
                action_type=at,
                core=f"sending {cls} data ({', '.join(f['entities'][:3]) or cls}) to external {dest}",
                findings=[
                    self.finding(
                        "act.send.restricted_payload",
                        category="exfil",
                        severity="critical",
                        data_class=cls,
                        excerpt=dest,
                    )
                ],
            )
        # 4. soft
        many = len(recips) > p.max_recipients
        ex.check(
            "recipients",
            "recipient count",
            len(recips),
            p.max_recipients,
            "fail" if many else "pass",
            f"{P}.max_recipients",
        )
        core = f"sending {cls} data to external {dest}"
        return await self.soft(
            ctx,
            interaction,
            cfg,
            core=core,
            explain=ex,
            action_type=at,
            title=f"{agent} wants to send {cls.lower()} data to {dest}",
            resource=interaction.resource,
            labels={
                "data_class": cls,
                "recipients": str(len(recips)),
                **({"bulk": "true"} if many else {}),
            },
            findings=[
                self.finding(
                    "act.send.external",
                    category="exfil",
                    severity="medium",
                    data_class=cls,
                    excerpt=dest,
                )
            ],
        )


CONTROLS = [ExternalSendGuard()]

"""Scene 8 · F5 config governance (+ pointer to the F6 runaway agent).

    uv run --frozen python demo/scenarios/run.py s8 [--approve-as u_emily]

1. u_piotr (member) raises `team:trading` USD/day $60 → $75 (+25 %) → GOV-05 → rule
   `raise-team-small` → needs an admin. u_emily approves → the executor applies the patch →
   policy v+1 → the Budgets gauges move live.
2. u_piotr asks for $60 → $150 (+150 %) → `raise-large` → needs the owner (left pending for the
   presenter, cancelled with `--cleanup`).
3. u_marek (admin) disables DLP-02 (critical) → needs the owner.
4. The owner tightens directly → applied immediately (no card).
F6 lives in `demo/agents/runaway.py` (`run.py runaway`).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src")]

from aegis.sdk import AegisAdmin, AegisClient  # noqa: E402
from aegis.sdk.results import AegisError  # noqa: E402
from demo.agents._common import (  # noqa: E402
    action_tag,
    banner,
    console,
    escape,
    say,
    section,
    wait_approval,
)
from demo.agents.catalog import disable_control_yaml  # noqa: E402

TITLE = "F5 · config governance: who may raise budgets and disable controls"


def _limit(admin: AegisAdmin, scope: str) -> float | None:
    for view in admin.budgets().get("scopes") or []:
        if view.get("scope") == scope:
            for b in view.get("limits") or []:
                if b.get("dimension") == "usd" and b.get("window") == "day":
                    return float(b.get("limit") or 0)
    return None


def _show(label: str, res: dict) -> str | None:
    apr = res.get("approval") or {}
    status = res.get("status")
    action = "require_approval" if status == "pending_approval" else (
        "allow" if status == "applied" else "block")
    extra = ""
    if apr:
        extra = f" · needs {apr.get('required_role')}{' + two-person' if apr.get('two_person') else ''}" \
                f" · rule {apr.get('rule_id')}"
    console.print(f"  {label:<52} {action_tag(action, 'GOV-05' if apr else None)}{escape(extra)}")
    return apr.get("id")


def run(opts: argparse.Namespace) -> bool | None:
    banner("u_piotr (member) · u_marek (admin) · u_katarzyna (owner)", TITLE, url=opts.url)
    ok = True
    leftovers: list[str] = []
    piotr = AegisAdmin(opts.url, view_as="u_piotr")
    owner = AegisAdmin(opts.url, view_as="u_katarzyna")
    try:
        base = _limit(owner, "team:trading") or 60.0
        section(f"u_piotr proposes budget raises on team:trading (now ${base:.0f}/day)")
        small = round(base * 1.25)
        res = piotr.budgets_raise("team:trading", "day", "usd", small,
                                  "more research calls during earnings week")
        apr_small = _show(f"${base:.0f} → ${small} (+25 %)", res)
        ok &= res.get("status") == "pending_approval" and \
            (res.get("approval") or {}).get("required_role") == "admin"
        res2 = piotr.budgets_raise("team:trading", "day", "usd", round(base * 2.5),
                                   "run the backtest grid on GPT")
        apr_large = _show(f"${base:.0f} → ${round(base * 2.5)} (+150 %)", res2)
        ok &= (res2.get("approval") or {}).get("required_role") == "owner"
        leftovers += [a for a in (apr_large,) if a]

        section("u_marek (admin) disables DLP-02 (critical)")
        with AegisAdmin(opts.url, view_as="u_marek") as marek:
            pol = marek.policy()
            res3 = marek.policy_apply(disable_control_yaml(pol.get("yaml") or "", "DLP-02"),
                                      pol.get("version"), "too many false positives")
        apr_dlp = _show("controls[DLP-02].enabled true → false", res3)
        ok &= (res3.get("approval") or {}).get("required_role") == "owner"
        leftovers += [a for a in (apr_dlp,) if a]

        if apr_small:
            section("an admin decides the +25 % raise")
            with AegisClient(opts.url) as c:
                final = wait_approval(c, apr_small, timeout=opts.approval_timeout,
                                      approve_as=opts.approve_as or None,
                                      approve_after=opts.approve_after, quiet=opts.quiet)
            if final.get("status") == "approved":
                new = _limit(owner, "team:trading")
                say(f"[green]team:trading now ${new:.0f}/day · policy "
                    f"v{(final.get('execution') or {}).get('policy_version', '?')}[/green]")
            elif final.get("status") == "pending":
                leftovers.append(apr_small)
    except AegisError as e:
        say(f"[red]API error: {escape(e.message)}[/red]")
        ok = False
    finally:
        if getattr(opts, "cleanup", True):
            for apr in leftovers:
                try:
                    owner.cancel(apr)
                except AegisError:
                    pass
            if leftovers:
                say(f"[bright_black]cancelled {len(leftovers)} demo card(s) (--no-cleanup keeps "
                    "them for the presenter)[/bright_black]")
        piotr.close()
        owner.close()
    say("[bright_black]F6 runaway agent: uv run --frozen python demo/agents/runaway.py[/bright_black]")
    return ok

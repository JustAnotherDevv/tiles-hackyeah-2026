"""Chaos agent — red-team sweep over `catalog.py`: every control family, every approval kind.

    uv run --frozen python demo/agents/chaos_agent.py                  # full sweep, table
    uv run --frozen python demo/agents/chaos_agent.py --fast           # skip the budget burner
    uv run --frozen python demo/agents/chaos_agent.py --family injection,data
    uv run --frozen python demo/agents/chaos_agent.py --only spend-50,curl-sh --approve
    uv run --frozen python demo/agents/chaos_agent.py --json           # + data/demo/chaos.json

Grades: ✓ action + control (+ approver role) as expected · ≈ action as expected, another control
decided · ✗ wrong action · · skipped (side service down, or the control is "configured, not
implemented" per `/api/controls`). Approval cards created by the sweep are cancelled at the end
(`--approve` instead approves *action* cards as the right human — never as the agent;
`--keep-pending` leaves them for the presenter). Exit 1 when fewer than `--min-pass` % of the
non-skipped steps are ✓/≈.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src")]

import httpx  # noqa: E402
from rich.table import Table  # noqa: E402

from aegis.sdk import DEMO_AGENT_SPONSORS, AegisAdmin  # noqa: E402
from aegis.sdk.results import AegisError  # noqa: E402
from demo.agents._common import (  # noqa: E402
    EXIT_MISMATCH,
    EXIT_OK,
    action_tag,
    banner,
    base_parser,
    console,
    escape,
    fresh_session,
    require_gateway,
    short,
)
from demo.agents.catalog import (  # noqa: E402
    EXFIL,
    KILL_STEP,
    STEPS,
    Ctx,
    Outcome,
    Step,
    execute,
    grade,
    ordered,
)

GRADE_STYLE = {"✓": "green", "≈": "yellow", "✗": "bold red", "·": "bright_black"}
ROLE_APPROVER = {"admin": "u_emily", "owner": "u_katarzyna"}


def implemented_controls(base_url: str) -> dict[str, bool]:
    try:
        with AegisAdmin(base_url, view_as="u_katarzyna") as a:
            return {c["id"]: bool(c.get("implemented", True)) and bool(c.get("enabled", True))
                    for c in a.controls()}
    except AegisError:
        return {}


def exfil_hits() -> int | None:
    try:
        return int(httpx.get(f"{EXFIL}/_mock/hits", timeout=2).json().get("count") or 0)
    except (httpx.HTTPError, ValueError):
        return None


def select(opts: Any) -> list[Step]:
    steps = list(STEPS)
    if opts.family:
        fams = {f.strip() for f in opts.family.split(",") if f.strip()}
        steps = [s for s in steps if s.family in fams]
    if opts.only:
        ids = [i.strip() for i in opts.only.split(",") if i.strip()]
        steps = [s for s in steps if s.id in ids]
    if opts.fast:
        steps = [s for s in steps if not s.burner]
    if opts.no_config:
        steps = [s for s in steps if s.family != "config"]
    steps = ordered(steps)
    if opts.kill:
        steps.append(KILL_STEP)
    return steps


def resolve_approvals(ctx: Ctx, rows: list[dict[str, Any]], opts: Any) -> None:
    """--approve: approve action cards as the right human; otherwise cancel (unless --keep)."""
    if opts.keep_pending or not ctx.created_approvals:
        return
    with AegisAdmin(ctx.base_url, view_as="u_katarzyna") as owner:
        for apr_id in dict.fromkeys(ctx.created_approvals):
            try:
                apr = owner.approval(apr_id)
            except AegisError:
                continue
            if apr.get("status") != "pending":
                continue
            if opts.approve and apr.get("kind") in ("action", "budget_raise"):
                _approve_right_human(ctx.base_url, apr)
                continue
            try:
                owner.cancel(apr_id)
            except AegisError:
                try:
                    owner.deny(apr_id, "chaos sweep cleanup")
                except AegisError:
                    pass


def _approve_right_human(base_url: str, apr: dict[str, Any]) -> None:
    role = apr.get("required_role")
    requester = (apr.get("requester") or {}).get("agent_id") or ""
    if role == "self":
        voters = [DEMO_AGENT_SPONSORS.get(requester, "u_emily")]
    else:
        voters = [ROLE_APPROVER.get(str(role), "u_katarzyna")]
        if apr.get("two_person"):
            voters.append("u_marek")
    for member in voters:
        try:
            with AegisAdmin(base_url, view_as=member) as a:
                a.approve(apr["id"], f"chaos sweep: approved by {member}")
            console.print(f"  [green]✓ {apr['id']} approved by {member} ({role})[/green]")
        except AegisError as e:
            console.print(f"  [yellow]≈ {apr['id']} approve as {member}: {escape(e.message)}[/yellow]")


def render(rows: list[dict[str, Any]]) -> None:
    wide = console.width >= 150
    t = Table(show_lines=False, header_style="bold", pad_edge=False, expand=False, box=None)
    cols = ("", "step", "family", "expected", "actual", "detail") if wide else \
        ("step", "expected", "actual")
    for col in cols:
        t.add_column(col, overflow="ellipsis", no_wrap=True, min_width=1 if not col else None,
                     max_width=60 if col == "detail" else None)
    for r in rows:
        g = r["grade"]
        exp = "/".join(r["expect"]) + (f" {'/'.join(r['controls'])}" if r["controls"] else "")
        if r.get("role"):
            exp += f" · {r['role']}{'+2p' if r.get('two_person') else ''}"
        act = action_tag(r["action"], r.get("control"))
        if r.get("actual_role"):
            act += f" · {escape(str(r['actual_role']))}{'+2p' if r.get('actual_two_person') else ''}"
        cells = [f"[{GRADE_STYLE[g]}]{g}[/]", r["id"], r["family"], escape(exp), act,
                 escape(short(r.get("skipped") or r.get("detail"), 70))]
        t.add_row(*(cells if wide else [f"{cells[0]} {r['id']}", cells[3], cells[4]]))
    console.print(t)


def main(argv: list[str] | None = None) -> int:
    p = base_parser("Chaos agent: run every catalog probe, expected vs actual", approvals=False)
    p.add_argument("--family", default=None, help="comma list: " + ",".join(sorted({s.family for s in STEPS})))
    p.add_argument("--only", default=None, help="comma list of step ids")
    p.add_argument("--fast", action="store_true", help="skip budget burners")
    p.add_argument("--no-config", action="store_true", help="skip config-governance steps")
    p.add_argument("--approve", action="store_true", help="approve action cards as the right human")
    p.add_argument("--keep-pending", action="store_true", help="leave created approvals pending")
    p.add_argument("--kill", action="store_true", help="also flip (and release) the kill switch")
    p.add_argument("--min-pass", type=float, default=90.0, help="exit 1 below this %% (default 90)")
    p.add_argument("--list", action="store_true", help="list the catalog and exit")
    opts = p.parse_args(argv)
    steps = select(opts)
    if opts.list:
        for s in steps:
            console.print(f"  {s.id:<16} {s.family:<10} {'/'.join(s.expect):<28} {s.title}")
        return EXIT_OK
    require_gateway(opts.url)
    session = opts.session or fresh_session("chaos-agent@platform", "sweep")
    banner("chaos-agent@platform", f"Chaos sweep · {len(steps)} probes", session=session, url=opts.url)
    impl = implemented_controls(opts.url)
    hits0 = exfil_hits()
    ctx = Ctx(opts.url, session=session)
    rows: list[dict[str, Any]] = []
    t0 = time.monotonic()
    try:
        for s in steps:
            if s.controls and impl and not any(impl.get(c, True) for c in s.controls):
                out = Outcome("skip", skipped=f"{'/'.join(s.controls)} configured, not implemented")
            else:
                with console.status(f"[bright_black]{s.id}: {escape(s.title)}[/bright_black]"):
                    out = execute(s, ctx)
            g = grade(s, out)
            row = {
                "id": s.id, "family": s.family, "title": s.title, "agent": s.agent,
                "expect": list(s.expect), "controls": list(s.controls), "role": s.role,
                "two_person": s.two_person, "grade": g, "action": out.action,
                "control": out.control, "approval_id": out.approval_id,
                "actual_role": out.role, "actual_two_person": out.two_person,
                "detail": out.detail, "skipped": out.skipped, "decision_id": out.decision_id,
            }
            rows.append(row)
            if not opts.quiet:
                console.print(f"  [{GRADE_STYLE[g]}]{g}[/] {s.id:<15} {action_tag(out.action, out.control)}"
                              f" [bright_black]{escape(short(out.skipped or out.detail, 60))}[/bright_black]")
        resolve_approvals(ctx, rows, opts)
    except KeyboardInterrupt:
        console.print("\n  [bright_black]interrupted[/bright_black]")
    finally:
        ctx.close()
    console.print()
    render(rows)
    graded = [r for r in rows if r["grade"] != "·"]
    good = [r for r in graded if r["grade"] in ("✓", "≈")]
    pct = 100.0 * len(good) / len(graded) if graded else 0.0
    hits1 = exfil_hits()
    sink = None if hits1 is None else hits1 - (hits0 or 0)
    console.print(
        f"\n  [bold]{len(good)}/{len(graded)} as expected[/bold] ({pct:.0f} %) · "
        f"✓ {sum(r['grade'] == '✓' for r in rows)} · ≈ {sum(r['grade'] == '≈' for r in rows)} · "
        f"✗ {sum(r['grade'] == '✗' for r in rows)} · skipped {len(rows) - len(graded)} · "
        f"{time.monotonic() - t0:.0f} s · attacker received: "
        + ("[green]0[/green]" if sink == 0 else f"[red]{sink}[/red]" if sink else "n/a")
    )
    for r in rows:
        if r["grade"] == "✗":
            console.print(f"  [red]✗ {r['id']}: expected {'/'.join(r['expect'])} "
                          f"{'/'.join(r['controls'])}, got {r['action']} {r.get('control') or ''}[/red]")
    summary = {"session": session, "pass_pct": round(pct, 1), "passed": len(good),
               "graded": len(graded), "exfil_hits": sink, "rows": rows}
    if opts.json:
        out_dir = _ROOT / "data" / "demo"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "chaos.json").write_text(json.dumps(summary, indent=2, default=str))
        print(json.dumps({k: v for k, v in summary.items() if k != "rows"}))
    return EXIT_OK if pct >= opts.min_pass and not sink else EXIT_MISMATCH


if __name__ == "__main__":
    raise SystemExit(main())

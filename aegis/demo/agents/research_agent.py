"""Research Agent — `research-agent@research` (sponsor u_agnieszka), local-first on Ollama.

    uv run --frozen python demo/agents/research_agent.py              # aegis-judge via /ollama/api/chat
    uv run --frozen python demo/agents/research_agent.py --no-llm     # scripted (no model load)
    uv run --frozen python demo/agents/research_agent.py --approve-as u_agnieszka

1. Reads `research_notes` from acme-db through the MCP proxy (granted read).
2. Summarises them with the **local** model (`aegis-judge`, fallback `qwen3:0.6b`; `think: false`,
   `num_predict` ≤ 160, 60 s timeout) through `/ollama/api/chat`.
3. Drafts a client note containing a PESEL: on the local destination the PESEL is allowed to stay
   (contrast with F1, where the same value is tokenized before a remote model); card data is still
   tokenized per the destination matrix.
4. Buys the $12 OpenData dataset → ACT-01 → rule `spend-self` → the sponsor u_agnieszka approves.

`--no-llm` replaces step 2/3 generation with `/v1/guard` checks on the same text (destination
`local`), so the policy story is identical without loading a model.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src")]

from aegis.sdk import AegisClient  # noqa: E402
from aegis.sdk.results import AegisError  # noqa: E402
from demo.agents._common import (  # noqa: E402
    EXIT_MISMATCH,
    EXIT_OK,
    banner,
    base_parser,
    console,
    error_action,
    escape,
    fresh_session,
    hop,
    require_gateway,
    say,
    section,
    short,
)
from demo.agents.trading_copilot import call_mcp_governed  # noqa: E402

AGENT = "research-agent@research"
MODELS = ("aegis-judge", "qwen3:0.6b")
CLIENT_NOTE = (
    "Draft a two-sentence note to client Jan Kowalski (PESEL 44051401359) saying his research "
    "pack is ready; his card 4111 1111 1111 1111 will not be charged."
)


def local_chat(client: AegisClient, prompt: str, opts: Any) -> tuple[str, str, str | None]:
    """(action, text, control) from the first local model that answers (or guard in --no-llm)."""
    if opts.no_llm:
        # dry-run: a non-dry guard on a local model call holds BUD-02's local-concurrency slot
        # until /v1/guard/complete, which a scripted run never sends
        g = client.guard(surface="model.request", text=prompt, destination="local",
                         model=MODELS[0], dry_run=True)
        return g.action, g.text or prompt, g.control_id
    last_err = ""
    for model in MODELS:
        try:
            r = client.ollama_chat(prompt, model=model, think=False,
                                   options={"num_predict": min(160, opts.num_predict)})
            return r.action, r.text, r.control_id
        except AegisError as e:
            last_err = e.message
            say(f"[yellow]{model}: {escape(short(e.message, 80))} — trying the next model[/yellow]")
    return "error", last_err, None


def main(argv: list[str] | None = None) -> int:
    p = base_parser("Research agent (research-agent@research) on local Ollama")
    p.add_argument("--no-llm", action="store_true", help="scripted: /v1/guard instead of Ollama")
    p.add_argument("--num-predict", type=int, default=120)
    p.add_argument("--skip-buy", action="store_true")
    p.add_argument("--assert", dest="assert_", action="store_true")
    opts = p.parse_args(argv)
    require_gateway(opts.url)
    session = opts.session or fresh_session(AGENT)
    client = AegisClient(opts.url, AGENT, session_id=session, timeout=90.0)
    banner(AGENT, "Research agent · local-first (Ollama)" + (" · --no-llm" if opts.no_llm else ""),
           session=session, url=opts.url)
    results: dict[str, bool] = {}
    ns: Any = opts
    ns.hold = 0.0
    try:
        section("1 · read research_notes (acme-db, granted read)")
        res, _ = call_mcp_governed(client, "acme-db", "query",
                                   {"sql": "SELECT title, body FROM research_notes LIMIT 3"},
                                   "acme-db.query research_notes", ns)
        notes = res.text if res is not None and res.ok else ""
        results["read"] = res is not None and res.ok
        if notes:
            console.print(f"    [bright_black]{escape(short(notes, 200))}[/bright_black]")

        section("2 · summarise locally")
        action, text, ctrl = local_chat(client, "Summarise these research notes in two sentences:\n"
                                        + (notes or "WIG20 +0.8 %, banks lead, copper weak."), opts)
        hop("ollama", f"{MODELS[0]} summary", action, ctrl, short(text, 90))
        results["summary"] = action != "error"

        section("3 · client note with a PESEL → stays local")
        action, text, ctrl = local_chat(client, CLIENT_NOTE, opts)
        kept = "44051401359" in (text or "")
        hop("ollama", "client note (local destination)", action, ctrl,
            "PESEL kept locally" if kept else short(text, 80))
        if opts.no_llm:
            say("[bright_black]compare: the same text to a remote model is tokenized "
                "([PESEL_1]) — scene s1[/bright_black]")
        results["local_pii"] = action in ("allow", "log", "redact")

        if not opts.skip_buy:
            section("4 · buy the $12 OpenData dataset → sponsor u_agnieszka self-approves")
            res, apr = call_mcp_governed(
                client, "payments", "create_charge",
                {"vendor": "opendata-shop", "amount_usd": 12, "currency": "USD"},
                "payments.create_charge opendata-shop $12.00", ns)
            if apr is None and res is not None and res.ok:
                say("[bright_black](no card: a still-valid grant for the same call was redeemed — "
                    "approvals are single-use grants with a TTL)[/bright_black]")
            results["buy"] = (apr is not None and apr.get("required_role") == "self") or (
                apr is None and res is not None and res.ok)
    except AegisError as e:
        hop("sdk", "error", error_action(e), e.control_id, short(e.message))
    except KeyboardInterrupt:
        console.print("\n  [bright_black]interrupted[/bright_black]")
    finally:
        client.close()
    if opts.json:
        print(json.dumps({"agent": AGENT, "results": results}))
    console.print()
    for k, v in results.items():
        console.print(f"  {'[green]PASS' if v else '[red]FAIL'}[/] {k}")
    ok = bool(results) and all(results.values())
    return EXIT_OK if (ok or not opts.assert_) else EXIT_MISMATCH


if __name__ == "__main__":
    raise SystemExit(main())

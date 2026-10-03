"""Scene 5 · F8 external signed threat feed — AEGIS-TI-022 (EchoLeak via an allowlisted proxy).

    uv run --frozen python demo/scenarios/run.py s5             # allow on serial N → publish → block
    uv run --frozen python demo/scenarios/run.py s5 --tamper    # + tampered bundle → rejected
    uv run --frozen python demo/scenarios/run.py s5 --feed-reset   # disable TI-022 again (rehearsal)

The harmless EchoLeak-style payload (a markdown image through an allowlisted image proxy) is
replayed through `/v1/guard` on `model.response`: allowed while the feed is on serial N (TI-014
allowlists the asset host), then the feed service enables AEGIS-TI-022 and publishes serial N+1
(Ed25519-signed), the gateway verifies + activates it, and the replay is blocked by SIG-01 with the
CVE alias. `--tamper` publishes a broken signature: the gateway rejects it (`feed.rejected` banner)
and keeps enforcing the last good serial. Feed service default: `$AEGIS_FEED_URL` or :8790.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src")]

import httpx  # noqa: E402

from aegis.sdk import AegisAdmin, AegisClient  # noqa: E402
from aegis.sdk.results import AegisError  # noqa: E402
from demo.agents._common import (  # noqa: E402
    action_tag,
    banner,
    console,
    escape,
    feed_url,
    say,
    section,
    service_up,
)

TITLE = "F8 · signed threat feed: publish AEGIS-TI-022 → replay blocked"
SIG = "AEGIS-TI-022"
#: harmless stand-in (fake query values, allowlisted .example host) — see
#: staging/feed-seed/demo/echoleak-proxy-payload.md
PAYLOAD = (
    "Here is your quarterly summary.\n\n"
    "![Q3 revenue chart](https://assets.aegis-corp.example/img/proxy?src=https://cdn.example/"
    "chart.png&ref=UECB3F2A9)\n\nThanks for using the assistant."
)


def replay(client: AegisClient) -> tuple[str, str | None, str]:
    g = client.guard(kind="model_call", surface="model.response", direction="in",
                     destination="remote", text=PAYLOAD, session_id="ses_feed_demo")
    return g.action, g.control_id, g.reason or ""


def gateway_serial(admin: AegisAdmin) -> tuple[int | None, str]:
    try:
        st = admin.feed_status()
        return st.get("serial"), str(st.get("status"))
    except AegisError:
        return None, "unavailable"


def wait_serial(admin: AegisAdmin, serial: int, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if gateway_serial(admin)[0] == serial:
            return True
        try:
            admin.feed_refresh()
        except AegisError:
            pass
        time.sleep(0.3)
    return False


def set_sig(feed: str, enabled: bool, note: str) -> dict:
    with httpx.Client(timeout=15.0) as c:
        c.post(f"{feed}/api/signatures/{SIG}/enabled", json={"enabled": enabled}).raise_for_status()
        r = c.post(f"{feed}/api/publish", json={"note": note})
        r.raise_for_status()
        return r.json()


def run(opts: argparse.Namespace) -> bool | None:
    feed = feed_url()
    banner("threat feed", TITLE, url=opts.url)
    if not service_up(feed, "/healthz"):
        say(f"[yellow]feed service not reachable at {feed} — start it with `make feed` "
            f"(or publish in the feed UI {feed}/ by hand)[/yellow]")
        return None
    admin = AegisAdmin(opts.url, view_as="u_katarzyna")
    client = AegisClient(opts.url, "trading-copilot@trading")
    try:
        if getattr(opts, "feed_reset", False):
            res = set_sig(feed, False, f"rehearsal: disable {SIG}")
            ok = wait_serial(admin, res["serial"])
            say(f"{SIG} disabled · serial #{res['serial']} {'active' if ok else 'NOT active'}")
            return ok
        serial, status = gateway_serial(admin)
        section(f"gateway on feed serial #{serial} ({status})")
        before, ctrl, reason = replay(client)
        console.print(f"  replay EchoLeak proxy payload → {action_tag(before, ctrl)} "
                      f"[bright_black]{escape(reason[:90])}[/bright_black]")
        if before == "block" and ctrl == "SIG-01":
            say(f"[yellow]{SIG} already active — run `run.py s5 --feed-reset` before the demo"
                "[/yellow]")
        section(f"feed service: enable {SIG} → publish (Ed25519-signed)")
        t0 = time.perf_counter()
        res = set_sig(feed, True, f"demo: enable {SIG}")
        new = res.get("serial")
        active = wait_serial(admin, new)
        ms = (time.perf_counter() - t0) * 1000
        console.print(f"  serial #{serial} → #{new} · gateway "
                      + (f"[green]verified + activated in {ms:.0f} ms[/green]" if active
                         else "[red]did not activate[/red]"))
        after, ctrl2, reason2 = replay(client)
        console.print(f"  replay → {action_tag(after, ctrl2)} "
                      f"[bright_black]{escape(reason2[:110])}[/bright_black]")
        ok = active and after == "block"
        if getattr(opts, "tamper", False):
            section("tamper: publish a bundle with a broken signature")
            with httpx.Client(timeout=15.0) as c:
                c.post(f"{feed}/api/tamper", json={"mode": "unsigned"})
            time.sleep(1.5)
            try:
                admin.feed_refresh()
            except AegisError:
                pass
            s2, st2 = gateway_serial(admin)
            console.print(f"  gateway status [red]{escape(st2)}[/red] · still enforcing #{s2}")
            ok = ok and s2 == new
        return ok
    except (httpx.HTTPError, KeyError) as e:
        say(f"[red]feed service error: {escape(str(e))}[/red]")
        return False
    finally:
        client.close()
        admin.close()

"""Capture the live product shots for the 60 s video (headless Chrome via CDP + the real demo scripts).

Needs the stack running on the fixed ports (`AEGIS_SEMANTIC=off make up`). Every dashboard shot is a
screenshot of the real /ui (1600x900 CSS px @ 1.2 = 1920x1080); every terminal card is the real stdout of
the demo command that produced the state. Writes PNGs, ANSI logs and capture.json into BUILD dir.

    uv run --no-project --with websockets python scripts/video/capture.py --build <dir>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdp import Browser  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]  # aegis/
GW = os.environ.get("AEGIS_URL", "http://127.0.0.1:8787")
FEED = os.environ.get("AEGIS_FEED_URL", "http://127.0.0.1:8790")
UI = f"{GW}/ui"
POLICY = ROOT / "config" / "policy.yaml"
GOLDEN = ROOT / "config" / "policy.golden.yaml"
ENV = {**os.environ, "FORCE_COLOR": "1", "COLUMNS": "104", "TERM": "xterm-256color"}
LOG: dict = {"shots": {}, "terms": {}, "facts": {}, "notes": []}


def note(msg: str) -> None:
    print(f"[capture] {msg}", flush=True)
    LOG["notes"].append(msg)


def api(path: str, view_as: str = "u_katarzyna", method: str = "GET", body: dict | None = None):
    req = urllib.request.Request(
        f"{GW}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-Aegis-View-As": view_as, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def run(cmd: list[str], out: Path, timeout: int = 180) -> str:
    """Run a demo command from aegis/ with colour on, store the ANSI stdout, return plain text."""
    note("$ " + " ".join(cmd))
    p = subprocess.run(cmd, cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=timeout)
    txt = p.stdout + (p.stderr if p.returncode else "")
    out.write_text(txt)
    LOG["terms"][out.stem] = {"cmd": " ".join(cmd), "rc": p.returncode}
    return strip_ansi(txt)


def strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", s)


PY = ["uv", "run", "--frozen", "python"]


async def shot(b: Browser, build: Path, name: str, desc: str) -> None:
    await b.shot(build / f"{name}.png")
    LOG["shots"][name] = desc
    note(f"shot {name}: {desc}")


async def toggle_text(b: Browser, text: str) -> bool:
    ok = await b.click_text(text)
    if not ok:
        note(f"WARN: could not click '{text}'")
    return ok


async def playground_run(b: Browser, preset: str, wait_verdict: str | None = None) -> str:
    await toggle_text(b, preset)
    await asyncio.sleep(0.6)
    await b.click_text("Run", "button")
    await asyncio.sleep(2.0)
    if wait_verdict:
        await b.wait_for(f"document.body.innerText.includes({json.dumps(wait_verdict)})", 8)
    await b.js("document.querySelector('.aegis-canvas') && document.querySelector('.aegis-canvas').scrollTo(0,0)")
    await asyncio.sleep(0.4)
    return await b.js("document.body.innerText")


APPROVE_READY = ("[...document.querySelectorAll('button')].some(e=>e.offsetParent&&"
                 "e.innerText.trim()==='Approve'&&!e.disabled)")


async def reveal_footer(b: Browser) -> None:
    """Scroll the page canvas just enough that the Approve / Deny footer is on screen."""
    await b.js("""(()=>{const a=[...document.querySelectorAll('button')].find(e=>e.offsetParent&&e.innerText.trim()==='Approve');
        if(a) a.scrollIntoView({block:'end'});})()""")
    await asyncio.sleep(0.5)


def set_inj02_threshold(value: str) -> tuple[str, str]:
    """Edit exactly controls[id=INJ-02].threshold in config/policy.yaml (what a judge does by hand)."""
    lines = POLICY.read_text().splitlines(keepends=True)
    start = next(i for i, ln in enumerate(lines) if re.match(r"\s*-\s*id:\s*INJ-02\b", ln))
    for j in range(start + 1, min(start + 40, len(lines))):
        m = re.match(r"(\s*threshold:\s*)([0-9.]+)(.*)", lines[j])
        if m:
            old = m.group(2)
            lines[j] = f"{m.group(1)}{value}{m.group(3)}\n"
            POLICY.write_text("".join(lines))
            return old, f"{j + 1}"
        if re.match(r"\s*-\s*id:\s*\S", lines[j]):
            break
    raise RuntimeError("INJ-02 threshold line not found")


async def main(build: Path, skip: set[str]) -> int:
    build.mkdir(parents=True, exist_ok=True)
    prev = build / "capture.json"
    if prev.exists() and skip:  # partial re-run: keep what earlier runs captured
        old = json.loads(prev.read_text())
        for k in ("shots", "terms", "facts"):
            LOG[k].update(old.get(k, {}))
    b = await Browser(1600, 900, 1.2).start()
    try:
        # ------------------------------------------------------------ preflight state
        pol = api("/api/policy/status") if True else {}
        LOG["facts"]["policy_version_start"] = pol.get("version")
        fs = api("/api/feed/status") if True else {}
        LOG["facts"]["feed_serial_start"] = fs.get("serial")
        await b.goto(f"{UI}/?view_as=u_katarzyna", 3)  # seeds localStorage view-as

        # ------------------------------------------------------------ scene 3: PII round trip
        if "pii" not in skip:
            txt = run(PY + ["demo/agents/trading_copilot.py", "pii-draft"], build / "t_pii.ansi")
            dec = re.search(r"decision\s+(dec_[0-9a-z]+)", txt.replace("\n", " "))
            LOG["facts"]["pii_decision"] = dec.group(1) if dec else None
            if dec:
                await b.goto(f"{UI}/security/live?d={dec.group(1)}", 3)
                await b.click_text("Wire", "[role=tab], button")
                await asyncio.sleep(1.0)
                await shot(b, build, "s3_wire", "Live feed decision drawer, Wire tab (local vs on-the-wire)")
            else:
                note("WARN: no decision id in pii-draft output")

        # ------------------------------------------------------------ scene 4: injection + EXE-01
        if "inj" not in skip:
            run(PY + ["demo/scenarios/run.py", "s2", "--claude-fallback"], build / "t_s2.ansi")
            await asyncio.sleep(0.5)
            items = api("/api/decisions?control_id=EXE-01&limit=1").get("items", [])
            LOG["facts"]["exe01_decision"] = items[0]["id"] if items else None
            await b.goto(f"{UI}/security/live", 3)
            await shot(b, build, "s4_live", "Live decisions feed after the SETUP.md / curl|sh hook events")
            if items:
                await b.goto(f"{UI}/security/live?d={items[0]['id']}", 3)
                await b.click_text("Trace", "[role=tab], button")
                await asyncio.sleep(0.8)
                await shot(b, build, "s4_exe01", "Decision drawer for the EXE-01 pipe-to-shell block")

        # ------------------------------------------------------------ scene 5: $50 approval
        if "apr" not in skip:
            sub_log = build / "t_sub.ansi"
            fh = open(sub_log, "w")
            note("$ trading_copilot.py subscribe (background, waits for a human)")
            proc = subprocess.Popen(PY + ["demo/agents/trading_copilot.py", "subscribe", "--approval-timeout", "120"],
                                    cwd=ROOT, env=ENV, stdout=fh, stderr=subprocess.STDOUT)
            apr = None
            for _ in range(60):
                time.sleep(0.5)
                m = re.search(r"pending approval (apr_[0-9a-z]+)", strip_ansi(sub_log.read_text()))
                if m:
                    apr = m.group(1)
                    break
            LOG["facts"]["approval"] = apr
            if apr:
                await b.goto(f"{UI}/governance/approvals?id={apr}&view_as=u_piotr", 3)
                await b.wait_for("[...document.querySelectorAll('button')].some(e=>e.innerText.trim()==='Approve')", 15)
                await asyncio.sleep(0.5)
                # collapse the JSON payload so the locked footer is on screen
                await b.js("""(()=>{const b=[...document.querySelectorAll('button')].find(e=>e.offsetParent&&e.innerText.trim()==='{');
                    if(b) b.click();})()""")
                await asyncio.sleep(0.6)
                await reveal_footer(b)
                await shot(b, build, "s5_piotr", "Approvals as u_piotr (sponsor, member): Approve locked")
                await b.goto(f"{UI}/governance/approvals?id={apr}&view_as=u_emily", 3)
                await b.wait_for(APPROVE_READY, 15)
                await asyncio.sleep(0.5)
                await b.js("""(()=>{const b=[...document.querySelectorAll('button')].find(e=>e.offsetParent&&e.innerText.trim()==='{');
                    if(b) b.click();})()""")
                await asyncio.sleep(0.6)
                await reveal_footer(b)
                await shot(b, build, "s5_emily_pre", "Approvals as u_emily (admin): Approve enabled")
                await b.js("""(()=>{const a=[...document.querySelectorAll('button')].filter(e=>e.offsetParent&&e.innerText.trim()==='Approve'&&!e.disabled);
                    a[a.length-1].click();})()""")
                await asyncio.sleep(1.0)
                await shot(b, build, "s5_emily_dialog", "Approve dialog as u_emily")
                # confirm inside the dialog if there is one
                await b.js("""(()=>{const d=document.querySelector('[role=dialog],[role=alertdialog]'); if(!d) return 'nodialog';
                    const bs=[...d.querySelectorAll('button')].filter(e=>/approve/i.test(e.innerText)&&!e.disabled);
                    if(bs.length){bs[bs.length-1].click(); return 'clicked'} return 'nobtn'})()""")
                await asyncio.sleep(1.5)
                await shot(b, build, "s5_emily_done", "After u_emily approved: toast + state")
            try:
                proc.wait(60)
            except subprocess.TimeoutExpired:
                proc.kill()
                note("WARN: subscribe agent did not finish")
            fh.close()
            LOG["terms"]["t_sub"] = {"cmd": "uv run --frozen python demo/agents/trading_copilot.py subscribe",
                                     "rc": proc.returncode}

        # ------------------------------------------------------------ scene 6: live policy edit
        if "pol" not in skip:
            await b.goto(f"{UI}/security/playground?view_as=u_katarzyna", 3)
            t = await playground_run(b, "Borderline (review band)", "Allow")
            LOG["facts"]["s6_before"] = "Allow" if "Allowed" in t or "Allow" in t else "?"
            await shot(b, build, "s6_allow", "Playground Borderline preset at INJ-02 0.80 -> allow")
            v0 = api("/api/policy/status").get("version")
            old, line = set_inj02_threshold("0.50")
            note(f"edited config/policy.yaml line {line}: INJ-02 threshold {old} -> 0.50")
            diff = subprocess.run(["diff", "-u", "config/policy.golden.yaml", "config/policy.yaml"], cwd=ROOT,
                                  capture_output=True, text=True).stdout
            (build / "t_policy.diff").write_text(diff)
            LOG["facts"]["s6_edit"] = {"line": line, "old": old, "new": "0.50", "version_before": v0}
            await asyncio.sleep(1.2)
            await shot(b, build, "s6_toast", "Dashboard toast right after the file save")
            for _ in range(20):
                v1 = api("/api/policy/status").get("version")
                if v1 != v0:
                    break
                await asyncio.sleep(0.25)
            LOG["facts"]["s6_edit"]["version_after"] = v1
            t = await playground_run(b, "Borderline (review band)", "Block")
            await shot(b, build, "s6_block", "Same preset after the edit -> block INJ-02")
            shutil.copyfile(GOLDEN, POLICY)
            note("restored config/policy.yaml from policy.golden.yaml")

        # ------------------------------------------------------------ scene 7: signed feed
        if "feed" not in skip:
            await b.goto(f"{UI}/security/playground?view_as=u_katarzyna", 3)
            await playground_run(b, "EchoLeak image proxy")
            await shot(b, build, "s7_allow", "EchoLeak preset before the feed update -> allow")
            s0 = api("/api/feed/status").get("serial")
            await b.goto(f"{FEED}/", 3)
            await b.click_text("AEGIS-TI-022", "li, button, div[role=button], a, [data-id]")
            await asyncio.sleep(0.8)
            await b.click_text("Enable", "button", exact=True)
            await asyncio.sleep(1.0)
            await b.click_text("Publish", "button")
            await asyncio.sleep(1.0)
            # confirm dialog, if the editor asks
            await b.js("""(()=>{const d=document.querySelector('[role=dialog],dialog[open],.modal'); if(!d) return;
                const bs=[...d.querySelectorAll('button')].filter(e=>/publish|sign|confirm/i.test(e.innerText)); if(bs.length) bs[bs.length-1].click();})()""")
            s1 = s0
            for _ in range(40):
                await asyncio.sleep(0.25)
                s1 = api("/api/feed/status").get("serial")
                if s1 != s0:
                    break
            await asyncio.sleep(1.0)
            LOG["facts"]["feed"] = {"serial_before": s0, "serial_after": s1}
            await shot(b, build, "s7_feed", "Feed editor :8790 after Enable + Publish of AEGIS-TI-022")
            await b.goto(f"{UI}/security/playground?view_as=u_katarzyna", 3)
            await playground_run(b, "EchoLeak image proxy", "Block")
            await shot(b, build, "s7_block", "EchoLeak preset after the publish -> block SIG-01 AEGIS-TI-022")

        # ------------------------------------------------------------ scene 8: audit
        if "audit" not in skip:
            await b.goto(f"{UI}/security/audit?view_as=u_katarzyna", 3)
            await b.click_text("Verify chain", "button")
            await b.wait_for("/chain ok/i.test(document.body.innerText)", 10)
            await asyncio.sleep(0.8)
            await shot(b, build, "s8_audit", "Audit log page after Verify chain")
            run(["make", "verify-audit"], build / "t_audit.ansi")
            await b.goto(f"{UI}/?view_as=u_katarzyna", 3)
            await shot(b, build, "s0_overview", "Command Center overview (spare shot)")
    finally:
        await b.close()
        if POLICY.read_text() != GOLDEN.read_text():
            shutil.copyfile(GOLDEN, POLICY)
            note("restored config/policy.yaml from policy.golden.yaml (finally)")
        (build / "capture.json").write_text(json.dumps(LOG, indent=2, default=str))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", required=True, type=Path)
    ap.add_argument("--skip", default="", help="comma list of pii,inj,apr,pol,feed,audit")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.build.resolve(), set(filter(None, a.skip.split(","))))))

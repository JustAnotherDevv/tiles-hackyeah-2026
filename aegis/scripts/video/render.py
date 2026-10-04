"""Compose and encode the ≤58 s Aegis demo video from the captures made by capture.py.

    uv run --no-project --with websockets python scripts/video/render.py --build <dir>

Steps: (1) render terminal cards (real ANSI stdout → HTML → PNG), caption overlays (transparent PNG) and
the animated title/end cards (docs/submission/video/cards.html, frame-stepped via the Web Animations
API) in headless Chrome; (2) one short clip per beat with ffmpeg (slow eased zoom on the still +
caption overlay); (3) chain the clips with crossfades → H.264 1920x1080 mp4 with a silent AAC track;
(4) export cover.png. Captions only quote values that appear in the captured output (capture.json).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdp import Browser  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
VIDEO_DIR = ROOT / "docs" / "submission" / "video"
CARDS = VIDEO_DIR / "cards.html"
ARCH = ROOT / "docs" / "assets" / "architecture.png"
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FPS = 30
XF = 0.35  # crossfade seconds
SCALE = 1.5  # zoompan canvas factor (sub-pixel smoothness vs. encode time)
W, H = 1920, 1080

# --------------------------------------------------------------------------- ANSI → HTML
PALETTE = {30: "#6b7280", 31: "#F2556F", 32: "#3CCB7F", 33: "#E8B04B", 34: "#5BA4F5", 35: "#B58CFF",
           36: "#4CC9E0", 37: "#D7DAE0", 90: "#7A808C", 91: "#FF7A8E", 92: "#5BE39A", 93: "#F5C86B",
           94: "#7FB8FF", 95: "#C9A6FF", 96: "#7DE3F2", 97: "#FFFFFF"}


def clean_lines(raw: str) -> list[str]:
    out = []
    for ln in raw.split("\n"):
        ln = ln.split("\r")[-1]
        ln = re.sub(r"\x1b\[[0-9;]*[A-HJKSTfhlsu]|\x1b\[\?[0-9;]*[a-z]", "", ln)  # non-SGR escapes
        if "waiting for a human decision" in ln:
            continue
        out.append(ln)
    return out


def plain(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


def ansi_to_html(line: str) -> str:
    parts, pos, style = [], 0, {}
    for m in re.finditer(r"\x1b\[([0-9;]*)m", line):
        if m.start() > pos:
            parts.append(span(line[pos:m.start()], style))
        codes = [int(c) for c in m.group(1).split(";") if c] or [0]
        for c in codes:
            if c == 0:
                style = {}
            elif c == 1:
                style["b"] = True
            elif c == 2:
                style["dim"] = True
            elif c == 3:
                style["i"] = True
            elif c in PALETTE:
                style["fg"] = PALETTE[c]
            elif c == 39:
                style.pop("fg", None)
        pos = m.end()
    parts.append(span(line[pos:], style))
    return "".join(parts)


def span(text: str, style: dict) -> str:
    if not text:
        return ""
    css = []
    if style.get("fg"):
        css.append(f"color:{style['fg']}")
    if style.get("b"):
        css.append("font-weight:700")
    if style.get("dim"):
        css.append("opacity:.6")
    if style.get("i"):
        css.append("font-style:italic")
    t = html.escape(text)
    return f'<span style="{";".join(css)}">{t}</span>' if css else t


def select(lines: list[str], start: str, end: str | None = None, drop: tuple[str, ...] = ()) -> list[str]:
    """Lines from the first one matching `start` up to and including the first matching `end`."""
    i = next(k for k, ln in enumerate(lines) if re.search(start, plain(ln)))
    j = len(lines) - 1
    if end:
        j = next(k for k in range(i, len(lines)) if re.search(end, plain(lines[k])))
    return [ln for ln in lines[i:j + 1] if not any(re.search(d, plain(ln)) for d in drop)]


# --------------------------------------------------------------------------- HTML templates
BASE_CSS = """
:root{--bg:#07080A;--t1:#ECEEF1;--t2:#A2A8B3;--t3:#7A808C;--iris:#6D5DFC;--accent:#9A8CFF;--allow:#3CCB7F;
 --mono:"SF Mono","SFMono-Regular","JetBrains Mono",Menlo,monospace;
 --sans:"Inter",-apple-system,"SF Pro Display","Helvetica Neue",Arial,sans-serif}
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1920px;height:1080px;overflow:hidden;font-family:var(--sans);color:var(--t1)}
.term{background:#0D0F13;border:1px solid #2A2F37;border-radius:18px;box-shadow:0 30px 80px rgba(0,0,0,.6);overflow:hidden}
.bar{height:46px;display:flex;align-items:center;gap:9px;padding:0 18px;background:#14171C;border-bottom:1px solid #22262D}
.dot{width:13px;height:13px;border-radius:50%}
.bar .cmd{margin-left:14px;font-family:var(--mono);font-size:19px;color:var(--t2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
pre{font-family:var(--mono);color:#D7DAE0;white-space:pre;padding:22px 26px;line-height:1.42}
.prompt{color:var(--allow)}
"""


def term_block(blocks: list[tuple[str, list[str]]], font: int, width: int, title: str) -> str:
    body = []
    for cmd, lines in blocks:
        if cmd:
            body.append(f'<span class="prompt">$</span> <span style="color:#ECEEF1">{html.escape(cmd)}</span>')
        body.extend(ansi_to_html(ln) for ln in lines)
    return (f'<div class="term" style="width:{width}px"><div class="bar">'
            '<i class="dot" style="background:#FF5F57"></i><i class="dot" style="background:#FEBC2E"></i>'
            f'<i class="dot" style="background:#28C840"></i><span class="cmd">{html.escape(title)}</span></div>'
            f'<pre style="font-size:{font}px">' + "\n".join(body) + "</pre></div>")


def page_term(blocks, font=25, width=1760, title="aegis — zsh") -> str:
    return (f"<!doctype html><html><head><meta charset=utf-8><style>{BASE_CSS}"
            "body{background:radial-gradient(1200px 700px at 50% 35%,rgba(109,93,252,.16),transparent 65%),#07080A;"
            "display:flex;align-items:center;justify-content:center;padding-bottom:110px}</style></head><body>"
            + term_block(blocks, font, width, title) + "</body></html>")


def page_overlay(img: Path, blocks, pos: dict, font=21, width=900, title="aegis — zsh") -> str:
    st = ";".join(f"{k}:{v}px" for k, v in pos.items())
    return (f"<!doctype html><html><head><meta charset=utf-8><style>{BASE_CSS}"
            f"body{{background:#07080A url('{img.as_uri()}') 0 0/1920px 1080px no-repeat}}"
            f".ov{{position:absolute;{st}}}</style></head><body><div class=ov>"
            + term_block(blocks, font, width, title) + "</div></body></html>")


def page_caption(caption: str, chip: str | None, note: str | None) -> str:
    chip_html = f'<div class="chip">{html.escape(chip)}</div>' if chip else ""
    note_html = f'<div class="note">{html.escape(note)}</div>' if note else ""
    cap_html = f'<div class="cap"><span>{html.escape(caption)}</span></div>' if caption else ""
    return (f"<!doctype html><html><head><meta charset=utf-8><style>{BASE_CSS}"
            "html,body{background:transparent}"
            ".cap{position:absolute;left:0;right:0;bottom:92px;display:flex;justify-content:center}"
            ".cap span{background:rgba(0,0,0,.72);color:#fff;font-size:46px;font-weight:650;letter-spacing:-.01em;"
            "padding:14px 34px;border-radius:14px;box-shadow:0 8px 30px rgba(0,0,0,.45)}"
            ".chip{position:absolute;left:36px;top:30px;background:rgba(109,93,252,.92);color:#fff;font-size:24px;"
            "font-weight:700;padding:8px 18px;border-radius:10px;letter-spacing:.02em;box-shadow:0 6px 20px rgba(0,0,0,.4)}"
            ".note{position:absolute;right:30px;bottom:26px;background:rgba(0,0,0,.6);color:#C9CDD4;font-size:19px;"
            "padding:6px 12px;border-radius:8px;font-family:var(--mono)}"
            "</style></head><body>" + chip_html + cap_html + note_html + "</body></html>")


# --------------------------------------------------------------------------- beats
LIVE_NOTE = "live capture · real stack · AEGIS_SEMANTIC=off (deterministic)"


def beats(build: Path, facts: dict, test_txt: str) -> list[dict]:
    t = {k: clean_lines((build / f"{k}.ansi").read_text()) for k in ("t_pii", "t_s2", "t_sub", "t_audit")}
    feed = facts.get("feed", {})
    s6 = facts.get("s6_edit", {})
    pii_reply = select(t["t_pii"], r"Reply you see", r"real values restored")
    s2 = select(t["t_s2"], r"F3 · Claude Code reads", r"attacker received", drop=(r"^\s*$",))
    sub = select(t["t_sub"], r"F4 · buy MarketPulse", r"subscription active", drop=(r"^\s*open http",))
    diff = [ln for ln in (build / "t_policy.diff").read_text().splitlines()[2:]]
    diff = [ln if len(ln) <= 64 else ln[:63] + "…" for ln in diff]
    diff = [("\x1b[31m" + ln + "\x1b[0m") if ln.startswith("-") else
            ("\x1b[32m" + ln + "\x1b[0m") if ln.startswith("+") else
            ("\x1b[36m" + ln + "\x1b[0m") if ln.startswith("@@") else ln for ln in diff]
    test_lines = [ln for ln in test_txt.rstrip("\n").split("\n") if ln.strip() and not ln.startswith("|---")]
    test_cmd = "make test"
    if test_lines and test_lines[0].startswith("$ "):
        test_cmd, test_lines = test_lines[0][2:], test_lines[1:]
    test_lines = [re.sub(r"\b(PASS|0 fail|0 UNTESTED)\b", "\x1b[1;32m\\1\x1b[0m", ln) for ln in test_lines]
    audit = ["\x1b[1;32m" + plain(ln) + "\x1b[0m" for ln in t["t_audit"][:1]]
    tests_cap = facts.get("tests_caption") or "Every control tested · audit chain OK"
    return [
        dict(id="b01", kind="anim", card="title", dur=4.0),
        dict(id="b02", kind="still", src=ARCH, dur=4.0, zoom=(960, 470, 1.07),
             cap="One control layer on every agent hop", chip=None, note=None),
        dict(id="b03", kind="still", src=build / "s3_wire.png", dur=5.6, zoom=(1500, 650, 1.55), zdelay=0.6,
             cap="Remote model sees placeholders only", chip="1 · Local redaction", note=LIVE_NOTE),
        dict(id="b04", kind="term", dur=4.0, cap="Real values restored locally; CVV dropped", chip="1 · Local redaction",
             html=page_term([("uv run --frozen python demo/agents/trading_copilot.py pii-draft", pii_reply)], 25),
             zoom=(960, 470, 1.03), note=None),
        dict(id="b05", kind="term", dur=4.5, cap="Hidden instruction neutralised; curl | sh denied",
             chip="2 · Agent attack", html=page_term([("uv run --frozen python demo/scenarios/run.py s2 --claude-fallback", s2)], 25),
             zoom=(960, 470, 1.03), note="scripted Claude Code hook events (same controls as live)"),
        dict(id="b06", kind="still", src=build / "s4_exe01.png", dur=3.5, zoom=(1515, 300, 1.5),
             cap="EXE-01 blocks the pipe-to-shell", chip="2 · Agent attack", note=LIVE_NOTE),
        dict(id="b07", kind="still", src=build / "s5_piotr.png", dur=4.0, zoom=(1380, 700, 1.35),
             cap="$50 purchase routed to an admin", chip="3 · Org approvals", note=LIVE_NOTE),
        dict(id="b08", kind="still", src=build / "s5_emily_dialog.png", dur=3.0, zoom=(960, 560, 1.75),
             cap="Sponsor locked out; admin approves", chip="3 · Org approvals", note=LIVE_NOTE),
        dict(id="b09", kind="term", dur=3.0, cap="Approved by admin → agent executes", chip="3 · Org approvals",
             html=page_term([("uv run --frozen python demo/agents/trading_copilot.py subscribe", sub)], 24),
             zoom=(960, 470, 1.03), note=None),
        dict(id="b10", kind="still", src=build / "s6_allow.png", dur=3.0, zoom=(1400, 420, 1.45),
             cap=f"Borderline prompt allowed at {s6.get('old', '0.80')}", chip="4 · Live policy edit", note=LIVE_NOTE),
        dict(id="b11", kind="overlay", src=build / "s6_toast.png", dur=3.6, zoom=(1150, 760, 1.18),
             html_fn=lambda: page_overlay(build / "s6_toast.png", [("diff -u config/policy.golden.yaml config/policy.yaml", diff)],
                                         {"left": 330, "top": 600}, font=21, width=940, title="config/policy.yaml · edited and saved (file watcher hot-reloads)"),
             cap=f"policy.yaml: INJ-02 {s6.get('old', '0.80')} → {s6.get('new', '0.50')}, hot-reloaded",
             chip="4 · Live policy edit", note=LIVE_NOTE),
        dict(id="b12", kind="still", src=build / "s6_block.png", dur=3.0, zoom=(1400, 420, 1.45),
             cap="Same prompt is now blocked", chip="4 · Live policy edit", note=LIVE_NOTE),
        dict(id="b13", kind="still", src=build / "s7_allow.png", dur=2.6, zoom=(1400, 420, 1.45),
             cap=f"EchoLeak payload allowed on feed #{feed.get('serial_before', '?')}", chip="5 · Signed threat feed",
             note=LIVE_NOTE),
        dict(id="b14", kind="still", src=build / "s7_feed.png", dur=3.0, zoom=(1100, 330, 1.25),
             cap=f"AEGIS-TI-022 published, signed #{feed.get('serial_after', '?')}", chip="5 · Signed threat feed",
             note="feed editor :8790 · Ed25519-signed bundle"),
        dict(id="b15", kind="still", src=build / "s7_block.png", dur=2.8, zoom=(1400, 420, 1.45),
             cap="Replay blocked: SIG-01 AEGIS-TI-022", chip="5 · Signed threat feed", note=LIVE_NOTE),
        dict(id="b16", kind="term", dur=3.6, cap=tests_cap, chip="6 · Tested and audited",
             html=page_term([(test_cmd, test_lines), ("make verify-audit", audit)], 24, width=1760),
             zoom=(960, 470, 1.03), note=None),
        dict(id="b17", kind="still", src=build / "s8_audit.png", dur=2.6, zoom=(1000, 320, 1.4),
             cap="Hash-chained audit log: chain OK", chip="6 · Tested and audited", note=LIVE_NOTE),
        dict(id="b18", kind="anim", card="end", dur=3.6),
    ]


# --------------------------------------------------------------------------- rendering
async def render_assets(build: Path, bl: list[dict]) -> None:
    work = build / "render"
    work.mkdir(exist_ok=True)
    b = await Browser(W, H, 1.0).start()
    try:
        for x in bl:
            if x["kind"] in ("term", "overlay"):
                src = work / f"{x['id']}.html"
                src.write_text(x["html"] if x["kind"] == "term" else x["html_fn"]())
                await b.goto(src.as_uri(), 0.6)
                await b.shot(work / f"{x['id']}_base.png")
                x["base"] = work / f"{x['id']}_base.png"
            elif x["kind"] == "still":
                x["base"] = x["src"]
            if x["kind"] != "anim":
                cap = work / f"{x['id']}_cap.html"
                cap.write_text(page_caption(x.get("cap", ""), x.get("chip"), x.get("note")))
                await b.send("Emulation.setDefaultBackgroundColorOverride", {"color": {"r": 0, "g": 0, "b": 0, "a": 0}})
                await b.goto(cap.as_uri(), 0.3)
                await b.shot(work / f"{x['id']}_cap.png")
                await b.send("Emulation.setDefaultBackgroundColorOverride", {})
                x["cap_png"] = work / f"{x['id']}_cap.png"
        # animated cards: step the CSS animations frame by frame (deterministic, no screen recording)
        for x in bl:
            if x["kind"] != "anim":
                continue
            d = work / f"{x['id']}_frames"
            n = int(round(x["dur"] * FPS))
            stamp = hashlib.sha256(CARDS.read_bytes() + f"{x['card']}{n}".encode()).hexdigest()
            x["frames"] = d
            if (d / "stamp").exists() and (d / "stamp").read_text() == stamp:
                continue  # frames already rendered from the same cards.html
            shutil.rmtree(d, ignore_errors=True)
            d.mkdir()
            await b.goto(CARDS.as_uri() + "#" + x["card"], 0.5)
            for i in range(n):
                ms = i * 1000 / FPS
                await b.js(f"document.getAnimations().forEach(a=>{{a.pause();a.currentTime={ms};}})")
                await b.shot(d / f"f{i:04d}.png")
            (d / "stamp").write_text(stamp)
    finally:
        await b.close()


def ff(args: list[str]) -> None:
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def _key(x: dict) -> str:
    h = hashlib.sha256(repr((x["kind"], x["dur"], x.get("zoom"), x.get("zdelay"), SCALE)).encode())
    for k in ("base", "cap_png"):
        if x.get(k):
            h.update(Path(x[k]).read_bytes())
    if x.get("frames"):
        for f in sorted(Path(x["frames"]).glob("f*.png")):
            h.update(f.read_bytes())
    return h.hexdigest()


def clip(x: dict, work: Path) -> Path:
    out = work / f"{x['id']}.mp4"
    keyf = work / f"{x['id']}.key"
    key = _key(x)
    if out.exists() and keyf.exists() and keyf.read_text() == key:
        return out  # unchanged since the last render
    _clip(x, work, out)
    keyf.write_text(key)
    return out


def _clip(x: dict, work: Path, out: Path) -> None:
    n = int(round(x["dur"] * FPS))
    enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p", "-r", str(FPS)]
    if x["kind"] == "anim":
        ff(["-framerate", str(FPS), "-i", str(x["frames"] / "f%04d.png"), "-frames:v", str(n),
            "-vf", f"scale={W}:{H},format=yuv420p", *enc, str(out)])
        return
    cx, cy, zt = x.get("zoom", (W / 2, H / 2, 1.0))
    delay = x.get("zdelay", 0.0)
    # eased (smoothstep) zoom from the full frame towards (cx, cy) at zoom zt, on a 2x canvas for smooth sub-pixel motion
    d0 = int(delay * FPS)
    tt = f"min(1,max(0,(in-{d0})/{max(1, n - 1 - d0)}))"
    e = f"({tt}*{tt}*(3-2*{tt}))"
    z = f"1+({zt}-1)*{e}"
    px = f"(iw/2+({cx * SCALE}-iw/2)*{e})"
    py = f"(ih/2+({cy * SCALE}-ih/2)*{e})"
    xx = f"max(0,min(iw-iw/zoom,{px}-iw/zoom/2))"
    yy = f"max(0,min(ih-ih/zoom,{py}-ih/zoom/2))"
    big = work / f"{x['id']}_2x.png"  # upscale once (zoompan on a 2x canvas = smooth sub-pixel motion)
    ff(["-i", str(x["base"]), "-vf", f"scale={int(W * SCALE)}:{int(H * SCALE)}:flags=lanczos", str(big)])
    fc = (f"[0:v]zoompan=z='{z}':x='{xx}':y='{yy}':d=1:s={W}x{H}:fps={FPS}[z];"
          f"[1:v]format=rgba[c];[z][c]overlay=0:0:format=auto,format=yuv420p[v]")
    ff(["-loop", "1", "-framerate", str(FPS), "-t", f"{x['dur']}", "-i", str(big),
        "-loop", "1", "-framerate", str(FPS), "-t", f"{x['dur']}", "-i", str(x["cap_png"]),
        "-filter_complex", fc, "-map", "[v]", "-frames:v", str(n), *enc, str(out)])


def assemble(bl: list[dict], clips: list[Path], out: Path) -> float:
    inputs, parts = [], []
    for c in clips:
        inputs += ["-i", str(c)]
    prev, acc = "[0:v]", bl[0]["dur"]
    for i in range(1, len(clips)):
        off = acc - XF
        lab = f"[x{i}]"
        trans = "fadeblack" if bl[i]["id"] in ("b03", "b18") else "fade"
        parts.append(f"{prev}[{i}:v]xfade=transition={trans}:duration={XF}:offset={off:.3f}{lab}")
        prev, acc = lab, acc + bl[i]["dur"] - XF
    total = acc
    parts.append(f"{prev}fade=t=out:st={total - 0.5:.3f}:d=0.5,format=yuv420p[v]")
    ff([*inputs, "-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
        "-filter_complex", ";".join(parts), "-map", "[v]", "-map", f"{len(clips)}:a",
        "-c:v", "libx264", "-preset", "slow", "-crf", "24", "-pix_fmt", "yuv420p", "-profile:v", "high",
        "-tune", "stillimage", "-r", str(FPS), "-c:a", "aac", "-b:a", "32k", "-shortest",
        "-movflags", "+faststart", str(out)])
    return total


def cover(build: Path, out: Path) -> None:
    """Cover image: the title card's final frame (designed card, not product footage)."""
    frames = sorted((build / "render" / "b01_frames").glob("f*.png"))
    shutil.copyfile(frames[-1], out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=VIDEO_DIR / "aegis-demo-60s.mp4")
    ap.add_argument("--tests", type=Path, default=VIDEO_DIR / "test-summary.txt",
                    help="captured `make test` summary (first line may be '# caption: ...')")
    a = ap.parse_args()
    build = a.build.resolve()
    facts = json.loads((build / "capture.json").read_text())["facts"]
    test_txt = a.tests.read_text()
    m = re.match(r"# caption: (.*)\n", test_txt)
    if m:
        facts["tests_caption"] = m.group(1).strip()
        test_txt = test_txt[m.end():]
    test_txt = "\n".join(ln for ln in test_txt.splitlines() if not ln.startswith("# "))
    bl = beats(build, facts, test_txt)
    total_planned = sum(x["dur"] for x in bl) - XF * (len(bl) - 1)
    print(f"[render] {len(bl)} beats, planned {total_planned:.2f} s")
    if total_planned > 58.0:
        raise SystemExit("planned duration > 58 s; shorten beats")
    asyncio.run(render_assets(build, bl))
    work = build / "render"
    clips = [clip(x, work) for x in bl]
    total = assemble(bl, clips, a.out)
    cover(build, VIDEO_DIR / "cover.png")
    (VIDEO_DIR / "captions.txt").write_text(caption_sheet(bl))
    print(f"[render] wrote {a.out} ({total:.2f} s, {a.out.stat().st_size / 1e6:.1f} MB) + cover.png")
    return 0


def caption_sheet(bl: list[dict]) -> str:
    t, rows = 0.0, []
    for i, x in enumerate(bl):
        start = t
        t += x["dur"] - (XF if i < len(bl) - 1 else 0)
        rows.append(f"{start:5.1f}–{t:5.1f} s  {x['id']}  {x.get('chip') or '':24s} {x.get('cap', '') or '(card)'}")
    return "Burned-in captions (generated by scripts/video/render.py)\n\n" + "\n".join(rows) + "\n"


if __name__ == "__main__":
    sys.exit(main())

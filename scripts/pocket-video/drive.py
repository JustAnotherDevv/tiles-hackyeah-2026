#!/usr/bin/env python3
"""Drive Aegis Pocket on a HarmonyOS emulator through the demo shot list and capture frames.

Standard library only. Controls are found by text in `uitest dumpLayout` output, not by fixed
coordinates (only the notification-shade swipe and scrolls use screen-relative positions).
Frames come from `snapshot_display` in a background thread at a steady cadence; each frame is
labelled with the beat that was active when it was taken. The frames stay on the device until
the end, then are pulled into <build>/raw/ and described in <build>/capture.json for render.py.

    python3 drive.py --hdc /path/to/hdc --target 127.0.0.1:5555 --build /tmp/pocket-video-build
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

BUNDLE = "com.hackyeah.aegispocket"
ABILITY = "EntryAbility"
DEV_DIR = "/data/local/tmp/pocketvid"
LAYOUT = "/data/local/tmp/pocketvid_layout.json"
HERE = Path(__file__).resolve().parent


def log(msg: str) -> None:
    print(f"[drive {time.strftime('%H:%M:%S')}] {msg}", flush=True)


class Hdc:
    def __init__(self, exe: str, target: str) -> None:
        self.exe = exe
        self.target = target
        self.lock = threading.Lock()  # one uitest call at a time (uitest rejects concurrent use)

    def run(self, *args: str, timeout: float = 30) -> str:
        cmd = [self.exe] + (["-t", self.target] if self.target else []) + list(args)
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (p.stdout or "") + (p.stderr or "")

    def shell(self, command: str, timeout: float = 30) -> str:
        return self.run("shell", command, timeout=timeout)


class Node:
    __slots__ = ("type", "text", "desc", "ident", "key", "bounds", "clickable")

    def __init__(self, attrs: dict) -> None:
        self.type = str(attrs.get("type", ""))
        self.text = str(attrs.get("text", "") or "")
        self.desc = str(attrs.get("description", "") or attrs.get("accessibilityText", "") or "")
        self.ident = str(attrs.get("id", "") or "")
        self.key = str(attrs.get("key", "") or "")
        self.clickable = str(attrs.get("clickable", "")).lower() == "true"
        m = re.findall(r"-?\d+", str(attrs.get("bounds", "")))
        self.bounds = tuple(int(v) for v in m[:4]) if len(m) >= 4 else (0, 0, 0, 0)

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return (x1 + x2) // 2, (y1 + y2) // 2

    def haystack(self) -> list[str]:
        return [self.text, self.desc, self.ident, self.key]


class Ui:
    def __init__(self, hdc: Hdc) -> None:
        self.hdc = hdc
        self.width = 0
        self.height = 0

    def dump(self) -> list[Node]:
        with self.hdc.lock:
            self.hdc.shell(f"rm -f {LAYOUT}; uitest dumpLayout -p {LAYOUT}", timeout=40)
            raw = self.hdc.shell(f"cat {LAYOUT}", timeout=20)
        start = raw.find("{")
        if start < 0:
            log("dumpLayout returned no JSON: " + raw[:200].replace("\n", " "))
            return []
        try:
            tree = json.loads(raw[start:raw.rfind("}") + 1])
        except json.JSONDecodeError as e:
            log(f"dumpLayout JSON error: {e}")
            return []
        nodes: list[Node] = []
        stack = [tree]
        while stack:
            n = stack.pop()
            if isinstance(n, dict):
                if isinstance(n.get("attributes"), dict):
                    nodes.append(Node(n["attributes"]))
                stack.extend(reversed(n.get("children", []) or []))
            elif isinstance(n, list):
                stack.extend(reversed(n))
        if nodes and not self.width:
            # The root node is the screen; scroll content below the fold can extend past it.
            root = nodes[0].bounds
            if root[2] > 0 and root[3] > 0:
                self.width, self.height = root[2], root[3]
            else:
                xs = [nd.bounds for nd in nodes if nd.bounds[2] > 0]
                self.width = max(b[2] for b in xs)
                self.height = max(b[3] for b in xs)
            log(f"screen ~{self.width}x{self.height}")
        return nodes

    def find(self, needle: str, nodes: list[Node] | None = None, exact: bool = False,
             on_screen: bool = True, case: bool = False, node_type: str = "") -> Node | None:
        nodes = self.dump() if nodes is None else nodes
        want = needle if case else needle.lower()
        best: Node | None = None
        for nd in nodes:
            if node_type:
                hit = nd.type == node_type
            else:
                hay = [h if case else h.lower() for h in nd.haystack() if h]
                hit = any((h == want) if exact else (want in h) for h in hay)
            if not hit:
                continue
            x, y = nd.center
            if on_screen and self.height and not (0 < y < self.height and 0 <= x <= self.width):
                continue
            # Prefer the smallest matching node (the control itself, not a container).
            if best is None or _area(nd) < _area(best):
                best = nd
        return best

    def wait_for(self, needles: list[str], timeout: float, exact: bool = False,
                 interval: float = 1.0) -> tuple[str, Node] | None:
        end = time.time() + timeout
        while time.time() < end:
            nodes = self.dump()
            for s in needles:
                nd = self.find(s, nodes, exact=exact)
                if nd is not None:
                    return s, nd
            time.sleep(interval)
        return None

    def click(self, x: int, y: int) -> None:
        with self.hdc.lock:
            self.hdc.shell(f"uitest uiInput click {x} {y}")

    def tap(self, needle: str, exact: bool = False, timeout: float = 8) -> bool:
        hit = self.wait_for([needle], timeout, exact=exact, interval=0.7)
        if hit is None:
            log(f"control not found: {needle!r}")
            return False
        x, y = hit[1].center
        log(f"tap {needle!r} at {x},{y}")
        self.click(x, y)
        return True

    def swipe(self, x1: int, y1: int, x2: int, y2: int, speed: int = 1600) -> None:
        with self.hdc.lock:
            self.hdc.shell(f"uitest uiInput swipe {x1} {y1} {x2} {y2} {speed}")

    def key(self, name: str) -> None:
        with self.hdc.lock:
            self.hdc.shell(f"uitest uiInput keyEvent {name}")

    def type_text(self, text: str, x: int, y: int) -> None:
        with self.hdc.lock:
            out = self.hdc.shell(f"uitest uiInput text {shlex.quote(text)}", timeout=60)
            if "error" in out.lower() or "usage" in out.lower():
                log("uiInput text unsupported, falling back to inputText x y")
                self.hdc.shell(f"uitest uiInput inputText {x} {y} {shlex.quote(text)}", timeout=60)

    def scroll_into_view(self, needle: str, target_frac: float = 0.35, exact: bool = False,
                         tries: int = 5) -> Node | None:
        """Scroll the page until the control's centre is near target_frac of the screen height."""
        for _ in range(tries):
            nd = self.find(needle, exact=exact, on_screen=False)
            x = self.width // 2
            if nd is None:  # off-screen controls may be filtered out of the dump: scroll down a bit
                self.swipe(x, int(self.height * 0.7), x, int(self.height * 0.4), 1200)
                time.sleep(0.9)
                continue
            dy = nd.center[1] - int(self.height * target_frac)
            if abs(dy) < self.height * 0.06:
                return nd
            dy = max(-int(self.height * 0.45), min(int(self.height * 0.45), dy))
            y0 = int(self.height * 0.72) if dy > 0 else int(self.height * 0.25)
            self.swipe(x, y0, x, y0 - dy, 1200)
            time.sleep(0.9)
        return self.find(needle, exact=exact)


def _area(nd: Node) -> int:
    x1, y1, x2, y2 = nd.bounds
    return max(1, (x2 - x1) * (y2 - y1))


class Capture(threading.Thread):
    """snapshot_display in a loop; frames stay on the device until pull()."""

    def __init__(self, hdc: Hdc, interval: float) -> None:
        super().__init__(daemon=True)
        self.hdc = hdc
        self.interval = interval
        self.beat = "_setup"
        self.frames: list[dict] = []
        self.stop_flag = threading.Event()
        self.t0 = time.time()

    def set_beat(self, beat: str) -> None:
        log(f"beat -> {beat}")
        self.beat = beat

    def run(self) -> None:
        i = 0
        while not self.stop_flag.is_set():
            started = time.time()
            name = f"f_{i:05d}.jpeg"
            beat = self.beat
            out = self.hdc.shell(f"snapshot_display -f {DEV_DIR}/{name}", timeout=20)
            if "fail" in out.lower() or "error" in out.lower():
                log("snapshot_display: " + out.strip()[:160])
            else:
                self.frames.append({"file": name, "t": round(started - self.t0, 3), "beat": beat})
                i += 1
            rest = self.interval - (time.time() - started)
            if rest > 0:
                time.sleep(rest)

    def stop(self) -> None:
        self.stop_flag.set()
        self.join(timeout=30)

    def pull(self, raw_dir: Path) -> None:
        raw_dir.mkdir(parents=True, exist_ok=True)
        log(f"pulling {len(self.frames)} frames")
        self.hdc.run("file", "recv", DEV_DIR, str(raw_dir), timeout=600)
        nested = raw_dir / Path(DEV_DIR).name
        if nested.is_dir():  # some hdc versions recv a directory into <dst>/<name>/
            for f in nested.iterdir():
                f.replace(raw_dir / f.name)
            nested.rmdir()
        for fr in self.frames:
            dst = raw_dir / fr["file"]
            if not dst.exists():
                self.hdc.run("file", "recv", f"{DEV_DIR}/{fr['file']}", str(dst), timeout=60)
        self.frames = [fr for fr in self.frames if (raw_dir / fr["file"]).exists()]


def hold(seconds: float) -> None:
    time.sleep(seconds)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hdc", required=True)
    ap.add_argument("--target", default="")
    ap.add_argument("--build", required=True)
    ap.add_argument("--interval", type=float, default=0.25, help="seconds between snapshot starts")
    ap.add_argument("--arrival-timeout", type=float, default=45)
    a = ap.parse_args()

    shots = json.loads((HERE / "shots.json").read_text())
    build = Path(a.build)
    build.mkdir(parents=True, exist_ok=True)
    hdc = Hdc(a.hdc, a.target)
    ui = Ui(hdc)
    variants: dict[str, str] = {}
    skipped: list[str] = []

    hdc.shell("power-shell wakeup")  # best effort: keep the emulator screen on
    hdc.shell(f"rm -rf {DEV_DIR}; mkdir -p {DEV_DIR}")

    log("launching (fresh process so the mock data and its 20 s first-request timer reset)")
    hdc.shell(f"aa force-stop {BUNDLE}")
    hold(1.0)
    out = hdc.shell(f"aa start -a {ABILITY} -b {BUNDLE}")
    log("aa start: " + out.strip()[:120])
    launched_at = time.time()

    cap = Capture(hdc, a.interval)
    cap.start()

    # First launch shows the notification permission dialog; allow it so the notification appears.
    ui.wait_for(["MOCK MODE", "LIVE", "Aegis Pocket"], timeout=25)
    hold(1.5)
    for _ in range(2):
        nodes = ui.dump()
        allow = ui.find("Allow", nodes, exact=True) or ui.find("允许", nodes, exact=True)
        if allow is None:
            break
        log("allowing notifications (system dialog)")
        ui.click(*allow.center)
        hold(1.2)
    nodes = ui.dump()
    if ui.find("MOCK MODE", nodes) is None:
        log("not in mock mode: switching in Settings")
        ui.tap("Settings", exact=True)
        hold(1.0)
        ui.tap("Mock (on-device demo)")
        hold(1.0)
        hdc.shell(f"aa force-stop {BUNDLE}")
        hold(1.0)
        hdc.shell(f"aa start -a {ABILITY} -b {BUNDLE}")
        launched_at = time.time()
        ui.wait_for(["MOCK MODE"], timeout=15)
    # Make sure Emily (admin) is the persona, from the Inbox, then come back Home.
    ui.tap("Inbox", exact=True)
    hold(0.8)
    emily = ui.find("Emily", exact=True)
    if emily is not None:
        ui.click(*emily.center)
        hold(0.6)
    ui.tap("Home", exact=True)
    hold(0.8)

    # 1. Home posture (frames until the simulated request arrives are a time-lapse of this beat).
    cap.set_beat("home")
    hold(4.0)
    remaining = max(5.0, a.arrival_timeout - (time.time() - launched_at))
    hit = ui.wait_for(["New approval request"], timeout=remaining, interval=0.8)
    # 2. Arrival banner.
    cap.set_beat("arrival")
    if hit is None:
        log("no in-app banner seen; continuing")
    hold(3.0)

    # 3. Notification shade: swipe down from the top-left (top-right opens Control Center).
    cap.set_beat("shade")
    w, h = ui.width or 1260, ui.height or 2720
    ui.swipe(int(w * 0.25), 2, int(w * 0.25), int(h * 0.6), 1800)
    hold(1.2)
    hit = ui.wait_for(["Approval needed"], timeout=6)
    if hit is not None:
        hold(1.5)
        ui.click(*hit[1].center)
        variants["shade"] = "default"
    else:
        log("notification not found in the shade; opening the request from the inbox instead")
        variants["shade"] = "banner"
        ui.key("Back")
        hold(0.8)
        ui.tap("Inbox", exact=True)
        hold(1.0)
        ui.tap("Buy dataset")
    hold(1.5)

    # 4. Risk explainer card.
    cap.set_beat("risk")
    nd = ui.scroll_into_view("WHY A HUMAN IS ASKED", target_frac=0.18, exact=True)
    hold(2.5)
    if nd is not None:
        ui.scroll_into_view("AGENT NOTE", target_frac=0.5, exact=True)
    hold(2.0)

    # 5. Open the $50 MarketPulse request (admin level, so Approve needs step-up).
    cap.set_beat("request")
    ui.key("Back")
    hold(0.8)
    ui.tap("Inbox", exact=True)
    hold(1.0)
    mp = ui.scroll_into_view("MarketPulse Pro", target_frac=0.45)
    if mp is None:
        log("ERROR: seeded MarketPulse Pro request not found in the inbox")
    else:
        ui.click(*mp.center)
    hold(1.5)
    ui.scroll_into_view("Approve", target_frac=0.72, exact=True)
    hold(1.0)

    # 6. Approve -> step-up (system sheet or labelled fallback dialog).
    cap.set_beat("stepup")
    ui.tap("Approve", exact=True)
    # Only the app's own fallback dialog has these strings; anything else is the system sheet.
    hit = ui.wait_for(["Device authentication unavailable"], timeout=10)
    hold(2.2)
    cap.set_beat("approved")
    if hit is not None:
        variants["stepup"] = variants["approved"] = "default"
        ui.tap("Confirm", exact=True)  # the fallback dialog's labelled manual-confirmation button
    else:
        log("system authentication sheet (or nothing) shown: cancelling, nothing is approved")
        variants["stepup"] = variants["approved"] = "sheet"
        ui.key("Back")
    hold(2.2)
    ui.key("Back")
    hold(1.6)

    # 7. "What data leaves" preview with synthetic identifiers typed in.
    cap.set_beat("preview")
    ui.tap("Preview", exact=True)
    hold(1.0)
    # Typing is skipped: on the emulator the first keyboard use opens the IME's own terms dialog, which this script
    # must not accept. The built-in synthetic sample has the same identifiers (email, phone, PESEL, IBAN, card).
    variants["preview"] = "sample"
    ui.tap("Clear", exact=True, timeout=2)
    ui.tap("Load sample", exact=True)
    hold(1.0)
    hold(1.0)
    # No Back key here: with the keyboard already hidden it would leave the app.
    ui.scroll_into_view("WHAT WOULD LEAVE THE DEVICE", target_frac=0.2, exact=True)
    hold(2.5)

    # 8. Home-screen widget, only if one is already placed (adding it through the launcher is manual).
    cap.set_beat("widget")
    ui.key("Home")
    hold(1.5)
    nodes = ui.dump()
    # Widget-only strings (the launcher icon label "Aegis Pocket" must not count).
    if any(ui.find(s, nodes, exact=True, case=True) for s in ("approvals waiting", "approval waiting", "AEGIS POCKET")):
        hold(3.0)
    else:
        log("no Aegis widget on the visible home screen page: widget beat skipped")
        skipped.append("widget")
    cap.set_beat("_end")
    hold(0.5)
    cap.stop()

    cap.pull(build / "raw")
    hdc.shell(f"rm -rf {DEV_DIR} {LAYOUT}")
    meta = {"frames": cap.frames, "variants": variants, "skipped": skipped,
            "screen": [ui.width, ui.height], "source": "device", "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    (build / "capture.json").write_text(json.dumps(meta, indent=1))
    counts: dict[str, int] = {}
    for fr in cap.frames:
        counts[fr["beat"]] = counts.get(fr["beat"], 0) + 1
    log(f"frames per beat: {counts}; variants: {variants}; skipped: {skipped}")
    missing = [b["id"] for b in shots["beats"] if not b.get("optional") and counts.get(b["id"], 0) == 0]
    if missing:
        log(f"ERROR: no frames for beats {missing}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Minimal Chrome DevTools Protocol driver for the demo-video capture (no project deps).

Run through `uv run --with websockets` (see make_video.sh). Launches headless Google Chrome with
a throwaway profile, exposes navigate / eval / screenshot helpers, and kills Chrome on close.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

CHROME = os.environ.get(
    "CHROME_BIN", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
)
DEBUG_PORT = int(os.environ.get("VIDEO_CDP_PORT", "8799"))


class Browser:
    def __init__(self, width: int = 1920, height: int = 1080, scale: float = 1.0):
        self.width, self.height, self.scale = width, height, scale
        self.proc: subprocess.Popen | None = None
        self.ws = None
        self._id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader: asyncio.Task | None = None
        self.profile = tempfile.mkdtemp(prefix="aegis-video-chrome-")

    async def start(self) -> "Browser":
        self.proc = subprocess.Popen(
            [
                CHROME,
                "--headless=new",
                f"--remote-debugging-port={DEBUG_PORT}",
                "--remote-allow-origins=*",
                f"--user-data-dir={self.profile}",
                f"--window-size={self.width},{self.height}",
                "--hide-scrollbars",
                "--force-color-profile=srgb",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-sync",
                "--mute-audio",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        url = None
        for _ in range(400):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json/list") as r:
                    pages = [p for p in json.load(r) if p.get("type") == "page"]
                if pages:
                    url = pages[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                pass
            time.sleep(0.1)
        if not url:
            await self.close()
            raise RuntimeError("Chrome did not expose a page target")
        self.ws = await websockets.connect(url, max_size=64 * 1024 * 1024)
        self._reader = asyncio.create_task(self._read())
        await self.send("Page.enable")
        await self.send("Runtime.enable")
        await self.send(
            "Emulation.setDeviceMetricsOverride",
            {"width": self.width, "height": self.height, "deviceScaleFactor": self.scale, "mobile": False},
        )
        await self.send(
            "Emulation.setEmulatedMedia",
            {"features": [{"name": "prefers-color-scheme", "value": "dark"},
                          {"name": "prefers-reduced-motion", "value": "reduce"}]},
        )
        return self

    async def _read(self):
        async for msg in self.ws:
            data = json.loads(msg)
            fut = self._pending.pop(data.get("id"), None) if "id" in data else None
            if fut and not fut.done():
                fut.set_result(data)

    async def send(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        fut = asyncio.get_running_loop().create_future()
        self._pending[self._id] = fut
        await self.ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        data = await asyncio.wait_for(fut, 60)
        if "error" in data:
            raise RuntimeError(f"{method}: {data['error']}")
        return data.get("result", {})

    async def resize(self, width: int, height: int, scale: float = 1.0):
        self.width, self.height, self.scale = width, height, scale
        await self.send(
            "Emulation.setDeviceMetricsOverride",
            {"width": width, "height": height, "deviceScaleFactor": scale, "mobile": False},
        )

    async def goto(self, url: str, settle: float = 1.5):
        await self.send("Page.navigate", {"url": url})
        await self.wait_for("document.readyState === 'complete'", 15)
        await asyncio.sleep(settle)

    async def js(self, expr: str):
        r = await self.send(
            "Runtime.evaluate",
            {"expression": expr, "awaitPromise": True, "returnByValue": True},
        )
        if "exceptionDetails" in r:
            raise RuntimeError(f"JS error: {r['exceptionDetails'].get('text')} :: {expr[:120]}")
        return r.get("result", {}).get("value")

    async def wait_for(self, expr: str, timeout: float = 10.0, interval: float = 0.2) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            try:
                if await self.js(f"!!({expr})"):
                    return True
            except RuntimeError:
                pass
            await asyncio.sleep(interval)
        return False

    async def click_text(self, text: str, selector: str = "button, [role=tab], a, [role=button]",
                         exact: bool = False) -> bool:
        """Click the first visible element matching selector whose text contains `text`."""
        t = json.dumps(text)
        return bool(await self.js(f"""(() => {{
          const want = {t}.toLowerCase();
          const els = [...document.querySelectorAll({json.dumps(selector)})].filter(e => {{
            const r = e.getBoundingClientRect(); if (!r.width || !r.height) return false;
            const s = (e.innerText || e.textContent || '').trim().toLowerCase();
            return {str(exact).lower()} ? s === want : s.includes(want);
          }});
          if (!els.length) return false; els[0].scrollIntoView({{block:'center'}}); els[0].click(); return true;
        }})()"""))

    async def shot(self, path: Path | str, clip: dict | None = None):
        params: dict = {"format": "png", "captureBeyondViewport": False}
        if clip:
            params["clip"] = {**clip, "scale": 1}
        r = await self.send("Page.captureScreenshot", params)
        Path(path).write_bytes(base64.b64decode(r["data"]))

    async def close(self):
        try:
            if self.ws:
                await self.ws.close()
        except Exception:
            pass
        if self._reader:
            self._reader.cancel()
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)

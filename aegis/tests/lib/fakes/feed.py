"""Signed fake threat feed (CONTRACTS §4.7) with test controls for update / tamper / rollback.

Serves `GET /feed/latest.json(.sig)`, `GET /feed/bundle/{name}(.sig)`, `GET /feed/pubkey`.
Test controls:
  POST /_test/publish {signatures: [...], withdraw: [ids]} → build, sign, bump serial
  POST /_test/tamper        → change the latest bundle bytes, keep the old signature
  POST /_test/serve_serial {n} → serve an older (validly signed) serial as latest
  POST /_test/wrong_key     → re-sign the next publish with another key
The base bundle is `config/feeds/seed_bundle.json` re-signed with a fresh test key (serial 1); it is
also written as `<dir>/seed_bundle.json(.sig)` so the gateway's seed load verifies with the test key.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

ROOT = Path(__file__).resolve().parents[3]
FEED_NAME = "aegis-threat-intel"
TEST_TOKEN = "AEGIS-FEED-UPDATE-TEST-91C2"


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(d: datetime) -> str:
    return d.isoformat().replace("+00:00", "Z")


def make_test_signature(
    sid: str = "AEGIS-TI-901", token: str = TEST_TOKEN, status: str = "stable"
) -> dict[str, Any]:
    """A harmless literal signature cloned from TI-000's shape."""
    return {
        "id": sid,
        "title": "Test signature published by the self-test suite",
        "status": status,
        "severity": "high",
        "confidence": "high",
        "aliases": [],
        "tags": ["test"],
        "references": [],
        "description": "Harmless marker used to prove feed updates reach the gateway.",
        "applies_to": {
            "surfaces": [
                "prompt.user",
                "model.request",
                "model.response",
                "tool.input",
                "tool.output",
                "mcp.call",
                "mcp.result",
                "egress.request",
            ]
        },
        "match": {"type": "literal_set", "values": [token], "case_insensitive": True},
        "action": "block",
        "message": "Self-test feed signature matched.",
        "published": "2026-10-03",
        "modified": "2026-10-03",
        "tests": {
            "positive": [{"name": "token", "surface": "model.request", "text": f"say {token} now"}],
            "negative": [{"name": "plain", "surface": "model.request", "text": "say hello now"}],
        },
    }


class FakeFeed:
    def __init__(self, directory: Path):
        from nacl.signing import SigningKey

        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.key = SigningKey.generate()
        self.other_key = SigningKey.generate()
        self.use_wrong_key = False
        pub = bytes(self.key.verify_key)
        self.key_id = hashlib.sha256(pub).hexdigest()[:8]
        self.pubkey_path = self.dir / "pub.b64"
        self.pubkey_path.write_text(base64.b64encode(pub).decode() + "\n")
        base_path = ROOT / "config" / "feeds" / "seed_bundle.json"
        if base_path.exists():
            self.base = json.loads(base_path.read_text())
        else:  # minimal bundle: just the canary
            self.base = {
                "feed": {"name": FEED_NAME, "schema_version": 1},
                "lists": {},
                "signatures": [],
            }
        self.signatures: list[dict[str, Any]] = list(self.base.get("signatures") or [])
        self.bundles: dict[int, tuple[bytes, str]] = {}
        self.pointers: dict[int, tuple[bytes, str]] = {}
        self.serial = 0
        self.latest = 0
        self.tampered = False
        self._build()  # serial 1 (= seed)
        b, sig = self.bundles[1]
        self.seed_path = self.dir / "seed_bundle.json"
        self.seed_path.write_bytes(b)
        Path(str(self.seed_path) + ".sig").write_text(sig)

    def _sign(self, data: bytes) -> str:
        k = self.other_key if self.use_wrong_key else self.key
        return base64.b64encode(k.sign(data).signature).decode()

    def _build(self) -> int:
        self.serial += 1
        now = _now()
        doc = copy.deepcopy(self.base)
        hdr = dict(doc.get("feed") or {})
        hdr.update(
            {
                "name": FEED_NAME,
                "schema_version": hdr.get("schema_version", 1),
                "serial": self.serial,
                "version": f"{now:%Y.%m.%d}-{self.serial}",
                "published": _iso(now),
                "expires": _iso(now + timedelta(days=30)),
                "key_id": self.key_id,
                "signature_count": len(self.signatures),
            }
        )
        doc["feed"] = hdr
        doc["signatures"] = self.signatures
        data = json.dumps(doc, indent=1, sort_keys=True).encode()
        name = f"bundle-{self.serial:06d}.json"
        self.bundles[self.serial] = (data, self._sign(data))
        ptr = {
            "feed": FEED_NAME,
            "serial": self.serial,
            "version": hdr["version"],
            "bundle": name,
            "sha256": hashlib.sha256(data).hexdigest(),
            "published": hdr["published"],
            "expires": hdr["expires"],
            "key_id": self.key_id,
        }
        pdata = json.dumps(ptr, sort_keys=True).encode()
        self.pointers[self.serial] = (pdata, self._sign(pdata))
        self.latest = self.serial
        self.tampered = False
        return self.serial

    # ------------------------------------------------------------------ controls (also callable directly)
    def publish(
        self, signatures: list[dict[str, Any]] | None = None, withdraw: list[str] | None = None
    ) -> int:
        with self.lock:
            by_id = {s["id"]: s for s in self.signatures}
            for s in signatures or []:
                by_id[s["id"]] = s
            for sid in withdraw or []:
                if sid in by_id:
                    by_id[sid] = {**by_id[sid], "status": "withdrawn"}
            self.signatures = list(by_id.values())
            return self._build()

    def tamper(self) -> None:
        with self.lock:
            data, sig = self.bundles[self.latest]
            self.bundles[self.latest] = (
                data.replace(b'"severity"', b'"severity" ', 1) + b"\n",
                sig,
            )
            self.tampered = True

    def create_app(self) -> FastAPI:
        app = FastAPI(title="aegis-test-fake-feed")

        @app.get("/feed/latest.json")
        async def latest() -> Response:
            return Response(self.pointers[self.latest][0], media_type="application/json")

        @app.get("/feed/latest.json.sig")
        async def latest_sig() -> PlainTextResponse:
            return PlainTextResponse(self.pointers[self.latest][1])

        @app.get("/feed/bundle/{name}")
        async def bundle(name: str) -> Response:
            serial, sig = self._lookup(name)
            if serial is None:
                return JSONResponse({"error": "not found"}, 404)
            data, s = self.bundles[serial]
            return PlainTextResponse(s) if sig else Response(data, media_type="application/json")

        @app.get("/feed/pubkey")
        async def pubkey() -> PlainTextResponse:
            return PlainTextResponse(self.pubkey_path.read_text())

        @app.post("/_test/publish")
        async def t_publish(request: Request) -> dict[str, Any]:
            body = await request.json() if (await request.body()) else {}
            return {"serial": self.publish(body.get("signatures"), body.get("withdraw"))}

        @app.post("/_test/tamper")
        async def t_tamper() -> dict[str, Any]:
            self.tamper()
            return {"serial": self.latest, "tampered": True}

        @app.post("/_test/serve_serial")
        async def t_serve(request: Request) -> dict[str, Any]:
            n = int((await request.json()).get("n", 1))
            self.latest = n if n in self.pointers else self.latest
            return {"serial": self.latest}

        @app.post("/_test/wrong_key")
        async def t_wrong(request: Request) -> dict[str, Any]:
            self.use_wrong_key = True
            return {"wrong_key": True}

        return app

    def _lookup(self, name: str) -> tuple[int | None, bool]:
        sig = name.endswith(".sig")
        base = name[:-4] if sig else name
        try:
            serial = int(base.removeprefix("bundle-").removesuffix(".json"))
        except ValueError:
            return None, sig
        return (serial if serial in self.bundles else None), sig


__all__ = ["TEST_TOKEN", "FakeFeed", "make_test_signature"]

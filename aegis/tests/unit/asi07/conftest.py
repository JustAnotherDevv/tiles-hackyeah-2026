"""ASI07 fixtures: the REAL gateway with the asi-07 snippet applied + mocks/mock_peer in-process.

`a2a_policy` folds `config/snippets/asi-07.yaml` (A2A-01/02 entries) into the temp policy copy of
the root `aegis_env` fixture, so these tests do not depend on the snippet having been merged into
config/policy.yaml yet. The peer is reached through an ASGI transport (no ports).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
SNIPPET = ROOT / "config" / "snippets" / "asi-07.yaml"
PEER_BASE = "http://127.0.0.1:8795"


def snippet_controls() -> list[dict[str, Any]]:
    return yaml.safe_load(SNIPPET.read_text())["controls"]


@pytest.fixture
def a2a_policy(aegis_env: dict[str, Any]) -> Path:
    path: Path = aegis_env["policy_path"]
    doc = yaml.safe_load(path.read_text())
    new = {c["id"]: c for c in snippet_controls()}
    controls = [c for c in doc.get("controls", []) if c.get("id") not in new]
    controls.extend(new.values())
    doc["controls"] = controls
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    return path


@pytest.fixture
def peer_app() -> Any:
    from mocks.mock_peer.app import create_app

    return create_app()


def _reset_shared_state() -> None:
    from aegis.a2a import card, nonces

    nonces.reset()
    card.reset()
    try:  # RES-01 (ASI08) quarantines an agent after 3 blocks - per-test isolation
        from aegis.controls.resilience._state import STATE

        STATE.reset()
    except Exception:
        pass


@pytest.fixture
async def a2a(a2a_policy: Path, aegis_env: dict[str, Any], peer_app: Any) -> Any:
    from asgi_lifespan import LifespanManager

    from aegis.app import create_app
    from aegis.settings import Settings

    _reset_shared_state()
    app = create_app(Settings.from_env())
    async with LifespanManager(app, startup_timeout=60, shutdown_timeout=30):
        rt = app.state.rt
        peer = httpx.AsyncClient(transport=httpx.ASGITransport(app=peer_app),
                                 base_url=PEER_BASE, timeout=30)
        rt.extras["a2a.client"] = peer
        gw = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                               base_url="http://aegis.test", timeout=30)
        try:
            yield gw, peer, rt
        finally:
            await gw.aclose()
            await peer.aclose()
            rt.extras.pop("a2a.client", None)
            _reset_shared_state()

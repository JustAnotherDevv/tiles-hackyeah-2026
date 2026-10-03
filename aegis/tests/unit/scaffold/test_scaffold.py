"""Scaffold smoke tests: frozen contract modules import, app boots, discovery works."""

from __future__ import annotations

import httpx
import pytest
from asgi_lifespan import LifespanManager


def test_frozen_modules_import() -> None:
    from aegis.core import policy_schema, protocols, types

    assert types.ACTION_PRECEDENCE["block"] > types.ACTION_PRECEDENCE["allow"]
    assert types.new_id("dec").startswith("dec_")
    doc = policy_schema.PolicyDoc()
    assert doc.profile == "balanced"
    assert issubclass(protocols.BaseControl, object)


def test_policy_doc_rejects_unknown_top_level_key() -> None:
    from pydantic import ValidationError

    from aegis.core.policy_schema import PolicyDoc

    with pytest.raises(ValidationError):
        PolicyDoc.model_validate({"controlz": []})


def test_discovery_finds_scaffold_routers() -> None:
    from aegis.core.discovery import create_registry, discover_routers

    names = [m.__name__ for m in discover_routers()]
    assert "aegis.api.routes.health" in names
    assert names[-1] == "aegis.api.routes.ui"  # ORDER 900 goes last
    assert create_registry().all() is not None


async def test_healthz_and_ui(tmp_path) -> None:
    from aegis.app import create_app
    from aegis.settings import Settings

    app = create_app(Settings(data_dir=tmp_path / "data", ui_dist=tmp_path / "dist"))
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://aegis.test") as client:
            r = await client.get("/healthz")
            assert r.status_code == 200
            body = r.json()
            assert body["status"] in {"ok", "degraded"}
            assert set(body) >= {
                "version",
                "uptime_s",
                "policy_version",
                "feed_serial",
                "components",
            }
            r = await client.get("/")
            assert r.status_code == 302 and r.headers["location"] == "/ui/"
            r = await client.get("/ui/anything")
            assert r.status_code == 200 and "make web" in r.text

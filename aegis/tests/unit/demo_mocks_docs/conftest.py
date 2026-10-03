"""Fixtures for demo-mocks-docs tests: in-process ASGI clients for the three owned mocks.

No ports are bound (httpx.ASGITransport); logs go to a tmp data dir. AEGIS_TEST_MODE=1.
"""

from __future__ import annotations

import os

import httpx
import pytest

os.environ.setdefault("AEGIS_TEST_MODE", "1")
os.environ.setdefault("AEGIS_SEMANTIC", "off")


def _client(app, base_url: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url)


@pytest.fixture
def llm_app(tmp_path):
    from mocks.mock_llm.app import create_app

    return create_app(data_dir=tmp_path, seed=1234, delta_ms=0)


@pytest.fixture
async def llm(llm_app):
    async with _client(llm_app, "http://mock-llm.test") as c:
        yield c


@pytest.fixture
async def sink(tmp_path):
    from mocks.exfil_sink.app import create_app

    async with _client(create_app(data_dir=tmp_path), "http://exfil.test") as c:
        yield c


@pytest.fixture
async def saas(tmp_path):
    from mocks.mock_saas.app import create_app

    async with _client(create_app(data_dir=tmp_path), "http://pay.saas.test") as c:
        yield c

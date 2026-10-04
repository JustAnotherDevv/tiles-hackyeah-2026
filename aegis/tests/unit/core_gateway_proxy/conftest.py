"""Fixtures for the model-proxy unit tests (bundle B02): fake runtime, in-process ASGI client,
mock upstream transport. No fixed ports, no network, no models."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator

import httpx
import pytest

from aegis.proxy import upstream
from tests.unit.core_gateway_proxy.fakes import FakeRuntime, Upstream, echo_anthropic, make_app


@pytest.fixture
def rt() -> FakeRuntime:
    return FakeRuntime()


@pytest.fixture
def set_upstream() -> Iterator[Callable[..., Upstream]]:
    def _set(handler: Callable[[httpx.Request], httpx.Response] = echo_anthropic) -> Upstream:
        up = Upstream(handler)
        upstream.set_transport(up.transport)
        return up

    yield _set
    upstream.set_transport(None)


@pytest.fixture
async def client(rt: FakeRuntime) -> AsyncIterator[httpx.AsyncClient]:
    app = make_app(rt)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://aegis.test") as c:
        yield c

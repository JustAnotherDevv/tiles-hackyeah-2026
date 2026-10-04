"""Root fixtures (CONTRACTS §7.3, binding names) + e2e stack fixtures (plan 18 §2.3).

Contract fixtures (function scope, in-process ASGI; usable by every workstream's unit tests):
    aegis_env, app, client, rt, mock_llm_url, policy_patch
E2E fixtures (real sockets on ephemeral ports, or the live stack when AEGIS_LIVE_URL is set):
    aegis_stack (module), gw (module; the stack's Gateway client), make_stack (factory), live
No fixture here is autouse, so other workstreams' tests are unaffected.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

pytest_plugins = ["tests.lib.plugin"]

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- contract fixtures (§7.3)
@pytest.fixture
def aegis_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Temp data dir + temp golden policy copy; semantic off, feed disabled, test mode on."""
    data = tmp_path / "data"
    data.mkdir()
    src = ROOT / "config" / "policy.golden.yaml"
    if not src.exists():
        src = ROOT / "config" / "policy.yaml"
    policy = tmp_path / "policy.yaml"
    if src.exists():
        shutil.copy(src, policy)
    env = {
        "AEGIS_DATA_DIR": str(data),
        "AEGIS_POLICY": str(policy),
        "AEGIS_SEMANTIC": "off",
        "AEGIS_FEED_URL": "disabled",
        "AEGIS_TEST_MODE": "1",
        "AEGIS_WARMUP": "off",
        "AEGIS_REPORTS_DIR": str(tmp_path / "reports"),
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    try:
        from aegis.settings import get_settings

        get_settings.cache_clear()
    except Exception:
        pass
    return {"data_dir": data, "policy_path": policy, "tmp": tmp_path, "env": env}


@pytest.fixture
async def app(aegis_env: dict[str, Any]) -> AsyncIterator[Any]:
    from asgi_lifespan import LifespanManager

    from aegis.app import create_app
    from aegis.settings import Settings

    application = create_app(Settings.from_env())
    async with LifespanManager(application, startup_timeout=60, shutdown_timeout=30):
        yield application


@pytest.fixture
async def client(app: Any) -> AsyncIterator[Any]:
    import httpx

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://aegis.test", timeout=30
    ) as c:
        yield c


@pytest.fixture
async def rt(app: Any) -> Any:
    return app.state.rt


@pytest.fixture
def mock_llm_url() -> Iterator[str]:
    """Fake (or, with AEGIS_TEST_MOCKS=real, the real mock_llm) LLM on an ephemeral port."""
    from tests.lib.fakes import llm
    from tests.lib.servers import ThreadedUvicorn

    application = None
    if os.environ.get("AEGIS_TEST_MOCKS") == "real":
        try:
            from mocks.mock_llm.app import create_app as real

            application = real()
        except Exception:
            application = None
    srv = ThreadedUvicorn(application or llm.create_app(), name="mock-llm").start()
    try:
        yield srv.url
    finally:
        srv.stop()


@pytest.fixture
def policy_patch(aegis_env: dict[str, Any], app: Any) -> Callable[..., Any]:
    """`await policy_patch(fn)`: ruamel-edit the temp policy, write atomically, apply via the store."""
    from tests.lib import policy_sandbox

    async def _patch(fn: Callable[[Any], Any]) -> Any:
        path: Path = aegis_env["policy_path"]
        text = policy_sandbox.edit(path.read_text(), fn)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text)
        tmp.replace(path)
        store = getattr(app.state.rt, "policy", None)
        apply = getattr(store, "apply_yaml", None)
        if apply is None:
            pytest.skip("policy store has no apply_yaml (Null fallback)")
        return await apply(text, actor=None, source="file")

    return _patch


# ---------------------------------------------------------------- e2e fixtures
@pytest.fixture(scope="session")
def live() -> bool:
    return bool(os.environ.get("AEGIS_LIVE_URL"))


def _boot(**kw: Any) -> Any:
    from tests.lib.matrix import RESULTS
    from tests.lib.stack import StackError, make_stack

    try:
        st = make_stack(**kw)
    except StackError as exc:
        RESULTS.stack_error = str(exc)
        pytest.skip(str(exc))
    if not RESULTS.gateway:
        RESULTS.gateway = st.info()
    if not RESULTS.controls_live:
        RESULTS.controls_live = st.gw.controls()
    return st


@pytest.fixture(scope="module")
def aegis_stack() -> Iterator[Any]:
    """One hermetic stack per test module (or the live stack)."""
    st = _boot()
    try:
        yield st
    finally:
        st.stop()


@pytest.fixture(scope="module")
def gw(aegis_stack: Any) -> Any:
    return aegis_stack.gw


@pytest.fixture
def make_stack() -> Iterator[Callable[..., Any]]:
    """Factory for custom stacks (feed / mcp / overrides / test_mode=False); one alive at a time."""
    made: list[Any] = []

    def _make(**kw: Any) -> Any:
        st = _boot(**kw)
        made.append(st)
        return st

    yield _make
    for st in reversed(made):
        st.stop()

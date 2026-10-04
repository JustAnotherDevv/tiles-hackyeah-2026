"""policy-engine unit-test fixtures (hermetic: temp config + data dirs, test mode, semantic off)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
POLICY_SRC = REPO / "config" / "policy.yaml"
PROFILES_SRC = REPO / "config" / "profiles"


@pytest.fixture(autouse=True)
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AEGIS_TEST_MODE", "1")
    monkeypatch.setenv("AEGIS_SEMANTIC", "off")
    monkeypatch.setenv("AEGIS_FEED_URL", "disabled")
    monkeypatch.setenv("AEGIS_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture
def policy_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = tmp_path / "config"
    cfg.mkdir()
    shutil.copy(POLICY_SRC, cfg / "policy.yaml")
    shutil.copy(POLICY_SRC, cfg / "policy.golden.yaml")
    shutil.copytree(PROFILES_SRC, cfg / "profiles")
    monkeypatch.setenv("AEGIS_POLICY", str(cfg / "policy.yaml"))
    return cfg


@pytest.fixture
def policy_text() -> str:
    return POLICY_SRC.read_text(encoding="utf-8")


class FakeBus:
    def __init__(self) -> None:
        self.messages: list[tuple[str, Any]] = []

    def publish(self, event: str, data: Any) -> None:
        self.messages.append((event, data))

    def events(self, name: str) -> list[Any]:
        return [d for e, d in self.messages if e == name]


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def record(self, event: Any) -> Any:
        self.events.append(event)
        return event

    def of(self, event_type: str) -> list[Any]:
        return [e for e in self.events if e.event_type == event_type]


class FakeMetrics:
    def __init__(self) -> None:
        self.gauges: dict[str, float] = {}
        self.counters: dict[tuple[str, str], float] = {}

    def inc(self, name: str, labels: Any = None, value: float = 1.0) -> None:
        key = (name, str(sorted((labels or {}).items())))
        self.counters[key] = self.counters.get(key, 0) + value

    def set_gauge(self, name: str, value: float, labels: Any = None) -> None:
        self.gauges[name] = value


class FakeSettings:
    def __init__(self, policy: Path, data_dir: Path):
        self.policy = policy
        self.data_dir = data_dir
        self.test_mode = True


class FakeRuntime:
    """No pipeline / approvals / org / db: the store keeps versions in memory and skips the gate."""

    def __init__(self, policy: Path, data_dir: Path):
        self.settings = FakeSettings(policy, data_dir)
        self.bus = FakeBus()
        self.audit = FakeAudit()
        self.metrics = FakeMetrics()


@pytest.fixture
def fake_rt(policy_dir: Path, tmp_path: Path) -> FakeRuntime:
    return FakeRuntime(policy_dir / "policy.yaml", tmp_path / "data")


@pytest.fixture
def store(fake_rt: FakeRuntime) -> Any:
    from aegis.policy.store import create

    return create(fake_rt)

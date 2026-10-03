"""TI-V09: SIG-03 package-install guard against the seed bundle lists."""

from __future__ import annotations

import pytest
from tf_fakes import cfg, ctx

from aegis.controls.signatures.sig03_packages import CONTROLS
from aegis.core.types import Interaction

SIG03 = CONTROLS[0]


def bash(cmd: str, surface: str = "tool.input") -> Interaction:
    return Interaction(
        kind="tool_call", surface=surface, tool_name="Bash", tool_args={"command": cmd}
    )


@pytest.mark.parametrize(
    "cmd,expected",
    [
        ("pip install litellm==1.82.8", "block"),
        ("npm i event-stream@3.3.6", "block"),
        ("pip install huggingface-cli", "require_approval"),
        ("pip install requests", "allow"),
        ("pip install acme-quant-utils", "require_approval"),
        ("pip install litellm", "log"),
        ("code --install-extension amazonwebservices.amazon-q-vscode@1.84.0", "block"),
    ],
)
async def test_install_commands(seed_manager, cmd: str, expected: str) -> None:
    d = await SIG03.evaluate(ctx(seed_manager.rt), bash(cmd), cfg())
    assert d is not None and d.action == expected, (cmd, d.reason if d else None)


async def test_unknown_package_approval_draft(seed_manager) -> None:
    d = await SIG03.evaluate(ctx(seed_manager.rt), bash("pip install acme-quant-utils"), cfg())
    assert d.approval is not None and d.approval.labels["signals"] == "unknown_package"
    assert d.approval.resource == "pkg:pypi/acme-quant-utils"


async def test_mcp_init_unknown_logs(seed_manager) -> None:
    i = Interaction(
        kind="mcp",
        surface="mcp.init",
        tool_args={"command": "npx", "args": ["-y", "some-mcp-thing"]},
    )
    d = await SIG03.evaluate(ctx(seed_manager.rt), i, cfg())
    assert d is not None and d.action == "log"


async def test_no_install_command(seed_manager) -> None:
    assert await SIG03.evaluate(ctx(seed_manager.rt), bash("ls -la"), cfg()) is None


async def test_no_lists_degraded(monkeypatch) -> None:
    from aegis.controls.signatures import _common

    monkeypatch.setattr(_common, "runtime", lambda: None)
    d = await SIG03.evaluate(ctx(), bash("pip install litellm==1.82.8"), cfg())
    assert d is not None and d.degraded and d.action == "allow"

"""SIG-03 — Package-install guard (TI-01 stub; returns None)."""

from __future__ import annotations

from aegis.core.protocols import BaseControl


class PackageInstallGuard(BaseControl):
    id, family, name, kind = "SIG-03", "SIG", "Package-install guard", "deterministic"

    async def evaluate(self, ctx, interaction, cfg):  # type: ignore[override]
        return None


CONTROLS = [PackageInstallGuard()]

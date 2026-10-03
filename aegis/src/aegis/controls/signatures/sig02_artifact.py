"""SIG-02 — Model-artifact gate (TI-01 stub; returns None)."""

from __future__ import annotations

from aegis.core.protocols import BaseControl


class ModelArtifactGate(BaseControl):
    id, family, name, kind = "SIG-02", "SIG", "Model-artifact gate", "deterministic"

    async def evaluate(self, ctx, interaction, cfg):  # type: ignore[override]
        return None


CONTROLS = [ModelArtifactGate()]

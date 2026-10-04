"""Rogue-agent detection support (ASI10): per-agent behavioural baselines + quarantine store.

The store is in-memory, bounded (LRU) and deterministic; ROG-01
(``aegis.controls.rogue.rog01_behaviour``) is its only writer. ``STORE.view()`` is a
read-only snapshot for dashboards / debugging.
"""

from aegis.rogue.store import STORE, AgentBaseline, BaselineStore, Quarantine, SessionState

__all__ = ["STORE", "AgentBaseline", "BaselineStore", "Quarantine", "SessionState"]

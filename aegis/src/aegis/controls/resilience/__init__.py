"""Resilience controls (ASI08 Cascading Failures).

* ``_failsafe`` - shared helper: a control's internal error becomes a decision that honours the
  control's configured ``fail_mode`` (closed -> degraded block), mirroring the pipeline's own
  ``_fail_decision`` so a fault inside one control never silently weakens the chain.
* ``res01_cascade`` - RES-01 cascading-failure breaker: quarantines an agent/session whose actions
  keep getting blocked, opens a circuit on a failing downstream tool / MCP server, and taints the
  consumers of a quarantined agent's outputs so the failure does not propagate to other agents.

Owner: ASI-FAILCLOSED (ASI08).
"""

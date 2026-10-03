# Aegis — AI Control Layer

Local-first gateway that governs agent ↔ model / MCP / third-party traffic: redaction, injection
and exfiltration defense, budgets, org approvals, signed threat feed, audit log and a live dashboard.
HackYeah 2026 · Goldman Sachs task.

**Start with [`HANDOFF.md`](HANDOFF.md)** (status, plans, rules), then [`docs/BRIEF.md`](docs/BRIEF.md)
and the binding contract [`docs/CONTRACTS.md`](docs/CONTRACTS.md). Workstream plans live in `docs/plan/`.

## Quick start

```bash
make setup          # uv sync (Python 3.13) + npm ci (web/)
make web            # build the dashboard into web/dist
make gateway        # http://127.0.0.1:8787/healthz · dashboard at /ui
make test           # test suite
make help           # every target
```

(The full judge-facing README is owned by the demo-mocks-docs workstream.)

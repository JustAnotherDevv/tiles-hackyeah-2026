"""Scripted demo agents (owner: demo-mocks-docs / bundle B23).

Every script here talks to Aegis only through the public `aegis.sdk` surface, so each printed row
in the terminal is also a real row in the dashboard's live feed.

    uv run --frozen python demo/agents/trading_copilot.py pii-draft     # F1
    uv run --frozen python demo/agents/trading_copilot.py subscribe     # F4
    uv run --frozen python demo/agents/runaway.py                       # F6
    uv run --frozen python demo/agents/chaos_agent.py --json            # every control family
    uv run --frozen python demo/agents/ambient.py --duration 600        # background traffic
    uv run --frozen python demo/agents/research_agent.py                # local Ollama agent
"""

"""MCP proxy & tool governance (owner: mcp-proxy).

Modules: `jsonrpc` (wire helpers), `detect` (tool-definition scan), `pins` (PinStore),
`interactions` (Interaction builders + verdict write-back), `proxy` (McpGovernor + HTTP
plumbing), `service` (McpService singleton), `events`, `inventory`, `client` (raw Streamable
HTTP client, public surface), `stdio` (wrapper CLI), `claude_config` (Claude Code config).

No import-time side effects.
"""

"""Mock LLM (Anthropic + OpenAI wires), port 8791 (owner: demo-mocks-docs).

`mocks.mock_llm.app:create_app()` for in-process use; `python -m mocks.mock_llm` to serve.
Echoes what it received so placeholders that left the gateway are visible; triggers in
`mocks.mock_llm.script`.
"""

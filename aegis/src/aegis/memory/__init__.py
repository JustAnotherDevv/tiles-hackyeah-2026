"""Persistent agent memory helpers for ctl MEM-01 (OWASP ASI06 Memory & Context Poisoning).

* :mod:`aegis.memory.classify`   - is this interaction a memory write / read? (files such as
  ``CLAUDE.md``/``AGENTS.md``/``.cursorrules``/``memory/*.md``/``.claude/**``, MCP memory-server
  tools, RAG ingestion tools, shell redirections into memory files) and what content it carries.
* :mod:`aegis.memory.scan`       - content scan: prompt-injection signatures (``aegis.injection``
  normalize + signatures), agent-directive heuristics, secrets/PII (``aegis.redaction.scan``).
* :mod:`aegis.memory.provenance` - per-session record of untrusted content the agent has seen
  (shingle fingerprints of tool/MCP/A2A results) so a memory write *derived from* it is caught,
  plus a bounded ledger of memory writes (provenance stamps).

Pure helpers: no policy reads, no runtime writes except the in-process provenance store.
"""

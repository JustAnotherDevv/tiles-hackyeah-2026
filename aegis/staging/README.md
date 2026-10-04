# staging/

Pre-integration spikes, corpora, model benchmarks and design prototypes that fed the shipped code in
`src/aegis/`. Nothing here is imported at runtime.

**Removed from the public history:** the legacy PII fixture files (`staging/pii/` test corpora) and some
spike tests were dropped when Aegis was merged into this monorepo, because they contained realistic-looking
fake secrets (test API keys, tokens, card numbers) that trip GitHub push protection. They were synthetic
test data, never real credentials. The live fixtures used by the test suite are either generated at
runtime or stored rot13-encoded under `src/aegis/redaction/data/fixtures/` (for example
`secrets_code.rot13.jsonl`), so `make test` and `make eval` do not depend on the removed files.

"""Auto-discovered controls (CONTRACTS section 2.1 / 4.4).

Any module below this package may expose `CONTROLS: list[Control]` (instances). Discovery
walks the package recursively and skips modules whose name starts with `_`.

Owner: scaffold (empty package); subpackages per CONTRACTS section 1.1 (docs/CONTRACTS.md section 1.2). Scaffold stub - safe to replace.
"""

# Notes for coding agents

- Python 3.12, stdlib only. Keep functions small and typed.
- Staging builds run on `build-07.corp.local`; logs are on `logs.acme.internal`.
- Never commit `.env` or anything under `letters/`.
- Customer letters go to `letters/<customer_id>.md` (local only, git-ignored).

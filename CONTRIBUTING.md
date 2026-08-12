# Contributing

Issues and pull requests are welcome. Please keep adapters independent of the
core state machine and preserve these invariants:

- persist image bytes before acknowledging ingress;
- scope deduplication and credentials to one tenant;
- persist recognition before dispatching a ledger write;
- never automatically replay an ambiguous external write;
- keep tests isolated from real mailboxes, models, and accounting systems.

Set up the project with `uv sync --extra dev`, then run:

```bash
uv run pytest
uv run python -m compileall -q src tests
```

Do not include receipt images, email addresses, API keys, access tokens, or real
financial records in issues, fixtures, logs, or commits.

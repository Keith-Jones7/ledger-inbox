# Architecture

Ledger Inbox is split into four boundaries so deployments can replace one part
without weakening the others.

## 1. Ingress

HTTPS uploads authenticate with a tenant API key. Email arrives through either
IMAP or a signed RFC822 webhook and resolves a random inbound alias to a tenant.
The ingress layer accepts image bytes and metadata; it never executes or forwards
email-body instructions.

## 2. Durable inbox

Image bytes are signature-validated, SHA-256 hashed, and atomically stored before
an SQLite event is committed. Deduplication uses `(tenant_id, content_sha256)`, so
the same screenshot sent twice or through two channels produces one event, while
different tenants remain isolated.

Event states:

```text
queued -> processing -> recognition_failed
                   \-> needs_review
                   \-> recognized -> delivering -> completed
                                              \-> delivery_failed
                                              \-> delivery_unknown
```

`recognition_failed` is known to occur before any ledger dispatch. A deployment
may explicitly requeue it after fixing the recognizer. `delivery_unknown` may
have reached the destination and must be reconciled by operation ID; it must not
be replayed automatically.

## 3. Recognition and review gate

A recognizer receives a local image path plus non-secret event context and
returns a normalized `LedgerEntry`. Entries with missing or invalid critical
fields become `needs_review`. The worker persists recognition before creating a
delivery operation.

The built-in OpenAI-compatible adapter is intentionally small. OCR ensembles,
merchant learning, model comparison, category taxonomies, and review workflows
belong in adapters or future optional packages.

## 4. Ledger delivery

A ledger sink receives the normalized entry, event ID, and stable operation ID.
The directory sink creates an immutable operation file. The webhook sink supplies
the operation ID as an idempotency key and optional HMAC signature.

The database is the control-plane record, not necessarily the final accounting
ledger. The target accounting application remains authoritative for confirmed
entries.

## Deployment model

The API and worker are separate processes sharing one private data volume. SQLite
is suitable for a small single-host deployment. A production multi-host backend
can implement the same repository contract with PostgreSQL and object storage.

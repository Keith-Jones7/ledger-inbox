# Ledger Inbox

Ledger Inbox is an open-source, self-hosted image inbox for bookkeeping automation.
It accepts payment screenshots and receipt images over HTTPS or email, normalizes
them into a durable processing pipeline, delegates recognition to a replaceable
model adapter, and delivers structured entries to a replaceable ledger adapter.

The project is intentionally **not tied to one accounting app, one model vendor,
or one client**. An iPhone Shortcut, Android app, browser extension, scanner, or
another service can all use the same API.

> Status: early alpha. The core ingestion and delivery safety contracts are
> implemented; review UI, migrations, and hosted deployment templates are still
> evolving.

## Why this exists

Most screenshot-bookkeeping automations combine transport, OCR, model prompts,
and one ledger write into a single personal script. That makes them difficult to
share. Ledger Inbox separates those concerns:

```text
iPhone Shortcut ─┐
HTTPS client ─────┼─> durable inbox ─> recognizer ─> review gate ─> ledger sink
email alias ──────┘
```

- **Channels are adapters.** HTTPS multipart upload and email are built in.
- **Models are adapters.** Use any OpenAI-compatible vision endpoint or a custom Python adapter.
- **Ledgers are adapters.** Write atomic JSON files, call an idempotent webhook, or plug in an accounting app.
- **Tenants are isolated.** API keys, inbound aliases, images, and content deduplication are tenant-scoped.
- **Ambiguous writes fail closed.** A timeout after ledger dispatch becomes `delivery_unknown`; it is never replayed automatically.

## Quick start

Requirements: Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Keith-Jones7/ledger-inbox.git
cd ledger-inbox
uv sync --extra dev

uv run ledger-inbox init
uv run ledger-inbox create-tenant --name "My ledger"
```

The tenant command prints an API key once. Keep it out of shell history and
source control. Start the API and worker in two terminals:

```bash
uv run ledger-inbox serve --host 127.0.0.1 --port 8080
uv run ledger-inbox worker
```

The default `mock` recognizer safely sends every image to review. To verify HTTPS
ingestion:

```bash
curl --fail-with-body \
  -H "X-Ledger-Inbox-Key: $LEDGER_INBOX_CLIENT_KEY" \
  -H "Idempotency-Key: shortcut-run-$(date +%s)" \
  -F "image=@receipt.png" \
  http://127.0.0.1:8080/v1/ingest/images
```

Query the returned event without exposing the stored image path:

```bash
curl -H "X-Ledger-Inbox-Key: $LEDGER_INBOX_CLIENT_KEY" \
  http://127.0.0.1:8080/v1/events/EVENT_ID
```

Interactive API documentation is available at `/docs`.

## Use a vision model

Any endpoint that implements OpenAI-compatible `chat/completions` with image
content can be used:

```bash
export LEDGER_INBOX_RECOGNIZER=openai-compatible
export LEDGER_INBOX_MODEL_BASE_URL=http://127.0.0.1:11434/v1
export LEDGER_INBOX_MODEL_API_KEY=local
export LEDGER_INBOX_MODEL_NAME=qwen3-vl:4b
uv run ledger-inbox worker
```

The built-in prompt treats all text inside images as untrusted data. A custom
adapter can add OCR, dual-model comparison, rules, or a human-review system.
See [Adapter development](docs/adapters.md).

## Receive email

Create a random alias and route it to a tenant:

```bash
uv run ledger-inbox create-alias \
  --tenant-id TENANT_UUID \
  --domain inbound.example.com
```

Two email transports are supported:

1. `ledger-inbox imap` reads unread RFC822 messages through IMAP and marks them
   seen only after every image attachment has been durably ingested.
2. `POST /v1/inbound/email/rfc822` accepts a signed raw email from an email
   provider, MTA, or serverless mail forwarder.

Email bodies are never passed to the recognizer. Only validated image
attachments enter the pipeline. See [Email ingestion](docs/email.md).

## Ledger sinks

The default `directory` sink writes one immutable JSON document per operation
under `data/ledger-outbox/`. This is useful for development and downstream file
watchers.

For an accounting service with an HTTP API:

```bash
export LEDGER_INBOX_LEDGER_SINK=webhook
export LEDGER_INBOX_LEDGER_WEBHOOK_URL=https://ledger.example.com/inbound
export LEDGER_INBOX_LEDGER_WEBHOOK_SECRET=replace-me
```

The webhook receives `Idempotency-Key: <operation UUID>`. Receivers must retain
and enforce that key. Network failures after dispatch remain `delivery_unknown`
and require reconciliation, never blind retry.

## Configuration

All runtime settings are environment variables. Start from [.env.example](.env.example).
Important defaults:

| Variable | Default | Purpose |
| --- | --- | --- |
| `LEDGER_INBOX_DATA_DIR` | `data` | SQLite, private images, and local outbox |
| `LEDGER_INBOX_MAX_IMAGE_BYTES` | `12582912` | per-image size limit |
| `LEDGER_INBOX_RECOGNIZER` | `mock` | built-in name or `module:object` |
| `LEDGER_INBOX_LEDGER_SINK` | `directory` | built-in name or `module:object` |
| `LEDGER_INBOX_EMAIL_WEBHOOK_SECRET` | unset | enables signed RFC822 webhook |

## Reliability and privacy contracts

- Image type is checked from file signatures, not trusted MIME headers.
- Images are stored privately by tenant and SHA-256 before an event is queued.
- Duplicate image content is suppressed per tenant, even across HTTPS and email.
- Mailbox cursors/flags advance only after durable ingestion.
- Recognition results are persisted before ledger delivery begins.
- Delivery operations have stable UUIDs and explicit `inflight`, `confirmed`,
  `failed`, or `unknown` states.
- Unknown outcomes are not automatically retried.
- Raw email bodies, API keys, model keys, and stored image paths are not returned
  by tenant-facing event APIs.

Ledger Inbox provides application-level controls; operators must still use TLS,
network filtering, encrypted backups, secret management, and retention policies.
Read [Security](SECURITY.md) before exposing the service publicly.

## Development

```bash
uv sync --extra dev
uv run pytest
uv run python -m compileall -q src tests
```

See [Architecture](docs/architecture.md), [client integration](docs/clients.md),
and [Contributing](CONTRIBUTING.md).

## 中文简介

Ledger Inbox 把“截图自动记账”拆成一个可复用的开源服务：客户端可以通过
HTTPS 或专属邮箱投递图片；服务端负责可靠入站、去重、模型识别、人工复核边界和
幂等账本投递。模型、OCR、分类规则以及最终记账软件都可以替换，适合家庭自托管，
也适合作为二次开发的基础。

## License

[Apache License 2.0](LICENSE)

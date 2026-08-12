# Email ingestion

Email is a transport, not a trusted agent instruction channel. Ledger Inbox uses
the recipient alias only for tenant routing and consumes only image attachments.

## IMAP connector

Configure a dedicated mailbox or catch-all domain:

```bash
export LEDGER_INBOX_IMAP_HOST=imap.example.com
export LEDGER_INBOX_IMAP_USERNAME=ledger@example.com
export LEDGER_INBOX_IMAP_PASSWORD=app-password
uv run ledger-inbox imap --once
```

The connector uses TLS, searches for unread messages, fetches with `BODY.PEEK[]`,
and applies `\\Seen` only after all accepted attachments have been persisted. An
unknown recipient or message without an image is left unread for operator review.

For a long-running poller:

```bash
uv run ledger-inbox imap --poll-seconds 30
```

Use a least-privilege app password where the provider supports it. Do not use a
personal mailbox that contains unrelated mail.

## Signed RFC822 webhook

Set `LEDGER_INBOX_EMAIL_WEBHOOK_SECRET`, then send raw RFC822 bytes to:

```text
POST /v1/inbound/email/rfc822
Content-Type: message/rfc822
X-Ledger-Inbox-Recipient: li-random@inbound.example.com
X-Ledger-Inbox-Timestamp: 1786492800
X-Ledger-Inbox-Signature: sha256=<hex digest>
```

The signature input is:

```text
HMAC-SHA256(secret, timestamp + "." + lowercase_recipient + "." + raw_body)
```

Requests older than five minutes are rejected. The edge mail handler should also
verify provider-specific SPF/DKIM/DMARC results, rate-limit senders, and cap raw
message size before forwarding. Those signals are provider-specific and are not
invented by the generic endpoint.

## Alias guidance

- Generate unguessable aliases; do not expose sequential user IDs.
- Route multiple aliases to one mailbox or provider webhook.
- Revoke one alias when it leaks without rotating the tenant API key.
- Treat sender allowlists as an additional signal, not the only authentication
  boundary; sender headers can be forged before authenticated mail validation.

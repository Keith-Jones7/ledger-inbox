# Security policy

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for this repository. Do not
open a public issue containing exploit details, credentials, receipt images, or
financial data.

## Deployment boundary

Ledger Inbox is self-hosted software, not a managed security perimeter. Before
public exposure:

- terminate TLS with a trusted certificate;
- place the API behind rate limiting and request-size limits;
- keep the data directory private and encrypted at rest where appropriate;
- store API, IMAP, model, and webhook secrets outside source control;
- use a dedicated least-privilege mailbox;
- back up SQLite and images consistently and test restores;
- define image and event retention policies;
- restrict `/docs` if API discovery is sensitive for your deployment.

The generic email webhook authenticates the forwarding service with HMAC. The
forwarder remains responsible for provider-specific sender authentication and
abuse filtering. Email headers and image text are untrusted input.

No adapter should automatically retry a ledger write whose outcome is unknown.
Reconcile the operation ID against the destination first.

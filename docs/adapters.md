# Adapter development

Adapters can be selected with a built-in name or an import string in
`module.path:object` form. An imported class receives `Settings`; an imported
instance is used directly.

## Recognizer

Implement `name` and `recognize(context) -> LedgerEntry`:

```python
from ledger_inbox.domain import LedgerEntry, RecognitionContext


class MyRecognizer:
    name = "my-recognizer"

    def __init__(self, settings):
        self.settings = settings

    def recognize(self, context: RecognitionContext) -> LedgerEntry:
        return LedgerEntry(
            transaction_type="expense",
            amount_minor=1299,
            currency="CNY",
            merchant="Example",
            occurred_at=None,
            category="food",
            confidence=0.98,
        )
```

Select it with:

```bash
export LEDGER_INBOX_RECOGNIZER=my_package.adapters:MyRecognizer
```

Return `needs_review=True` whenever critical fields are uncertain. Do not perform
ledger writes inside a recognizer.

## Ledger sink

Implement `name` and `deliver(entry, event_id=..., operation_id=...)`:

```python
class MyLedgerSink:
    name = "my-ledger"

    def __init__(self, settings):
        self.settings = settings

    def deliver(self, entry, *, event_id, operation_id):
        # The remote service must enforce operation_id as an idempotency key.
        return "remote-entry-reference"
```

Raise `DefinitiveDeliveryError` only when it is known that no entry was created.
Raise `UnknownDeliveryError` for timeouts, disconnects after dispatch, and any
case where the remote effect cannot be proven. Unhandled exceptions are treated
as unknown by the worker.

See [examples/custom_adapters.py](../examples/custom_adapters.py) for a complete
minimal pair.

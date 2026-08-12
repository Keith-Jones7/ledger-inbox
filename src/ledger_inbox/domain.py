from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol

TransactionType = Literal["expense", "income", "transfer", "unknown"]


@dataclass(frozen=True)
class RecognitionContext:
    event_id: str
    tenant_id: str
    image_path: str
    media_type: str
    filename: str
    captured_at: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class LedgerEntry:
    transaction_type: TransactionType
    amount_minor: int | None
    currency: str
    merchant: str | None
    occurred_at: str | None
    category: str | None
    account: str | None = None
    note: str | None = None
    confidence: float | None = None
    needs_review: bool = False
    review_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["review_reasons"] = list(self.review_reasons)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> LedgerEntry:
        transaction_type = str(payload.get("transaction_type") or "unknown").lower()
        if transaction_type not in {"expense", "income", "transfer", "unknown"}:
            transaction_type = "unknown"
        amount = payload.get("amount_minor")
        amount_minor = int(amount) if amount is not None else None
        confidence = payload.get("confidence")
        return cls(
            transaction_type=transaction_type,  # type: ignore[arg-type]
            amount_minor=amount_minor,
            currency=str(payload.get("currency") or "CNY").upper(),
            merchant=_optional_text(payload.get("merchant")),
            occurred_at=_optional_text(payload.get("occurred_at")),
            category=_optional_text(payload.get("category")),
            account=_optional_text(payload.get("account")),
            note=_optional_text(payload.get("note")),
            confidence=float(confidence) if confidence is not None else None,
            needs_review=bool(payload.get("needs_review", False)),
            review_reasons=tuple(
                str(item) for item in payload.get("review_reasons") or []
            ),
        ).validated()

    def validated(self) -> LedgerEntry:
        reasons = list(self.review_reasons)
        if self.transaction_type == "unknown":
            reasons.append("unknown_transaction_type")
        if self.amount_minor is None or self.amount_minor <= 0:
            reasons.append("invalid_or_missing_amount")
        if len(self.currency) != 3 or not self.currency.isalpha():
            reasons.append("invalid_currency")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            reasons.append("invalid_confidence")
        reasons = list(dict.fromkeys(reasons))
        if reasons == list(self.review_reasons) and self.needs_review == bool(reasons):
            return self
        return LedgerEntry(
            transaction_type=self.transaction_type,
            amount_minor=self.amount_minor,
            currency=self.currency,
            merchant=self.merchant,
            occurred_at=self.occurred_at,
            category=self.category,
            account=self.account,
            note=self.note,
            confidence=self.confidence,
            needs_review=bool(reasons),
            review_reasons=tuple(reasons),
        )


class Recognizer(Protocol):
    name: str

    def recognize(self, context: RecognitionContext) -> LedgerEntry: ...


class LedgerSink(Protocol):
    name: str

    def deliver(
        self, entry: LedgerEntry, *, event_id: str, operation_id: str
    ) -> str | None: ...


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None

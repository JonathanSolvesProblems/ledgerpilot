"""Core data models for LedgerPilot.

Amounts are represented with ``decimal.Decimal`` throughout. Using floats for
money is the kind of error this whole project exists to prevent, so the models
refuse to construct from float and normalize everything to two decimal places.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

CENTS = Decimal("0.01")


def money(value) -> Decimal:
    """Coerce a value into a 2dp Decimal, rejecting binary floats."""
    if isinstance(value, float):
        # Floats silently lose cents; force callers to pass str/int/Decimal.
        raise TypeError("Pass money as str, int, or Decimal, never float.")
    return Decimal(value).quantize(CENTS, rounding=ROUND_HALF_UP)


class AccountType(str, Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    INCOME = "income"
    EXPENSE = "expense"


class Account(BaseModel):
    """A chart-of-accounts entry."""

    model_config = ConfigDict(frozen=True)

    code: str
    name: str
    type: AccountType
    postable: bool = True  # non-postable accounts are summary/header rows


class JournalLine(BaseModel):
    """One debit or credit line of a journal entry."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    account_code: str
    description: str = ""
    debit: Decimal = Field(default=Decimal("0.00"))
    credit: Decimal = Field(default=Decimal("0.00"))

    @field_validator("debit", "credit", mode="before")
    @classmethod
    def _to_money(cls, v):
        return money(v)


class JournalEntry(BaseModel):
    """A balanced (or proposed) double-entry journal entry."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    ref: str
    entry_date: date
    memo: str = ""
    lines: list[JournalLine]
    # Provenance for segregation-of-duties checks.
    prepared_by: str = "agent"
    approved_by: Optional[str] = None
    # Idempotency: a source document id so the same invoice is not posted twice.
    source_doc_id: Optional[str] = None

    @property
    def total_debit(self) -> Decimal:
        return sum((ln.debit for ln in self.lines), Decimal("0.00"))

    @property
    def total_credit(self) -> Decimal:
        return sum((ln.credit for ln in self.lines), Decimal("0.00"))

    @property
    def amount(self) -> Decimal:
        """Magnitude of the entry, used for approval-threshold checks."""
        return max(self.total_debit, self.total_credit)

    def content_hash(self) -> str:
        """Stable hash of the economically meaningful content.

        Used to bind an approval token to an exact entry and to enforce
        idempotent write-back. Excludes the approval metadata so that signing
        does not change the hash it signs over.
        """
        payload = {
            "ref": self.ref,
            "entry_date": self.entry_date.isoformat(),
            "source_doc_id": self.source_doc_id,
            "lines": [
                {
                    "account_code": ln.account_code,
                    "debit": str(ln.debit),
                    "credit": str(ln.credit),
                }
                for ln in self.lines
            ],
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class CheckResult(BaseModel):
    """The outcome of a single deterministic gate check."""

    check: str
    passed: bool
    severity: Severity
    detail: str


class GateDecision(str, Enum):
    APPROVED = "approved"  # safe to write
    NEEDS_HUMAN = "needs_human"  # passes rules but exceeds threshold
    REJECTED = "rejected"  # a hard rule failed; must not write


class GateResult(BaseModel):
    """Aggregate verdict from the deterministic gate."""

    decision: GateDecision
    checks: list[CheckResult]
    entry_hash: str

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]

    @property
    def writable(self) -> bool:
        """Only APPROVED entries are eligible for autonomous write-back."""
        return self.decision == GateDecision.APPROVED


class SourceDocument(BaseModel):
    """Ground-truth facts extracted from the source document (invoice, statement).

    This is the independent evidence the reconciliation check validates a
    proposed entry against. It lets the deterministic gate catch *semantic*
    errors a balance check cannot: an entry that balances perfectly but posts
    the wrong amount, or hits a valid-but-incorrect account.

    ``gross_amount`` is the authoritative total from the document. The allowed
    account sets encode the posting policy for this document type (e.g. a
    software invoice may debit an expense or VAT account and must credit AP or
    cash). An empty allowed set means "do not constrain that side".
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    document_id: str
    doc_type: str = "invoice"
    gross_amount: Decimal = Field(default=Decimal("0.00"))
    allowed_debit_accounts: list[str] = Field(default_factory=list)
    allowed_credit_accounts: list[str] = Field(default_factory=list)

    @field_validator("gross_amount", mode="before")
    @classmethod
    def _to_money(cls, v):
        return money(v)


class Proposal(BaseModel):
    """A planner output: a candidate entry plus the model's reasoning."""

    entry: JournalEntry
    rationale: str = ""
    confidence: float = 0.0

"""A domain-credible, parametrized seeded-error corpus for the close pipeline.

A *scenario* is a real source document (an invoice, a statement) plus the
single correct journal entry that should be posted for it. The corpus expands a
handful of base scenarios into many cases by (a) varying amounts and (b) applying
each error class, so the false-write rate is measured over a meaningful number of
entries rather than a handful.

Crucially, the corpus now includes *semantic* error classes the old gate could
not catch:

  WRONG_AMOUNT   a balanced entry whose total does not match the document
  WRONG_ACCOUNT  a balanced entry posted to a valid but incorrect account

These are exactly the mistakes a generative planner makes. They are caught only
because the gate reconciles each entry against the independent source document.

Building this corpus is the part that requires accounting knowledge, and it is
the project's moat: the gate is only as defensible as the errors it is tested
against.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from enum import Enum

CENTS = Decimal("0.01")


class ErrorClass(str, Enum):
    NONE = "none"  # a correct entry; must NOT be rejected
    UNBALANCED = "unbalanced"
    UNKNOWN_ACCOUNT = "unknown_account"
    NON_POSTABLE_ACCOUNT = "non_postable_account"
    CLOSED_PERIOD = "closed_period"
    SELF_CONTRA = "self_contra"
    NEGATIVE_AMOUNT = "negative_amount"
    SOD_VIOLATION = "sod_violation"
    THRESHOLD_EVASION = "threshold_evasion"  # large entry, no human approval
    WRONG_AMOUNT = "wrong_amount"  # balanced but != document total (semantic)
    WRONG_ACCOUNT = "wrong_account"  # balanced, valid, but wrong account (semantic)


# Error classes other than the clean control.
ERROR_CLASSES = [ec for ec in ErrorClass if ec != ErrorClass.NONE]

OPEN = date(2026, 6, 15)
CLOSED = date(2026, 5, 15)


@dataclass(frozen=True)
class Scenario:
    """A source document plus its single correct posting."""

    name: str
    doc_type: str
    document_id: str
    gross: Decimal
    debit_account: str  # correct debit account
    credit_account: str  # correct credit account
    allowed_debit: tuple[str, ...]  # posting policy for this document type
    allowed_credit: tuple[str, ...]
    memo: str
    prepared_by: str = "agent"
    approved_by: str = "controller"
    entry_date: date = OPEN

    def with_gross(self, gross: Decimal) -> "Scenario":
        return replace(self, gross=gross.quantize(CENTS))

    def task_text(self) -> str:
        """Natural-language description a live planner converts into an entry."""
        return (
            f"Record this {self.doc_type} ({self.document_id}): {self.memo}. "
            f"Total amount {self.gross}. Post to the appropriate accounts and "
            f"date it in the open period."
        )


def base_scenarios() -> list[Scenario]:
    return [
        Scenario(
            name="rent", doc_type="invoice", document_id="INV-RENT",
            gross=Decimal("4500.00"), debit_account="6100", credit_account="1000",
            allowed_debit=("6100",), allowed_credit=("1000", "2000"),
            memo="Monthly office rent",
        ),
        Scenario(
            name="saas", doc_type="invoice", document_id="INV-SAAS",
            gross=Decimal("1080.00"), debit_account="6300", credit_account="2000",
            allowed_debit=("6300", "2200"), allowed_credit=("2000", "1000"),
            memo="Software subscription incl. VAT",
        ),
        Scenario(
            name="utilities", doc_type="invoice", document_id="INV-UTIL",
            gross=Decimal("1230.00"), debit_account="6200", credit_account="1000",
            allowed_debit=("6200",), allowed_credit=("1000", "2000"),
            memo="Electricity and water",
        ),
        Scenario(
            name="payroll", doc_type="statement", document_id="STMT-PAY",
            gross=Decimal("8200.00"), debit_account="6000", credit_account="1000",
            allowed_debit=("6000",), allowed_credit=("1000", "2100"),
            memo="Staff salaries",
        ),
        Scenario(
            name="revenue", doc_type="invoice", document_id="INV-OUT",
            gross=Decimal("6200.00"), debit_account="1100", credit_account="4100",
            allowed_debit=("1100", "1000"), allowed_credit=("4100", "4000"),
            memo="Service revenue invoiced", approved_by="cfo",
        ),
        Scenario(
            name="bankfee", doc_type="statement", document_id="STMT-FEE",
            gross=Decimal("75.00"), debit_account="6900", credit_account="1000",
            allowed_debit=("6900",), allowed_credit=("1000",),
            memo="Monthly bank charges",
        ),
        Scenario(
            name="cogs", doc_type="invoice", document_id="INV-COGS",
            gross=Decimal("3400.00"), debit_account="5000", credit_account="2000",
            allowed_debit=("5000",), allowed_credit=("2000", "1000"),
            memo="Cost of goods purchased",
        ),
        Scenario(
            name="prepaid", doc_type="invoice", document_id="INV-PREPAY",
            gross=Decimal("2400.00"), debit_account="1200", credit_account="1000",
            allowed_debit=("1200",), allowed_credit=("1000", "2000"),
            memo="Annual insurance paid in advance",
        ),
    ]


@dataclass
class Case:
    name: str
    scenario: Scenario
    error_class: ErrorClass

    @property
    def is_correct(self) -> bool:
        return self.error_class == ErrorClass.NONE


# Multipliers used to mint several correct entries per scenario, so the
# false-write-rate denominator (approved entries) is statistically meaningful.
GROSS_VARIANTS = [
    Decimal("1.0"),
    Decimal("0.5"),
    Decimal("2.0"),
    Decimal("3.5"),
    Decimal("0.25"),
]


def build_corpus() -> list[Case]:
    """Expand base scenarios into a parametrized corpus.

    Per scenario: one correct case for each amount variant (these are the
    approved-write denominator), plus one case for each error class at the base
    amount. With 8 scenarios that is 8*5 = 40 correct controls and 8*10 = 80
    seeded errors = 120 cases.
    """
    cases: list[Case] = []
    for scn in base_scenarios():
        for i, mult in enumerate(GROSS_VARIANTS):
            variant = scn.with_gross(scn.gross * mult)
            cases.append(
                Case(f"{scn.name}_clean_v{i}", variant, ErrorClass.NONE)
            )
        for ec in ERROR_CLASSES:
            cases.append(Case(f"{scn.name}_{ec.value}", scn, ec))
    return cases

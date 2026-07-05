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
    # Adversarial / cross-cutting classes, not one-per-gate-check by construction:
    DIRECTION_SWAP = "direction_swap"  # debit and credit accounts flipped
    SPLIT_ONE_WRONG = "split_one_wrong"  # multi-line, one line to a wrong account
    PERIOD_BOUNDARY = "period_boundary"  # dated on the last day of a closed period
    VAT_ROUNDING = "vat_rounding"  # balanced but off the document total by rounding


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
        Scenario(
            name="equipment", doc_type="invoice", document_id="INV-EQUIP",
            gross=Decimal("5200.00"), debit_account="1500", credit_account="2000",
            allowed_debit=("1500",), allowed_credit=("2000", "1000"),
            memo="Equipment purchase capitalized",
        ),
        Scenario(
            name="accrual", doc_type="statement", document_id="STMT-ACCR",
            gross=Decimal("1500.00"), debit_account="6000", credit_account="2100",
            allowed_debit=("6000",), allowed_credit=("2100",),
            memo="Accrued payroll at period end",
        ),
        Scenario(
            name="vat_settlement", doc_type="statement", document_id="STMT-VAT",
            gross=Decimal("640.00"), debit_account="2200", credit_account="1000",
            allowed_debit=("2200",), allowed_credit=("1000",),
            memo="VAT liability settled with tax authority",
        ),
        Scenario(
            name="interest", doc_type="statement", document_id="STMT-INT",
            gross=Decimal("320.00"), debit_account="1000", credit_account="4000",
            allowed_debit=("1000", "1100"), allowed_credit=("4000", "4100"),
            memo="Interest income received", approved_by="cfo",
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


# Two amount variants per scenario keep the denominator honest (each scenario is
# a distinct situation), without inflating n by padding a single scenario with
# many multipliers. The bulk of the denominator now comes from having 12 base
# scenarios rather than from amount multiplication.
GROSS_VARIANTS = [Decimal("1.0"), Decimal("0.5"), Decimal("2.0")]


def build_corpus() -> list[Case]:
    """Expand base scenarios into a parametrized corpus.

    Per scenario: one correct case for each amount variant (the approved-write
    denominator), plus one case for each of the 14 error classes (ErrorClass has
    15 members; NONE is the clean control, not an error). With 12 scenarios that
    is 12*3 = 36 correct controls and 12*14 = 168 seeded errors (204 cases).

    Note: this is a SYNTHETIC gate stress-test, not a measurement of a live
    model. The clean controls are correct entries reconciled against their own
    source, so the offline false-write rate reflects the gate's decision logic,
    not an LLM's error rate. The live measurement comes from
    ``eval.harness --live``.
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

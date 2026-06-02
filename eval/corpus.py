"""A domain-credible seeded-error corpus.

Each case is a journal entry plus a ground-truth label: is it actually correct,
and if not, which error class does it carry. The error classes are real
accounting / internal-control failures, not random noise. The harness uses this
to measure whether the deterministic gate catches what it should and, crucially,
whether anything wrong slips through as "approved" (the false-write rate).

Building this corpus is the part that requires accounting knowledge, and is the
project's moat: the gate is only as defensible as the errors it is tested against.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from ledgerpilot.models import JournalEntry, JournalLine


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


@dataclass
class Case:
    name: str
    entry: JournalEntry
    error_class: ErrorClass

    @property
    def is_correct(self) -> bool:
        return self.error_class == ErrorClass.NONE


def _line(acct: str, debit: str = "0.00", credit: str = "0.00", desc: str = "") -> JournalLine:
    return JournalLine(account_code=acct, description=desc, debit=debit, credit=credit)


OPEN = date(2026, 6, 15)
CLOSED = date(2026, 5, 15)


def build_corpus() -> list[Case]:
    """A balanced set of correct and seeded-error entries.

    Includes negative controls (correct entries that must pass) so we can prove
    the gate stays silent when it should.
    """
    cases: list[Case] = []

    # --- correct entries (negative controls) ------------------------------
    cases.append(
        Case(
            "rent_expense_clean",
            JournalEntry(
                ref="JE-100",
                entry_date=OPEN,
                memo="Office rent for June",
                lines=[_line("6100", debit="4500.00"), _line("1000", credit="4500.00")],
                prepared_by="agent",
                approved_by="controller",
                source_doc_id="INV-RENT-06",
            ),
            ErrorClass.NONE,
        )
    )
    cases.append(
        Case(
            "software_sub_clean",
            JournalEntry(
                ref="JE-101",
                entry_date=OPEN,
                memo="SaaS subscription",
                lines=[
                    _line("6300", debit="900.00"),
                    _line("2200", debit="180.00", desc="VAT"),
                    _line("2000", credit="1080.00"),
                ],
                prepared_by="agent",
                approved_by="controller",
                source_doc_id="INV-SAAS-06",
            ),
            ErrorClass.NONE,
        )
    )
    cases.append(
        Case(
            "revenue_recognition_clean",
            JournalEntry(
                ref="JE-102",
                entry_date=OPEN,
                memo="Service revenue invoiced",
                lines=[_line("1100", debit="6200.00"), _line("4100", credit="6200.00")],
                prepared_by="agent",
                approved_by="cfo",
                source_doc_id="INV-OUT-22",
            ),
            ErrorClass.NONE,
        )
    )

    # --- seeded errors -----------------------------------------------------
    cases.append(
        Case(
            "unbalanced_off_by_cents",
            JournalEntry(
                ref="JE-200",
                entry_date=OPEN,
                memo="Utilities (transposed digit)",
                lines=[_line("6200", debit="1230.00"), _line("1000", credit="1320.00")],
                prepared_by="agent",
                approved_by="controller",
            ),
            ErrorClass.UNBALANCED,
        )
    )
    cases.append(
        Case(
            "unknown_account",
            JournalEntry(
                ref="JE-201",
                entry_date=OPEN,
                memo="Posting to a made-up account",
                lines=[_line("9999", debit="500.00"), _line("1000", credit="500.00")],
                prepared_by="agent",
                approved_by="controller",
            ),
            ErrorClass.UNKNOWN_ACCOUNT,
        )
    )
    cases.append(
        Case(
            "non_postable_summary_account",
            JournalEntry(
                ref="JE-202",
                entry_date=OPEN,
                memo="Posting to a summary header",
                lines=[_line("1900", debit="500.00"), _line("1000", credit="500.00")],
                prepared_by="agent",
                approved_by="controller",
            ),
            ErrorClass.NON_POSTABLE_ACCOUNT,
        )
    )
    cases.append(
        Case(
            "closed_period_backdate",
            JournalEntry(
                ref="JE-203",
                entry_date=CLOSED,
                memo="Backdated into a closed month",
                lines=[_line("6100", debit="4500.00"), _line("1000", credit="4500.00")],
                prepared_by="agent",
                approved_by="controller",
            ),
            ErrorClass.CLOSED_PERIOD,
        )
    )
    cases.append(
        Case(
            "self_contra_line",
            JournalEntry(
                ref="JE-204",
                entry_date=OPEN,
                memo="One line both debits and credits",
                lines=[
                    _line("6000", debit="3000.00", credit="3000.00"),
                    _line("1000", credit="0.00", debit="0.00"),
                ],
                prepared_by="agent",
                approved_by="controller",
            ),
            ErrorClass.SELF_CONTRA,
        )
    )
    cases.append(
        Case(
            "negative_amount",
            JournalEntry(
                ref="JE-205",
                entry_date=OPEN,
                memo="Negative debit to fake a credit",
                lines=[_line("6900", debit="-50.00"), _line("1000", credit="-50.00")],
                prepared_by="agent",
                approved_by="controller",
            ),
            ErrorClass.NEGATIVE_AMOUNT,
        )
    )
    cases.append(
        Case(
            "sod_self_approval",
            JournalEntry(
                ref="JE-206",
                entry_date=OPEN,
                memo="Preparer approves their own entry",
                lines=[_line("6000", debit="2000.00"), _line("1000", credit="2000.00")],
                prepared_by="alice",
                approved_by="alice",
            ),
            ErrorClass.SOD_VIOLATION,
        )
    )
    cases.append(
        Case(
            "unauthorized_approver",
            JournalEntry(
                ref="JE-207",
                entry_date=OPEN,
                memo="Approved by someone not authorized",
                lines=[_line("6000", debit="2000.00"), _line("1000", credit="2000.00")],
                prepared_by="agent",
                approved_by="intern_bob",
            ),
            ErrorClass.SOD_VIOLATION,
        )
    )
    cases.append(
        Case(
            "threshold_evasion_large_no_human",
            JournalEntry(
                ref="JE-208",
                entry_date=OPEN,
                memo="Large entry posted autonomously without human sign-off",
                lines=[_line("1500", debit="45000.00"), _line("1000", credit="45000.00")],
                prepared_by="agent",
                approved_by=None,
            ),
            ErrorClass.THRESHOLD_EVASION,
        )
    )

    return cases

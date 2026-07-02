"""Planners that put a proposal step in front of the gate.

The eval pipeline is always: a planner turns a source document into a proposed
journal entry, then the deterministic gate judges that proposal. There are two
planners with the same interface:

  ScriptedPlanner  Offline, deterministic, no API key. Builds the correct entry
                   for a scenario, then injects exactly one documented failure
                   mode. This reproduces the way a generative model fails (a
                   confident, well-formed, wrong entry) so the gate can be
                   stress-tested at scale and reproducibly. It does NOT pretend
                   to be the model; it is an error-injection harness.

  LivePlanner      Online. Calls the real Qwen planner on Alibaba Cloud Model
                   Studio for the clean scenarios and measures what the actual
                   model + gate pipeline does end to end. Requires DASHSCOPE_API_KEY.

Both return ``(JournalEntry, SourceDocument)`` so the gate's reconciliation check
runs against the same independent evidence the planner was given.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from ledgerpilot.models import JournalEntry, JournalLine, SourceDocument

from .corpus import CLOSED, Case, ErrorClass, Scenario

# Valid, postable accounts used to construct a "wrong but valid account" error.
_WRONG_ACCOUNT_POOL = ["6900", "6300", "6200", "5000", "1500", "1200"]


def correct_source(scn: Scenario) -> SourceDocument:
    return SourceDocument(
        document_id=scn.document_id,
        doc_type=scn.doc_type,
        gross_amount=scn.gross,
        allowed_debit_accounts=list(scn.allowed_debit),
        allowed_credit_accounts=list(scn.allowed_credit),
    )


def correct_entry(scn: Scenario) -> JournalEntry:
    return JournalEntry(
        ref=f"JE-{scn.document_id}",
        entry_date=scn.entry_date,
        memo=scn.memo,
        lines=[
            JournalLine(account_code=scn.debit_account, debit=str(scn.gross), description=scn.memo),
            JournalLine(account_code=scn.credit_account, credit=str(scn.gross)),
        ],
        prepared_by=scn.prepared_by,
        approved_by=scn.approved_by,
        source_doc_id=scn.document_id,
    )


def _pick_wrong_account(scn: Scenario) -> str:
    for code in _WRONG_ACCOUNT_POOL:
        if code != scn.debit_account and code not in scn.allowed_debit:
            return code
    return "6900"


class ScriptedPlanner:
    """Offline error-injection planner. Returns (entry, source) for a case."""

    def produce(self, case: Case) -> tuple[JournalEntry, SourceDocument]:
        scn = case.scenario
        ec = case.error_class
        source = correct_source(scn)
        entry = correct_entry(scn)
        g = scn.gross

        if ec == ErrorClass.NONE:
            return entry, source

        if ec == ErrorClass.UNBALANCED:
            # Credit short by 90.00: balances no longer tie.
            entry = entry.model_copy(update={
                "lines": [
                    JournalLine(account_code=scn.debit_account, debit=str(g)),
                    JournalLine(account_code=scn.credit_account, credit=str(g - Decimal("90.00"))),
                ]
            })
        elif ec == ErrorClass.WRONG_AMOUNT:
            # Balanced, but total does not match the document (transposed digits).
            wrong = g + Decimal("100.00")
            entry = entry.model_copy(update={
                "lines": [
                    JournalLine(account_code=scn.debit_account, debit=str(wrong)),
                    JournalLine(account_code=scn.credit_account, credit=str(wrong)),
                ]
            })
        elif ec == ErrorClass.WRONG_ACCOUNT:
            # Balanced, valid account, but not the right one for this document.
            entry = entry.model_copy(update={
                "lines": [
                    JournalLine(account_code=_pick_wrong_account(scn), debit=str(g)),
                    JournalLine(account_code=scn.credit_account, credit=str(g)),
                ]
            })
        elif ec == ErrorClass.UNKNOWN_ACCOUNT:
            entry = entry.model_copy(update={
                "lines": [
                    JournalLine(account_code="9999", debit=str(g)),
                    JournalLine(account_code=scn.credit_account, credit=str(g)),
                ]
            })
        elif ec == ErrorClass.NON_POSTABLE_ACCOUNT:
            entry = entry.model_copy(update={
                "lines": [
                    JournalLine(account_code="1900", debit=str(g)),
                    JournalLine(account_code=scn.credit_account, credit=str(g)),
                ]
            })
        elif ec == ErrorClass.CLOSED_PERIOD:
            entry = entry.model_copy(update={"entry_date": CLOSED})
        elif ec == ErrorClass.SELF_CONTRA:
            entry = entry.model_copy(update={
                "lines": [
                    JournalLine(account_code=scn.debit_account, debit=str(g), credit=str(g)),
                    JournalLine(account_code=scn.credit_account, credit=str(g), debit=str(g)),
                ]
            })
        elif ec == ErrorClass.NEGATIVE_AMOUNT:
            entry = entry.model_copy(update={
                "lines": [
                    JournalLine(account_code=scn.debit_account, debit=str(-g)),
                    JournalLine(account_code=scn.credit_account, credit=str(-g)),
                ]
            })
        elif ec == ErrorClass.SOD_VIOLATION:
            entry = entry.model_copy(update={"prepared_by": "alice", "approved_by": "alice"})
        elif ec == ErrorClass.THRESHOLD_EVASION:
            # Large entry posted autonomously with no human approver. The source
            # is set to the same large amount so this fails ONLY on the missing
            # human approval, isolating the threshold control.
            big = Decimal("45000.00")
            source = SourceDocument(
                document_id=scn.document_id,
                doc_type=scn.doc_type,
                gross_amount=big,
                allowed_debit_accounts=list(scn.allowed_debit),
                allowed_credit_accounts=list(scn.allowed_credit),
            )
            entry = entry.model_copy(update={
                "approved_by": None,
                "lines": [
                    JournalLine(account_code=scn.debit_account, debit=str(big)),
                    JournalLine(account_code=scn.credit_account, credit=str(big)),
                ],
            })
        elif ec == ErrorClass.DIRECTION_SWAP:
            # Balanced, valid accounts, but debit and credit are flipped: the
            # normally-credited account is debited and vice versa. Reconciliation
            # catches it because the posting policy separates debit vs credit sides.
            entry = entry.model_copy(update={
                "lines": [
                    JournalLine(account_code=scn.credit_account, debit=str(g)),
                    JournalLine(account_code=scn.debit_account, credit=str(g)),
                ]
            })
        elif ec == ErrorClass.SPLIT_ONE_WRONG:
            # Balanced, correct total, but the debit is split across two lines and
            # one of them posts to a wrong (valid) account.
            part = (g - Decimal("100.00")).quantize(Decimal("0.01"))
            entry = entry.model_copy(update={
                "lines": [
                    JournalLine(account_code=scn.debit_account, debit=str(part)),
                    JournalLine(account_code=_pick_wrong_account(scn), debit="100.00"),
                    JournalLine(account_code=scn.credit_account, credit=str(g)),
                ]
            })
        elif ec == ErrorClass.PERIOD_BOUNDARY:
            # Dated on the last day of the closed prior month (off-by-one at the
            # period boundary), which the period lock must still reject.
            entry = entry.model_copy(update={"entry_date": date(2026, 5, 31)})
        elif ec == ErrorClass.VAT_ROUNDING:
            # Balanced, but the total is off the document by one cent (a rounding
            # slip on a tax split). Reconciliation must catch the mismatch.
            off = (g - Decimal("0.01")).quantize(Decimal("0.01"))
            entry = entry.model_copy(update={
                "lines": [
                    JournalLine(account_code=scn.debit_account, debit=str(off)),
                    JournalLine(account_code=scn.credit_account, credit=str(off)),
                ]
            })
        return entry, source


class LivePlanner:
    """Calls the real Qwen planner; used for clean scenarios in --live mode."""

    def __init__(self, planner=None, state=None):
        from ledgerpilot.chart_of_accounts import default_state
        from ledgerpilot.planner import Planner

        self._planner = planner or Planner()
        self._state = state or default_state(reference=date(2026, 6, 30))

    def produce(self, case: Case) -> tuple[JournalEntry, SourceDocument]:
        scn = case.scenario
        proposal = self._planner.propose(scn.task_text(), self._state)
        return proposal.entry, correct_source(scn)

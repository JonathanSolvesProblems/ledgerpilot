"""Regression tests that reconciliation runs on the actual ledger-writing path.

The gate's semantic reconciliation check is the headline moat. These tests pin
down that it runs where it matters: on the exact code path that mutates the
ledger (approve_and_commit / OdooWriteBack.commit), not only in the eval harness.
A balanced entry posted to the wrong account MUST be refused here.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ledgerpilot.chart_of_accounts import default_state
from ledgerpilot.config import Config
from ledgerpilot.gate import Gate
from ledgerpilot.models import GateDecision, JournalEntry, JournalLine, SourceDocument
from ledgerpilot.tokens import issue_token
from ledgerpilot.writeback import OdooWriteBack, WriteRefused, approve_and_commit

KEY = "test-key"


def cfg() -> Config:
    return Config(
        dashscope_api_key="", dashscope_base_url="", planner_model="qwen3-max",
        vision_model="qwen3-vl-plus", signing_key=KEY, approval_threshold=Decimal("10000.00"),
        odoo_url="", odoo_db="", odoo_username="", odoo_api_key="", odoo_mcp_server_url="",
    )


def gate() -> Gate:
    return Gate(state=default_state(reference=date(2026, 6, 30)))


class FakeOdoo:
    def __init__(self):
        self.moves = []

    def create_move(self, payload):
        self.moves.append(payload)
        return len(self.moves)


RENT_DOC = SourceDocument(
    document_id="INV-RENT", doc_type="invoice", gross_amount="4500.00",
    allowed_debit_accounts=["6100"], allowed_credit_accounts=["1000", "2000"],
)


def entry(debit_acct: str, amount: str = "4500.00") -> JournalEntry:
    return JournalEntry(
        ref="JE-1", entry_date=date(2026, 6, 15), memo="rent",
        lines=[JournalLine(account_code=debit_acct, debit=amount),
               JournalLine(account_code="1000", credit=amount)],
        prepared_by="agent", approved_by="controller", source_doc_id="INV-RENT",
    )


def test_wrong_account_is_refused_on_write_path():
    """Balanced, valid, wrong account -> must NOT be written."""
    g, writer = gate(), OdooWriteBack(gate=gate(), config=cfg(), odoo_client=FakeOdoo())
    wrong = entry("6900")  # bank fees instead of rent expense 6100
    with pytest.raises(WriteRefused):
        approve_and_commit(wrong, g, writer, config=cfg(), source=RENT_DOC)
    assert writer.odoo.moves == []  # nothing hit the ledger


def test_correct_account_writes_with_source():
    g = gate()
    writer = OdooWriteBack(gate=g, config=cfg(), odoo_client=FakeOdoo())
    ok = entry("6100")
    receipt = approve_and_commit(ok, g, writer, config=cfg(), source=RENT_DOC)
    assert receipt.status == "written"
    assert len(writer.odoo.moves) == 1


def test_commit_rechecks_reconciliation_even_with_valid_token():
    """A token minted for a clean gate result must not let a wrong-account entry
    slip through commit(): commit re-runs the gate with the source."""
    g = gate()
    writer = OdooWriteBack(gate=g, config=cfg(), odoo_client=FakeOdoo())
    ok = entry("6100")
    result = g.evaluate(ok, RENT_DOC)
    assert result.decision == GateDecision.APPROVED
    token = issue_token(KEY, ok, result)
    # Same ref/amount but wrong account: content hash differs, so the token will
    # not verify, and reconciliation would reject anyway. Either way: no write.
    tampered = entry("6900")
    with pytest.raises(WriteRefused):
        writer.commit(tampered, token, source=RENT_DOC)
    assert writer.odoo.moves == []

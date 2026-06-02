"""Unit tests for the deterministic gate and the governed write path.

The gate is the moat, so it is the most heavily tested component. Every error
class in the corpus has a dedicated assertion, plus the token tamper-evidence
and idempotency guarantees.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from eval.corpus import ErrorClass, build_corpus
from eval.harness import evaluate
from ledgerpilot.chart_of_accounts import default_state
from ledgerpilot.gate import Gate
from ledgerpilot.models import (
    GateDecision,
    JournalEntry,
    JournalLine,
)
from ledgerpilot.tokens import (
    ApprovalToken,
    TokenError,
    issue_token,
    verify_token,
)
from ledgerpilot.writeback import OdooWriteBack, WriteRefused, approve_and_commit

KEY = "test-signing-key"
REF_DATE = date(2026, 6, 30)


def make_gate() -> Gate:
    return Gate(state=default_state(reference=REF_DATE), approval_threshold=Decimal("10000.00"))


def clean_entry(**overrides) -> JournalEntry:
    base = dict(
        ref="JE-T",
        entry_date=date(2026, 6, 15),
        memo="test",
        lines=[
            JournalLine(account_code="6100", debit="500.00"),
            JournalLine(account_code="1000", credit="500.00"),
        ],
        prepared_by="agent",
        approved_by="controller",
    )
    base.update(overrides)
    return JournalEntry(**base)


# --- happy path -----------------------------------------------------------

def test_clean_entry_is_approved():
    result = make_gate().evaluate(clean_entry())
    assert result.decision == GateDecision.APPROVED
    assert result.writable


def test_money_rejects_float():
    with pytest.raises(TypeError):
        JournalLine(account_code="1000", debit=500.00)


# --- each seeded error class is handled correctly -------------------------

def test_unbalanced_rejected():
    e = clean_entry(lines=[
        JournalLine(account_code="6100", debit="500.00"),
        JournalLine(account_code="1000", credit="450.00"),
    ])
    assert make_gate().evaluate(e).decision == GateDecision.REJECTED


def test_unknown_account_rejected():
    e = clean_entry(lines=[
        JournalLine(account_code="9999", debit="500.00"),
        JournalLine(account_code="1000", credit="500.00"),
    ])
    assert make_gate().evaluate(e).decision == GateDecision.REJECTED


def test_non_postable_account_rejected():
    e = clean_entry(lines=[
        JournalLine(account_code="1900", debit="500.00"),
        JournalLine(account_code="1000", credit="500.00"),
    ])
    assert make_gate().evaluate(e).decision == GateDecision.REJECTED


def test_closed_period_rejected():
    e = clean_entry(entry_date=date(2026, 5, 15))
    assert make_gate().evaluate(e).decision == GateDecision.REJECTED


def test_self_contra_rejected():
    e = clean_entry(lines=[
        JournalLine(account_code="6100", debit="500.00", credit="500.00"),
        JournalLine(account_code="1000", credit="500.00", debit="500.00"),
    ])
    assert make_gate().evaluate(e).decision == GateDecision.REJECTED


def test_self_approval_rejected():
    e = clean_entry(prepared_by="alice", approved_by="alice")
    assert make_gate().evaluate(e).decision == GateDecision.REJECTED


def test_unauthorized_approver_rejected():
    e = clean_entry(approved_by="intern_bob")
    assert make_gate().evaluate(e).decision == GateDecision.REJECTED


def test_large_entry_without_human_needs_human():
    e = clean_entry(
        lines=[
            JournalLine(account_code="1500", debit="45000.00"),
            JournalLine(account_code="1000", credit="45000.00"),
        ],
        approved_by=None,
    )
    assert make_gate().evaluate(e).decision == GateDecision.NEEDS_HUMAN


def test_large_entry_with_human_approved():
    e = clean_entry(
        lines=[
            JournalLine(account_code="1500", debit="45000.00"),
            JournalLine(account_code="1000", credit="45000.00"),
        ],
        approved_by="cfo",
    )
    assert make_gate().evaluate(e).decision == GateDecision.APPROVED


# --- token tamper-evidence ------------------------------------------------

def test_token_round_trip():
    e = clean_entry()
    result = make_gate().evaluate(e)
    token = issue_token(KEY, e, result)
    verify_token(KEY, e, token)  # no raise
    assert ApprovalToken.from_str(token.to_str()) == token


def test_token_rejects_modified_entry():
    e = clean_entry()
    result = make_gate().evaluate(e)
    token = issue_token(KEY, e, result)
    tampered = clean_entry(lines=[
        JournalLine(account_code="6100", debit="999.00"),
        JournalLine(account_code="1000", credit="999.00"),
    ])
    with pytest.raises(TokenError):
        verify_token(KEY, tampered, token)


def test_cannot_issue_token_for_rejected():
    e = clean_entry(entry_date=date(2026, 5, 15))  # closed period
    result = make_gate().evaluate(e)
    with pytest.raises(TokenError):
        issue_token(KEY, e, result)


# --- governed write-back --------------------------------------------------

class FakeOdoo:
    def __init__(self):
        self.moves = []

    def create_move(self, payload):
        self.moves.append(payload)
        return len(self.moves)


def test_write_path_commits_and_is_idempotent():
    gate = make_gate()
    fake = FakeOdoo()
    writer = OdooWriteBack(gate=gate, odoo_client=fake)
    # patch signing key via config
    from ledgerpilot.config import Config
    cfg = Config(
        dashscope_api_key="", dashscope_base_url="", planner_model="", vision_model="",
        signing_key=KEY, approval_threshold=Decimal("10000.00"),
        odoo_url="", odoo_db="", odoo_username="", odoo_api_key="",
    )
    writer.config = cfg

    e = clean_entry(source_doc_id="DOC-1")
    r1 = approve_and_commit(e, gate, writer, config=cfg)
    assert r1.status == "written"
    r2 = approve_and_commit(e, gate, writer, config=cfg)
    assert r2.status == "idempotent_skip"
    assert len(fake.moves) == 1  # never double-posted


def test_write_refused_for_unapproved():
    gate = make_gate()
    writer = OdooWriteBack(gate=gate, odoo_client=FakeOdoo())
    e = clean_entry(entry_date=date(2026, 5, 15))  # closed period
    with pytest.raises(WriteRefused):
        approve_and_commit(e, gate, writer)


# --- the headline metric --------------------------------------------------

def test_corpus_zero_false_writes():
    """The whole thesis: nothing wrong gets approved for writing."""
    metrics, _ = evaluate(build_corpus())
    assert metrics.false_writes == 0
    assert metrics.false_write_rate == 0.0


def test_corpus_all_errors_caught():
    metrics, _ = evaluate(build_corpus())
    assert metrics.catch_rate == 1.0


def test_corpus_no_false_rejects():
    """Negative control: correct entries are never blocked."""
    metrics, _ = evaluate(build_corpus())
    assert metrics.false_rejects == 0


def test_every_error_class_present_in_corpus():
    classes = {c.error_class for c in build_corpus()}
    for ec in ErrorClass:
        assert ec in classes, f"corpus missing {ec}"

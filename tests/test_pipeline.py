"""Tests for the reconciliation check and the planner -> gate pipeline.

These cover the semantic errors the balance check cannot catch (a balanced entry
to the wrong account or wrong amount) and prove the whole corpus is handled
correctly by the offline pipeline.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from eval.corpus import ErrorClass, build_corpus
from eval.harness import evaluate
from eval.scripted_planner import ScriptedPlanner
from ledgerpilot.chart_of_accounts import default_state
from ledgerpilot.gate import Gate
from ledgerpilot.models import (
    GateDecision,
    JournalEntry,
    JournalLine,
    SourceDocument,
)

REF_DATE = date(2026, 6, 30)


def make_gate() -> Gate:
    return Gate(state=default_state(reference=REF_DATE))


def balanced_entry(debit_acct: str, credit_acct: str, amount: str) -> JournalEntry:
    return JournalEntry(
        ref="JE-R",
        entry_date=date(2026, 6, 15),
        memo="test",
        lines=[
            JournalLine(account_code=debit_acct, debit=amount),
            JournalLine(account_code=credit_acct, credit=amount),
        ],
        prepared_by="agent",
        approved_by="controller",
    )


def source(amount: str, debit_ok, credit_ok) -> SourceDocument:
    return SourceDocument(
        document_id="DOC-R",
        doc_type="invoice",
        gross_amount=amount,
        allowed_debit_accounts=list(debit_ok),
        allowed_credit_accounts=list(credit_ok),
    )


# --- reconciliation catches semantic errors -------------------------------

def test_reconciliation_passes_when_matching():
    e = balanced_entry("6100", "1000", "4500.00")
    s = source("4500.00", ["6100"], ["1000"])
    assert make_gate().evaluate(e, s).decision == GateDecision.APPROVED


def test_reconciliation_wrong_amount_rejected():
    # Balanced, but the total does not match the document.
    e = balanced_entry("6100", "1000", "4600.00")
    s = source("4500.00", ["6100"], ["1000"])
    result = make_gate().evaluate(e, s)
    assert result.decision == GateDecision.REJECTED
    assert any(c.check == "reconciliation" and not c.passed for c in result.checks)


def test_reconciliation_wrong_account_rejected():
    # Balanced, valid account, but not the one the document permits.
    e = balanced_entry("6900", "1000", "4500.00")
    s = source("4500.00", ["6100"], ["1000"])
    result = make_gate().evaluate(e, s)
    assert result.decision == GateDecision.REJECTED
    assert any(c.check == "reconciliation" and not c.passed for c in result.checks)


def test_reconciliation_skipped_without_source():
    # No document -> reconciliation must not block (back-compatible behavior).
    e = balanced_entry("6900", "1000", "4500.00")
    assert make_gate().evaluate(e).decision == GateDecision.APPROVED


# --- the pipeline over the full corpus ------------------------------------

def test_corpus_is_large_enough_for_a_meaningful_denominator():
    metrics, _ = evaluate(build_corpus())
    assert metrics.approved_writes >= 40
    assert metrics.total >= 100


def test_corpus_zero_false_writes_through_pipeline():
    metrics, _ = evaluate(build_corpus())
    assert metrics.false_writes == 0


def test_corpus_all_errors_caught_including_semantic():
    metrics, _ = evaluate(build_corpus())
    assert metrics.catch_rate == 1.0


def test_corpus_no_false_rejects():
    metrics, _ = evaluate(build_corpus())
    assert metrics.false_rejects == 0


def test_rule_of_three_bound_reported():
    metrics, _ = evaluate(build_corpus())
    # 0 failures over >=40 approved -> bound at most ~7.5%.
    assert metrics.false_writes == 0
    assert metrics.rule_of_three_upper_bound <= 0.075 + 1e-9


def test_semantic_error_classes_present():
    classes = {c.error_class for c in build_corpus()}
    assert ErrorClass.WRONG_AMOUNT in classes
    assert ErrorClass.WRONG_ACCOUNT in classes


def test_scripted_planner_each_class_handled():
    """Every seeded error is blocked/escalated; every clean case is approved."""
    gate = make_gate()
    planner = ScriptedPlanner()
    for case in build_corpus():
        entry, src = planner.produce(case)
        decision = gate.evaluate(entry, src).decision
        if case.is_correct:
            assert decision == GateDecision.APPROVED, case.name
        else:
            assert decision != GateDecision.APPROVED, case.name

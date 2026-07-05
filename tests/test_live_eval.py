"""Tests for the live measurement path, using a fake planner (no API key).

These prove the measured-evaluation logic is correct: the gate approves only the
entries the model got right, every model mistake is blocked, and nothing wrong is
written. The real run swaps the fake planner for the Qwen planner.
"""

from __future__ import annotations

from datetime import date

import pytest

from eval.live_eval import evaluate_live
from eval.live_tasks import LiveTask, build_live_tasks
from eval.stats import wilson_interval, wilson_upper_bound
from ledgerpilot.models import JournalEntry, JournalLine, Proposal


def mk_entry(debit, credit, amount, when=date(2026, 6, 15), approver="controller"):
    return JournalEntry(
        ref="JE", entry_date=when, memo="m",
        lines=[JournalLine(account_code=debit, debit=amount),
               JournalLine(account_code=credit, credit=amount)],
        prepared_by="agent", approved_by=approver,
    )


class FakePlanner:
    """Returns a preset entry per prompt; raises for prompts mapped to None."""

    def __init__(self, mapping):
        self.mapping = mapping

    def propose(self, prompt, state):
        entry = self.mapping[prompt]
        if entry is None:
            raise RuntimeError("simulated planner failure")
        return Proposal(entry=entry)


EXPENSE = ("5000", "6000", "6100", "6200", "6300", "6900")

# Policy is class-level (all expense accounts), independent of the single oracle
# account, so a within-class wrong pick can pass the gate: the measurement is
# falsifiable, not zero by construction.
TASKS = [
    LiveTask("ok", "p-ok", "4500.00", "6100", "1000", EXPENSE, ("1000",)),
    LiveTask("within_class", "p-wc", "4500.00", "6100", "1000", EXPENSE, ("1000",)),
    LiveTask("cross_class", "p-cc", "4500.00", "6100", "1000", EXPENSE, ("1000",)),
    LiveTask("wrong_amt", "p-amt", "4500.00", "6100", "1000", EXPENSE, ("1000",)),
]


def test_measured_eval_is_falsifiable_not_zero_by_construction():
    planner = FakePlanner({
        "p-ok": mk_entry("6100", "1000", "4500.00"),   # correct
        "p-wc": mk_entry("6900", "1000", "4500.00"),   # within-class wrong -> APPROVED but wrong
        "p-cc": mk_entry("1200", "1000", "4500.00"),   # cross-class (asset) -> blocked
        "p-amt": mk_entry("6100", "1000", "4600.00"),  # wrong amount -> blocked
    })
    metrics, rows = evaluate_live(planner, TASKS)
    # Two entries pass the policy gate: the correct one and the within-class wrong one.
    assert metrics.approved == 2
    # The within-class wrong posting is a real, measured false write (not caught).
    assert metrics.false_writes == 1
    assert metrics.false_write_rate == 0.5
    assert metrics.model_correct == 1
    assert metrics.model_errors == 3
    # Cross-class + wrong-amount are caught; the within-class one is not.
    assert metrics.model_errors_caught == 2
    assert 0.0 < metrics.false_write_upper_95 <= 1.0


def test_planner_errors_are_counted_not_fatal():
    planner = FakePlanner({
        "p-ok": mk_entry("6100", "1000", "4500.00"),
        "p-wc": None, "p-cc": None, "p-amt": None,
    })
    metrics, _ = evaluate_live(planner, TASKS)
    assert metrics.errored == 3
    assert metrics.scored == 1
    assert metrics.approved == 1


def test_live_task_set_is_nontrivial():
    tasks = build_live_tasks()
    assert len(tasks) >= 12
    for t in tasks:
        assert t.expected_debit and t.expected_credit
        assert float(t.gross) > 0
        # the oracle account must be within the policy the gate enforces
        assert t.expected_debit in t.policy_debit
        assert t.expected_credit in t.policy_credit


def test_policy_is_broader_than_oracle_for_some_tasks():
    """At least some tasks have a multi-account policy, so a within-policy wrong
    pick is possible and the measured false-write rate is not zero by construction."""
    tasks = build_live_tasks()
    assert any(len(t.policy_debit) > 1 for t in tasks)


# --- Wilson interval sanity ------------------------------------------------

def test_wilson_zero_successes_has_positive_upper_bound():
    assert wilson_upper_bound(0, 0) == 0.0
    ub = wilson_upper_bound(0, 30)
    assert 0.05 < ub < 0.15  # ~9.6% for 0/30


def test_wilson_upper_bound_shrinks_with_n():
    assert wilson_upper_bound(0, 100) < wilson_upper_bound(0, 30)


def test_wilson_interval_brackets_point_estimate():
    lo, hi = wilson_interval(5, 50)
    assert lo < 0.10 < hi

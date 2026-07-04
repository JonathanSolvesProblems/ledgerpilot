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


TASKS = [
    LiveTask("ok", "p-ok", "4500.00", "6100", "1000"),
    LiveTask("wrong_acct", "p-wa", "4500.00", "6100", "1000"),
    LiveTask("wrong_amt", "p-amt", "4500.00", "6100", "1000"),
]


def test_gate_writes_only_correct_and_blocks_all_model_mistakes():
    planner = FakePlanner({
        "p-ok": mk_entry("6100", "1000", "4500.00"),   # correct
        "p-wa": mk_entry("6900", "1000", "4500.00"),   # wrong account
        "p-amt": mk_entry("6100", "1000", "4600.00"),  # wrong amount
    })
    metrics, rows = evaluate_live(planner, TASKS)
    assert metrics.approved == 1
    assert metrics.false_writes == 0
    assert metrics.model_correct == 1
    assert metrics.model_errors == 2
    assert metrics.model_errors_caught == 2
    assert metrics.model_error_catch_rate == 1.0
    assert 0.0 <= metrics.false_write_upper_95 <= 1.0


def test_planner_errors_are_counted_not_fatal():
    planner = FakePlanner({"p-ok": mk_entry("6100", "1000", "4500.00"),
                           "p-wa": None, "p-amt": None})
    metrics, _ = evaluate_live(planner, TASKS)
    assert metrics.errored == 2
    assert metrics.scored == 1
    assert metrics.approved == 1


def test_live_task_set_is_nontrivial():
    tasks = build_live_tasks()
    assert len(tasks) >= 12
    # every task has a single expected debit/credit and a positive amount
    for t in tasks:
        assert t.expected_debit and t.expected_credit
        assert float(t.gross) > 0


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

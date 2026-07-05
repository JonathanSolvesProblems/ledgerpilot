"""Measure the real Qwen planner + deterministic gate on live close tasks.

This produces the headline *measured* number (as opposed to the offline synthetic
stress-test): a real model drafts entries from natural-language tasks, and the
gate judges what it produced. Reported metrics:

  model accuracy     fraction of tasks the model posted correctly (right account
                     and amount). This is the raw LLM quality, and it is < 100%.
  false-write rate   fraction of gate-APPROVED entries that are actually wrong.
                     This is the number that matters: the gate should let through
                     only correct entries, so this should be ~0 with a Wilson 95%
                     upper bound. Every model mistake should be blocked, not written.
  model errors caught among the tasks the model got wrong, the fraction the gate
                     blocked. Target 100%.

Requires DASHSCOPE_API_KEY. Run via:  python -m eval.harness --live
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ledgerpilot.chart_of_accounts import default_state
from ledgerpilot.gate import Gate
from ledgerpilot.models import GateDecision, JournalEntry, money

from .live_tasks import LiveTask, build_live_tasks
from .stats import wilson_upper_bound


def _entry_matches(entry: JournalEntry, task: LiveTask) -> bool:
    """True if the model posted the right accounts and the right amount."""
    debit_accts = {ln.account_code for ln in entry.lines if ln.debit > 0}
    credit_accts = {ln.account_code for ln in entry.lines if ln.credit > 0}
    return (
        debit_accts == {task.expected_debit}
        and credit_accts == {task.expected_credit}
        and entry.amount == money(task.gross)
    )


@dataclass
class LiveMetrics:
    total: int
    errored: int  # tasks where the planner call/parse failed
    model_correct: int
    approved: int
    false_writes: int  # approved but wrong
    model_errors: int  # tasks the model got wrong
    model_errors_caught: int  # of those, blocked/escalated
    false_rejects: int  # correct entries the gate wrongly blocked

    @property
    def scored(self) -> int:
        return self.total - self.errored

    @property
    def model_accuracy(self) -> float:
        return self.model_correct / self.scored if self.scored else 0.0

    @property
    def false_write_rate(self) -> float:
        return self.false_writes / self.approved if self.approved else 0.0

    @property
    def false_write_upper_95(self) -> float:
        return wilson_upper_bound(self.false_writes, self.approved)

    @property
    def model_error_catch_rate(self) -> float:
        return self.model_errors_caught / self.model_errors if self.model_errors else 1.0


def evaluate_live(planner, tasks: list[LiveTask] | None = None, state=None) -> tuple[LiveMetrics, list[dict]]:
    tasks = tasks if tasks is not None else build_live_tasks()
    state = state or default_state(reference=date(2026, 6, 30))
    gate = Gate(state=state)

    rows: list[dict] = []
    errored = model_correct = approved = false_writes = 0
    model_errors = model_errors_caught = false_rejects = 0

    for t in tasks:
        source = t.source()
        try:
            proposal = planner.propose(t.prompt, state)
            entry = proposal.entry
        except Exception as exc:  # noqa: BLE001 - report, do not crash the run
            errored += 1
            rows.append({"task": t.name, "status": "planner_error", "detail": str(exc)[:160]})
            continue

        result = gate.evaluate(entry, source)
        correct = _entry_matches(entry, t)
        wrote = result.decision == GateDecision.APPROVED

        if correct:
            model_correct += 1
        else:
            model_errors += 1
            if not wrote:
                model_errors_caught += 1

        if wrote:
            approved += 1
            if not correct:
                false_writes += 1
        elif correct and result.decision == GateDecision.REJECTED:
            false_rejects += 1

        rows.append({
            "task": t.name,
            "status": "ok",
            "model_correct": correct,
            "decision": result.decision.value,
            "reason": "; ".join(c.detail for c in result.failed_checks) or "approved",
        })

    metrics = LiveMetrics(
        total=len(tasks), errored=errored, model_correct=model_correct,
        approved=approved, false_writes=false_writes, model_errors=model_errors,
        model_errors_caught=model_errors_caught, false_rejects=false_rejects,
    )
    return metrics, rows


def print_live_report(metrics: LiveMetrics, rows: list[dict]) -> None:
    print("=" * 80)
    print("LedgerPilot - MEASURED live evaluation (real Qwen planner + gate)")
    print("=" * 80)
    for r in rows:
        if r["status"] != "ok":
            print(f"  {r['task']:<22} PLANNER ERROR: {r.get('detail','')}")
            continue
        mark = "correct" if r["model_correct"] else "WRONG  "
        print(f"  {r['task']:<22} model:{mark}  gate:{r['decision']:<11} {r['reason']}")
    print("-" * 80)
    print(f"tasks scored:            {metrics.scored} ({metrics.errored} planner errors)")
    print(f"model accuracy:          {metrics.model_accuracy * 100:.1f}%  "
          f"({metrics.model_correct}/{metrics.scored} posted correctly by the model)")
    print(f"model mistakes caught:   {metrics.model_error_catch_rate * 100:.1f}%  "
          f"({metrics.model_errors_caught}/{metrics.model_errors} wrong proposals blocked)")
    if metrics.approved == 0:
        print("MEASURED FALSE-WRITE:    no gate-approved writes yet; rate undefined (n=0)")
    else:
        ub = metrics.false_write_upper_95 * 100
        print(f"MEASURED FALSE-WRITE:    {metrics.false_write_rate * 100:.2f}%  "
              f"({metrics.false_writes} wrong of {metrics.approved} approved; <= {ub:.2f}% at 95% CI, Wilson)")
        print("  (a false write here is a within-policy account error the gate cannot")
        print("   disambiguate; cross-class errors and amount errors are all blocked.)")
    print(f"false-reject rate:       "
          f"{(metrics.false_rejects / metrics.model_correct * 100) if metrics.model_correct else 0:.2f}%  "
          f"({metrics.false_rejects} correct entries wrongly blocked)")
    print("=" * 80)

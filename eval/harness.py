"""Run the seeded-error corpus through the deterministic gate and report metrics.

This produces LedgerPilot's headline numbers:

  false-write rate  of the entries the gate APPROVED, how many are actually
                    wrong. This is the number the project lives or dies on.
                    Target: 0% on this corpus.
  catch rate        of the seeded-error entries, how many the gate rejected
                    (or escalated to a human). Target: 100%.
  false-reject rate of the correct entries (negative controls), how many the
                    gate wrongly blocked. Target: 0%.

Run:  python -m eval.harness
"""

from __future__ import annotations

from dataclasses import dataclass

from ledgerpilot.chart_of_accounts import default_state
from ledgerpilot.gate import Gate
from ledgerpilot.models import GateDecision

from .corpus import Case, ErrorClass, build_corpus


@dataclass
class Metrics:
    total: int
    correct_count: int
    error_count: int
    approved_writes: int
    false_writes: int  # approved but actually wrong
    caught: int  # error cases rejected or escalated
    false_rejects: int  # correct cases blocked

    @property
    def false_write_rate(self) -> float:
        return self.false_writes / self.approved_writes if self.approved_writes else 0.0

    @property
    def catch_rate(self) -> float:
        return self.caught / self.error_count if self.error_count else 1.0

    @property
    def false_reject_rate(self) -> float:
        return self.false_rejects / self.correct_count if self.correct_count else 0.0


def evaluate(cases: list[Case]) -> tuple[Metrics, list[dict]]:
    # Reference date keeps May closed and June open, matching the corpus.
    from datetime import date

    gate = Gate(state=default_state(reference=date(2026, 6, 30)))

    rows: list[dict] = []
    approved_writes = false_writes = caught = false_rejects = 0
    correct_count = sum(1 for c in cases if c.is_correct)
    error_count = len(cases) - correct_count

    for case in cases:
        result = gate.evaluate(case.entry)
        wrote = result.decision == GateDecision.APPROVED

        if wrote and not case.is_correct:
            false_writes += 1
        if wrote:
            approved_writes += 1
        if not case.is_correct and result.decision != GateDecision.APPROVED:
            caught += 1
        if case.is_correct and result.decision == GateDecision.REJECTED:
            false_rejects += 1

        rows.append(
            {
                "case": case.name,
                "truth": case.error_class.value,
                "decision": result.decision.value,
                "correct_handling": _correct_handling(case, result.decision),
                "reason": "; ".join(
                    c.detail for c in result.failed_checks
                ) or "all checks passed",
            }
        )

    metrics = Metrics(
        total=len(cases),
        correct_count=correct_count,
        error_count=error_count,
        approved_writes=approved_writes,
        false_writes=false_writes,
        caught=caught,
        false_rejects=false_rejects,
    )
    return metrics, rows


def _correct_handling(case: Case, decision: GateDecision) -> bool:
    if case.is_correct:
        return decision == GateDecision.APPROVED
    # Any non-approval of a wrong entry is correct handling.
    return decision != GateDecision.APPROVED


def _print_report(metrics: Metrics, rows: list[dict]) -> None:
    print("=" * 78)
    print("LedgerPilot — deterministic gate evaluation")
    print("=" * 78)
    header = f"{'case':<34}{'truth':<20}{'decision':<14}{'ok':<4}"
    print(header)
    print("-" * 78)
    for r in rows:
        ok = "PASS" if r["correct_handling"] else "FAIL"
        print(f"{r['case']:<34}{r['truth']:<20}{r['decision']:<14}{ok:<4}")
    print("-" * 78)
    print(f"Total cases:            {metrics.total}")
    print(f"  correct (controls):   {metrics.correct_count}")
    print(f"  seeded errors:        {metrics.error_count}")
    print(f"Gate-approved writes:   {metrics.approved_writes}")
    print()
    print(f"  FALSE-WRITE RATE:     {metrics.false_write_rate * 100:.2f}%  "
          f"({metrics.false_writes} wrong entries approved)")
    print(f"  catch rate:           {metrics.catch_rate * 100:.2f}%  "
          f"({metrics.caught}/{metrics.error_count} errors blocked)")
    print(f"  false-reject rate:    {metrics.false_reject_rate * 100:.2f}%  "
          f"({metrics.false_rejects}/{metrics.correct_count} controls wrongly blocked)")
    print("=" * 78)


def main() -> None:
    cases = build_corpus()
    metrics, rows = evaluate(cases)
    _print_report(metrics, rows)


if __name__ == "__main__":
    main()

"""Run the close pipeline (planner -> gate) over the corpus and report metrics.

Unlike a gate-only check, every case here goes through a *planner* first, so the
metrics describe the real pipeline rather than the rules in isolation:

  false-write rate  of the entries the gate APPROVED, how many are actually
                    wrong. The number the project lives or dies on. Reported with
                    a 95% upper confidence bound (Rule of Three) so a 0/N result
                    is presented honestly rather than as a bare "0%".
  catch rate        of the seeded-error entries, how many the gate blocked or
                    escalated. Target: 100%.
  false-reject rate of the correct entries (negative controls), how many the
                    gate wrongly blocked. Target: 0%.

By default the offline ScriptedPlanner injects documented failure modes so the
gate is stress-tested at scale with no API key. With --live it calls the real
Qwen planner on the clean scenarios and measures the actual model + gate pipeline.

Run:  python -m eval.harness            (offline, deterministic, 120 cases)
      python -m eval.harness --live     (real Qwen planner on clean scenarios)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date

from ledgerpilot.chart_of_accounts import default_state
from ledgerpilot.gate import Gate
from ledgerpilot.models import GateDecision

from .corpus import Case, build_corpus
from .scripted_planner import ScriptedPlanner


@dataclass
class Metrics:
    total: int
    correct_count: int
    error_count: int
    approved_writes: int
    false_writes: int  # approved but actually wrong
    caught: int  # error cases rejected or escalated
    blocked: int  # error cases hard-rejected
    escalated: int  # error cases sent to a human (NEEDS_HUMAN)
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

    @property
    def rule_of_three_upper_bound(self) -> float:
        """95% upper bound on the false-write rate when zero are observed.

        For 0 failures in n trials the 95% CI upper bound is ~3/n. Reporting it
        turns a bare "0%" into an honest "0%, consistent with <=X% at 95%".
        """
        if self.false_writes == 0 and self.approved_writes > 0:
            return 3.0 / self.approved_writes
        # With observed failures, report the point estimate (no bound needed).
        return self.false_write_rate


def _handled_correctly(case: Case, decision: GateDecision) -> bool:
    if case.is_correct:
        return decision == GateDecision.APPROVED
    return decision != GateDecision.APPROVED


def evaluate(cases: list[Case], planner=None) -> tuple[Metrics, list[dict]]:
    planner = planner or ScriptedPlanner()
    gate = Gate(state=default_state(reference=date(2026, 6, 30)))

    rows: list[dict] = []
    approved_writes = false_writes = caught = blocked = escalated = false_rejects = 0
    correct_count = sum(1 for c in cases if c.is_correct)
    error_count = len(cases) - correct_count

    for case in cases:
        entry, source = planner.produce(case)
        result = gate.evaluate(entry, source)
        wrote = result.decision == GateDecision.APPROVED

        if wrote:
            approved_writes += 1
            if not case.is_correct:
                false_writes += 1
        if not case.is_correct and not wrote:
            caught += 1
            if result.decision == GateDecision.REJECTED:
                blocked += 1
            elif result.decision == GateDecision.NEEDS_HUMAN:
                escalated += 1
        if case.is_correct and result.decision == GateDecision.REJECTED:
            false_rejects += 1

        rows.append({
            "case": case.name,
            "truth": case.error_class.value,
            "decision": result.decision.value,
            "ok": _handled_correctly(case, result.decision),
            "reason": "; ".join(c.detail for c in result.failed_checks) or "all checks passed",
        })

    metrics = Metrics(
        total=len(cases),
        correct_count=correct_count,
        error_count=error_count,
        approved_writes=approved_writes,
        false_writes=false_writes,
        caught=caught,
        blocked=blocked,
        escalated=escalated,
        false_rejects=false_rejects,
    )
    return metrics, rows


def _print_report(metrics: Metrics, rows: list[dict], mode: str) -> None:
    print("=" * 80)
    print(f"LedgerPilot - close pipeline evaluation  [{mode}]")
    print("=" * 80)
    # Show any mishandled cases explicitly; summarize the rest.
    failures = [r for r in rows if not r["ok"]]
    print(f"cases: {metrics.total}   handled correctly: {metrics.total - len(failures)}")
    if failures:
        print("\nMISHANDLED CASES:")
        for r in failures:
            print(f"  {r['case']:<28}{r['truth']:<18}{r['decision']:<12}{r['reason']}")
    print("-" * 80)
    print(f"correct controls:       {metrics.correct_count}")
    print(f"seeded errors:          {metrics.error_count}")
    print(f"gate-approved writes:   {metrics.approved_writes}")
    print()
    ub = metrics.rule_of_three_upper_bound * 100
    print(f"  FALSE-WRITE RATE:     {metrics.false_write_rate * 100:.2f}%  "
          f"({metrics.false_writes} wrong of {metrics.approved_writes} approved; "
          f"<= {ub:.2f}% at 95% CI)")
    print(f"  catch rate:           {metrics.catch_rate * 100:.2f}%  "
          f"({metrics.caught}/{metrics.error_count} = {metrics.blocked} blocked "
          f"+ {metrics.escalated} escalated to human)")
    print(f"  false-reject rate:    {metrics.false_reject_rate * 100:.2f}%  "
          f"({metrics.false_rejects}/{metrics.correct_count} controls wrongly blocked)")
    if "offline" in mode:
        print("\n  NOTE: this is a SYNTHETIC gate stress-test (no LLM). It measures the")
        print("  gate's decision logic against injected errors. The measured false-write")
        print("  rate on real model output comes from:  python -m eval.harness --live")
    print("=" * 80)


def main(argv: list[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    if "--live" in argv:
        # Measured run: the real Qwen planner drafts entries from natural-language
        # close tasks and the gate judges what it produced.
        from ledgerpilot.planner import Planner

        from .live_eval import evaluate_live, print_live_report
        metrics, rows = evaluate_live(Planner())
        print_live_report(metrics, rows)
        if metrics.errored == metrics.total and metrics.total:
            print("\nAll planner calls failed. If you see 403 'Access to model")
            print("denied', the Alibaba Cloud account is not yet authorized to call")
            print("models: finish Identity Verification so the 'Some Features")
            print("Restricted' banner clears, then re-run. The key/endpoint are fine.")
        return
    # Offline synthetic gate stress-test (no LLM, no key).
    metrics, rows = evaluate(build_corpus(), ScriptedPlanner())
    _print_report(metrics, rows, "offline synthetic gate stress-test (no LLM)")


if __name__ == "__main__":
    main()

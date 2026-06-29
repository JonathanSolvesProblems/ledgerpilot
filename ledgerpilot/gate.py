"""The deterministic validation gate: LedgerPilot's trust boundary.

This module is intentionally free of any LLM call, network I/O, or randomness.
Given the same entry and ledger state it always returns the same verdict, so it
is fully auditable and reproducible. The generative layers may propose anything;
nothing reaches the ledger unless every hard check here passes.

Each check maps to a real accounting / internal-control concern:

  balance            double-entry must balance to the cent
  account_validity   every account exists and is postable
  no_self_contra     a line cannot debit and credit the same account
  positive_amounts   no negative or zero-magnitude lines
  period_lock        entry date must fall in an OPEN period
  segregation        preparer != approver, approver must be authorized
  approval_threshold large entries require explicit human approval (HITL)
  reconciliation     (when a source document is supplied) the entry's amount and
                     accounts must match the independent document evidence

The reconciliation check is what lets the gate catch *semantic* errors that a
balance check cannot: a journal entry can balance to the cent yet post the wrong
amount or hit a valid-but-incorrect account. Those are exactly the mistakes a
generative planner makes, so reconciling against the source document is how the
deterministic layer guards against a confident, well-formed, wrong proposal.
"""

from __future__ import annotations

from decimal import Decimal

from .chart_of_accounts import ACCOUNTS, LedgerState
from .models import (
    CheckResult,
    GateDecision,
    GateResult,
    JournalEntry,
    Severity,
    SourceDocument,
)


class Gate:
    """Runs the full battery of deterministic checks over a journal entry."""

    def __init__(
        self,
        state: LedgerState,
        accounts: dict | None = None,
        approval_threshold: Decimal = Decimal("10000.00"),
    ) -> None:
        self.state = state
        self.accounts = accounts if accounts is not None else ACCOUNTS
        self.approval_threshold = approval_threshold

    # --- individual checks -------------------------------------------------

    def _check_balance(self, entry: JournalEntry) -> CheckResult:
        diff = entry.total_debit - entry.total_credit
        passed = diff == Decimal("0.00")
        return CheckResult(
            check="balance",
            passed=passed,
            severity=Severity.ERROR,
            detail=(
                "Debits equal credits."
                if passed
                else f"Out of balance by {diff:+} "
                f"(debits {entry.total_debit}, credits {entry.total_credit})."
            ),
        )

    def _check_account_validity(self, entry: JournalEntry) -> CheckResult:
        unknown = []
        non_postable = []
        for ln in entry.lines:
            acct = self.accounts.get(ln.account_code)
            if acct is None:
                unknown.append(ln.account_code)
            elif not acct.postable:
                non_postable.append(ln.account_code)
        passed = not unknown and not non_postable
        if passed:
            detail = "All accounts exist and are postable."
        else:
            parts = []
            if unknown:
                parts.append(f"unknown accounts {sorted(set(unknown))}")
            if non_postable:
                parts.append(f"non-postable accounts {sorted(set(non_postable))}")
            detail = "; ".join(parts).capitalize() + "."
        return CheckResult(
            check="account_validity",
            passed=passed,
            severity=Severity.ERROR,
            detail=detail,
        )

    def _check_no_self_contra(self, entry: JournalEntry) -> CheckResult:
        offenders = [
            ln.account_code
            for ln in entry.lines
            if ln.debit > 0 and ln.credit > 0
        ]
        passed = not offenders
        return CheckResult(
            check="no_self_contra",
            passed=passed,
            severity=Severity.ERROR,
            detail=(
                "No line both debits and credits."
                if passed
                else f"Lines debit and credit simultaneously: {sorted(set(offenders))}."
            ),
        )

    def _check_positive_amounts(self, entry: JournalEntry) -> CheckResult:
        bad = [
            ln.account_code
            for ln in entry.lines
            if ln.debit < 0 or ln.credit < 0 or (ln.debit == 0 and ln.credit == 0)
        ]
        passed = not bad
        return CheckResult(
            check="positive_amounts",
            passed=passed,
            severity=Severity.ERROR,
            detail=(
                "All lines carry a positive debit or credit."
                if passed
                else f"Negative or empty lines on accounts {sorted(set(bad))}."
            ),
        )

    def _check_period_lock(self, entry: JournalEntry) -> CheckResult:
        period = self.state.period_for(entry.entry_date)
        if period is None:
            passed, detail = False, f"No accounting period defined for {entry.entry_date}."
        elif not period.is_open:
            passed, detail = False, (
                f"Period {period.year}-{period.month:02d} is closed for posting."
            )
        else:
            passed, detail = True, f"Period {period.year}-{period.month:02d} is open."
        return CheckResult(
            check="period_lock",
            passed=passed,
            severity=Severity.ERROR,
            detail=detail,
        )

    def _check_segregation(self, entry: JournalEntry) -> CheckResult:
        preparer = entry.prepared_by
        approver = entry.approved_by
        if approver is None:
            # No approver yet; not a hard failure on its own (threshold check
            # decides whether one is required), but record it.
            return CheckResult(
                check="segregation",
                passed=True,
                severity=Severity.INFO,
                detail="No approver recorded yet.",
            )
        if approver == preparer:
            return CheckResult(
                check="segregation",
                passed=False,
                severity=Severity.ERROR,
                detail=f"Preparer and approver are the same person ({approver}).",
            )
        if approver not in self.state.approvers:
            return CheckResult(
                check="segregation",
                passed=False,
                severity=Severity.ERROR,
                detail=f"Approver '{approver}' is not an authorized approver.",
            )
        return CheckResult(
            check="segregation",
            passed=True,
            severity=Severity.INFO,
            detail=f"Approved by authorized '{approver}', distinct from preparer.",
        )

    def _check_approval_threshold(self, entry: JournalEntry) -> CheckResult:
        over = entry.amount > self.approval_threshold
        has_human = entry.approved_by is not None and entry.approved_by != "agent"
        if not over:
            return CheckResult(
                check="approval_threshold",
                passed=True,
                severity=Severity.INFO,
                detail=f"Amount {entry.amount} within autonomous limit {self.approval_threshold}.",
            )
        # Over threshold: requires a human approver.
        return CheckResult(
            check="approval_threshold",
            passed=has_human,
            severity=Severity.WARNING,
            detail=(
                f"Amount {entry.amount} exceeds {self.approval_threshold}; "
                + (
                    f"human approval present ({entry.approved_by})."
                    if has_human
                    else "human approval required."
                )
            ),
        )

    def _check_reconciliation(
        self, entry: JournalEntry, source: SourceDocument | None
    ) -> CheckResult:
        if source is None:
            return CheckResult(
                check="reconciliation",
                passed=True,
                severity=Severity.INFO,
                detail="No source document supplied; reconciliation skipped.",
            )
        problems: list[str] = []

        # Amount must match the authoritative document total.
        if entry.amount != source.gross_amount:
            problems.append(
                f"amount {entry.amount} does not match document total "
                f"{source.gross_amount}"
            )

        # Accounts must fall within the posting policy for this document.
        if source.allowed_debit_accounts:
            bad_debits = sorted(
                {
                    ln.account_code
                    for ln in entry.lines
                    if ln.debit > 0 and ln.account_code not in source.allowed_debit_accounts
                }
            )
            if bad_debits:
                problems.append(
                    f"debit accounts {bad_debits} not permitted for "
                    f"{source.doc_type} (allowed {source.allowed_debit_accounts})"
                )
        if source.allowed_credit_accounts:
            bad_credits = sorted(
                {
                    ln.account_code
                    for ln in entry.lines
                    if ln.credit > 0 and ln.account_code not in source.allowed_credit_accounts
                }
            )
            if bad_credits:
                problems.append(
                    f"credit accounts {bad_credits} not permitted for "
                    f"{source.doc_type} (allowed {source.allowed_credit_accounts})"
                )

        passed = not problems
        return CheckResult(
            check="reconciliation",
            passed=passed,
            severity=Severity.ERROR,
            detail=(
                f"Entry reconciles to document {source.document_id}."
                if passed
                else f"Does not reconcile to {source.document_id}: "
                + "; ".join(problems)
                + "."
            ),
        )

    # --- aggregate ---------------------------------------------------------

    def evaluate(
        self, entry: JournalEntry, source: SourceDocument | None = None
    ) -> GateResult:
        checks = [
            self._check_balance(entry),
            self._check_account_validity(entry),
            self._check_no_self_contra(entry),
            self._check_positive_amounts(entry),
            self._check_period_lock(entry),
            self._check_segregation(entry),
            self._check_approval_threshold(entry),
            self._check_reconciliation(entry, source),
        ]

        hard_failure = any(
            (not c.passed) and c.severity == Severity.ERROR for c in checks
        )
        threshold = next(c for c in checks if c.check == "approval_threshold")

        if hard_failure:
            decision = GateDecision.REJECTED
        elif not threshold.passed:
            # Rules otherwise pass but a human sign-off is missing.
            decision = GateDecision.NEEDS_HUMAN
        else:
            decision = GateDecision.APPROVED

        return GateResult(
            decision=decision,
            checks=checks,
            entry_hash=entry.content_hash(),
        )

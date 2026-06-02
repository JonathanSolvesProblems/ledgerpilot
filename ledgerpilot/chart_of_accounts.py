"""A small but realistic chart of accounts and accounting-period state.

In production this is read from the Odoo system of record. Here it is a
self-contained fixture so the gate and eval harness run without a live ERP.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .models import Account, AccountType

# A compact chart covering the account classes a close touches.
_ACCOUNTS: list[Account] = [
    Account(code="1000", name="Cash and cash equivalents", type=AccountType.ASSET),
    Account(code="1100", name="Accounts receivable", type=AccountType.ASSET),
    Account(code="1200", name="Prepaid expenses", type=AccountType.ASSET),
    Account(code="1500", name="Fixed assets", type=AccountType.ASSET),
    Account(code="1900", name="Assets (summary)", type=AccountType.ASSET, postable=False),
    Account(code="2000", name="Accounts payable", type=AccountType.LIABILITY),
    Account(code="2100", name="Accrued liabilities", type=AccountType.LIABILITY),
    Account(code="2200", name="VAT payable", type=AccountType.LIABILITY),
    Account(code="3000", name="Share capital", type=AccountType.EQUITY),
    Account(code="3100", name="Retained earnings", type=AccountType.EQUITY),
    Account(code="4000", name="Revenue", type=AccountType.INCOME),
    Account(code="4100", name="Service revenue", type=AccountType.INCOME),
    Account(code="5000", name="Cost of goods sold", type=AccountType.EXPENSE),
    Account(code="6000", name="Salaries expense", type=AccountType.EXPENSE),
    Account(code="6100", name="Rent expense", type=AccountType.EXPENSE),
    Account(code="6200", name="Utilities expense", type=AccountType.EXPENSE),
    Account(code="6300", name="Software subscriptions", type=AccountType.EXPENSE),
    Account(code="6900", name="Bank fees", type=AccountType.EXPENSE),
]

ACCOUNTS: dict[str, Account] = {a.code: a for a in _ACCOUNTS}


@dataclass
class Period:
    """An accounting period and whether it is open for posting."""

    year: int
    month: int
    is_open: bool

    def contains(self, d: date) -> bool:
        return d.year == self.year and d.month == self.month


@dataclass
class LedgerState:
    """Snapshot of the system-of-record state the gate validates against."""

    periods: list[Period] = field(default_factory=list)
    # Authorized approvers and their per-entry approval limit.
    approvers: dict[str, str] = field(default_factory=dict)  # user -> role

    def period_for(self, d: date) -> Period | None:
        for p in self.periods:
            if p.contains(d):
                return p
        return None

    def is_open_period(self, d: date) -> bool:
        p = self.period_for(d)
        return bool(p and p.is_open)


def default_state(reference: date = date(2026, 6, 30)) -> LedgerState:
    """A ledger where the current month is open and the prior month is closed."""
    prior_month = 12 if reference.month == 1 else reference.month - 1
    prior_year = reference.year - 1 if reference.month == 1 else reference.year
    return LedgerState(
        periods=[
            Period(year=prior_year, month=prior_month, is_open=False),
            Period(year=reference.year, month=reference.month, is_open=True),
        ],
        approvers={"controller": "controller", "cfo": "cfo"},
    )

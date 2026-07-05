"""Realistic month-end close tasks for the live (real Qwen) measurement.

Each task is a natural-language description of a financial event, plus the
ground-truth posting it should produce.

IMPORTANT (methodology): the gate is NOT handed the answer. Each task carries a
deterministic *posting policy* (the set of accounts permitted for that kind of
document, e.g. "an expense invoice may debit any expense account and credit cash
or accounts payable") that is INDEPENDENT of the single correct account. The gate
validates the model's entry against that policy and the source amount; the
separate ground-truth oracle (`expected_debit` / `expected_credit`) is used only
to score whether the model actually got it right.

Because the policy is broader than the oracle, a plausible-but-wrong posting can
pass the gate (e.g. rent booked to a different expense account), so the measured
false-write rate is genuinely falsifiable, not zero by construction. The gate
catches cross-class errors (an expense posted to an asset, wrong amount, unknown
or non-postable account, closed period, self-approval); within-class account
selection is the residual the measurement exposes honestly.
"""

from __future__ import annotations

from dataclasses import dataclass

from ledgerpilot.models import SourceDocument

# Account classes = the deterministic posting policy vocabulary. These are real
# groupings from the chart of accounts, defined once and applied uniformly, not
# tuned per task.
EXPENSE = ("5000", "6000", "6100", "6200", "6300", "6900")
CURRENT_ASSET = ("1000", "1100", "1200")
NONCURRENT_ASSET = ("1500",)
LIABILITY = ("2000", "2100", "2200")
INCOME = ("4000", "4100")


@dataclass(frozen=True)
class LiveTask:
    name: str
    prompt: str
    gross: str
    expected_debit: str          # oracle: the single correct debit account
    expected_credit: str         # oracle: the single correct credit account
    policy_debit: tuple[str, ...]   # accounts the gate permits on the debit side
    policy_credit: tuple[str, ...]  # accounts the gate permits on the credit side

    def source(self) -> SourceDocument:
        return SourceDocument(
            document_id=self.name,
            doc_type="invoice",
            gross_amount=self.gross,
            allowed_debit_accounts=list(self.policy_debit),
            allowed_credit_accounts=list(self.policy_credit),
        )


def build_live_tasks() -> list[LiveTask]:
    return [
        LiveTask("rent",
                 "Record the June office rent. Invoice INV-RENT-06 for 4,500.00, paid from the company bank account.",
                 "4500.00", "6100", "1000", EXPENSE, ("1000", "2000")),
        LiveTask("utilities",
                 "Post the June electricity and water bill, 1,230.00, paid from the bank.",
                 "1230.00", "6200", "1000", EXPENSE, ("1000", "2000")),
        LiveTask("salaries",
                 "Book June staff salaries of 8,200.00 paid out of the bank account.",
                 "8200.00", "6000", "1000", EXPENSE, ("1000", "2100")),
        LiveTask("bank_fee",
                 "The bank statement shows a monthly account maintenance charge of 75.00.",
                 "75.00", "6900", "1000", EXPENSE, ("1000",)),
        LiveTask("software",
                 "Record a 900.00 software subscription paid from the bank (no tax).",
                 "900.00", "6300", "1000", EXPENSE, ("1000", "2000")),
        LiveTask("cogs",
                 "Record 3,400.00 of inventory sold this month (cost of goods sold), payable to the supplier on credit.",
                 "3400.00", "5000", "2000", EXPENSE, ("2000", "1000")),
        LiveTask("accrued_payroll",
                 "Accrue 1,500.00 of payroll earned by staff in June but not yet paid; it will be paid in July. Record the accrued liability.",
                 "1500.00", "6000", "2100", EXPENSE, ("2100",)),
        LiveTask("utilities_accrual",
                 "Accrue 1,230.00 for June utilities used but not yet billed; the invoice arrives in July. Record the accrued liability.",
                 "1230.00", "6200", "2100", EXPENSE, ("2100",)),
        # Cross-class traps: the natural mistake is the wrong CLASS, which the
        # policy catches.
        LiveTask("prepaid_insurance",
                 "We paid 2,400.00 up front for a full year of insurance starting next month, from the bank. It should be carried as an asset, not expensed now.",
                 "2400.00", "1200", "1000", ("1200",), ("1000",)),
        LiveTask("rent_prepaid_trap",
                 "Paid 4,500.00 from the bank for NEXT month's office rent, in advance. It relates to a future period and should be carried as prepaid, not expensed this month.",
                 "4500.00", "1200", "1000", ("1200", "1500"), ("1000",)),
        LiveTask("equipment",
                 "Purchased a server for 5,200.00 on credit. It is a long-lived asset and should be capitalized, not expensed.",
                 "5200.00", "1500", "2000", ("1500",), ("2000", "1000")),
        LiveTask("service_revenue",
                 "We invoiced a client 6,200.00 for consulting delivered in June, on credit (accounts receivable).",
                 "6200.00", "1100", "4100", ("1100", "1000"), INCOME),
        LiveTask("interest_income",
                 "The bank credited 320.00 of interest income to our account this month.",
                 "320.00", "1000", "4000", ("1000", "1100"), INCOME),
        LiveTask("vat_settlement",
                 "Settle 640.00 of VAT owed to the tax authority, paid from the bank. This clears the VAT payable liability.",
                 "640.00", "2200", "1000", ("2200",), ("1000",)),
        LiveTask("ap_payment",
                 "Pay 1,080.00 to a supplier to clear an outstanding accounts-payable balance, from the bank.",
                 "1080.00", "2000", "1000", ("2000",), ("1000",)),
        LiveTask("ar_collection",
                 "A customer paid 6,200.00 against their outstanding invoice; the cash landed in the bank and clears their receivable.",
                 "6200.00", "1000", "1100", ("1000",), ("1100",)),
    ]

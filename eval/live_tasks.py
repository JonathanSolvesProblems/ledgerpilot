"""Realistic month-end close tasks for the live (real Qwen) measurement.

Each task is a natural-language description of a financial event, the way it
would arrive in an inbox or on a statement, plus the ground-truth posting it
should produce. The live harness feeds the prompt to the real Qwen planner and
checks what the model actually drafts against the deterministic gate.

The tasks are single-debit / single-credit so the gate's reconciliation fully
determines correctness (right account + right amount). Some are deliberately
easy to misclassify (prepaid vs expense, capitalize vs expense, which expense
account), so the model genuinely errs sometimes and the gate is seen catching a
real model mistake rather than a hand-built one. Multi-line tax splits are out
of scope for the measured set and listed under Known Limitations in the README.
"""

from __future__ import annotations

from dataclasses import dataclass

from ledgerpilot.models import SourceDocument


@dataclass(frozen=True)
class LiveTask:
    name: str
    prompt: str
    gross: str
    expected_debit: str
    expected_credit: str

    def source(self) -> SourceDocument:
        # Allowed sets are the single correct account, so the gate approves an
        # entry only if the model got both the account and the amount right.
        return SourceDocument(
            document_id=self.name,
            doc_type="invoice",
            gross_amount=self.gross,
            allowed_debit_accounts=[self.expected_debit],
            allowed_credit_accounts=[self.expected_credit],
        )


def build_live_tasks() -> list[LiveTask]:
    return [
        LiveTask(
            "rent",
            "Record the June office rent. Invoice INV-RENT-06 for 4,500.00, paid from the company bank account.",
            "4500.00", "6100", "1000",
        ),
        LiveTask(
            "utilities",
            "Post the June electricity and water bill, 1,230.00, paid from the bank.",
            "1230.00", "6200", "1000",
        ),
        LiveTask(
            "salaries",
            "Book June staff salaries of 8,200.00 paid out of the bank account.",
            "8200.00", "6000", "1000",
        ),
        LiveTask(
            "bank_fee",
            "The bank statement shows a monthly account maintenance charge of 75.00.",
            "75.00", "6900", "1000",
        ),
        LiveTask(
            "software",
            "Record a 900.00 software subscription paid from the bank (no tax).",
            "900.00", "6300", "1000",
        ),
        LiveTask(
            "prepaid_insurance",
            "We paid 2,400.00 up front for a full year of insurance coverage starting next month, from the bank. It should be carried as an asset, not expensed now.",
            "2400.00", "1200", "1000",
        ),
        LiveTask(
            "equipment",
            "Purchased a server for 5,200.00 on credit from the supplier. It is a long-lived asset and should be capitalized, not expensed.",
            "5200.00", "1500", "2000",
        ),
        LiveTask(
            "cogs",
            "Record 3,400.00 of inventory purchased on credit that was sold this month (cost of goods sold), payable to the supplier.",
            "3400.00", "5000", "2000",
        ),
        LiveTask(
            "service_revenue",
            "We invoiced a client 6,200.00 for consulting services delivered in June, on credit (accounts receivable).",
            "6200.00", "1100", "4100",
        ),
        LiveTask(
            "interest_income",
            "The bank credited 320.00 of interest income to our account this month.",
            "320.00", "1000", "4000",
        ),
        LiveTask(
            "accrued_payroll",
            "Accrue 1,500.00 of payroll earned by staff in June but not yet paid; it will be paid in July. Record the accrued liability.",
            "1500.00", "6000", "2100",
        ),
        LiveTask(
            "vat_settlement",
            "Settle 640.00 of VAT owed to the tax authority, paid from the bank. This clears the VAT payable liability.",
            "640.00", "2200", "1000",
        ),
        LiveTask(
            "ap_payment",
            "Pay 1,080.00 to a supplier to clear an outstanding accounts-payable balance, from the bank.",
            "1080.00", "2000", "1000",
        ),
        LiveTask(
            "ar_collection",
            "A customer paid 6,200.00 against their outstanding invoice; the cash landed in the bank and clears their receivable.",
            "6200.00", "1000", "1100",
        ),
        LiveTask(
            "rent_prepaid_trap",
            "Paid 4,500.00 from the bank for next month's office rent, in advance. It relates to a future period and should be carried as prepaid, not expensed this month.",
            "4500.00", "1200", "1000",
        ),
        LiveTask(
            "utilities_accrual",
            "Accrue 1,230.00 for June utilities used but not yet billed; the invoice arrives in July. Record the accrued liability.",
            "1230.00", "6200", "2100",
        ),
    ]

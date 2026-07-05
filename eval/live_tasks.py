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
EQUITY = ("3000", "3100")


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
        LiveTask("cash_sale",
                 "A walk-in customer paid 3,500.00 in cash for goods sold today.",
                 "3500.00", "1000", "4000", ("1000", "1100"), INCOME),
        LiveTask("service_cash",
                 "A client paid 2,800.00 in cash for a completed consulting service.",
                 "2800.00", "1000", "4100", ("1000", "1100"), INCOME),
        LiveTask("rent_on_credit",
                 "Received the 4,500.00 office rent invoice, to be paid later on account.",
                 "4500.00", "6100", "2000", EXPENSE, ("2000", "1000")),
        LiveTask("utilities_on_credit",
                 "The 920.00 utilities invoice arrived, payable to the utility company on credit.",
                 "920.00", "6200", "2000", EXPENSE, ("2000", "1000")),
        LiveTask("software_on_credit",
                 "A 1,200.00 annual software license, invoiced on net-30 terms.",
                 "1200.00", "6300", "2000", EXPENSE, ("2000", "1000")),
        LiveTask("cogs_cash",
                 "Paid 2,200.00 in cash for goods that were sold this month.",
                 "2200.00", "5000", "1000", EXPENSE, ("1000", "2000")),
        LiveTask("wire_fee",
                 "A 45.00 wire transfer fee appears on the bank statement.",
                 "45.00", "6900", "1000", EXPENSE, ("1000",)),
        LiveTask("prepaid_rent_quarter",
                 "Paid 3,000.00 from the bank for next quarter's rent in advance; carry it as an asset.",
                 "3000.00", "1200", "1000", ("1200", "1500"), ("1000",)),
        LiveTask("equipment_cash",
                 "Bought a 6,500.00 laptop fleet outright from the bank; capitalize it as a fixed asset.",
                 "6500.00", "1500", "1000", ("1500",), ("1000", "2000")),
        LiveTask("ar_collection_2",
                 "A customer settled their 4,200.00 invoice; the funds hit the bank account.",
                 "4200.00", "1000", "1100", ("1000",), ("1100",)),
        LiveTask("ap_payment_2",
                 "Paid a supplier 780.00 to clear an open payable, from the bank.",
                 "780.00", "2000", "1000", ("2000",), ("1000",)),
        LiveTask("vat_payment_2",
                 "Remitted 410.00 of VAT owed to the tax authority from the bank.",
                 "410.00", "2200", "1000", ("2200",), ("1000",)),
        LiveTask("interest_income_2",
                 "The bank posted 150.00 of interest earned this month.",
                 "150.00", "1000", "4000", ("1000", "1100"), INCOME),
        LiveTask("accrue_utilities_2",
                 "Accrue 610.00 of utilities consumed but not yet invoiced; invoice arrives next month.",
                 "610.00", "6200", "2100", EXPENSE, ("2100",)),
        LiveTask("accrue_rent",
                 "Accrue 4,500.00 of rent for the period; the invoice is still pending.",
                 "4500.00", "6100", "2100", EXPENSE, ("2100",)),
        LiveTask("prepaid_insurance_2",
                 "Paid 1,800.00 upfront for six months of insurance coverage; carry it as an asset.",
                 "1800.00", "1200", "1000", ("1200",), ("1000",)),
        LiveTask("dividend_paid",
                 "Paid a 5,000.00 dividend to shareholders from the bank; reduce retained earnings.",
                 "5000.00", "3100", "1000", EQUITY, ("1000",)),
        LiveTask("share_issue",
                 "Issued new shares for 8,000.00; the cash was received into the bank.",
                 "8000.00", "1000", "3000", ("1000", "1100"), ("3000",)),
        LiveTask("salaries_cash",
                 "Paid 6,800.00 of wages from the bank this period.",
                 "6800.00", "6000", "1000", EXPENSE, ("1000", "2100")),
        LiveTask("saas_cash",
                 "A 640.00 monthly SaaS subscription was paid from the bank.",
                 "640.00", "6300", "1000", EXPENSE, ("1000", "2000")),
        LiveTask("cogs_on_credit_2",
                 "Recorded 3,900.00 of goods sold this month, payable to the vendor on account.",
                 "3900.00", "5000", "2000", EXPENSE, ("2000", "1000")),
        LiveTask("utilities_cash_2",
                 "Paid a 1,100.00 electricity bill from the bank.",
                 "1100.00", "6200", "1000", EXPENSE, ("1000", "2000")),
        LiveTask("bank_fee_monthly",
                 "A 30.00 monthly account maintenance fee was charged by the bank.",
                 "30.00", "6900", "1000", EXPENSE, ("1000",)),
    ]

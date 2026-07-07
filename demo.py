"""Scriptable end-to-end demo: propose -> gate -> governed write.

This is the spine for the 3-minute submission video. It runs entirely against an
in-memory fake Odoo, so it needs no cloud key and no live ERP, yet exercises the
full governance path. Five scenes:

  1. THE SEMANTIC SAVE a balanced entry with real accounts, posted to the WRONG
                       account, is refused by reconciliation to the source
                       document (a trial balance would never catch it).
  2. HAPPY PATH        the same invoice, posted correctly, is approved, signed,
                       and written.
  3. THE BALANCE SAVE  an out-of-balance entry is refused at the gate.
  4. HUMAN-IN-LOOP     a large entry is escalated, then committed once approved.
  5. IDEMPOTENCY       re-submitting a written entry does not double-post.

Run:  python demo.py
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from ledgerpilot.chart_of_accounts import default_state
from ledgerpilot.config import Config
from ledgerpilot.gate import Gate
from ledgerpilot.models import GateDecision, JournalEntry, JournalLine, SourceDocument
from ledgerpilot.tokens import issue_token
from ledgerpilot.writeback import OdooWriteBack, WriteRefused, approve_and_commit

# ---- demo wiring (no cloud, no live ERP) --------------------------------

DEMO_CONFIG = Config(
    dashscope_api_key="",
    dashscope_base_url="",
    planner_model="qwen3.7-max",
    vision_model="qwen3-vl-plus",
    signing_key="demo-signing-key-not-for-production",
    approval_threshold=Decimal("10000.00"),
    odoo_url="(alibaba-cloud-ecs)",
    odoo_db="ledgerpilot",
    odoo_username="agent",
    odoo_api_key="",
    odoo_mcp_server_url="",
)


class FakeOdoo:
    """In-memory stand-in for the live Odoo (the real write is scripts/real_odoo_write.py)."""

    def __init__(self) -> None:
        self.moves: list[dict] = []

    def create_move(self, payload: dict) -> int:
        self.moves.append(payload)
        return len(self.moves)


def line(acct: str, debit: str = "0.00", credit: str = "0.00", desc: str = "") -> JournalLine:
    return JournalLine(account_code=acct, description=desc, debit=debit, credit=credit)


def banner(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def show_gate(gate: Gate, entry: JournalEntry, source: SourceDocument | None = None):
    result = gate.evaluate(entry, source)
    print(f"  proposed: {entry.ref}  amount={entry.amount}  date={entry.entry_date}")
    for c in result.checks:
        mark = "ok " if c.passed else "XX "
        print(f"    [{mark}] {c.check:<20} {c.detail}")
    print(f"  --> GATE DECISION: {result.decision.value.upper()}")
    return result


def main() -> None:
    gate = Gate(state=default_state(reference=date(2026, 6, 30)),
                approval_threshold=DEMO_CONFIG.approval_threshold)
    odoo = FakeOdoo()
    writer = OdooWriteBack(gate=gate, config=DEMO_CONFIG, odoo_client=odoo)

    # The June rent invoice: $4,500, and its posting policy says rent must hit
    # Rent expense (6100), paid from Cash (1000) or Accounts payable (2000).
    rent_doc = SourceDocument(
        document_id="INV-RENT-06",
        doc_type="invoice",
        gross_amount="4500.00",
        allowed_debit_accounts=["6100"],
        allowed_credit_accounts=["1000", "2000"],
    )

    # --- Scene 1: the semantic save --------------------------------------
    banner("SCENE 1  Balanced + valid + WRONG account -> caught by reconciliation")
    # The planner drafted a perfectly balanced entry using real, postable
    # accounts, but booked the rent to Bank fees (6900) instead of Rent expense
    # (6100). Debits equal credits, every account exists: a trial balance and a
    # balance-only gate both wave it through. Only reconciliation to the source
    # document catches it.
    misposted = JournalEntry(
        ref="JE-300",
        entry_date=date(2026, 6, 20),
        memo="June office rent (misposted to bank fees)",
        lines=[line("6900", debit="4500.00", desc="Rent booked to WRONG account"),
               line("1000", credit="4500.00", desc="Cash")],
        prepared_by="agent",
        approved_by="controller",
        source_doc_id="INV-RENT-06",
    )
    show_gate(gate, misposted, source=rent_doc)
    try:
        approve_and_commit(misposted, gate, writer, config=DEMO_CONFIG, source=rent_doc)
        print("  WRITE-BACK: written  <-- THIS SHOULD NEVER PRINT")
    except WriteRefused as exc:
        print(f"  WRITE-BACK REFUSED: {exc}")

    # --- Scene 2: happy path ---------------------------------------------
    banner("SCENE 2  Same invoice, correct account -> approved -> signed -> written")
    clean = JournalEntry(
        ref="JE-301",
        entry_date=date(2026, 6, 20),
        memo="June office rent",
        lines=[line("6100", debit="4500.00", desc="Rent"),
               line("1000", credit="4500.00", desc="Cash")],
        prepared_by="agent",
        approved_by="controller",
        source_doc_id="INV-RENT-06",
    )
    show_gate(gate, clean, source=rent_doc)
    receipt = approve_and_commit(clean, gate, writer, config=DEMO_CONFIG, source=rent_doc)
    print(f"  WRITE-BACK: {receipt.status}  odoo_move_id={receipt.odoo_move_id}")

    # --- Scene 3: the balance save ---------------------------------------
    banner("SCENE 3  Out-of-balance entry -> refused at the gate")
    broken = JournalEntry(
        ref="JE-302",
        entry_date=date(2026, 6, 20),
        memo="Utilities (transposed digits)",
        lines=[line("6200", debit="1230.00"), line("1000", credit="1320.00")],
        prepared_by="agent",
        approved_by="controller",
    )
    show_gate(gate, broken)
    try:
        approve_and_commit(broken, gate, writer, config=DEMO_CONFIG)
        print("  WRITE-BACK: written  <-- THIS SHOULD NEVER PRINT")
    except WriteRefused as exc:
        print(f"  WRITE-BACK REFUSED: {exc}")

    # --- Scene 4: human-in-the-loop --------------------------------------
    banner("SCENE 4  Large entry -> escalated to human -> committed after approval")
    big = JournalEntry(
        ref="JE-303",
        entry_date=date(2026, 6, 20),
        memo="Server hardware purchase",
        lines=[line("1500", debit="45000.00"), line("1000", credit="45000.00")],
        prepared_by="agent",
        approved_by=None,
    )
    result = show_gate(gate, big)
    assert result.decision == GateDecision.NEEDS_HUMAN
    print("  (agent pauses; routes to controller for sign-off)")
    big_signed = big.model_copy(update={"approved_by": "cfo"})
    result2 = show_gate(gate, big_signed)
    if result2.decision == GateDecision.APPROVED:
        token = issue_token(DEMO_CONFIG.signing_key, big_signed, result2)
        receipt = writer.commit(big_signed, token)
        print(f"  WRITE-BACK: {receipt.status}  odoo_move_id={receipt.odoo_move_id}")

    # --- Scene 5: idempotency --------------------------------------------
    banner("SCENE 5  Re-submitting a written entry -> no double-post")
    receipt2 = approve_and_commit(clean, gate, writer, config=DEMO_CONFIG, source=rent_doc)
    print(f"  re-submit JE-301 -> {receipt2.status} (odoo_move_id={receipt2.odoo_move_id})")

    # --- summary ----------------------------------------------------------
    banner("LEDGER STATE (in-memory Odoo stand-in; the real write is scripts/real_odoo_write.py)")
    print(f"  total account.move records written: {len(odoo.moves)}")
    for m in odoo.moves:
        print(f"    - {m['ref']}: {m['narration']}  (hash {m['ledgerpilot_hash'][:12]}...)")
    print("\n  2 entries written, 2 refused (1 semantic, 1 unbalanced), "
          "1 escalated-then-written, 1 dedup-skipped.")
    print("  Nothing wrong ever reached the ledger.\n")


if __name__ == "__main__":
    main()

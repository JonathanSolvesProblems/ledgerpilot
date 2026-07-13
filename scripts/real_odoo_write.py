"""Post ONE real governed journal entry to a live Odoo, end to end.

This runs the actual project code path against a real ERP: the deterministic gate
approves the entry, an HMAC token is issued, and XmlrpcOdooClient creates and
POSTS a real account.move. Nothing is mocked.

Requires ODOO_URL / ODOO_DB / ODOO_USERNAME / ODOO_API_KEY in .env, pointing at a
live Odoo (tested on Odoo 19 / odoo.sh) that has LedgerPilot's chart of accounts.

Two scenarios are provided so the write can be demonstrated twice without the
idempotency guard deduping the second run into the first:

  rent       June office rent, $4,500  (Dr 6100 Rent / Cr 1000 Cash)
  utilities  June utilities,   $1,280  (Dr 6200 Utilities / Cr 1000 Cash)

Re-running the SAME scenario is a no-op by design: the entry's content hash is
embedded in the Odoo move, and the client searches before it creates, so the
second run returns the existing move instead of double-posting.

Run:  python scripts/real_odoo_write.py
      python scripts/real_odoo_write.py --scenario utilities
"""

from __future__ import annotations

import argparse
import socket
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledgerpilot.chart_of_accounts import default_state
from ledgerpilot.config import load_config
from ledgerpilot.gate import Gate
from ledgerpilot.models import JournalEntry, JournalLine, SourceDocument
from ledgerpilot.odoo_client import XmlrpcOdooClient
from ledgerpilot.writeback import OdooWriteBack, approve_and_commit

SCENARIOS = {
    "rent": (
        SourceDocument(
            document_id="INV-RENT-06", doc_type="invoice", gross_amount="4500.00",
            allowed_debit_accounts=["6100"], allowed_credit_accounts=["1000", "2000"],
        ),
        JournalEntry(
            ref="LP-RENT-2026-06", entry_date=date(2026, 6, 20),
            memo="June office rent (LedgerPilot governed write)",
            lines=[
                JournalLine(account_code="6100", debit="4500.00", description="Rent expense"),
                JournalLine(account_code="1000", credit="4500.00", description="Cash"),
            ],
            prepared_by="agent", approved_by="controller", source_doc_id="INV-RENT-06",
        ),
    ),
    "utilities": (
        SourceDocument(
            document_id="INV-UTIL-06", doc_type="invoice", gross_amount="1280.00",
            allowed_debit_accounts=["6200"], allowed_credit_accounts=["1000", "2000"],
        ),
        JournalEntry(
            ref="LP-UTIL-2026-06", entry_date=date(2026, 6, 24),
            memo="June utilities (LedgerPilot governed write from Alibaba Cloud ECS)",
            lines=[
                JournalLine(account_code="6200", debit="1280.00", description="Utilities expense"),
                JournalLine(account_code="1000", credit="1280.00", description="Cash"),
            ],
            prepared_by="agent", approved_by="controller", source_doc_id="INV-UTIL-06",
        ),
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="rent",
                        help="which source document to post (default: rent)")
    args = parser.parse_args()
    source, entry = SCENARIOS[args.scenario]

    cfg = load_config()
    gate = Gate(state=default_state(reference=date(2026, 6, 30)),
                approval_threshold=cfg.approval_threshold)
    client = XmlrpcOdooClient(config=cfg)
    writer = OdooWriteBack(gate=gate, config=cfg, odoo_client=client)

    print(f"scenario      : {args.scenario}  ({entry.ref}, {entry.amount})")
    print(f"running on    : {socket.gethostname()}")

    receipt = approve_and_commit(entry, gate, writer, config=cfg, source=source)
    print("write status  :", receipt.status)
    print("odoo_move_id  :", receipt.odoo_move_id)
    print("entry_hash    :", receipt.entry_hash[:16])

    move = client._kw("account.move", "read", [[receipt.odoo_move_id]],
                      {"fields": ["name", "state", "ref", "amount_total", "date"]})
    print("posted move   :", move)


if __name__ == "__main__":
    main()

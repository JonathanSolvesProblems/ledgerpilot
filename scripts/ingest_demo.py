"""From a scanned invoice image to a governed posting decision, end to end.

This is the whole thesis on one document, with nothing hand-fed:

    a PNG of a scanned invoice
      -> qwen3-vl-plus reads the pixels          (Alibaba Cloud Model Studio)
      -> the extracted record drives the planner (function calling, real chart lookup)
      -> the deterministic gate decides          (8 pure rules, no LLM)

Nothing about the invoice is hard-coded here. The amount, the document id, the date
and the line items all come out of the image. The only thing supplied alongside is
the *posting policy* (which accounts an invoice of this kind may touch), which is
deliberately NOT on the invoice: a vendor does not get to say which account you book
their bill to. That comes from the organisation's own mapping rules, and it is what
the gate reconciles against.

Two runs, to show the vision layer is load-bearing rather than decorative:

  1. The planner is told what the vision model actually read. It books rent to Rent
     expense, and the gate approves.
  2. The same extracted document, but the planner is nudged to book it to Bank fees.
     It balances and every account is real, so a trial balance passes it. The gate
     reconciles it against the document Qwen-VL just read, and refuses.

Run:  python scripts/ingest_demo.py
      python scripts/ingest_demo.py --image samples/invoice_rent_june_2026.png
"""

from __future__ import annotations

import argparse
import base64
import io
import mimetypes
import sys
from datetime import date
from pathlib import Path

# The extracted line items carry the punctuation on the invoice (an em-dash in
# "Office rent - Suite 400", say), which the Windows cp1252 console cannot encode,
# so force UTF-8 on stdout to keep this recordable in any shell.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (ValueError, io.UnsupportedOperation):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledgerpilot.chart_of_accounts import default_state
from ledgerpilot.config import load_config
from ledgerpilot.gate import Gate
from ledgerpilot.ingest import DocumentIngestor
from ledgerpilot.models import GateDecision, SourceDocument
from ledgerpilot.planner import Planner

DEFAULT_IMAGE = Path(__file__).resolve().parent.parent / "samples" / "invoice_rent_june_2026.png"

# The posting policy for a rent invoice. This is the organisation's rule, not the
# vendor's: rent belongs in Rent expense (6100), settled from Cash (1000) or
# Accounts payable (2000). The gate enforces it against whatever the model proposes.
RENT_POLICY = {"debit": ["6100"], "credit": ["1000", "2000"]}


def data_uri(path: Path) -> str:
    """Inline the image so no bucket or public URL is needed to reproduce this."""
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def banner(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def show_gate(gate: Gate, entry, source):
    result = gate.evaluate(entry, source)
    for c in result.checks:
        print(f"    [{'ok ' if c.passed else 'XX '}] {c.check:<20} {c.detail}")
    print(f"  --> GATE DECISION: {result.decision.value.upper()}")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    args = ap.parse_args()
    if not args.image.exists():
        sys.exit(f"no such image: {args.image}")

    cfg = load_config()
    state = default_state(reference=date(2026, 6, 30))
    gate = Gate(state=state, approval_threshold=cfg.approval_threshold)

    banner("STEP 1  qwen3-vl-plus reads the scanned invoice (nothing is hard-coded)")
    print(f"  image        : {args.image.name} ({args.image.stat().st_size/1024:.0f} KB)")
    print(f"  vision model : {cfg.vision_model}  (Alibaba Cloud Model Studio)")
    doc = DocumentIngestor(config=cfg).extract(data_uri(args.image))
    print(f"\n  doc_type     : {doc.doc_type}")
    print(f"  document_id  : {doc.document_id}")
    print(f"  counterparty : {doc.counterparty}")
    print(f"  date         : {doc.date}")
    print(f"  net / tax    : {doc.net_amount} / {doc.tax_amount} {doc.currency}")
    print(f"  gross_amount : {doc.gross_amount}")
    for li in doc.line_items:
        print(f"    line       : {li.get('description','')} = {li.get('amount','')}")
    print(f"\n  planner task derived from the image:\n    {doc.to_task()}")

    # The document facts come from the image; the posting policy comes from us.
    source = SourceDocument(
        document_id=doc.document_id or "INV-RENT-06",
        doc_type=doc.doc_type or "invoice",
        gross_amount=doc.gross_amount,
        allowed_debit_accounts=RENT_POLICY["debit"],
        allowed_credit_accounts=RENT_POLICY["credit"],
    )

    planner = Planner(config=cfg)

    banner("STEP 2  The planner drafts an entry from what the vision model read")
    proposal = planner.propose(doc.to_task() + " Pay from the bank account.", state)
    entry = proposal.entry.model_copy(update={
        "ref": f"VL-{source.document_id}", "approved_by": "controller",
        "source_doc_id": source.document_id,
    })
    print(f"  proposed: {entry.ref}  amount={entry.amount}")
    for ln in entry.lines:
        side = f"Dr {ln.debit}" if ln.debit > 0 else f"Cr {ln.credit}"
        print(f"    {ln.account_code}  {side:<16} {ln.description}")
    print()
    result = show_gate(gate, entry, source)

    banner("STEP 3  Same invoice, planner nudged to the WRONG account -> refused")
    print("  A trial balance passes this: it balances and every account is real.")
    print("  Only reconciliation against the document Qwen-VL just read catches it.\n")
    bad = planner.propose(
        doc.to_task() + " Book this to Bank fees (6900), paid from the bank account.",
        state,
    )
    bad_entry = bad.entry.model_copy(update={
        "ref": f"VL-{source.document_id}-BAD", "approved_by": "controller",
        "source_doc_id": source.document_id,
    })
    print(f"  proposed: {bad_entry.ref}  amount={bad_entry.amount}")
    for ln in bad_entry.lines:
        side = f"Dr {ln.debit}" if ln.debit > 0 else f"Cr {ln.credit}"
        print(f"    {ln.account_code}  {side:<16} {ln.description}")
    print()
    bad_result = show_gate(gate, bad_entry, source)

    banner("RESULT")
    print(f"  The amount the gate reconciled against ({source.gross_amount}) was never")
    print(f"  typed by a human. Qwen-VL read it off the invoice image.")
    print(f"    correct posting -> {result.decision.value}")
    print(f"    wrong posting   -> {bad_result.decision.value}")
    if result.decision == GateDecision.APPROVED and bad_result.decision == GateDecision.REJECTED:
        print("\n  Pixels in, governed decision out. The vision layer feeds the same gate.")


if __name__ == "__main__":
    main()

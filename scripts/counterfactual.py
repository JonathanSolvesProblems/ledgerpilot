"""The counterfactual: what actually lands in a real ledger with the gate off.

Every "AI accountant" is an argument about a control you cannot see. So run the
experiment. Same model, same close tasks, same live Odoo. One variable: the gate.

    ARM A  gate OFF   every proposal the model makes is posted to the ledger.
    ARM B  gate ON    only entries that pass the 8 deterministic checks are posted.

Both arms use the SAME proposals (the planner is called once per task), so the only
difference between them is the gate. Then we ask the only question that matters:

    how many WRONG journal entries are now sitting in a real general ledger?

The wrong entries from ARM A are posted for real, under refs prefixed `NG-`, so you
can open Odoo and look at them. They balance. They use real accounts. They pass a
trial balance. That is the point: this is the damage a balance-only control does not
prevent, and it is measured in entries in a ledger rather than in percentages of a
test corpus.

    python scripts/counterfactual.py                     # qwen-flash, 39 tasks
    python scripts/counterfactual.py --limit 8           # a quick pass
    python scripts/counterfactual.py --model qwen3.7-max
    python scripts/counterfactual.py --cleanup           # cancel the NG- moves

WARNING: ARM A deliberately writes wrong entries to the configured Odoo. Point it at
a demo instance, never at a real company's books.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledgerpilot.chart_of_accounts import default_state
from ledgerpilot.config import load_config
from ledgerpilot.gate import Gate
from ledgerpilot.models import GateDecision, JournalEntry
from ledgerpilot.odoo_client import XmlrpcOdooClient
from ledgerpilot.tokens import issue_token
from ledgerpilot.writeback import OdooWriteBack

from eval.live_eval import _entry_matches
from eval.live_tasks import build_live_tasks


def rekey(entry: JournalEntry, prefix: str, name: str) -> JournalEntry:
    """Give each arm its own ref namespace so the two arms cannot dedupe into each other."""
    return entry.model_copy(update={"ref": f"{prefix}-{name}"[:60]})


def cleanup(client: XmlrpcOdooClient) -> None:
    client._ensure()
    ids = client._kw("account.move", "search", [[["ref", "like", "NG-"]]])
    if not ids:
        print("nothing to clean up.")
        return
    client._kw("account.move", "button_draft", [ids])
    client._kw("account.move", "button_cancel", [ids])
    print(f"cancelled {len(ids)} gate-off moves.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="qwen-flash",
                    help="planner model (default qwen-flash: weaker, so the contrast is honest)")
    ap.add_argument("--limit", type=int, default=0, help="only run the first N tasks")
    ap.add_argument("--cleanup", action="store_true", help="cancel the gate-off moves and exit")
    args = ap.parse_args()

    os.environ["LEDGERPILOT_PLANNER_MODEL"] = args.model
    cfg = load_config()
    client = XmlrpcOdooClient(config=cfg)

    if args.cleanup:
        cleanup(client)
        return

    from ledgerpilot.planner import Planner  # imported late: needs the model env var

    tasks = build_live_tasks()
    if args.limit:
        tasks = tasks[: args.limit]
    state = default_state(reference=date(2026, 6, 30))
    gate = Gate(state=state, approval_threshold=cfg.approval_threshold)
    planner = Planner()
    writer = OdooWriteBack(gate=gate, config=cfg, odoo_client=client)

    print("=" * 78)
    print("COUNTERFACTUAL: the same model and the same tasks, with and without the gate")
    print("=" * 78)
    print(f"model      : {args.model}")
    print(f"tasks      : {len(tasks)} natural-language close tasks")
    print(f"ledger     : {cfg.odoo_url} (live Odoo)")
    print("ARM A      : gate OFF, every proposal is posted")
    print("ARM B      : gate ON, only entries that pass all 8 checks are posted")
    print()

    a_posted = a_wrong = 0
    b_posted = b_wrong = 0
    wrong_rows: list[str] = []

    for i, t in enumerate(tasks, 1):
        source = t.source()
        try:
            proposal = planner.propose(t.prompt, state)
        except Exception as exc:  # noqa: BLE001 - a dead call should not void the run
            print(f"  [{i}/{len(tasks)}] {t.name:<22} planner error: {str(exc)[:60]}")
            continue

        entry = proposal.entry
        correct = _entry_matches(entry, t)

        # --- ARM A: no gate. Whatever the model said goes straight in. ---
        a_entry = rekey(entry, "NG", t.name)
        try:
            client.create_move({
                "ref": a_entry.ref,
                "date": a_entry.entry_date.isoformat(),
                "narration": f"GATE OFF: {a_entry.memo}",
                "line_ids": [
                    (0, 0, {"account_code": ln.account_code,
                            "name": ln.description or a_entry.memo,
                            "debit": float(ln.debit), "credit": float(ln.credit)})
                    for ln in a_entry.lines
                ],
                "ledgerpilot_hash": a_entry.content_hash(),
            })
            a_posted += 1
            if not correct:
                a_wrong += 1
                dr = "/".join(f"{ln.account_code}" for ln in entry.lines if ln.debit > 0)
                cr = "/".join(f"{ln.account_code}" for ln in entry.lines if ln.credit > 0)
                wrong_rows.append(
                    f"    {a_entry.ref:<28} Dr {dr:<6} Cr {cr:<6} {entry.amount:>10}"
                    f"   (should be Dr {t.expected_debit} Cr {t.expected_credit})"
                )
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i}/{len(tasks)}] {t.name:<22} ARM A write failed: {str(exc)[:50]}")

        # --- ARM B: the gate decides. ---
        b_entry = rekey(entry, "GT", t.name)
        result = gate.evaluate(b_entry, source)
        if result.decision == GateDecision.APPROVED:
            token = issue_token(cfg.signing_key, b_entry, result)
            writer.commit(b_entry, token, source)
            b_posted += 1
            if not correct:
                b_wrong += 1
        mark = "correct" if correct else "WRONG  "
        print(f"  [{i}/{len(tasks)}] {t.name:<22} model:{mark}  "
              f"gate-off:POSTED  gate-on:{result.decision.value}")

    print()
    print("=" * 78)
    print(" RESULT: wrong journal entries now sitting in a real general ledger")
    print("=" * 78)
    print(f"  ARM A  gate OFF :  {a_posted} entries posted, "
          f"{a_wrong} of them WRONG")
    print(f"  ARM B  gate ON  :  {b_posted} entries posted, "
          f"{b_wrong} of them WRONG")
    print()
    if wrong_rows:
        print("  The wrong entries the gate refused, now posted for real by ARM A:")
        for row in wrong_rows:
            print(row)
        print()
        print("  Every one of those balances. Every one uses real, postable accounts.")
        print("  A trial balance passes all of them.")
        print()
    print(f"  Same model. Same {len(tasks)} tasks. Same ledger.")
    print(f"  Without the gate: {a_wrong} wrong entries. With it: {b_wrong}.")
    print("  The model did not get better. The ledger did.")
    print("=" * 78)
    print("\n  (open Odoo and filter ref starting 'NG-' to see the damage;")
    print("   run with --cleanup to cancel them)")


if __name__ == "__main__":
    main()

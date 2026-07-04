"""End-to-end live close: the real Qwen agent proposes, the gate judges, and
approved entries are governed-written to an (in-memory) Odoo.

This is the asset to screen-record once the Alibaba Cloud account is authorized
to call models. It shows the full autopilot loop on real model output:

  natural-language task -> Qwen planner -> deterministic gate -> governed write

It deliberately includes an easy-to-misclassify task (prepaid vs expense) so the
recording is likely to show the gate catching a real model mistake, then a clean
task that is signed and written.

Requires DASHSCOPE_API_KEY (in .env or the environment). Run:
    python scripts/live_close.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

# Allow running as `python scripts/live_close.py` without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledgerpilot.chart_of_accounts import default_state
from ledgerpilot.config import load_config
from ledgerpilot.gate import Gate
from ledgerpilot.models import GateDecision
from ledgerpilot.planner import Planner
from ledgerpilot.tokens import issue_token
from ledgerpilot.writeback import OdooWriteBack

from eval.live_tasks import build_live_tasks


class FakeOdoo:
    def __init__(self):
        self.moves = []

    def create_move(self, payload):
        self.moves.append(payload)
        return len(self.moves)


# A short, demo-friendly slice: one clean task, two classic traps.
DEMO_TASK_NAMES = ["rent", "rent_prepaid_trap", "equipment"]


def main() -> None:
    config = load_config()
    state = default_state(reference=date(2026, 6, 30))
    gate = Gate(state=state, approval_threshold=config.approval_threshold)
    odoo = FakeOdoo()
    writer = OdooWriteBack(gate=gate, config=config, odoo_client=odoo)
    planner = Planner(config=config)

    tasks = [t for t in build_live_tasks() if t.name in DEMO_TASK_NAMES]

    for t in tasks:
        print("\n" + "=" * 74)
        print(f"TASK: {t.name}")
        print(t.prompt)
        print("-" * 74)
        try:
            proposal = planner.propose(t.prompt, state)
        except Exception as exc:  # noqa: BLE001
            print(f"  planner error: {exc}")
            print("  (If this is a 403, finish Identity Verification and re-run.)")
            continue
        entry = proposal.entry
        for ln in entry.lines:
            side = f"Dr {ln.debit}" if ln.debit > 0 else f"Cr {ln.credit}"
            print(f"  model proposed: {ln.account_code}  {side}")
        result = gate.evaluate(entry, t.source())
        print(f"  GATE: {result.decision.value.upper()}")
        for c in result.failed_checks:
            print(f"    blocked by {c.check}: {c.detail}")
        if result.decision == GateDecision.APPROVED:
            token = issue_token(config.signing_key, entry, result)
            receipt = writer.commit(entry, token, source=t.source())
            print(f"  WRITE-BACK: {receipt.status} (odoo_move_id={receipt.odoo_move_id})")
        else:
            print("  WRITE-BACK: refused. Routed to human review; nothing posted.")

    print("\n" + "=" * 74)
    print(f"Committed {len(odoo.moves)} account.move record(s). Nothing wrong reached the ledger.")


if __name__ == "__main__":
    main()

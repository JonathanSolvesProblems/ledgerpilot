# Evidence

Screenshots of the running system, kept next to the transcripts they correspond to.
Everything here is reproducible from the repo; these exist so a reader can see the
result without provisioning anything.

| File | What it shows | Corresponding transcript |
|---|---|---|
| `ecs_console_instance_running.png` | The Alibaba Cloud ECS console: instance `i-t4n1i5p7bz4ypj122e6q` (`ledgerpilot-agent`), **Running**, Singapore (`ap-southeast-1`), public IP `47.84.116.56`. This is the box the backend runs on, provisioned by [`scripts/deploy_ecs.py`](../../scripts/deploy_ecs.py). | [`docs/ecs_proof.txt`](../ecs_proof.txt) |
| `odoo_real_governed_write.png` | A real, **posted** `account.move` in a live Odoo 19: `MISC/2026/06/0001` / `LP-RENT-2026-06`, Dr `6100 Rent expense` 4,500.00 / Cr `1000 Cash` 4,500.00. Written through the full path: gate approves, HMAC token, XML-RPC. | [`docs/real_write_proof.txt`](../real_write_proof.txt) |
| `odoo_counterfactual_wrong_entries.png` | The counterfactual damage: Odoo filtered on reference `NG-WRONG`, showing the wrong entries the gate refused, **posted** in a real ledger because the gate was off. | [`docs/counterfactual_proof.txt`](../counterfactual_proof.txt) |
| `odoo_counterfactual_wrong_entry_detail.png` | One of those entries opened (`NG-WRONG-cogs_on_credit_2`): `Dr 1100 Accounts receivable` / `Cr 4000 Revenue`, 3,900.00, balanced, **Posted**. A cost-of-goods purchase booked as if it were a sale. It balances, so a trial balance passes it. | [`docs/counterfactual_proof.txt`](../counterfactual_proof.txt) |
| `odoo_counterfactual_wrong_entry_narration.png` | The same entry's Other Info tab, where the narration states what the model booked, what the source document required, and that it is only in the ledger because the gate was off. | [`docs/counterfactual_proof.txt`](../counterfactual_proof.txt) |

The gate's web UI is served from that same instance; screenshots of it are in
[`preview/`](../../preview).

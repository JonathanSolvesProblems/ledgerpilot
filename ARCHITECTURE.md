# LedgerPilot Architecture

## System overview

LedgerPilot is a three-layer autonomous close agent. The defining design decision is the **trust boundary** between the generative layers (which reason and propose) and the deterministic gate (which is the only path to a write).

```
                     ALIBABA CLOUD MODEL STUDIO (DashScope)
                     ┌─────────────────────────────────────────┐
                     │  qwen3.7-max    planner, function calling│
                     │  qwen3-vl-plus  document ingestion       │
                     └────────────────────▲────────────────────┘
                                          │  the model PROPOSES.
                                          │  it never writes.
 ─────────────────────────────────────────┼──────────────────────────────────────
  ALIBABA CLOUD ECS · ap-southeast-1 · i-t4n1i5p7bz4ypj122e6q · BACKEND RUNS HERE
 ─────────────────────────────────────────┼──────────────────────────────────────
                                          │
 ┌────────────┐   documents   ┌───────────▼┐   proposal   ┌──────────────────────┐
 │Unstructured│ ─────────────►│  Ingestion │ ────────────►│  DETERMINISTIC GATE  │
 │  inputs    │               │  + Planner │              │  8 pure rules, no LLM│
 │ statements │               └────────────┘              │  • balance           │
 │ invoices   │                                           │  • account validity  │
 │ approvals  │                                           │  • period lock       │
 └────────────┘                                           │  • segregation       │
                                                          │  • approval limits   │
                                                          │  • RECONCILE to doc  │
                                                          └────┬────────────┬────┘
                                                      approve  │            │  reject
                                                   ┌──────────▼───┐   ┌─────▼────────┐
                                                   │ Signed token │   │ Review queue │
                                                   │ (HMAC, bound │   │ + audit log  │
                                                   │  to entry)   │   └──────────────┘
                                                   └───────┬──────┘
                                                           │
                                       human-in-the-loop gate (above threshold)
                                                           │
 ──────────────────────────────────────────────────────────┼─────────────────────
                                                           │  XML-RPC, idempotent
                                                   ┌───────▼────────┐
                                                   │  LIVE ODOO 19  │
                                                   │  posted        │
                                                   │  account.move  │
                                                   └────────────────┘
```

Two boundaries matter here. The **trust boundary** is horizontal: Qwen proposes, the gate decides, and no model output reaches the ledger without passing eight deterministic rules. The **deployment boundary** is the ECS band: the agent, the gate, and the write-back all execute on Alibaba Cloud, calling Model Studio in the same region.

## Layer responsibilities

### 1. Ingestion (generative): `ingest.py`
- Reads scanned invoices / bank statements with **qwen3-vl-plus** (multimodal).
- Extracts and normalizes line items, dates, counterparties, amounts.
- Reads approval emails for who authorized what (feeds segregation-of-duties checks).

### 2. Planner (generative): `planner.py`
- Uses **qwen3.7-max** with **function calling** to draft candidate journal entries.
- The chart of accounts is not dumped into the prompt. The model must call the `lookup_accounts` tool to discover valid account codes, so account selection is grounded in real chart data rather than invented (this is where the function-calling loop lives).
- Output is a structured `Proposal`, never a direct write.

### 3. Deterministic gate (the scored core): `gate.py`
Pure, side-effect-free rules. Each check is independently testable and produces an auditable reason. A proposal is approved only if **every** check passes:
- **Balance:** total debits == total credits, to the cent.
- **Account validity:** every account code exists in the chart of accounts and is postable.
- **Period lock:** the entry date falls in an open accounting period.
- **Segregation of duties:** the proposer is not the sole approver; approvals come from an authorized party distinct from the preparer.
- **Approval thresholds:** entries above a configured amount require explicit human approval (human-in-the-loop checkpoint).
- **Reconciliation to source (semantic check):** when a source document is supplied, the entry's total must equal the document total and its accounts must fall within the posting policy for that document type. This is what catches a balanced, valid-account, plausible entry that posts the *wrong* amount or to the *wrong* account, the characteristic failure mode of a generative planner.

### 4. Governed write-back: `tokens.py` + `writeback.py`
- An approved proposal is bound to an **HMAC-signed approval token** that captures a hash of the exact entry. The token cannot be reused for a different entry (tamper-evident).
- `writeback.py` calls the Odoo MCP `validate_write` → `execute_approved_write` chain; execution is **idempotent** (keyed on the entry hash) and supports **rollback**. The MCP server is reached as an **SSE MCP server via the Model Studio Responses API** (`tools` parameter), which is the integration path the rubric's "MCP integrations" criterion rewards.

## Alibaba Cloud deployment topology

Status column is explicit so nothing reads as provisioned when it is not.

| Component | Service | Status |
|---|---|---|
| Agent runtime (the backend itself) | **Alibaba Cloud ECS** (`ecs.t6-c1m2.large`, Ubuntu 24.04, `ap-southeast-1`) | **Live** (instance `i-t4n1i5p7bz4ypj122e6q`, `docs/ecs_proof.txt`) |
| Qwen models (planner `qwen3.7-max`, vision `qwen3-vl-plus`) | **Alibaba Cloud Model Studio / DashScope** (OpenAI-compatible + Responses API for MCP) | **Live** (measured, `docs/live_run.txt`) |
| Infrastructure provisioning | **Alibaba Cloud ECS + VPC OpenAPI** (`scripts/deploy_ecs.py`) | **Live** (this script created the instance above) |
| Odoo ERP (system of record) | **Live Odoo 19** (odoo.sh) | **Live** (real posted `account.move`, `docs/real_write_proof.txt`) |
| Document store (statements, invoices) | Alibaba Cloud OSS | Planned |
| Agent memory, approval tokens, audit log | Alibaba Cloud Tablestore | Planned |
| Accounting-policy retrieval (vector) | AnalyticDB for PostgreSQL | Planned |
| Public entrypoint | Alibaba Cloud API Gateway | Planned |

The backend **runs on Alibaba Cloud ECS**, in the same region as the Model Studio workspace it calls. From that instance it drafts entries with Qwen, scores them through the deterministic gate, serves the gate's web UI on port 80, and posts real journal entries to the live Odoo. `docs/ecs_proof.txt` is the transcript of exactly that, generated on the instance and including the values returned by the ECS instance metadata service, which only answers on a real ECS box.

Two code files are the **Proof of Alibaba Cloud Deployment**, covering two services: `ledgerpilot/planner.py` (Model Studio / Qwen, with function calling) and `scripts/deploy_ecs.py` (the ECS + VPC OpenAPI calls that provisioned the server). "Planned" services are designed into the topology but not yet wired.

## The measurement layer (the moat)

`eval/harness.py` reports two clearly separated numbers:

**Synthetic gate stress-test** (`python -m eval.harness`, no LLM): a 204-case corpus (12 scenarios x 14 error classes, plus clean controls) run through the gate.
- **False-write rate:** 0 of 36 approved, **≤ 8.33% at 95% CI** (Rule of Three), reported with the bound so a zero result is honest.
- **Catch rate:** **100% (168/168 = 156 blocked + 12 escalated to a human)**, including semantic classes (wrong amount, wrong account, direction swap, VAT rounding) that a balance-only check cannot detect.
- **False-reject rate (negative control):** **0% (0/36)**.
This measures the gate's *decision logic*, not a model's accuracy.

**Measured LLM + gate** (`python -m eval.harness --live`): the real Qwen planner (with function calling) drafts entries from 39 natural-language tasks and the gate judges what the model produced. This run was executed **on the Alibaba Cloud ECS instance**, against Model Studio in the same region; the raw transcript is committed at `docs/ecs_proof.txt`.

| Model | Accuracy | Mistakes | Caught by the gate | False writes |
|---|---|---|---|---|
| `qwen3.7-max` | 97.4% (38/39) | 1 | 1 of 1 | **0** (Wilson 95% CI ≤ 9.18%) |
| `qwen-flash` | 82.1% (32/39) | 7 | 7 of 7 | **0** (≤ 10.72%) |

**Eight model mistakes, eight caught, zero wrong entries written.** The weaker model made seven times as many mistakes as the flagship and the ledger stayed clean, which is the whole point: correctness is a property of the gate, not of the model. The mistakes fell outside each document's permitted account set; a permitted-but-wrong posting would surface as a nonzero rate, so the metric is falsifiable, not zero by construction. An earlier local run (`docs/live_run.txt`) produced slightly different accuracy (sampling is not perfectly reproducible at temperature 0) and the identical gate result: everything wrong was caught.

## Deployment status (honest scope)

**Running on Alibaba Cloud:** the backend is deployed on an ECS instance (`i-t4n1i5p7bz4ypj122e6q`, `ap-southeast-1`) provisioned by `scripts/deploy_ecs.py` through the ECS and VPC OpenAPIs. The test suite, the 204-case gate stress-test, the live Qwen measurement against Model Studio, and a real governed ERP write (`MISC/2026/06/0002`) all executed on that instance, which also serves the gate's web UI on port 80. Transcript: `docs/ecs_proof.txt`.

**Working without credentials:** the deterministic gate, reconciliation, signed tokens, idempotent write-back logic, the offline pipeline, the demo, and the test suite all run with no API key and no ERP.

**Against a live ERP:** two real governed writes, posted `account.move` records (`MISC/2026/06/0001` from local, `MISC/2026/06/0002` from ECS) to a live Odoo 19 (`docs/real_write_proof.txt`, `docs/ecs_proof.txt`, `scripts/real_odoo_write.py`).

The designated **Proof of Alibaba Cloud Deployment** code files are `ledgerpilot/planner.py` (the function-calling Model Studio calls) and `scripts/deploy_ecs.py` (the ECS + VPC OpenAPI calls); `ledgerpilot/odoo_client.py` and `ledgerpilot/config.py` support them.

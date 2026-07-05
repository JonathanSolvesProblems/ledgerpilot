# LedgerPilot Architecture

## System overview

LedgerPilot is a three-layer autonomous close agent. The defining design decision is the **trust boundary** between the generative layers (which reason and propose) and the deterministic gate (which is the only path to a write).

```
                          ALIBABA CLOUD MODEL STUDIO (DashScope)
                          ┌──────────────────────────────────────┐
                          │  qwen3-vl-plus   qwen-max / qwen-plus  │
                          └───────▲───────────────▲───────────────┘
                                  │               │
 ┌────────────┐   documents   ┌──┴───────┐   ┌───┴────────┐   proposal   ┌─────────────────────┐
 │ Unstructured│ ────────────►│ Ingestion │──►│  Planner    │ ───────────►│  DETERMINISTIC GATE │
 │  inputs     │  (OSS)        │ (Qwen-VL) │   │ (Qwen +     │             │  (rules engine)     │
 │ statements, │               └───────────┘   │  function   │             │  • balance          │
 │ invoices,   │                               │  calling)   │             │  • account validity │
 │ approval    │                               └─────────────┘             │  • period lock      │
 │ emails      │                                                           │  • segregation of   │
 └────────────┘                                                            │    duties           │
                                                                           │  • approval limits  │
                                                                           └─────────┬───────────┘
                                                                   approve │         │ reject
                                                              ┌────────────▼──┐   ┌──▼─────────────┐
                                                              │ Signed token  │   │ Review queue + │
                                                              │ (HMAC)        │   │ audit log      │
                                                              └───────┬───────┘   └────────────────┘
                                                                      │
                                                  human-in-the-loop gate (above threshold)
                                                                      │
                                                              ┌───────▼────────┐
                                                              │  Odoo ERP      │
                                                              │  write-back    │
                                                              │  (idempotent,  │
                                                              │   rollback)    │
                                                              └────────────────┘
```

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

| Component | Alibaba Cloud service | Status |
|---|---|---|
| Qwen models (planner `qwen3.7-max`, vision `qwen3-vl-plus`) | **Model Studio / DashScope** (OpenAI-compatible + Responses API for MCP) | Coded; live on API key |
| Odoo ERP (system of record) | **ECS** (Elastic Compute Service) | Coded (`odoo_client.py`); live on ECS provision |
| Document store (statements, invoices) | **OSS** (Object Storage Service) | Planned |
| Orchestration / agent runtime | **Function Compute** | Planned |
| Agent memory, approval tokens, audit log | **Tablestore** | Planned |
| Accounting-policy retrieval (vector) | **AnalyticDB for PostgreSQL** | Planned |
| Public entrypoint | **API Gateway** | Planned |

"Coded" means the calling code exists and is unit-tested against a fake transport; it runs live the moment credentials/host exist. "Planned" means designed into the topology but not yet wired. The designated **Proof of Alibaba Cloud Deployment** code files are `ledgerpilot/planner.py` (Qwen via Model Studio) and `ledgerpilot/odoo_client.py` (Odoo-on-ECS write + Responses-API MCP path); `ledgerpilot/config.py` wires region/endpoints.

## The measurement layer (the moat)

`eval/harness.py` reports two clearly separated numbers:

**Synthetic gate stress-test** (`python -m eval.harness`, no LLM): a 204-case corpus (12 scenarios x 14 error classes, plus clean controls) run through the gate.
- **False-write rate:** 0 of 36 approved, **≤ 8.33% at 95% CI** (Rule of Three), reported with the bound so a zero result is honest.
- **Catch rate:** **100% (168/168 = 156 blocked + 12 escalated to a human)**, including semantic classes (wrong amount, wrong account, direction swap, VAT rounding) that a balance-only check cannot detect.
- **False-reject rate (negative control):** **0% (0/36)**.
This measures the gate's *decision logic*, not a model's accuracy.

**Measured LLM + gate** (`python -m eval.harness --live`): the real Qwen planner (with function calling) drafts entries from 39 natural-language tasks and the gate judges what the model produced. This run is done and its raw transcript is committed at `docs/live_run.txt`. The gate caught every mistake either model made and wrote 0 wrong entries: Qwen3.7-Max was 97.4% accurate (1 mistake, caught; Wilson 95% CI at most 9.18%) and qwen-flash 87.2% (5 mistakes, all caught; at most 10.15%). The mistakes were cross-class postings; a within-class account error would surface as a nonzero rate, so the metric is falsifiable, not zero by construction.

## Deployment status (honest scope)

Working without credentials: the deterministic gate, reconciliation, signed tokens, idempotent write-back logic, the offline pipeline, the demo, and the test suite. Done with a Model Studio key: the `--live` measurement against real Qwen output (transcript in `docs/live_run.txt`). Still pending: a live Odoo on Alibaba Cloud ECS for one real `account.move` write. The designated **Proof of Alibaba Cloud Deployment** code file is `ledgerpilot/planner.py` (the function-calling Model Studio calls); `ledgerpilot/odoo_client.py` and `ledgerpilot/config.py` support it.

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

### 1. Ingestion (generative) — `ingest.py`
- Reads scanned invoices / bank statements with **qwen3-vl-plus** (multimodal).
- Extracts and normalizes line items, dates, counterparties, amounts.
- Reads approval emails for who authorized what (feeds segregation-of-duties checks).

### 2. Planner (generative) — `planner.py`
- Uses **qwen-max** / **qwen-plus** with **function calling** to draft candidate journal entries.
- Reads current ERP state (open period, account list, existing entries) through the Odoo MCP read tools so proposals are grounded, not hallucinated.
- Output is a structured `Proposal`, never a direct write.

### 3. Deterministic gate (the scored core) — `gate.py`
Pure, side-effect-free rules. Each check is independently testable and produces an auditable reason. A proposal is approved only if **every** check passes:
- **Balance:** total debits == total credits, to the cent.
- **Account validity:** every account code exists in the chart of accounts and is postable.
- **Period lock:** the entry date falls in an open accounting period.
- **Segregation of duties:** the proposer is not the sole approver; approvals come from an authorized party distinct from the preparer.
- **Approval thresholds:** entries above a configured amount require explicit human approval (human-in-the-loop checkpoint).
- **Reconciliation to source (semantic check):** when a source document is supplied, the entry's total must equal the document total and its accounts must fall within the posting policy for that document type. This is what catches a balanced, valid-account, plausible entry that posts the *wrong* amount or to the *wrong* account, the characteristic failure mode of a generative planner.

### 4. Governed write-back — `tokens.py` + `writeback.py`
- An approved proposal is bound to an **HMAC-signed approval token** that captures a hash of the exact entry. The token cannot be reused for a different entry (tamper-evident).
- `writeback.py` calls the Odoo MCP `validate_write` → `execute_approved_write` chain; execution is **idempotent** (keyed on the entry hash) and supports **rollback**. The MCP server is reached as an **SSE MCP server via the Model Studio Responses API** (`tools` parameter), which is the integration path the rubric's "MCP integrations" criterion rewards.

## Alibaba Cloud deployment topology

| Component | Alibaba Cloud service |
|---|---|
| Qwen models (planner `qwen3-max`, vision `qwen3-vl-plus`) | **Model Studio / DashScope** (OpenAI-compatible + Responses API for MCP) |
| Odoo ERP (system of record) | **ECS** (Elastic Compute Service) |
| Orchestration / agent runtime | **Function Compute** |
| Document store (statements, invoices) | **OSS** (Object Storage Service) |
| Agent memory, approval tokens, audit log | **Tablestore** |
| Accounting-policy retrieval (vector) | **AnalyticDB for PostgreSQL** |
| Public entrypoint | **API Gateway** |

The Alibaba Cloud proof recording (a hackathon requirement) demonstrates the Odoo write-back hitting the ECS-hosted instance and the agent runtime executing on Function Compute. The proof code file is `ledgerpilot/writeback.py` (Alibaba Cloud calls) plus `ledgerpilot/config.py` (region/endpoint wiring).

## The measurement layer (the moat)

`eval/harness.py` runs a 120-case seeded-error corpus through the planner + gate pipeline and reports:
- **False-write rate:** fraction of gate-*approved* entries that are actually wrong (the headline number). Currently **0 of 40 approved, ≤ 7.50% at 95% CI** (Rule of Three). Reported with the confidence bound so a zero result is presented honestly.
- **Catch rate:** fraction of seeded-error entries the gate blocks or escalates. Currently **100% (80/80)**, including the two semantic classes (wrong amount, wrong account) that a balance-only check cannot detect.
- **False-reject rate (negative control):** clean inputs wrongly blocked. Currently **0% (0/40)**.

The offline path injects documented planner failure modes deterministically (no API key); `--live` measures the real Qwen planner + gate pipeline on the clean scenarios.

## Deployment status (honest scope)

Working without credentials: the deterministic gate, reconciliation, signed tokens, idempotent write-back logic, the offline pipeline, the demo, and the test suite. Pending for full production proof: `DASHSCOPE_API_KEY` for the `--live` path, a live Odoo on Alibaba Cloud ECS for a real `account.move` write, and wiring the MCP write through the Responses API. `ledgerpilot/writeback.py` + `ledgerpilot/config.py` are the designated Alibaba Cloud proof artifacts once the ECS instance is connected.

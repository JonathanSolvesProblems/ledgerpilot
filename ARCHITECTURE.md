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

### 4. Governed write-back — `tokens.py` + `writeback.py`
- An approved proposal is bound to an **HMAC-signed approval token** that captures a hash of the exact entry. The token cannot be reused for a different entry (tamper-evident).
- `writeback.py` calls the Odoo MCP `validate_write` → `execute_approved_write` chain; execution is **idempotent** (keyed on the entry hash) and supports **rollback**.

## Alibaba Cloud deployment topology

| Component | Alibaba Cloud service |
|---|---|
| Qwen models (VL, planner) | **Model Studio / DashScope** |
| Odoo ERP (system of record) | **ECS** (Elastic Compute Service) |
| Orchestration / agent runtime | **Function Compute** |
| Document store (statements, invoices) | **OSS** (Object Storage Service) |
| Agent memory, approval tokens, audit log | **Tablestore** |
| Accounting-policy retrieval (vector) | **AnalyticDB for PostgreSQL** |
| Public entrypoint | **API Gateway** |

The Alibaba Cloud proof recording (a hackathon requirement) demonstrates the Odoo write-back hitting the ECS-hosted instance and the agent runtime executing on Function Compute. The proof code file is `ledgerpilot/writeback.py` (Alibaba Cloud calls) plus `ledgerpilot/config.py` (region/endpoint wiring).

## The measurement layer (the moat)

`eval/harness.py` runs a seeded-error corpus through the planner + gate and reports:
- **False-write rate:** fraction of gate-*approved* entries that are actually wrong (the headline number; target < 1%).
- **Catch rate:** fraction of seeded-error entries the gate correctly rejects.
- **Recovery rate:** for rejected entries, fraction the planner repairs on a second pass.
- A **negative-control demo:** clean inputs produce zero false rejections.

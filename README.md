# LedgerPilot

**An autonomous month-end-close agent that proposes journal entries from messy financial inputs and writes them back to a real ERP only through a deterministic, auditable validation gate, with a measured false-write rate.**

> **Uniqueness claim:** No other entry combines a generative planner over unstructured financial inputs + a deterministic SOX-style validation gate with signed approval tokens + governed write-back to a real ERP system-of-record + a measured false-write rate on a domain-credible seeded-error corpus.

Built for the **Global AI Hackathon Series with Qwen Cloud** — Track 4: **Autopilot Agent**.

---

## The problem

Month-end close is one of the most error-prone, labor-intensive workflows in finance. Teams spend days reconciling bank statements, invoices, and email approvals into journal entries, and a non-trivial fraction of those entries carry errors that surface only at audit. A naive "AI accountant" that writes directly to the ledger is worse than no automation: a single hallucinated or unbalanced journal entry posted to a system of record is an audit finding, not a convenience.

LedgerPilot treats the ledger as a **system of record that must never be corrupted**. The generative model is allowed to *reason and propose*; it is never allowed to *write*. Every write passes a deterministic gate first.

## The thesis: deterministic vs generative

| Concern | Layer | Why |
|---|---|---|
| Reading messy multi-source inputs, extracting line items, drafting entries | **Generative (Qwen)** | Unstructured, ambiguous, needs reasoning |
| Double-entry balance, account validity, period locks, segregation of duties, approval thresholds | **Deterministic (rules engine)** | Must be exact, auditable, reproducible |
| Committing an approved entry to the ledger | **Governed write-back** | Signed token, idempotent, human-in-the-loop gate, rollback |

The deterministic gate is the trust boundary. The headline metric is the **false-write rate**: of the entries the gate *approves*, how many are actually wrong, measured against a seeded-error corpus.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full diagram and Alibaba Cloud deployment topology.

```
unstructured inputs ──► Qwen perception ──► Qwen planner ──► DETERMINISTIC GATE ──► signed token ──► Odoo write-back
 (statements, invoices,    (Qwen3-VL)         (Qwen3 +         (balance, accounts,    (HMAC)           (idempotent,
  approval emails)                             function calling) period, SoD, limits)                   human gate, rollback)
                                                                       │
                                                                       └──► rejected entries ──► audit log + review queue
```

## Repository layout

```
ledgerpilot/
  config.py            # environment + cloud config
  models.py            # JournalEntry / JournalLine / Proposal / GateResult
  chart_of_accounts.py # sample chart of accounts + period state
  planner.py           # Qwen/DashScope generative planner (propose entries)
  ingest.py            # Qwen-VL document/email ingestion
  gate.py              # THE deterministic validation gate (scored core)
  tokens.py            # HMAC-signed approval tokens
  writeback.py         # Odoo write-back via MCP validate_write/execute_approved_write
eval/
  corpus.py            # seeded-error corpus generator
  harness.py           # runs corpus through planner+gate, reports false-write rate
tests/
  test_gate.py         # gate unit tests (the moat must be correct)
```

## Quick start

```bash
pip install -e .
cp .env.example .env          # fill in DASHSCOPE_API_KEY and LEDGERPILOT_SIGNING_KEY
python -m eval.harness        # generate corpus, run gate, print false-write rate
pytest                        # validate the gate
```

The deterministic gate and eval harness run **without a live ERP**. Write-back targets an Odoo instance on Alibaba Cloud ECS (see ARCHITECTURE.md).

## Why this is hard to clone

1. A **realistically seeded ERP** on Alibaba Cloud (not a toy ledger).
2. A **domain-credible seeded-error corpus** that requires real accounting knowledge to construct (unbalanced entries, wrong account classes, period violations, duplicate invoices, threshold evasions).
3. The **deterministic SOX-style gate** with signed approval tokens.

Anyone can prompt "build me an accounting agent." Nobody can fake a defensible false-write rate without 1 and 2.

## License

Apache License 2.0. See [LICENSE](LICENSE).

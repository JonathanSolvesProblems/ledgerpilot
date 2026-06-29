# LedgerPilot

**An autonomous month-end-close agent that proposes journal entries from messy financial inputs and writes them back to a real ERP only through a deterministic, auditable validation gate, with a measured false-write rate.**

> **Uniqueness claim:** No other entry combines a generative planner over unstructured financial inputs + a deterministic SOX-style validation gate with signed approval tokens + governed write-back to a real ERP system-of-record + a measured false-write rate on a domain-credible seeded-error corpus.

Built for the **Global AI Hackathon Series with Qwen Cloud** — Track 4: **Autopilot Agent**.

## Measured result

Across a 120-case seeded-error corpus run through the full planner → gate pipeline:

| Metric | Result |
|---|---|
| **False-write rate** | **0 wrong of 40 approved entries (≤ 7.50% at 95% CI, Rule of Three)** |
| Catch rate | 100% (80/80 seeded errors blocked or escalated) |
| False-reject rate | 0% (0/40 clean controls wrongly blocked) |

Reproduce it with `python -m eval.harness` (offline, no key) or `python -m eval.harness --live` (real Qwen planner). The corpus includes *semantic* errors a balance check cannot catch (a balanced entry posted to the wrong account or wrong amount); those are caught by reconciling each proposal against the source document.

---

## The problem

Month-end close is one of the most error-prone, labor-intensive workflows in finance. Teams spend days reconciling bank statements, invoices, and email approvals into journal entries, and a non-trivial fraction of those entries carry errors that surface only at audit. A naive "AI accountant" that writes directly to the ledger is worse than no automation: a single hallucinated or unbalanced journal entry posted to a system of record is an audit finding, not a convenience.

LedgerPilot treats the ledger as a **system of record that must never be corrupted**. The generative model is allowed to *reason and propose*; it is never allowed to *write*. Every write passes a deterministic gate first.

## The thesis: deterministic vs generative

| Concern | Layer | Why |
|---|---|---|
| Reading messy multi-source inputs, extracting line items, drafting entries | **Generative (Qwen3)** | Unstructured, ambiguous, needs reasoning |
| Balance, account validity, period locks, segregation of duties, approval thresholds, **reconciliation to the source document** | **Deterministic (rules engine)** | Must be exact, auditable, reproducible |
| Committing an approved entry to the ledger | **Governed write-back** | Signed token, idempotent, human-in-the-loop gate, rollback |

The deterministic gate is the trust boundary. The headline metric is the **false-write rate**: of the entries the gate *approves*, how many are actually wrong, measured against a seeded-error corpus and reported with a 95% confidence bound.

The gate does not only check that an entry is *well-formed* (it balances, the accounts exist); it checks that the entry is *correct* by reconciling it against the independent source document. That is what lets it catch a confident, balanced, plausible-looking entry that a generative model posted to the wrong account or for the wrong amount.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full diagram and Alibaba Cloud deployment topology.

```
unstructured inputs ──► Qwen perception ──► Qwen planner ──► DETERMINISTIC GATE ──► signed token ──► Odoo write-back
 (statements, invoices,    (qwen3-vl-plus)    (qwen3-max +     (balance, accounts,    (HMAC)           (idempotent,
  approval emails)                             function calling) period, SoD, limits,                  human gate, rollback)
                                                                 reconcile-to-source)
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
  corpus.py            # parametrized seeded-error corpus (scenarios + error classes)
  scripted_planner.py  # offline error-injection planner + live Qwen planner
  harness.py           # runs corpus through planner+gate, reports false-write rate + CI
tests/
  test_gate.py         # gate unit tests (the moat must be correct)
  test_pipeline.py     # reconciliation + full-pipeline tests
```

## Quick start

```bash
pip install -e .
cp .env.example .env          # fill in DASHSCOPE_API_KEY and LEDGERPILOT_SIGNING_KEY
python -m eval.harness        # offline: 120-case corpus, false-write rate + CI
python -m eval.harness --live # online: real Qwen planner on clean scenarios
python demo.py                # end-to-end propose -> gate -> governed write
pytest                        # 31 tests: gate, reconciliation, tokens, pipeline
```

The deterministic gate and eval harness run **without a live ERP and without an API key** (the offline path uses an error-injection planner). The `--live` path and write-back target real Qwen models and an Odoo instance on Alibaba Cloud ECS (see ARCHITECTURE.md).

## Impact and compliance

Month-end close is slow and error-prone at scale, and the harm is quantifiable:

- A typical close still takes **~6.4 business days**, and only ~40% of companies are confident in their numbers ([APQC](https://www.apqc.org/), [Ventana/ISG close benchmarks](https://www.ventanaresearch.com/)).
- Manual journal entries are a leading source of **financial-statement error and restatement**; the PCAOB and audit-deficiency data tie manual GL adjustments to control failures ([PCAOB AS 2201, ICFR](https://pcaobus.org/oversight/standards/auditing-standards/details/AS2201)).
- Weak **segregation of duties** is a top enabler of occupational fraud; median loss per scheme is in the six figures ([ACFE Report to the Nations](https://www.acfe.com/report-to-the-nations/)).

LedgerPilot's gate maps each check to a named control:

| Gate check | Control framework |
|---|---|
| Balance, account validity, reconciliation to source | SOX 404 ICFR; COSO control activities |
| Period lock | Close-calendar / cut-off controls |
| Segregation of duties (preparer ≠ approver) | SOX 404; COSO; 4-eyes anti-fraud control |
| Approval thresholds (human-in-the-loop) | Delegation-of-authority / approval-matrix control |
| HMAC token bound to entry + evidence | Non-repudiation / audit-trail of control execution |

## Why this is hard to clone

1. A **measured false-write rate on a seeded-error corpus** with a stated confidence bound. No surveyed vendor or open-source project publishes this; accuracy/touch-free percentages are not the same thing.
2. A **deterministic reconciliation check** that catches *semantic* errors (right form, wrong account/amount), which a balance-only gate and a pure-LLM agent both miss.
3. A **domain-credible seeded-error corpus** that requires real accounting knowledge to construct.
4. The gate as a **reproducible trust boundary** with HMAC-signed, content-bound approval tokens.

Anyone can prompt "build me an accounting agent." The defensible part is the measured, reproducible control layer, not the LLM.

## Status (honest scope)

- **Working today, no credentials:** the deterministic gate, reconciliation, signed tokens, idempotent write-back logic, the 120-case offline pipeline, the demo, and 31 tests.
- **Needs a key / cloud:** the `--live` Qwen path (set `DASHSCOPE_API_KEY`), a live Odoo on Alibaba Cloud ECS for a real `account.move` write, and the real MCP write path (SSE MCP via the Model Studio Responses API). See ARCHITECTURE.md for the deployment topology.

## License

Apache License 2.0. See [LICENSE](LICENSE).

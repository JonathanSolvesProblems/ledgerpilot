# LedgerPilot

**Track 4: Autopilot Agent**

## What it is

LedgerPilot is an autonomous month-end-close agent that reads messy financial inputs, drafts journal entries, and writes them back to a real ERP system of record only through a deterministic, auditable validation gate, with a measured false-write rate.

**Uniqueness claim:** LedgerPilot is the only entry that pairs a generative planner over unstructured financial inputs with a deterministic SOX-style validation gate, signed approval tokens, and governed write-back to a real ERP, and then publishes a measured false-write rate (with a confidence bound, on a domain-seeded error corpus) for the entries it actually posts, backed by a reconciliation check that catches the balanced-but-wrong-account and wrong-amount errors a trial-balance never will.

Most "AI accountant" projects measure whether an agent can find or answer things. LedgerPilot measures the opposite and harder thing: whether an autonomous agent avoids introducing errors when it writes to the ledger.

## The problem

Month-end close is one of the most error-prone, labor-intensive workflows in finance, and the harm is quantifiable:

- A typical close still takes about **6.4 business days**, and only around **40% of finance teams** are confident in their numbers (APQC; Ventana/ISG close benchmarks).
- Manual journal entries are a leading source of financial-statement error and restatement. The PCAOB ties manual GL adjustments to internal-control failures (PCAOB AS 2201, ICFR).
- Weak segregation of duties is a top enabler of occupational fraud, with a median loss per scheme in the six figures (ACFE Report to the Nations).
- Foundation models are not reliable enough to trust with unsupervised posting. The DualEntry Accounting AI Benchmark 2026 found the best model still fails roughly **1 in 5** real accounting tasks (top model 77.3%).

That last number is the whole point. A naive agent that writes directly to the ledger is worse than no automation: a single hallucinated, unbalanced, or misposted entry in a system of record is an audit finding, not a convenience. So I built LedgerPilot around a rule: the model may reason and propose, but it may never write. Every write passes a deterministic gate first.

## The thesis: deterministic vs generative

This is the headline answer to the AI Factor question, not a demo of what the model noticed.

| Concern | Layer | Why |
|---|---|---|
| Reading messy multi-source inputs, extracting line items, drafting entries | **Generative (Qwen3)** | Unstructured, ambiguous, needs reasoning |
| Balance, account validity, period locks, segregation of duties, approval thresholds, reconciliation to the source document | **Deterministic (rules engine)** | Must be exact, auditable, reproducible |
| Committing an approved entry to the ledger | **Governed write-back** | Signed token, idempotent, human-in-the-loop gate, rollback |

The deterministic gate is the single trust boundary and the only path to the ledger. Critically, the gate does not only check that an entry is well-formed (it balances, the accounts exist). It checks that the entry is correct by reconciling each proposal against the independent source document. That is what lets it catch a confident, balanced, plausible-looking entry that a generative model posted to the wrong account or for the wrong amount, the class of semantic error (error of principle, error of commission, compensating error) that a balance-only check and a pure-LLM agent both miss.

## Features and functionality

- **Ingestion.** LedgerPilot reads bank statements, invoices, and approval emails and extracts structured line items.
- **Planner.** A Qwen3 planner drafts a candidate journal entry grounded in the chart of accounts, and returns its reasoning alongside the entry.
- **Deterministic gate.** Every proposal runs through side-effect-free checks: balance, account validity, period lock, segregation of duties (preparer is not approver), approval thresholds, and reconciliation to the source document. Money is `Decimal`-only, with floats rejected at the model boundary.
- **Signed approval tokens.** An approved entry gets an HMAC token content-bound to the entry and its evidence, so a tampered entry cannot reuse an approval. This is the non-repudiation record of the control's execution.
- **Governed write-back.** Writes are idempotent on a content hash (no double-posting), pass through a human-in-the-loop gate for anything over threshold, and support rollback.
- **Audit trail.** Rejected entries route to an audit log and a review queue rather than the ledger.

## How I use Qwen Cloud

Everything runs on Alibaba Cloud Model Studio through the OpenAI-compatible endpoint.

- **Planner: `qwen3.7-max` with function calling.** The planner drafts entries and calls tools to ground each line against the chart of accounts, so account codes are resolved against real data instead of invented. Harder cases can enable Qwen3 thinking mode.
- **Ingestion: `qwen3-vl-plus`.** The vision model reads document and email images (statements, invoices, approvals) and extracts the line items and amounts the planner works from.
- **Governed write via SSE-MCP on the Responses API.** The Odoo MCP server is attached as an SSE MCP tool through Model Studio's Responses API (`tools=[{"type": "mcp", ...}]`). An entry reaches this path only after LedgerPilot's own deterministic gate has re-checked and approved it, so the gate, not the model, is authoritative: the MCP client is instructed to call `validate_write` then `execute_approved_write`, but the safety guarantee comes from the pre-gate, not from the prompt. An XML-RPC client provides a direct, idempotent write path to the same Odoo instance (the content hash is embedded in the move and deduplicated server-side).

## Architecture

```
unstructured inputs ──► Qwen perception ──► Qwen planner ──► DETERMINISTIC GATE ──► signed token ──► Odoo write-back
 (statements, invoices,   (qwen3-vl-plus)    (qwen3.7-max +     (balance, accounts,    (HMAC)          (idempotent,
  approval emails)                            function calling) period, SoD, limits,                  human gate, rollback)
                                                                reconcile-to-source)
                                                                      │
                                                                      └──► rejected entries ──► audit log + review queue
```

## Measured result

I report two numbers, kept separate on purpose. The offline synthetic gate stress-test runs a 204-case seeded-error corpus (12 scenarios, 14 error classes) through the gate to prove the decision logic is sound. The measured live number runs the real Qwen planner (with function calling) on 39 close tasks and reports the false-write rate on what the model actually produced. On Alibaba Cloud Model Studio the gate caught every mistake either model made and wrote 0 wrong entries. Qwen3.7-Max was 97.4% accurate; its one mistake, booking a software invoice to a prepaid asset instead of an expense, was caught by reconciliation. The faster qwen-flash was 87.2% accurate and the gate caught all 5 of its cross-class mistakes, including a cost-of-goods entry it tried to post to accounts receivable and revenue. False-write rate 0% for both (Wilson 95% CI at most 9.18% and 10.15%); the raw transcript is committed at `docs/live_run.txt`. This is not zero by construction: a within-class account error would surface as a nonzero rate (the gate enforces account class and amount, not the choice within a class); in this run every model error was cross-class and caught. I do not quote a vendor-style accuracy percentage.

| Metric (offline synthetic stress-test) | Result |
|---|---|
| **False-write rate** | **0 wrong of 36 approved entries (≤ 8.33% at 95% CI)** |
| Catch rate | 100% (168 of 168 seeded errors = 156 blocked + 12 escalated to a human) |
| False-reject rate | 0% (0 of 36 clean controls wrongly blocked) |

The false-reject line is the negative control: on clean, correct entries the gate stays silent and lets them through, so the catch rate is not bought with over-blocking. The corpus deliberately includes semantic errors a balance check cannot catch (a balanced entry posted to the wrong account or wrong amount, a flipped debit/credit, a rounding slip), which are caught by reconciling each proposal against its source document. This offline number measures the gate's decision logic, not a model. The live measured number (`python -m eval.harness --live`) validates the real Qwen planner against a class-level posting policy independent of the answer, so a plausible-but-wrong posting can pass and the false-write rate is genuinely falsifiable. Reproduce the offline number with `python -m eval.harness` (no key needed).

## Mapping to named controls

Each gate check maps to a named control framework, so the gate is auditable in the language a controller and an external auditor already use.

| Gate check | Control framework |
|---|---|
| Balance, account validity, reconciliation to source | SOX 404 ICFR; COSO control activities |
| Period lock | Close-calendar / cut-off controls |
| Segregation of duties (preparer is not approver) | SOX 404; COSO; four-eyes anti-fraud control |
| Approval thresholds (human-in-the-loop) | Delegation-of-authority / approval-matrix control |
| HMAC token bound to entry and evidence | Non-repudiation / audit-trail of control execution |

## Why this is hard to clone

Anyone can prompt "build me an accounting agent." The defensible part is not the LLM. It is the measured, reproducible control layer: a false-write rate on a seeded-error corpus with a stated confidence bound (no surveyed vendor or open-source project publishes this), a deterministic reconciliation check that catches semantic wrong-account and wrong-amount errors, a domain-credible seeded-error corpus that takes real accounting knowledge to build, and a reproducible trust boundary with content-bound signed tokens.

## Honest scope and path to production

I want to be precise about what runs today versus what a production deployment would require.

- **Working now, no credentials:** the deterministic gate, reconciliation, signed tokens, idempotent write-back logic, the 204-case offline synthetic stress-test, the demo, and the test suite. The offline harness uses an error-injection planner to stress every gate check against known ground truth, so the reported numbers are a gate stress-test on a synthetic, self-constructed corpus, not yet a production sensitivity study.
- **Done, with a Model Studio key:** the `--live` measurement against real Qwen output (Qwen3.7-Max and qwen-flash) on 39 close tasks, reported above.
- **Needs cloud:** a live Odoo on Alibaba Cloud ECS for a real `account.move` write through the XML-RPC client or the SSE-MCP path on the Model Studio Responses API.
- **To production this would need:** integration with a real ERP and its actual chart of accounts and period calendar, a prospective study measuring false-write rate against a gold-standard set of real closes, and proper key management for the signing key (it currently defaults to a development value).

The thesis holds regardless of scale: the ledger is a system of record that must never be corrupted, so the generative model proposes and a deterministic, control-mapped gate is the only thing allowed to write.
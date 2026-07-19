# LedgerPilot

**Track 4: Autopilot Agent**

**Watch the 3-minute demo:** https://www.youtube.com/watch?v=TZ48qdSpMJk

**Read the build story:** https://jonathanandrei.com/blog/ledgerpilot-qwen-mcp-odoo-counterfactual-close-agent/

## What it is

LedgerPilot is an autonomous month-end-close agent, built on **Qwen Cloud**, that reads messy financial inputs, drafts journal entries with Qwen, and writes them back to a real ERP system of record only through a deterministic, auditable validation gate, with a measured false-write rate.

**Uniqueness claim:** LedgerPilot is the only entry that pairs a generative planner over unstructured financial inputs with a deterministic SOX-style validation gate, signed approval tokens, and governed write-back to a real ERP, and then publishes a measured false-write rate (with a confidence bound, on a domain-seeded error corpus) for the entries it actually posts, backed by a reconciliation check that catches the balanced-but-wrong-account and wrong-amount errors a trial-balance never will.

Most "AI accountant" projects measure whether an agent can find or answer things. LedgerPilot measures the opposite and harder thing: whether an autonomous agent avoids introducing errors when it writes to the ledger.

## The problem

Month-end close is one of the most error-prone, labor-intensive workflows in finance, and the harm is quantifiable:

- A typical close still takes about **6.4 business days**, and only around **40% of finance teams** are confident in their numbers (APQC; Ventana/ISG close benchmarks).
- Manual journal entries are a leading source of financial-statement error and restatement. The PCAOB ties manual GL adjustments to internal-control failures (PCAOB AS 2201, ICFR).
- Weak segregation of duties is a top enabler of occupational fraud, with a median loss per scheme in the six figures (ACFE Report to the Nations).
- Foundation models are not reliable enough to trust with unsupervised posting. On the DualEntry Accounting AI Benchmark the top model still fails roughly **1 in 6** real accounting tasks (top model 83.2%, leaderboard retrieved July 2026).

That last number is the whole point. A naive agent that writes directly to the ledger is worse than no automation: a single hallucinated, unbalanced, or misposted entry in a system of record is an audit finding, not a convenience. So I built LedgerPilot around a rule: the model may reason and propose, but it may never write. Every write passes a deterministic gate first.

## The thesis: deterministic vs generative

This is the headline answer to the AI Factor question, not a demo of what the model noticed.

| Concern | Layer | Why |
|---|---|---|
| Reading messy multi-source inputs, extracting line items, drafting entries | **Generative (Qwen3)** | Unstructured, ambiguous, needs reasoning |
| Balance, account validity, period locks, segregation of duties, approval thresholds, reconciliation to the source document | **Deterministic (rules engine)** | Must be exact, auditable, reproducible |
| Committing an approved entry to the ledger | **Governed write-back** | Signed token, idempotent on retry, human-in-the-loop gate above threshold |

The deterministic gate is the single trust boundary and the only path to the ledger. Critically, the gate does not only check that an entry is well-formed (it balances, the accounts exist). It checks that the entry is correct by reconciling each proposal against the independent source document. That is what lets it catch a confident, balanced, plausible-looking entry that a generative model posted to the wrong account or for the wrong amount, the class of semantic error (error of principle, error of commission, compensating error) that a balance-only check and a pure-LLM agent both miss.

## Features and functionality

- **Ingestion.** LedgerPilot reads scanned invoices with `qwen3-vl-plus` and extracts a structured record (document id, date, vendor, net/tax/gross, line items). That extraction then drives the planner, and the gate reconciles the resulting entry against the document the vision model just read: `scripts/ingest_demo.py` runs it from a PNG, and the wrong-account variant of the same invoice is refused (`docs/vision_ingest_proof.txt`).
- **Planner.** A Qwen3 planner drafts a candidate journal entry, calling a `lookup_accounts` tool to ground each account code against the real chart, and returns its reasoning alongside the entry.
- **Deterministic gate.** Every proposal runs through eight side-effect-free checks: balance (including that the entry actually moves value), account validity, no account on both sides, positive amounts, period lock, segregation of duties (preparer is not approver), approval thresholds, and reconciliation to the source document. Money is `Decimal`-only, with floats rejected at the model boundary. The gate fails closed: any failing check other than the human-approval threshold rejects.
- **Signed approval tokens.** An approved entry gets an HMAC token content-bound to the entry, including the amounts, accounts, narration, and the preparer/approver, so neither the numbers nor the audit trail can be altered after approval without invalidating the token.
- **Governed write-back.** Writes are idempotent on a content hash (no double-posting on a sequential retry) and pass through a human-in-the-loop gate for anything over threshold.
- **MCP.** The gate is also an MCP server, so Qwen can call the write tool directly and still cannot write anything wrong: the server re-runs the gate and verifies the token. Reversal entries and a persisted audit log / review queue are designed into the topology but not yet implemented.

## How I use Qwen Cloud

The backend runs **on Alibaba Cloud ECS** and calls Qwen on **Alibaba Cloud Model Studio** in the same region, through the OpenAI-compatible endpoint.

- **Agent runtime: Alibaba Cloud ECS.** `scripts/deploy_ecs.py` provisions the instance through the ECS and VPC OpenAPIs (key pair, security group, VPC, vSwitch, instance), and the agent, the gate, and the write-back all execute there. It also serves the gate's web UI, over a TLS certificate terminated on the instance, at https://ledgerpilot.jonathanandrei.com, so the running backend is visible in a browser.
- **Planner: `qwen3.7-max` with function calling.** The planner drafts entries and calls tools to ground each line against the chart of accounts, so account codes are resolved against real data instead of invented. Harder cases can enable Qwen3 thinking mode.
- **Ingestion: `qwen3-vl-plus`.** The vision model reads a scanned invoice image and extracts the record the planner works from. The amount the gate later reconciles against is read off the pixels, never typed in (`docs/vision_ingest_proof.txt`, generated on ECS).
- **The gate as an MCP server, driven by Qwen on the Responses API.** `ledgerpilot/mcp_server.py` exposes the deterministic gate as an SSE MCP tool, attached to Qwen through Model Studio's Responses API (`tools=[{"type": "mcp", "server_protocol": "sse", ...}]`). This is the design that makes the MCP integration meaningful rather than decorative: the model is the *caller* of the write tool, not the authority. `validate_write` is read-only; `execute_approved_write` re-runs the full gate and verifies an HMAC token bound to the entry's content hash before it touches Odoo. In `scripts/mcp_demo.py`, Qwen posts a real `account.move` (`move_id 3`), and when the same run instructs it to inflate the amount first, the server refuses because the hash no longer matches the token. A direct XML-RPC client provides the same governed, idempotent write path for non-MCP callers.

## Architecture

```
unstructured inputs ──► Qwen planner ──────► DETERMINISTIC GATE ──► signed token ──► Odoo write-back
 (statements, invoices)   (qwen3.7-max +      (balance, accounts,    (HMAC, bound     (idempotent on retry,
                           function calling)   period, SoD, limits,   to the entry)     human gate above
                                               reconcile-to-source)                     threshold)
                                                     │
                                                     └──► rejected / escalated, with the failing check as the reason
```

## Measured result

**The headline is a counterfactual on a real ledger.** Same qwen-flash planner, same 39 close tasks, same live Odoo. Post every proposal with the gate off, then again with it on. The only variable is the gate.

| | Entries posted | Wrong entries in the ledger |
|---|---|---|
| Gate OFF | 39 | **5** |
| Gate ON | 34 | **0** |

The wrong entries were posted for real with the gate off, under references starting `NG-WRONG` (transcript: `docs/counterfactual_proof.txt`, generated on ECS). Each balances, uses real accounts, and passes a trial balance: salaries paid out of accounts receivable, cost-of-goods booked to receivables and revenue. **Same model, same tasks, same ledger; the wrong entries become 0. The model did not get better. The ledger did.** That is the number to remember, and it is impact in a general ledger, not a percentage of my own test set.

The rest of this section is the evidence for *why* that works: the gate's decision logic is sound at scale, and it holds on live model output.

**On the offline synthetic stress-test**, a 204-case seeded-error corpus (12 scenarios, 14 error classes) run through the gate: 0 false writes of 36 approved (≤ 8.33% at 95% CI), 100% catch (168/168), 0% false-reject.

**On live Qwen output**, run on the Alibaba Cloud ECS instance the backend is deployed to, calling Model Studio in the same region (transcript `docs/ecs_proof.txt`): **eight model mistakes, eight caught, zero wrong entries reached the ledger.**

| Model | Accuracy | Mistakes | Caught | False writes |
|---|---|---|---|---|
| `qwen3.7-max` | 97.4% (38/39) | 1 | 1 of 1 | **0** (Wilson 95% CI ≤ 9.18%) |
| `qwen-flash` | 82.1% (32/39) | 7 | 7 of 7 | **0** (≤ 10.72%) |

The mistakes are the interesting part. Nearly all were cross-class postings: settling an invoice by crediting accounts receivable instead of cash, or booking cost-of-goods to receivables and revenue. Every one of them balances, uses real accounts, and reads plausibly, so a trial balance passes all of them. Only reconciliation to the source document catches them.

Swap the flagship for a model that makes seven times as many mistakes, and the ledger is still clean. **That is the claim: correctness is a property of the gate, not of the model being right.**

This is not zero by construction: a permitted-but-wrong account posting would surface as a nonzero rate (the gate enforces the document's posting policy and the amount, not the choice among the accounts that policy permits); in this run every model error fell outside the permitted set and was caught. I do not quote a vendor-style accuracy percentage.

| Metric (offline synthetic stress-test) | Result |
|---|---|
| **False-write rate** | **0 wrong of 36 approved entries (≤ 8.33% at 95% CI)** |
| Catch rate | 100% (168 of 168 seeded errors = 156 blocked + 12 escalated to a human) |
| False-reject rate | 0% (0 of 36 clean controls wrongly blocked) |

The false-reject line is the negative control: on clean, correct entries the gate stays silent and lets them through, so the catch rate is not bought with over-blocking. The corpus deliberately includes semantic errors a balance check cannot catch (a balanced entry posted to the wrong account or wrong amount, a flipped debit/credit, a rounding slip), which are caught by reconciling each proposal against its source document. This offline number measures the gate's decision logic, not a model. The live measured number (`python -m eval.harness --live`) validates the real Qwen planner against a per-document posting policy independent of the answer, so a plausible-but-wrong posting can pass and the false-write rate is genuinely falsifiable. Reproduce the offline number with `python -m eval.harness` (no key needed).

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

- **Deployed and running on Alibaba Cloud:** the backend runs on an ECS instance (`i-t4n1i5p7bz4ypj122e6q`, `ap-southeast-1`), provisioned by `scripts/deploy_ecs.py` through the ECS and VPC OpenAPIs. The test suite, the 204-case gate stress-test, the live Qwen measurement, and a real ERP write all executed on that instance, which also serves the gate's web UI on port 80. `docs/ecs_proof.txt` is the transcript, including values from the ECS instance metadata service, which only answers on a real ECS box.
- **Working now, no credentials:** the deterministic gate, reconciliation, signed tokens, idempotent write-back logic, the 204-case offline synthetic stress-test, the demo, and the test suite. The offline harness uses an error-injection planner to stress every gate check against known ground truth, so the reported numbers are a gate stress-test on a synthetic, self-constructed corpus, not yet a production sensitivity study.
- **Done, with a Model Studio key:** the `--live` measurement against real Qwen output (Qwen3.7-Max and qwen-flash) on 39 close tasks, reported above. Model accuracy moves a few points between runs (sampling is not perfectly reproducible even at temperature 0); the gate's result did not move.
- **Done, against a live ERP:** real governed writes through the full path (gate approves, HMAC token, XML-RPC or MCP). Posted `account.move` records to a live Odoo 19: `MISC/2026/06/0001` (rent) from local, `MISC/2026/06/0002` (utilities) from the agent on ECS, and `move_id 3` (SaaS) driven by Qwen through the MCP server. Idempotency proven on re-run. Proof in `docs/real_write_proof.txt`, `docs/ecs_proof.txt`, and `scripts/mcp_demo.py`.
- **Not yet implemented (stated plainly):** reversal/rollback entries, a persisted audit log and review queue (rejections are refused with the failing check as the reason, but not stored), and per-line net/VAT reconciliation. The measured false-write rates start from text rather than images, so they score the planner and the gate, not OCR accuracy. Idempotency is sequential-retry safe, not concurrency safe.
- **To production this would need:** integration with a real ERP and its actual chart of accounts and period calendar, a posting policy derived from the ERP's own account structure rather than a per-task list, a prospective study measuring false-write rate against a gold-standard set of real closes, and key management for the signing key from a secret manager (the config already refuses to run against a live ERP with the development default).

The thesis holds regardless of scale: the ledger is a system of record that must never be corrupted, so the generative model proposes and a deterministic, control-mapped gate is the only thing allowed to write.
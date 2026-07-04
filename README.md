# LedgerPilot

![license](https://img.shields.io/badge/license-Apache--2.0-blue) ![python](https://img.shields.io/badge/python-3.10%2B-blue) ![gate](https://img.shields.io/badge/gate-0%20false--writes%2F36-brightgreen) ![built on](https://img.shields.io/badge/built%20on-Qwen%20Cloud-ff6a00)

**An autonomous month-end-close agent that proposes journal entries from messy financial inputs and writes them back to a real ERP only through a deterministic, auditable validation gate, with a measured false-write rate.**

> It is like an AI accountant that posts straight to your ERP, but with a hard deterministic gate and a *measured safety number* for the entries it actually writes.

> **Uniqueness claim:** LedgerPilot is the only month-end-close agent that publishes a measured false-write rate, with a confidence interval, on a domain-seeded error corpus, for the entries it actually posts, backed by a deterministic reconciliation check that catches the balanced-but-wrong-account and wrong-amount errors a trial balance never will.

Built for the **Global AI Hackathon Series with Qwen Cloud** (Track 4: **Autopilot Agent**).

## Results

Two numbers, and I keep them separate on purpose.

**1. Synthetic gate stress-test** (`python -m eval.harness`, offline, no API key): 204 cases across 12 scenarios and 15 error classes, run through the gate.

| Metric | Result |
|---|---|
| False-write rate | 0 wrong of 36 approved (≤ 8.33% at 95% CI, Rule of Three) |
| Catch rate | 100% (168/168 = 156 blocked + 12 escalated to a human) |
| False-reject rate | 0% (0/36 clean controls wrongly blocked) |

This measures the **gate's decision logic**, not a model. It is a stress-test: the clean controls are correct entries, so a 0% false-write here means the rules are sound, not that an LLM is accurate.

**2. Measured LLM + gate** (`python -m eval.harness --live`, needs `DASHSCOPE_API_KEY`): the real Qwen planner drafts entries from natural-language close tasks, and the gate judges what the model actually produced. This is the number that reflects the real pipeline, reported with a confidence interval. (Pending a key; the harness is wired and one command produces it.)

The corpus includes *semantic* errors a balance check cannot catch (a balanced entry posted to the wrong account, wrong amount, flipped debit/credit, or off by a rounding cent). Those are caught by reconciling each proposal against the source document, which is the point.

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
  writeback.py         # governed write-back (gate re-check -> token -> idempotent commit)
  odoo_client.py       # XmlrpcOdooClient (ECS) + ModelStudioMcpClient (Responses API MCP)
eval/
  corpus.py            # parametrized seeded-error corpus (12 scenarios x 15 error classes)
  scripted_planner.py  # offline error-injection planner
  harness.py           # offline stress-test + --live measured run
  live_tasks.py        # realistic close tasks with ground truth for the live run
  live_eval.py         # measured false-write rate + Wilson 95% CI + model accuracy
  stats.py             # Wilson score interval
scripts/
  live_close.py        # end-to-end real close (record this on model access)
tests/                 # 46 tests: gate, reconciliation, tokens, pipeline, clients, live eval
docs/
  architecture.svg     # system + Alibaba Cloud topology diagram
  DEVPOST.md BLOG.md DEMO_SCRIPT.md
```

## Quick start

```bash
pip install -e .
cp .env.example .env          # add DASHSCOPE_API_KEY (a signing key is generated for you)
python -m eval.harness        # offline: 204-case synthetic stress-test, no key needed
python demo.py                # end-to-end propose -> gate -> governed write, no key needed
pytest                        # 46 tests

# with a Model Studio key in .env (auto-loaded):
python -m eval.harness --live # MEASURED false-write rate on real Qwen output + Wilson CI
python scripts/live_close.py  # watch the real agent propose -> gate -> governed write
```

The deterministic gate, demo, and offline harness run **without a live ERP and without an API key** (the offline path uses an error-injection planner). The `--live` path and write-back target real Qwen models and an Odoo instance on Alibaba Cloud ECS (see ARCHITECTURE.md).

## Impact and compliance

Month-end close is slow and error-prone at scale, and the harm is per-entry, not abstract:

- A typical close still takes **~6.4 business days**, and only ~40% of finance teams are confident in their numbers ([APQC](https://www.apqc.org/), [Ventana/ISG close benchmarks](https://www.ventanaresearch.com/)).
- **LLMs post wrong entries at a rate you cannot ignore.** On a real accounting-workflow benchmark, the best model scored **77.3%, so roughly 1 in 5 tasks is wrong** ([DualEntry Accounting AI Benchmark 2026](https://www.dualentry.com/accounting-ai-benchmark)); and when an agent is allowed to write with a single control, the false-success rate spikes to ~45-48% ([arXiv:2606.09863](https://arxiv.org/pdf/2606.09863)). A single wrong journal entry posted to a system of record is an audit adjustment, and every audit-adjusting entry carries review, rework, and restatement-risk cost. That per-entry cost is exactly what a hard write gate removes.
- Manual GL adjustments are a leading source of **financial-statement error and restatement** ([PCAOB AS 2201, ICFR](https://pcaobus.org/oversight/standards/auditing-standards/details/AS2201)); weak **segregation of duties** is a top enabler of occupational fraud, median loss per scheme in the six figures ([ACFE Report to the Nations](https://www.acfe.com/report-to-the-nations/)).
- Detecting seeded errors is not the same as refusing to write them: the write side is the unsolved part ([Simthetic seeded-error corpus, arXiv:2606.02494](https://arxiv.org/html/2606.02494v1)).

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

## Reproduce the measured number

```bash
pip install -e .
echo "DASHSCOPE_API_KEY=sk-..." >> .env         # a workspace key from Model Studio
python -m eval.harness --live                    # measured false-write rate + Wilson 95% CI
```

`--live` feeds 16 natural-language close tasks (some deliberately easy to misclassify, e.g. prepaid vs expense, capitalize vs expense) to the real Qwen planner, then judges what the model produced. It reports the model's raw accuracy, how many of its mistakes the gate blocked, and the false-write rate on the entries the gate approved.

## Known limitations (honest scope)

- **Multi-line tax splits are not yet enforced by reconciliation.** The gate checks that every account is within policy and the total matches the document; it does not yet verify a per-line net/VAT split, so a VAT-inclusive invoice lumped into one expense line can pass. The measured task set is single-account for that reason; per-line reconciliation against document net/tax is the next extension.
- **The live measurement needs an authorized Model Studio account** (`--live` returns 403 until Identity Verification clears). The gate, demo, and offline stress-test need no key.
- **A real ERP write** requires an Odoo instance on Alibaba Cloud ECS; `odoo_client.py` is unit-tested against a fake transport and runs live once `ODOO_*` point at the instance.
- **Production key management:** the HMAC signing key defaults to a development placeholder and must come from a secret manager (e.g. Alibaba Cloud KMS) via `LEDGERPILOT_SIGNING_KEY`.

## Submission artifacts (Global AI Hackathon with Qwen Cloud)

| Requirement | Where |
|---|---|
| Track | Autopilot Agent |
| Public repo + OSS license | this repo, [LICENSE](LICENSE) (Apache-2.0) |
| Proof of Alibaba Cloud Deployment (code file) | [ledgerpilot/planner.py](ledgerpilot/planner.py) (Qwen via Model Studio), [ledgerpilot/odoo_client.py](ledgerpilot/odoo_client.py) (Odoo-on-ECS + Responses-API MCP) |
| Architecture diagram | [docs/architecture.svg](docs/architecture.svg), [ARCHITECTURE.md](ARCHITECTURE.md) |
| Demo video script | [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) |
| Text description | [docs/DEVPOST.md](docs/DEVPOST.md) |
| Blog post (bonus) | [docs/BLOG.md](docs/BLOG.md) |

## License

Apache License 2.0. See [LICENSE](LICENSE).

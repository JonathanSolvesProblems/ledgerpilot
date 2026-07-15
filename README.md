# LedgerPilot

![license](https://img.shields.io/badge/license-Apache--2.0-blue) ![python](https://img.shields.io/badge/python-3.10%2B-blue) ![ledger](https://img.shields.io/badge/gate%20off%20vs%20on-7%20wrong%20writes%20vs%200-brightgreen) ![built on](https://img.shields.io/badge/runs%20on-Alibaba%20Cloud%20ECS%20%2B%20Qwen-ff6a00)

**Same Qwen model, same 39 month-end close tasks, same live ERP. Without the gate, 7 wrong journal entries get posted to the ledger. With it, 0. The model did not get better; the ledger did.**

LedgerPilot is an autonomous month-end-close agent. Qwen proposes journal entries from messy financial inputs; a deterministic, auditable gate is the only path to a write. The point of the project is not that the agent posts to a real ERP (many do). It is that the write side is *measured*: the agent posts to a live Odoo ledger behind a control whose false-write rate is reported with a confidence bound, and the [counterfactual](docs/counterfactual_proof.txt) shows exactly what that control keeps out of the books.

> It is like an AI accountant that posts straight to your ERP, except a hard deterministic gate stands between the model and the ledger, and the entries the gate catches are shown sitting in a real general ledger when you turn it off.

> **Uniqueness claim:** LedgerPilot is the only month-end-close agent that demonstrates its safety as a counterfactual on a real ledger (wrong entries posted with the gate off, zero with it on) and publishes a measured false-write rate with a confidence interval, backed by a deterministic reconciliation check that catches the balanced-but-wrong-account and wrong-amount errors a trial balance never will.

Built for the **Global AI Hackathon Series with Qwen Cloud** (Track 4: **Autopilot Agent**). The backend runs on Alibaba Cloud ECS; Qwen drives the ERP write through an MCP server that puts the gate behind the tool.

## Results

**0. The counterfactual: what the gate keeps out of a real ledger** (`python scripts/counterfactual.py`). The same qwen-flash planner drafts entries for the same 39 close tasks. Then each proposal is posted to a live Odoo two ways: once with the gate off, once with it on. The only variable is the gate.

| | Entries posted | Wrong entries in the ledger |
|---|---|---|
| **Gate OFF** | 39 | **7** |
| **Gate ON** | 32 | **0** |

The seven wrong entries the gate refused were posted for real with the gate off, so you can open the ledger and see them. Each one balances, uses real postable accounts, and passes a trial balance. Examples from the run: salaries paid out of Accounts receivable (`Dr 6000 / Cr 1100`) instead of Cash; a cost-of-goods entry booked to receivables and revenue (`Dr 1100 / Cr 4000`) instead of COGS and payables. Transcript: [docs/counterfactual_proof.txt](docs/counterfactual_proof.txt), generated on Alibaba Cloud ECS. This is the number to remember: **same model, same tasks, same ledger; 7 wrong entries become 0.**

The two numbers below say *why* that works: the gate's decision logic is sound (1), and it holds on real model output (2).

**1. Synthetic gate stress-test** (`python -m eval.harness`, offline, no API key): 204 cases across 12 scenarios and 14 error classes (plus clean controls), run through the gate.

| Metric | Result |
|---|---|
| False-write rate | 0 wrong of 36 approved (≤ 8.33% at 95% CI, Rule of Three) |
| Catch rate | 100% (168/168 = 156 blocked + 12 escalated to a human) |
| False-reject rate | 0% (0/36 clean controls wrongly blocked) |

This measures the **gate's decision logic**, not a model. It is a stress-test: the clean controls are correct entries, so a 0% false-write here means the rules are sound, not that an LLM is accurate.

**2. Measured LLM + gate** (`python -m eval.harness --live`, needs `DASHSCOPE_API_KEY`): the real Qwen planner drafts entries from 39 natural-language close tasks, and the gate judges what the model actually produced. This run executed **on the Alibaba Cloud ECS instance**, calling Alibaba Cloud Model Studio in the same region:

| Model | Model accuracy | Model mistakes caught | False-write rate | Wilson 95% CI |
|---|---|---|---|---|
| **Qwen3.7-Max** (flagship) | 97.4% (38/39) | **1 of 1** | **0%** | ≤ 9.18% |
| qwen-flash (faster, weaker) | 82.1% (32/39) | **7 of 7** | **0%** | ≤ 10.72% |

**The gate caught every mistake either model made, eight in total, and wrote zero wrong entries.** Most were cross-class postings that only reconciliation catches: settling an invoice by crediting accounts receivable instead of cash, or booking cost-of-goods to receivables and revenue. Each one balances, uses real accounts, and reads plausibly. A trial balance passes all of them.

That is the whole argument for the gate: a weaker, cheaper model makes seven times as many mistakes, and the ledger is still clean. **Correctness comes from the gate, not from the model being right.**

The raw transcript is committed at [docs/ecs_proof.txt](docs/ecs_proof.txt). The 0% is not zero by construction: the gate enforces each document's posting policy (the permitted account set) and the amount, not the choice among the accounts that policy permits, so a permitted-but-wrong posting would surface as a nonzero rate (see Known limitations); in this run every model error fell outside the permitted set and was caught.

An earlier run from a local machine ([docs/live_run.txt](docs/live_run.txt)) gave slightly different accuracy (97.4% and 87.2%), because model sampling is not perfectly reproducible even at temperature 0. What was identical in both runs is the part that matters: **every model mistake was caught and nothing wrong was approved.**

The offline corpus includes *semantic* errors a balance check cannot catch (a balanced entry posted to the wrong account, wrong amount, flipped debit/credit, or off by a rounding cent). Those are caught by reconciling each proposal against the source document, which is the point.

**3. Real governed writes to a live ERP.** LedgerPilot posted real, *posted* `account.move` records to a live **Odoo 19** instance, through the actual project path: gate approves, HMAC token, `XmlrpcOdooClient` creates and posts. Nothing is mocked.

| Entry | Amount | Written by | Proof |
|---|---|---|---|
| `MISC/2026/06/0001` (June rent) | 4,500.00 | local run | [docs/real_write_proof.txt](docs/real_write_proof.txt) |
| `MISC/2026/06/0002` (June utilities) | 1,280.00 | **the agent on Alibaba Cloud ECS** | [docs/ecs_proof.txt](docs/ecs_proof.txt) |

Re-running either returns the same entry instead of double-posting (dedupe on the content hash embedded in the move). Reproduce with [scripts/real_odoo_write.py](scripts/real_odoo_write.py).

**4. The backend runs on Alibaba Cloud.** The agent is deployed on an **Alibaba Cloud ECS** instance (`i-t4n1i5p7bz4ypj122e6q`, `ecs.t6-c1m2.large`, Ubuntu 24.04, `ap-southeast-1`), provisioned by [scripts/deploy_ecs.py](scripts/deploy_ecs.py) through the ECS and VPC OpenAPIs. Everything above (the test suite, the gate stress-test, the live Qwen measurement, the counterfactual, and the ERP write) was executed **on that instance**, and it serves the gate's web UI on port 80. [docs/ecs_proof.txt](docs/ecs_proof.txt) is the transcript, including the values returned by the ECS instance metadata service, which only answers on a real ECS instance.

**5. Qwen drives the ERP write through MCP, and still cannot write anything wrong.** The gate is exposed as an **MCP server** ([ledgerpilot/mcp_server.py](ledgerpilot/mcp_server.py)) running on the ECS box, attached to Qwen on Model Studio as an SSE MCP tool through the Responses API. The model is the *caller* of the write tool, not the authority: `validate_write` is read-only, and `execute_approved_write` re-runs the full gate and verifies an HMAC token bound to the entry's content hash before it touches Odoo. [scripts/mcp_demo.py](scripts/mcp_demo.py) shows all three cases end to end:

- **Correct entry:** Qwen calls `validate_write`, then `execute_approved_write`, and posts a real `account.move` (`move_id 3`) to the live Odoo.
- **The model is told to inflate the amount before writing:** the content hash changes, the token no longer verifies, and the server refuses. Tampering by the calling model is detectable, not merely discouraged.
- **Wrong account:** reconciliation refuses it.

Putting the gate behind the tool is what lets the model be given write access without being given the ability to write something wrong. "The model drove the write and still could not corrupt the ledger" is the claim; the demo is the evidence.

---

## The problem

Month-end close is one of the most error-prone, labor-intensive workflows in finance. Teams spend days reconciling bank statements, invoices, and email approvals into journal entries, and a non-trivial fraction of those entries carry errors that surface only at audit. A naive "AI accountant" that writes directly to the ledger is worse than no automation: a single hallucinated or unbalanced journal entry posted to a system of record is an audit finding, not a convenience.

LedgerPilot treats the ledger as a **system of record that must never be corrupted**. The generative model is allowed to *reason and propose*; it is never allowed to *write*. Every write passes a deterministic gate first.

## The thesis: deterministic vs generative

| Concern | Layer | Why |
|---|---|---|
| Reading messy multi-source inputs, extracting line items, drafting entries | **Generative (Qwen3)** | Unstructured, ambiguous, needs reasoning |
| Balance, account validity, period locks, segregation of duties, approval thresholds, **reconciliation to the source document** | **Deterministic (rules engine)** | Must be exact, auditable, reproducible |
| Committing an approved entry to the ledger | **Governed write-back** | Signed token, idempotent on retry, human-in-the-loop gate above threshold |

The deterministic gate is the trust boundary. The headline metric is the **false-write rate**: of the entries the gate *approves*, how many are actually wrong, measured against a seeded-error corpus and reported with a 95% confidence bound.

The gate does not only check that an entry is *well-formed* (it balances, the accounts exist); it checks that the entry is *correct* by reconciling it against the independent source document. That is what lets it catch a confident, balanced, plausible-looking entry that a generative model posted to the wrong account or for the wrong amount.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full diagram and Alibaba Cloud deployment topology.

```
unstructured inputs ──► Qwen planner ──────► DETERMINISTIC GATE ──► signed token ──► Odoo write-back
 (statements, invoices)   (qwen3.7-max +      (balance, accounts,    (HMAC, bound     (idempotent on retry,
                           function calling)   period, SoD, limits,   to the entry)     human gate above
                                               reconcile-to-source)                     threshold)
                                                     │
                                                     └──► rejected / escalated, with the failing check as the reason
```

## Repository layout

```
ledgerpilot/
  config.py            # environment + cloud config (refuses a dev signing key against a live ERP)
  models.py            # JournalEntry / JournalLine / Proposal / GateResult
  chart_of_accounts.py # sample chart of accounts + period state
  planner.py           # Qwen/DashScope generative planner (propose entries, function calling)
  ingest.py            # Qwen-VL document ingestion (implemented; not in the measured path)
  gate.py              # THE deterministic validation gate (scored core, 8 checks)
  tokens.py            # HMAC-signed approval tokens
  writeback.py         # governed write-back (gate re-check -> token -> idempotent commit)
  odoo_client.py       # XmlrpcOdooClient: creates and posts a real account.move
  mcp_server.py        # the gate exposed as MCP tools, so a model can call the write
eval/
  corpus.py            # parametrized seeded-error corpus (12 scenarios x 14 error classes)
  scripted_planner.py  # offline error-injection planner
  harness.py           # offline stress-test + --live measured run
  live_tasks.py        # realistic close tasks with ground truth for the live run
  live_eval.py         # measured false-write rate + Wilson 95% CI + model accuracy
  stats.py             # Wilson score interval
scripts/
  deploy_ecs.py        # provision the Alibaba Cloud ECS backend (ECS + VPC OpenAPI)
  real_odoo_write.py   # one real governed write to a live Odoo
  counterfactual.py    # gate off vs gate on, posted to a live ledger
  mcp_demo.py          # Qwen drives the ERP write through MCP, and cannot write anything wrong
webui.py               # builds web/index.html: a visual frontend over the real gate
tests/                 # 72 tests: gate, reconciliation, tokens, pipeline, clients, MCP, live eval
docs/
  architecture.svg     # system + Alibaba Cloud topology diagram
  DEVPOST.md BLOG.md DEMO_SCRIPT.md
```

## Quick start

```bash
pip install -e ".[dev]"
cp .env.example .env          # add DASHSCOPE_API_KEY; generate a signing key with the line in .env.example
python -m eval.harness        # offline: 204-case synthetic stress-test, no key needed
python demo.py                # end-to-end propose -> gate -> governed write, no key needed
python webui.py               # builds web/index.html; open it in a browser to watch the gate
pytest                        # 72 tests

# with a Model Studio key in .env (auto-loaded):
python -m eval.harness --live # MEASURED false-write rate on real Qwen output + Wilson CI
python scripts/live_close.py  # real Qwen proposals + gate + governed write to an in-memory ledger
```

The deterministic gate, demo, and offline harness run **without a live ERP and without an API key** (the offline path uses an error-injection planner). The `--live` path targets real Qwen models on Alibaba Cloud Model Studio; the write-back targets a live Odoo 19. In deployment all of this runs on an Alibaba Cloud ECS instance, provisioned with:

```bash
pip install -e ".[deploy]"
export ALIBABA_CLOUD_ACCESS_KEY_ID=... ALIBABA_CLOUD_ACCESS_KEY_SECRET=...
python scripts/deploy_ecs.py     # creates the VPC, security group, key pair and instance
                                 # --destroy releases it
```

## Impact and compliance

Month-end close is slow and error-prone at scale, and the harm is per-entry, not abstract:

- A typical close still takes **~6.4 business days**, and only ~40% of finance teams are confident in their numbers (widely cited close benchmarks from APQC and Ventana/ISG).
- **LLMs post wrong entries at a rate you cannot ignore.** On a real accounting-workflow benchmark, the top model scores **83.2%, so roughly 1 in 6 real accounting tasks is still wrong** ([DualEntry Accounting AI Benchmark](https://www.dualentry.com/accounting-ai-benchmark), leaderboard retrieved July 2026); and in single-control agent settings, **45-48% of an agent's failures are silent false successes** (it reports done while the environment says otherwise) ([arXiv:2606.09863](https://arxiv.org/pdf/2606.09863)). A single wrong journal entry posted to a system of record is an audit adjustment, and every audit-adjusting entry carries review, rework, and restatement-risk cost. That per-entry cost is exactly what a hard write gate removes, and the counterfactual above shows it: 7 such entries kept out of the ledger on a 39-task close, from qwen-flash alone.
- Manual GL adjustments are a leading source of **financial-statement error and restatement** ([PCAOB AS 2201, ICFR](https://pcaobus.org/oversight/standards/auditing-standards/details/AS2201)); weak **segregation of duties** is a top enabler of occupational fraud, median loss per scheme in the six figures ([ACFE Report to the Nations](https://www.acfe.com/report-to-the-nations/)).
- Detecting seeded errors is not the same as refusing to write them: the write side is the unsolved part (synthetic controlled-error work such as *Monitoring Agentic Systems Before They're Reliable*, [arXiv:2606.02494](https://arxiv.org/html/2606.02494v1), §4.1).

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
pip install -e ".[dev]"
echo "DASHSCOPE_API_KEY=sk-..." >> .env         # a workspace key from Model Studio
python -m eval.harness --live                    # measured false-write rate + Wilson 95% CI
```

`--live` feeds 39 natural-language close tasks (some deliberately easy to misclassify, e.g. prepaid vs expense, capitalize vs expense) to the real Qwen planner, then judges what the model produced. It reports the model's raw accuracy, how many of its mistakes the gate blocked, and the false-write rate on the entries the gate approved. Switch `LEDGERPILOT_PLANNER_MODEL` to compare models (the results above are `qwen3.7-max` and `qwen-flash`).

## Known limitations (honest scope)

- **The reconciliation policy is per-document, not per-line, so within-document account selection can slip.** Each document type carries a posting policy: the set of accounts permitted for that kind of document (an expense invoice may debit any expense account, and credit cash or accounts payable). The gate enforces that set plus the amount. If a model posts to a permitted-but-wrong account, the gate passes it, so it would surface as a nonzero false-write rate. This is why the metric is falsifiable rather than zero by construction; in the committed runs every model mistake happened to fall outside the permitted set and was caught, so the measured rate was 0%. In production the policy comes from the ERP's own chart-of-accounts structure and the organization's mapping rules maintained by controllers, not from a per-task list; the next step is escalating genuinely ambiguous choices to a human rather than accepting any permitted account. The measured task set is single-account for the same reason; per-line reconciliation against a document's net/VAT split is the next extension.
- **The live measurement varies between runs.** Raw transcripts for both models are committed ([docs/ecs_proof.txt](docs/ecs_proof.txt), run on Alibaba Cloud ECS, and [docs/live_run.txt](docs/live_run.txt), run locally) so the headline numbers are verifiable rather than asserted. Model accuracy moves a few points run to run because sampling is not perfectly reproducible even at temperature 0; the gate's behaviour did not move, catching every mistake in every run.
- **Two confidence-bound methods.** The offline bound uses Rule of Three (3/36 = 8.33%); the live bound uses the Wilson score interval. Both are disclosed inline where they appear; they differ because a bare "0%" deserves an explicit bound and Wilson is the more standard choice for the live proportion.
- **Idempotency is sequential-retry safe, not concurrency safe.** The client searches for the entry's content hash (and its business ref) before creating the move, so a re-run does not double-post. Two agents writing the same entry at the same instant could still race; production would use a unique constraint on the hash in the ERP.
- **Ingestion is implemented but not in the measured path.** `ledgerpilot/ingest.py` uses `qwen3-vl-plus` to read scanned documents, but every measured result in this README starts from a natural-language task or a structured source document, not an image. The vision path is not exercised in the committed transcripts.
- **Rollback and a persisted audit log / review queue are not implemented.** A posted move can be reversed manually in Odoo today; rejected entries are refused with the failing check as the reason, but that record is not yet persisted to a queue. Both are designed into the topology (see ARCHITECTURE.md) and marked Planned.
- **`float()` at the Odoo boundary.** Money is `Decimal` everywhere internally (the models refuse to construct money from a float), but Odoo's XML-RPC monetary fields require float, so the value is converted at the very last step in `writeback.py`. This is the one deliberate exception to the no-float rule, and it is confined to the transport layer.
- **Production key management.** The HMAC signing key defaults to a development placeholder for the offline gate, demo and tests. `load_config()` **refuses to run against a live Odoo** with that default, so a real deployment must supply `LEDGERPILOT_SIGNING_KEY` (from a secret manager such as Alibaba Cloud KMS). The MCP server binds a network-facing write endpoint, so this check is what stands between it and an unauthenticated writer.

## Submission artifacts (Global AI Hackathon with Qwen Cloud)

| Requirement | Where |
|---|---|
| Track | Autopilot Agent |
| Public repo + OSS license | this repo, [LICENSE](LICENSE) (Apache-2.0) |
| Proof of Alibaba Cloud Deployment (code file) | [ledgerpilot/planner.py](ledgerpilot/planner.py) (Qwen on Model Studio, function calling) and [scripts/deploy_ecs.py](scripts/deploy_ecs.py) (the ECS + VPC OpenAPI calls that provisioned the server the backend runs on) |
| Proof the backend ran on Alibaba Cloud (transcript) | [docs/ecs_proof.txt](docs/ecs_proof.txt), generated on ECS instance `i-t4n1i5p7bz4ypj122e6q` |
| Real ERP write (bonus) | [scripts/real_odoo_write.py](scripts/real_odoo_write.py); posted `MISC/2026/06/0001` from local ([docs/real_write_proof.txt](docs/real_write_proof.txt)) and `MISC/2026/06/0002` from ECS ([docs/ecs_proof.txt](docs/ecs_proof.txt)) to a live Odoo 19 |
| MCP integration (Technical Depth) | [ledgerpilot/mcp_server.py](ledgerpilot/mcp_server.py) + [scripts/mcp_demo.py](scripts/mcp_demo.py): Qwen posts `move_id 3` through MCP and is refused when told to tamper |
| Counterfactual (Impact) | [scripts/counterfactual.py](scripts/counterfactual.py), [docs/counterfactual_proof.txt](docs/counterfactual_proof.txt): 7 wrong entries gate-off vs 0 gate-on |
| Architecture diagram | [docs/architecture.svg](docs/architecture.svg), [ARCHITECTURE.md](ARCHITECTURE.md) |
| Demo video script | [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) |
| Text description | [docs/DEVPOST.md](docs/DEVPOST.md) |
| Blog post (bonus) | [docs/BLOG.md](docs/BLOG.md) |

## License

Apache License 2.0. See [LICENSE](LICENSE).

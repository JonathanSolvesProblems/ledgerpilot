# Why I refused to let an LLM write to the ledger

LedgerPilot is a month-end-close agent. It reads the messy pile a finance team drowns in every month (bank statements, supplier invoices, approval emails) and proposes the journal entries that should be posted to the general ledger. The entire project is built around one decision I made on the first day and never walked back: the language model is allowed to *propose* an entry, and it is never allowed to *write* one.

That sounds like a small architectural detail. It is actually the whole product.

## A wrong journal entry is not a bug you patch

Most LLM demos treat a mistake as a retry. In accounting it is not. A single hallucinated or mis-posted journal entry landing in a system of record is an audit finding. It flows into a trial balance, into financial statements, and possibly into a restatement. Weak controls around manual journal entries are one of the classic enablers of both error and fraud, which is why frameworks like SOX 404 and COSO exist in the first place. An "AI accountant" that writes directly to the ledger is not a convenience. It is a liability with a chat interface.

So I drew a hard line and called it the gate. Reading and drafting are messy, ambiguous, reasoning-heavy work, and that is exactly what a generative model is good at. Deciding whether something is allowed to touch the ledger is exact, auditable, reproducible work, and that belongs in deterministic code. The gate is the trust boundary between those two worlds.

## The gate has no model in it, on purpose

The gate is a plain Python rules engine with no LLM call, no network I/O, and no randomness anywhere in it. Given the same entry and the same ledger state it returns the same verdict every time, so it is fully reproducible and I can put it under a debugger and a test suite. Money is `Decimal` only; a float amount is rejected rather than silently rounded. It runs eight checks: balance, account validity, no self-contra, positive amounts, period lock, segregation of duties (preparer cannot equal approver), an approval threshold that forces a human sign-off above a limit, and reconciliation to the source document. Each check maps to a named control, so "the gate approved this" translates directly into "these controls were satisfied."

Nothing reaches the ledger unless every hard check passes. The model can propose anything it likes. The gate is the only door.

## The check I care about most: balanced but wrong

Double-entry balancing is necessary but not sufficient, and this is the part most people miss. An entry can tie to the cent and still be completely wrong. Transpose two digits and debits still equal credits. Post rent to the bank-charges account instead of the rent account and it still balances, because both are valid, postable accounts. A naive trial-balance check waves both through. These are exactly the confident, well-formed, wrong entries a generative planner produces.

The reconciliation check is what catches them. When a proposal arrives with the source document that produced it, the gate compares the entry's total against the authoritative document total, and checks that the debit and credit accounts fall inside the posting policy for that document type. A transposed amount no longer matches the invoice. A valid-but-wrong account is no longer in the allowed set. In accounting terms these are errors of commission and errors of principle, and they are the ones a balance check can never see. Reconciling against independent evidence is the only deterministic way to catch a plausible lie.

## Putting the LLM in the eval loop

My first version tested the gate in isolation. That proves the rules are correct. It does not prove the system is safe once a real model is feeding it, because the interesting failures live in the handoff. So I stopped testing the gate alone and put a planner in front of it, then measured the pipeline end to end.

I run this two ways. The offline path uses an error-injection planner that builds the correct entry for a scenario and then introduces exactly one documented failure mode, so I can stress-test the gate across every error class at scale with no API key and no cost. The live path swaps in the real Qwen planner and measures what the actual model plus gate does, validating the model's output against a class-level posting policy that is independent of the answer, so a plausible-but-wrong posting can pass and the number is genuinely falsifiable. Both hand the gate the same source document the planner was given, so the reconciliation check runs against real evidence rather than a convenient copy. The offline corpus is twelve domain-credible scenarios (rent, payroll, revenue, cost of goods, prepaid, accruals, and so on) expanded across amounts and fourteen error classes into 204 cases. Building that corpus is the part that needed actual accounting knowledge, and it is the part that is hard to clone.

## Measuring a false-write rate, with a bound

The number the project lives or dies on is the false-write rate: of the entries the gate *approved*, how many were actually wrong. Not accuracy, not touch-free percentage. Wrong entries that got written.

On the offline stress-test it is zero false writes out of 36 approved entries, 100% of the 168 seeded errors handled (most blocked, the large ones escalated to a human), and zero of the 36 clean controls wrongly rejected. But I refuse to report that as a flat "0%", because zero observed failures is not the same as zero failures. A 95% confidence bound puts the true rate at or below about 8.3%, so I report it as "0 of 36, at most 8.3% at 95% CI." That is the honest statement.

Then I ran it live against real Qwen output on Alibaba Cloud Model Studio, across 39 close tasks, with the planner using function calling to look up account codes. Qwen3.7-Max was 97.4% accurate. It made one mistake, booking a software invoice to a prepaid asset instead of an expense, and the gate caught it. Then I ran the faster, weaker qwen-flash: 87.2% accurate, five mistakes, and the gate caught all five, including a cost-of-goods entry it tried to post to accounts receivable and revenue. Six model mistakes across two models, six caught, and zero wrong entries written by either one. The false-write rate was 0% with Wilson upper bounds of 9.18% and 10.15%, and I committed the raw transcript to the repo. That number is not zero by construction: the honest boundary is within-class account selection, because the gate enforces the account class and the amount, not the choice between two accounts of the same class, so a within-class error would surface as a nonzero rate. In this run every error was cross-class and caught, and closing that within-class gap by escalating ambiguous choices is the next step. A production claim would still need a prospective study against real closes with a gold standard, and I would rather say that plainly than quote a number I cannot defend.

## Building it on Qwen Cloud

Concretely, the planner calls `qwen3.7-max` on Alibaba Cloud Model Studio through the OpenAI-compatible endpoint, at temperature 0 with JSON-object output and a strict entry schema, and steps up to the thinking variant for harder cases. Document and email ingestion uses `qwen3-vl-plus` to pull line items out of scanned statements and invoices. The write-back targets an Odoo instance on Alibaba Cloud ECS, and it mirrors Odoo's MCP tools: a `validate_write` that returns a checked plan and an `execute_approved_write` that only commits behind an explicit confirm, wired over SSE MCP through Model Studio's Responses API. Every approval is carried by an HMAC token bound to the exact entry, so a stale or tampered approval cannot authorize a different write.

The model does the reading. The gate does the deciding. The ledger only ever hears from the gate. That boundary is not a feature of the product. It is the product.
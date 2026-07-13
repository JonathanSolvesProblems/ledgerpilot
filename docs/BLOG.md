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

I run this two ways. The offline path uses an error-injection planner that builds the correct entry for a scenario and then introduces exactly one documented failure mode, so I can stress-test the gate across every error class at scale with no API key and no cost. The live path swaps in the real Qwen planner and measures what the actual model plus gate does, validating the model's output against a per-document posting policy that is independent of the answer, so a plausible-but-wrong posting can pass and the number is genuinely falsifiable. Both hand the gate the same source document the planner was given, so the reconciliation check runs against real evidence rather than a convenient copy. The offline corpus is twelve domain-credible scenarios (rent, payroll, revenue, cost of goods, prepaid, accruals, and so on) expanded across amounts and fourteen error classes into 204 cases. Building that corpus is the part that needed actual accounting knowledge, and it is the part that is hard to clone.

## Measuring a false-write rate, with a bound

The number the project lives or dies on is the false-write rate: of the entries the gate *approved*, how many were actually wrong. Not accuracy, not touch-free percentage. Wrong entries that got written.

On the offline stress-test it is zero false writes out of 36 approved entries, 100% of the 168 seeded errors handled (most blocked, the large ones escalated to a human), and zero of the 36 clean controls wrongly rejected. But I refuse to report that as a flat "0%", because zero observed failures is not the same as zero failures. A 95% confidence bound puts the true rate at or below about 8.3%, so I report it as "0 of 36, at most 8.3% at 95% CI." That is the honest statement.

Then I ran it live against real Qwen output, across 39 close tasks, with the planner using function calling to look up account codes. This ran on the Alibaba Cloud ECS instance the agent is deployed to, calling Model Studio in the same region.

Qwen3.7-Max was 97.4% accurate. It made one mistake and the gate caught it. Then I ran the faster, weaker qwen-flash: 82.1% accurate, seven mistakes, and the gate caught all seven. Eight model mistakes across the two models, eight caught, zero wrong entries written by either one.

The mistakes are worth dwelling on. Most were settlement errors: paying an invoice by crediting accounts receivable instead of cash, or booking cost-of-goods to receivables and revenue. Every one of those entries balances. Every one uses real, postable accounts. Every one reads perfectly plausibly. A trial balance waves all of them through, and so would any gate that only checks that debits equal credits. They are caught by exactly one thing: reconciling the proposal against the source document it claims to represent.

That is also the result I care about most. I swapped in a model that makes seven times as many mistakes, and the ledger stayed clean. The correctness of the ledger is a property of the gate, not of the model happening to be right.

The false-write rate was 0% with Wilson upper bounds of 9.18% and 10.72%, and I committed the raw transcript to the repo. That number is not zero by construction: the honest boundary is the posting policy, which is per-document, not per-line. The gate enforces the set of accounts a document type permits and the amount, not the choice among the accounts that set allows, so a permitted-but-wrong posting would surface as a nonzero rate. In this run every error fell outside the permitted set and was caught, and closing that gap by escalating ambiguous choices is the next step. Model accuracy also moves a few points between runs, because sampling is not perfectly reproducible even at temperature 0; the gate's result did not move. A production claim would still need a prospective study against real closes with a gold standard, and I would rather say that plainly than quote a number I cannot defend.

## Building it on Qwen Cloud

The backend runs on an Alibaba Cloud ECS instance, provisioned from code: `scripts/deploy_ecs.py` calls the ECS and VPC OpenAPIs to create the key pair, security group, network and instance, and the same script tears it down. From that box, the planner calls `qwen3.7-max` on Alibaba Cloud Model Studio through the OpenAI-compatible endpoint at temperature 0, using function calling: it has to call a `lookup_accounts` tool to discover valid account codes rather than being handed the chart, so account selection is grounded in real data. Document and email ingestion uses `qwen3-vl-plus` to pull line items out of scanned statements and invoices.

The write-back is demonstrated against a live Odoo 19: the same gated path created and posted real `account.move` records over XML-RPC, one from my laptop and one from the agent running on ECS (it can also route through the Odoo MCP server on Model Studio's Responses API). Every approval is carried by an HMAC token bound to the exact entry, so a stale or tampered approval cannot authorize a different write, and the entry's content hash is embedded in the move so a re-run finds the existing entry instead of posting a second one.

The model does the reading. The gate does the deciding. The ledger only ever hears from the gate. That boundary is not a feature of the product. It is the product.
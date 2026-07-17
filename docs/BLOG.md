# I let an AI post to a real general ledger, twice

Same model. Same thirty-nine month-end close tasks. Same live Odoo instance. The only difference between the two runs was a few hundred lines of boring Python sitting between the model and the database.

In the first run, five wrong journal entries landed in the ledger. Salaries paid out of accounts receivable. A cost-of-goods purchase booked as though it were a sale. Every one of them balances to the cent. Every one uses real, postable accounts. Every one passes a trial balance. They are still sitting there, and you can open them.

In the second run, the same model made the same mistakes, and zero of them reached the ledger.

The model did not get better. The ledger did.

That is LedgerPilot, and this is what I learned building it.

## A wrong journal entry is not a bug you patch

Most LLM demos treat a mistake as a retry. In accounting it is not. A single mis-posted journal entry landing in a system of record is an audit finding. It flows into a trial balance, into financial statements, and possibly into a restatement. Weak controls around manual journal entries are one of the classic enablers of both error and fraud, which is why SOX 404 and COSO exist. An "AI accountant" that writes directly to the ledger is not a convenience. It is a liability with a chat interface.

And the models are not good enough to skip the question. On a real accounting-workflow benchmark the best model still gets roughly one task in six wrong. You cannot ship that straight into a general ledger and call the remainder a rounding error.

So I drew a hard line and called it the gate. Reading and drafting are messy, ambiguous, reasoning-heavy work, which is exactly what a generative model is good at. Deciding whether something may touch the ledger is exact, auditable, reproducible work, which belongs in deterministic code. The gate is the boundary between those two worlds, and it is the only door.

## The gate has no model in it, on purpose

The gate is a plain Python rules engine. No LLM call, no network, no randomness, no clock. Given the same entry and the same ledger state it returns the same verdict every time, so I can put it under a debugger and a test suite. Money is `Decimal` only; a float amount is rejected rather than silently rounded.

It runs eight checks: balance, account validity, no account on both sides, positive amounts, period lock, segregation of duties, an approval threshold that forces a human sign-off above a limit, and reconciliation to the source document. Each maps to a named control, so "the gate approved this" translates into "these controls were satisfied."

It also fails closed. Any failing check other than the human-approval threshold rejects. That sounds obvious and it was not what I wrote first, which I will come back to.

## The check that matters: balanced but wrong

Double-entry balancing is necessary and nowhere near sufficient. This is the part most people miss.

An entry can tie to the cent and be completely wrong. Transpose two digits and debits still equal credits. Post rent to bank charges instead of rent expense and it still balances, because both are real, postable accounts. A trial balance waves both through. These are precisely the confident, well-formed, wrong entries a generative planner produces.

The reconciliation check is what catches them. When a proposal arrives with the source document that produced it, the gate compares the entry's total against the document total, and checks that the debit and credit accounts fall inside the posting policy for that document type. A transposed amount no longer matches the invoice. A valid-but-wrong account is no longer in the permitted set.

In accounting these are errors of commission and errors of principle, and a balance check can never see them. Reconciling against independent evidence is the only deterministic way to catch a plausible lie.

## Measuring the thing that actually matters

Most agent projects report accuracy. Accuracy is the model's problem. I wanted the number that describes *my* problem: of the entries the gate approved, how many were wrong? Wrong entries that got written. I called it the false-write rate.

My first attempt at measuring it was garbage, and it took me embarrassingly long to notice. I handed the gate the correct answer for each task as its "source document," so the gate could not possibly approve a wrong entry. The result was zero by construction: a number that could never have come out any other way, which makes it worthless. I tore it out and rebuilt the evaluation so the gate validates each proposal against a posting policy that is independent of the single correct answer. Now a plausible-but-wrong posting *can* pass and be counted, which is the only reason the zero means anything.

Offline, against 204 seeded-error cases across fourteen error classes: zero false writes of 36 approved, every one of the 168 seeded errors caught or escalated, and zero of the 36 clean controls wrongly blocked. That last number is the one people forget. A gate that blocks everything has a perfect catch rate and is useless; the false-reject rate is what proves the catch rate was not bought by over-blocking.

I also refuse to report "0%" flat. Zero observed failures is not zero failures. A 95% confidence bound puts the true rate at or below about 8.3%, so I report "0 of 36, at most 8.3% at 95% CI."

Then I ran it live against real Qwen, on the Alibaba Cloud box the agent is deployed to. Qwen3.7-Max: 97.4%, one mistake, caught. The cheaper qwen-flash: 82.1%, seven mistakes, all seven caught. Eight model mistakes, eight caught, zero wrong writes.

Swapping in a model that makes seven times as many mistakes left the ledger just as clean. That is the entire thesis in one experiment: the correctness of the ledger is a property of the gate, not of the model happening to be right.

## The counterfactual, and why I bothered

All of the above is still just me asserting that a control works. So I ran the experiment properly and gave it a control arm.

The same planner drafts entries for the same 39 tasks. Then every proposal is posted to a live Odoo twice: once with the gate off, once with it on. The only variable is the gate. Gate off, five wrong entries are posted for real. Gate on, zero.

The wrong ones are still in the ledger under references starting `NG-WRONG`, and each one's narration says what the model booked, what the source document required, and that it is only there because the gate was off. Odoo totals them for you: twenty-one thousand dollars of wrong entries, sitting in a real general ledger, all balanced, all passing a trial balance.

This changed how I think about safety claims. "0% false-write rate with a 95% bound" is a statement about my test harness. "Here are the five wrong entries in the ledger, and here is the same ledger with the gate on" is a statement about the world. One of those a reader can check by looking.

The count moves between runs, because model sampling is not reproducible even at temperature 0. Across my runs the gate-off number has been five to seven. The gate-on number has been zero every single time. That asymmetry is the claim, and it is the part that does not drift.

## Giving the model the pen anyway

Here is the part I am proudest of, and it started as an argument with myself.

The safe design is obvious: never let the model near the write. But that is not how anyone will actually build these systems. People are going to hand models MCP tools that write to real systems, because that is the entire point of MCP. So the interesting question is not "can I keep the model away from the database," it is "can I hand the model the write tool and still be safe?"

So I did. The gate is exposed as an MCP server, attached to Qwen through Model Studio's Responses API. The model calls the tools itself: `validate_write` is read-only, and `execute_approved_write` is the only path to the ledger.

The trick is that the gate lives inside the server, not in the prompt. Instructing a model to "not modify any amounts" is not a control, it is a wish. Instead, `execute_approved_write` re-runs the full gate and verifies an HMAC token bound to the entry's content hash before it touches Odoo. The token is minted by the part of the system that holds the signing key; the model only relays it.

Then I tried to break it. I told the model to inflate the amount from 2,400 to 9,900 before writing, using the same approval token. It tried. The server recomputed the content hash, the signature no longer verified, and the write was refused:

```
"refused": "approval token rejected: Token hash does not match entry; entry was modified."
```

The model is holding the pen and it still cannot forge the cheque. That property survives *because* the gate is behind the tool rather than in the instructions.

I also had to make the hash cover more than I first thought. My original hash covered the amounts and accounts. It did not cover the memo, or who approved the entry. Which meant a valid token still verified after you rewrote the narration or forged the approver's name. Tamper-evident for cents, forgeable for the audit trail. On a product whose entire thesis is that the ledger must not be corrupted, the approver's name is not a free-text field.

## From pixels to a posting decision

The other half is multimodal. `qwen3-vl-plus` reads a scanned invoice image and extracts the record: document id, date, vendor, net, tax, gross, line items. That extraction drives the planner, and the gate then reconciles the resulting entry against the document the vision model just read. The amount the gate reconciles against was never typed by a human.

Book it correctly and the gate approves. Nudge the same invoice to the wrong account and it balances, uses real accounts, and is refused. The thesis holds one layer further back, where the wrong entry is derived from a real document rather than a fixture.

Running it also caught a bug I would never have found by reading the code. The prompt asked for a "counterparty" and never said which party that meant, so the model returned the bill-to, which is *my own company*, instead of the vendor on the letterhead. That silently misattributes every transaction. The fix was one sentence in the prompt. The lesson was that an ambiguous field name in a prompt is a bug, not a style issue.

## What broke when I tried to break it

I ran an adversarial review over my own gate late in the build, and it found real holes. I am listing them because a safety claim from someone who never tried to break their own thing is worth nothing:

- **An entry with no lines was approved.** Zero debits equals zero credits, so it balanced, and every other check passed vacuously. The gate happily authorised a write that moved no value.
- **A wash entry was approved.** `Dr 6100 5,000 / Cr 6100 5,000` balances, uses a real account, and does nothing. Self-contra was checked per line rather than per account.
- **The gate failed open.** Only checks marked `ERROR` rejected. Any check added later at a softer severity would have failed silently and been approved anyway.
- **A cancelled entry blocked a legitimate one.** The idempotency guard matched cancelled moves, so after a cleanup, two thirds of a run silently never posted and the caller got handed the ids of moves that no longer existed.
- **One dropped connection killed a run mid-ledger.** `xmlrpc.client` reuses a single connection, so one expired keep-alive poisoned every later call and left the ledger half written.

Every one of those is now a fix and a regression test. The suite went from 53 tests to 79. Finding them myself was uncomfortable; finding them after a judge did would have been worse.

## Building it on Qwen Cloud

The backend runs on an Alibaba Cloud ECS instance, provisioned from code: `scripts/deploy_ecs.py` calls the ECS and VPC OpenAPIs to create the key pair, security group, network and instance, and tears it all down again. From that box the planner calls `qwen3.7-max` on Model Studio at temperature 0 using function calling. The chart of accounts is deliberately kept out of the prompt, so the model has to call a `lookup_accounts` tool to discover valid codes and account selection is grounded in real data rather than invented.

Everything else runs there too: the test suite, the 204-case stress test, the live measurement, the MCP server, the counterfactual, and the real writes into a live Odoo 19. The instance metadata service only answers from inside a real ECS box, which is what makes the transcript in the repo worth anything.

## What I would tell myself at the start

Measure the thing you are actually claiming. I claimed the write side was safe and spent my first evaluation measuring whether the rules were internally consistent, which is a different and much easier question.

Make the number falsifiable or do not report it. A metric that cannot come out badly is decoration.

And if you are going to claim a control works, turn it off and show what happens. Every safety argument I made in prose was less convincing than five wrong entries sitting in a ledger with the gate off, next to the same ledger with it on.

The model does the reading. The gate does the deciding. The ledger only ever hears from the gate. That boundary is not a feature of the product. It is the product.

---

*LedgerPilot is open source (Apache-2.0): [github.com/JonathanSolvesProblems/ledgerpilot](https://github.com/JonathanSolvesProblems/ledgerpilot). Built for the Global AI Hackathon with Qwen Cloud, Track 4. Every number above is reproducible from the repo, and the raw transcripts are committed alongside the code.*

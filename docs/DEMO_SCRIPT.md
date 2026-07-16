Two recording scripts, grounded in the exact on-screen output. The demo opens on the reconciliation catch and refuses the write; the suite passes (76 tests); the harness prints the 0.00% / <=8.33% CI numbers.

> Never narrate a specific model mistake count. Sampling varies between runs (the flagship is stable at 97.4%, qwen-flash moves a few points), so state the invariant instead: every mistake caught, zero wrong writes, every run. See the note at the end of `demo_script.md`.

> The primary, up-to-date shot list and voiceover is `demo_script.md` in the repo root, which leads with the counterfactual (wrong entries gate-off vs 0 gate-on) and the MCP tamper scene. This file is the longer reference version; where they differ, follow `demo_script.md`.

---

# SCRIPT 1: Demo video voiceover (target 2:52, hard cap 3:00)

Format: `TIME | ON SCREEN (exact action) | NARRATION (voiceover)`. One flagship feature (the deterministic gate) shown deeply on one real invoice. Record narration at ~135 wpm.

Pre-roll setup (not recorded): open a full-screen terminal, dark theme, large font, in the repo root. Have `demo.py` output already generated once so you know where each scene lands. Have `ARCHITECTURE.md` / `docs/architecture.svg` open in a second tab.

---

**[0:00 - 0:14] COLD OPEN: the save**

ON SCREEN: Start on a static terminal frame pre-scrolled to the `SCENE 1` block of `python demo.py`. The eight gate checks are visible with the last line highlighted:
`[XX ] reconciliation  Does not reconcile to INV-RENT-06: debit accounts ['6900'] not permitted for invoice (allowed ['6100']).`
then `--> GATE DECISION: REJECTED` and `WRITE-BACK REFUSED`. Push in slightly on the reconciliation line and REJECTED.

NARRATION: "This journal entry balances to the cent. Every account on it is real and postable. A trial balance waves it straight through. And it is still wrong. It books the June rent to bank fees. LedgerPilot caught that, and refused to post it."

---

**[0:14 - 0:38] The problem and the thesis**

ON SCREEN: Cut to a title card: "LedgerPilot" with the subtitle "An autonomous month-end-close agent with a deterministic write gate." Then cut to the README "deterministic vs generative" table.

NARRATION: "Month-end close is people stitching invoices, statements, and email approvals into journal entries. Hand that to an AI that writes straight to the ledger, and one confident, wrong entry is not a convenience, it is an audit finding. So LedgerPilot splits the job. The Qwen model reasons and proposes. It never writes. A deterministic gate is the only path to the ledger."

---

**[0:38 - 1:22] propose -> gate -> governed write (demo.py)**

ON SCREEN: Run `python demo.py` from the top. Let SCENE 1 scroll and rest on it for ~6 seconds (the eight named checks on the real rent invoice, reconciliation failing, write refused). Then let SCENE 2 land: same invoice posted to 6100, all eight checks green, `GATE DECISION: APPROVED`, `WRITE-BACK: written  odoo_move_id=1`. Then SCENE 4: `NEEDS_HUMAN`, then the second pass `APPROVED` after cfo sign-off, `odoo_move_id=2`. Then SCENE 5: `re-submit JE-301 -> idempotent_skip`.

NARRATION: "Here is the whole path on one real invoice. The gate runs eight deterministic checks: balance, valid accounts, period lock, segregation of duties, approval limits, and the one that matters most here, reconciliation against the source document. That is what catches a balanced entry posted to the wrong account. Post it correctly and the gate approves it, binds it to an HMAC-signed token, and writes one account.move to Odoo. A large entry is not blocked, it is escalated to a human, then written once the CFO signs. And re-submitting the same entry does not double-post. Nothing wrong ever reaches the ledger."

---

**[1:22 - 2:05] The measured false-write rate (the harness)**

ON SCREEN: Run `python -m eval.harness`. Rest on the final report block. Highlight the three lines in turn:
`FALSE-WRITE RATE:  0.00%  (0 wrong of 36 approved; <= 8.33% at 95% CI)`
`catch rate:  100.00%  (168/168 = 156 blocked + 12 escalated to human)`
`false-reject rate:  0.00%  (0/36 controls wrongly blocked)`

NARRATION: "And I measure it. This offline run is a 204-case synthetic stress-test, built with real accounting knowledge, including semantic errors a balance check cannot see: wrong amount, wrong account, a flipped debit and credit. Of the thirty-six entries the gate approved, zero were wrong, and I report that honestly with a ninety-five-percent confidence bound at or below eight point three percent. It handled all one hundred sixty-eight seeded errors, blocking most and escalating the large ones to a human, and it wrongly blocked zero clean entries. The live run swaps in the real Qwen model and measures the same number on what the model actually produced. No close vendor I found publishes a number like this on the write side."

---

**[2:05 - 2:38] Architecture**

ON SCREEN: Switch to `docs/architecture.png` (or the ARCHITECTURE.md ASCII diagram). Trace the flow left to right with the cursor: unstructured inputs, qwen3-vl-plus ingestion, qwen3.7-max planner, the DETERMINISTIC GATE, HMAC token, Odoo write-back. Briefly show the "Gate check to control framework" table in the README.

NARRATION: "The generative layers run on Alibaba Cloud Model Studio: Qwen3-VL reads the documents, Qwen3.7-Max drafts the entry. The gate is pure, side-effect-free Python, so every verdict is reproducible and auditable. Each check maps to a named control: SOX 404 and COSO for reconciliation and segregation of duties, an approval matrix for the human-in-the-loop threshold. The write reaches a real Odoo system of record over XML-RPC, or through the Model Studio Responses API as an SSE MCP tool, so the same governance runs on the model side too."

---

**[2:38 - 2:52] Close and honest scope**

ON SCREEN: Uniqueness-claim card (trimmed from the README opening): "The only close agent that shows you the wrong entries with the gate off, then zero with it on, and publishes a measured false-write rate with a confidence bound." Below it: "Track 4: Autopilot Agent" and the repo URL with the Apache-2.0 badge.

NARRATION: "That is the claim: the only close agent that publishes a measured false-write rate, backed by a deterministic check that catches the balanced-but-wrong entries a trial balance never will. It runs on Alibaba Cloud, it writes to a real ERP, and across every run so far, every mistake the model made was caught and nothing wrong ever reached the ledger. LedgerPilot: the model proposes, the gate decides."

---

# SCRIPT 2: Proof of Alibaba Cloud Deployment (target 1:05, separate from the demo)

Purpose: satisfy the hackathon's separate proof requirement by showing the backend **running on Alibaba Cloud**, not merely calling it. Four beats: prove we are on an ECS box, run the live Qwen measurement there, post a real ERP entry from there, and show the proof code files. A plain screen-capture voiceover is fine.

Prerequisites: the ECS instance is up (`python scripts/deploy_ecs.py` prints the IP) and `/opt/ledgerpilot/.env` on the box holds the Model Studio key and the Odoo connection. Both are set.

---

**[0:00 - 0:18] Beat 1: we are on an Alibaba Cloud ECS instance**

ON SCREEN:
1. Terminal: `ssh -i ~/.ssh/ledgerpilot_ecs root@47.84.116.56`. The prompt becomes `root@ledgerpilot`.
2. Rest on the login banner: it reads **"Welcome to Alibaba Cloud Elastic Compute Service !"** and the prompt becomes `root@ledgerpilot`.
3. Run these ONE AT A TIME (curl prints no trailing newline, so without the `; echo` the two values run together on screen):
   `curl -s http://100.100.100.200/latest/meta-data/instance-id; echo`  -> `i-t4n1i5p7bz4ypj122e6q`
   `curl -s http://100.100.100.200/latest/meta-data/region-id; echo`    -> `ap-southeast-1`

NARRATION: "This is not my laptop. That is Alibaba Cloud's instance metadata service, which only answers from inside a real ECS instance, and it is telling us the instance ID and region. The LedgerPilot backend runs here."

---

**[0:18 - 0:40] Beat 2: the live Qwen call, from the cloud box**

ON SCREEN:
1. Still on the ECS box: `.venv/bin/python -m eval.harness --live`. Rest on "MEASURED live evaluation", the per-task lines, and the metrics (97.4%, its one mistake caught, 0 false writes).
2. Optional: quick cut to the Model Studio console.

NARRATION: "From that instance, the harness sends real close tasks to qwen3.7-max on Alibaba Cloud Model Studio, in the same region. The planner uses function calling to look up accounts, and every proposal is scored by the deterministic gate. Real model, real gate, running on Alibaba Cloud."

---

**[0:40 - 0:58] Beat 3: a real posted entry in a live Odoo, written from the cloud box**

ON SCREEN:
1. Run `.venv/bin/python scripts/real_odoo_write.py --scenario utilities`. Rest on `write status: written` and `posted move: MISC/2026/06/0002 ... state 'posted'`.
2. Cut to the Odoo web app (Accounting > Journal Entries), open `MISC/2026/06/0002`: Dr 6200 Utilities 1,280.00 / Cr 1000 Cash 1,280.00, posted.

NARRATION: "And it writes. The same gated path posts a real journal entry to a live Odoo 19 from this cloud instance: the gate approves, signs a token, and the client creates and posts this account.move. Here it is in the ledger. Re-running returns the same entry instead of double-posting."

---

**[0:58 - 1:05] Beat 4: the proof code files**

ON SCREEN:
1. Open `scripts/deploy_ecs.py`: the `ALIBABA CLOUD DEPLOYMENT PROOF` header and the `run_instances` / `create_security_group` calls.
2. Cut to `ledgerpilot/planner.py`: the same header and the function-calling loop against Model Studio.
3. Finish in a browser at `http://47.84.116.56/`, URL bar visible, clicking one gate scenario.

NARRATION: "Two code files, two Alibaba Cloud services: deploy_ecs.py calls the ECS and VPC APIs that built this server, and planner.py calls Qwen on Model Studio. And the gate's UI is served straight off the instance."

---

## Notes for recording (read before shooting)

The demo opens on the semantic save: the "Wrong account (the save)" tab in the web UI (`python webui.py`, open `web/index.html`), or `SCENE 1` in `demo.py`, proposes a balanced entry posted to the wrong account, and the gate refuses it. Reconciliation runs on the exact path that writes to the ledger, so this is the true behavior on camera, not staged. The full suite passes.

Caveats:
- Script 1 is fully recordable offline (the web UI, `demo.py`, and the offline harness need no key). Better: open the web UI at the live ECS URL so the address bar doubles as deployment proof.
- Script 2 runs on the ECS instance. Beat 1 (the metadata service) is what proves the backend is *running on* Alibaba Cloud rather than merely calling it, which is the eligibility bar.
- Host on YouTube or Vimeo (both appear on both versions of the rules), set PUBLIC. Keep the demo strictly under 3:00; judges are not required to watch past it.
- Deployment proof: submit the code-file link (`scripts/deploy_ecs.py`, and `ledgerpilot/planner.py` if a second is allowed), an ECS console screenshot showing the instance Running, and this short separate recording.
- Keep the ECS box running through the judging window so a judge can open `http://47.84.116.56/` and the live URL in the video still resolves. Release it (`python scripts/deploy_ecs.py --destroy`) only after judging closes.
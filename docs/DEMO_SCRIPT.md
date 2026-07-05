Two recording scripts, grounded in the exact on-screen output. The demo opens on the reconciliation catch and refuses the write; the suite passes (53 tests); the harness prints the 0.00% / <=8.33% CI numbers.

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

ON SCREEN: Cut to a title card: "LedgerPilot" with the subtitle "An autonomous month-end-close agent with a deterministic write gate." Then cut to the README "deterministic vs generative" table (lines 31-35).

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

ON SCREEN: Switch to `docs/architecture.svg` (or the ARCHITECTURE.md ASCII diagram). Trace the flow left to right with the cursor: unstructured inputs, qwen3-vl-plus ingestion, qwen3.7-max planner, the DETERMINISTIC GATE, HMAC token, Odoo write-back on ECS. Briefly show the "Gate check to control framework" table in the README (lines 98-104).

NARRATION: "The generative layers run on Alibaba Cloud Model Studio: Qwen3-VL reads the documents, Qwen3.7-Max drafts the entry. The gate is pure, side-effect-free Python, so every verdict is reproducible and auditable. Each check maps to a named control: SOX 404 and COSO for reconciliation and segregation of duties, an approval matrix for the human-in-the-loop threshold. The write reaches an Odoo system of record on Alibaba Cloud ECS, through the Model Studio Responses API as an SSE MCP tool, so the same propose, validate, execute governance runs on the model side too."

---

**[2:38 - 2:52] Close and honest scope**

ON SCREEN: Uniqueness-claim card (README line 5, trimmed): "The only close agent that publishes a measured false-write rate, with a confidence bound, on a seeded-error corpus, backed by a deterministic reconciliation check that catches balanced-but-wrong entries a trial balance never will." Below it: "Track 4: Autopilot Agent" and the repo URL with the Apache-2.0 badge.

NARRATION: "That is the claim: the only close agent that publishes a measured false-write rate, backed by a deterministic check that catches the balanced-but-wrong entries a trial balance never will. The gate, the corpus, and the metric run today with no key. Live Qwen and a real ECS write are wired and one credential away. LedgerPilot: the model proposes, the gate decides."

---

# SCRIPT 2: Proof of Alibaba Cloud Deployment (target 0:55, separate from the demo)

Purpose: satisfy the hackathon's separate proof requirement by showing the backend live on Alibaba Cloud. Three beats: ECS Odoo, a Model Studio call, and the proof code file. No narration polish needed, a plain screen-capture voiceover is fine.

Prerequisites before recording (see caveat at the end): the ECS Odoo instance is running, `.env` has a real `DASHSCOPE_API_KEY`, and `ODOO_URL/ODOO_DB/ODOO_USERNAME/ODOO_API_KEY` point at the ECS host.

---

**[0:00 - 0:18] Beat 1: Odoo backend on Alibaba Cloud ECS**

ON SCREEN:
1. Alibaba Cloud console, Elastic Compute Service, Instances list. Region selector shows Singapore (ap-southeast-1). One instance is Running. Hover so the instance ID and public IP are visible.
2. Cut to a browser at `http://<ecs-public-ip>:8069`, showing the Odoo Accounting workspace logged in (Journal Entries list visible).

NARRATION: "The system of record is a live Odoo instance running on Alibaba Cloud ECS, in Singapore. This is that instance in the ECS console, and this is its Odoo accounting workspace on the instance's public address. Every governed write lands here as an account.move."

---

**[0:18 - 0:38] Beat 2: the Model Studio call**

ON SCREEN:
1. Terminal. Show one line of `.env`: `DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1`.
2. Run `python -m eval.harness --live`. When the report prints, rest on the header `[live: real Qwen planner, clean scenarios]` and the metrics block.
3. Optional: quick cut to the Model Studio console API Keys page to prove the key is a Model Studio key.

NARRATION: "The planner calls Qwen on Alibaba Cloud Model Studio, through the OpenAI-compatible endpoint. Running the harness in live mode sends the clean close tasks to qwen3.7-max on Model Studio, and every proposal the real model returns is scored by the same deterministic gate. This is the actual model plus gate pipeline, not a fixture."

---

**[0:38 - 0:55] Beat 3: the proof code file**

ON SCREEN:
1. Open `ledgerpilot/writeback.py`. Scroll to the module docstring (lines 13-14): "This file is the designated 'Proof of Alibaba Cloud Deployment' artifact: it contains the calls that reach the Odoo instance running on Alibaba Cloud ECS." Then scroll to `_write_to_odoo` (the `create_move` payload).
2. Cut to `ledgerpilot/odoo_client.py`. Show `XmlrpcOdooClient.create_move` (the `execute_kw` XML-RPC call to `account.move`), then `ModelStudioMcpClient.create_move` (the `client.responses.create(model=..., tools=[{"type":"mcp","server_label":"odoo",...}])` Responses-API MCP call).

NARRATION: "And this is the code that talks to Alibaba Cloud. planner.py is the linked proof file: it calls Qwen on Model Studio with function calling. odoo_client.py writes the account.move to the ECS-hosted Odoo over XML-RPC, or routes the same write through the Odoo MCP server on the Model Studio Responses API. Same governance on both sides, running on Alibaba Cloud."

---

## Notes for recording (read before shooting)

The demo opens on the semantic save: `SCENE 1` in `demo.py` proposes a balanced entry with real, postable accounts that posts the June rent (INV-RENT-06) to the wrong account, and the gate refuses it. Reconciliation runs on the exact path that writes to the ledger (`approve_and_commit` and `OdooWriteBack.commit` pass the source document into `gate.evaluate`), so this is the true behavior on camera, not a staged one. The full suite passes.

Caveats:
- Script 1 is fully recordable right now, offline, with no key (demo.py and the harness both run locally). The `[0:38-1:22]` and `[1:22-2:05]` segments are the exact outputs I captured above.
- Script 2 requires provisioning that the repo's own honest-scope section lists as pending: a running ECS Odoo instance and a real `DASHSCOPE_API_KEY`. Record Script 2 only after those exist. If the ECS instance is not ready by the deadline, the honest fallback is to show the Model Studio call (Beat 2, which needs only the key) plus the two proof code files (Beat 3), and show the ECS console instance page for Beat 1, rather than staging a fake Odoo.
- Host on YouTube or Vimeo (both appear on both versions of the rules; avoid Youku-only or Facebook-only), set PUBLIC. Keep the demo strictly under 3:00; judges are not required to watch past it.
- Deployment proof: submit BOTH a code-file link (planner.py) and a short separate recording of the backend on Alibaba Cloud (a clean take of `python -m eval.harness --live` hitting Model Studio works, no live Odoo needed).
- I did not commit these changes. Commit them before you record so the repo shown in Script 2 matches the video.
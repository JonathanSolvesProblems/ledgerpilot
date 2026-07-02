# LedgerPilot — Definitive Next-Steps Plan to Win (Qwen Cloud Hackathon)

Today Jun 29, 2026. Hard deadline **Jul 9, 2026, 5:00pm EDT = 2:00pm PDT** (https://qwencloud-hackathon.devpost.com/rules). ~10 days. Track to enter: **Autopilot Agent** (an agent that autonomously executes writes to a system of record with governance — the tightest fit of the five; reasoning in D6). Judging weights: Innovation & AI Creativity 30% + Technical Depth & Engineering 30% + Problem Value 25% + Presentation 15%. The 60% at the top is won by a LIVE Qwen-produced number and a real ERP write, both of which are credential-gated, so credentials are the critical path.

---

## ⭐ THE SINGLE MOST IMPORTANT NEXT ACTION (do in the next hour, Jun 29)

- [ ] **[USER] Redeem the Qwen Cloud hackathon voucher AND mint a Model Studio API key today.** Voucher approval can take days and it gates the two highest-weighted deliverables (live Qwen metric + real write = 60% of score). Do not let this sit.
  - Voucher/credit request form: https://www.qwencloud.com/challenge/hackathon/voucher-application
  - Create account + generate `DASHSCOPE_API_KEY` (free trial quota works immediately, before the voucher clears, so I can start live runs the moment you paste the key): https://modelstudio.console.alibabacloud.com/
  - Free-quota how-to: https://docs.qwencloud.com/resources/free-quota#get-the-free-quota
  - Paste the key into a local `.env` as `DASHSCOPE_API_KEY=...` and send it to me (or set it in the shell I run in). Everything in Group A/C that needs live cloud unblocks the instant this exists.

---

## (A) BLOCKING / CREDENTIALS — only USER can do these

- [ ] **A1 [USER] — Redeem voucher.** (see top action) — **Day 1 (Jun 29).** https://www.qwencloud.com/challenge/hackathon/voucher-application
- [ ] **A2 [USER] — Generate `DASHSCOPE_API_KEY` in Model Studio console.** — **Day 1 (Jun 29).** https://modelstudio.console.alibabacloud.com/ · Base URL to configure: `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` (this is what the hackathon Resources page tells participants to use: https://qwencloud-hackathon.devpost.com/resources). Models: text `qwen3.7-max`, vision `qwen3-vl-plus`.
- [ ] **A3 [USER] — Provision one Alibaba Cloud ECS instance and run Docker Odoo + the agent runtime on it.** This is the "backend running on Alibaba Cloud" proof surface (satisfies both the deployment code-file link and the separate proof recording). One small ECS box hosting Odoo-in-Docker plus the LedgerPilot process is the minimum viable footprint. — **Day 2–3 (Jun 30 / Jul 1).** ECS: https://www.alibabacloud.com/en/product/ecs · (fallback compute if you prefer serverless: Function Compute https://www.alibabacloud.com/en/product/function-compute). Send me the ECS host/SSH so I can deploy and wire `XmlrpcOdooClient` to it.
- [ ] **A4 [USER] — Join the Qwen Cloud Discord for support / voucher-status chasing.** — **Day 1 (Jun 29).** https://discord.gg/cDEHSV4Qqj
- [ ] **A5 [USER] — Confirm eligibility** (not resident/domiciled in an unsupported/sanctioned jurisdiction per rules). You are in scope as an individual; just a 2-minute read: https://qwencloud-hackathon.devpost.com/rules

---

## (B) CODE / DOCS — I can automate now, NO credentials needed

Start immediately, in parallel with A. Files below are exact paths in `c:\Users\Jon_A\OneDrive\Desktop\Projects\Time2\Qwen`.

- [ ] **B1 [I automate] — FIX R1 (CRITICAL): wire reconciliation into the real write path + add a regression test.** `approve_and_commit` (`ledgerpilot/writeback.py:139`), `OdooWriteBack.commit` (`ledgerpilot/writeback.py:63`), and `demo.py:65` must accept and pass the `SourceDocument` into `gate.evaluate`, so `_check_reconciliation` (`ledgerpilot/gate.py:212`) actually runs on the ledger-touching path. Add a test: balanced entry to wrong account (6900 vs 6100) must be `rejected` and must NOT write. This is the highest leverage single change; today it self-falsifies the headline thesis. — **Day 1 (Jun 29).**
- [ ] **B2 [I automate] — FIX R5: put `odoo_client.py` in the default write path and add an integration test that actually posts a move** (against `FakeOdoo` now, swapped to the real ECS Odoo in B/C once A3 lands). Exercise `XmlrpcOdooClient`; make the Responses-API MCP path (`ledgerpilot/odoo_client.py:139`) reachable and at least one test drive it. — **Day 1–2 (Jun 29 / 30).** MCP ref: https://www.alibabacloud.com/help/en/model-studio/mcp · Responses-API MCP (SSE): https://www.alibabacloud.com/help/en/model-studio/compatibility-with-openai-responses-api
- [ ] **B3 [I automate] — Make `eval/harness.py --live` compute and report a MEASURED false-write / catch rate from actual model proposals** (not `ScriptedPlanner`). Write all the plumbing + reporting now so that the second the key exists, one command produces the real number. — **Day 2 (Jun 30).**
- [ ] **B4 [I automate] — HARDEN the corpus (R2/R3): add adversarial, held-out error types the gate authors did not hand-pick** — debit/credit direction swap *within* allowed accounts, multi-line tax split with one wrong line, period-boundary off-by-one, VAT rounding. Stop padding the denominator with `GROSS_VARIANTS` amount-multipliers (`eval/corpus.py:149`). Relabel the offline number as **"synthetic gate stress-test"** and reserve **"measured false-write rate"** for the live LLM+gate run. — **Day 2–3 (Jun 30 / Jul 1).**
- [ ] **B5 [I automate] — Reframe README + ARCHITECTURE honestly (R2/R3/R4/R6/R7).** (a) Separate "synthetic gate stress-test" from the "live measured LLM+gate" number. (b) In `ARCHITECTURE.md:~76`, mark which Alibaba services are *provisioned* vs *planned* (do not describe Function Compute/OSS/Tablestore/AnalyticDB as live if they are not). (c) Fix the 80/80 line to "72 blocked + 8 escalated (NEEDS_HUMAN)." (d) Add one line on production signing-key management (currently `dev-insecure-key`, `config.py:39`). — **Day 3 (Jul 1).**
- [ ] **B6 [I automate] — Sharpen the uniqueness sentence to the WRITE side, with Simthetic as the explicit foil.** Ship this exact framing in README top: *"LedgerPilot is the only month-end-close agent that publishes a measured false-write rate — with a confidence interval, on a domain-seeded error corpus — for the entries it actually posts, backed by a deterministic reconciliation check that catches the balanced-but-wrong-account and wrong-amount errors a trial balance never will."* Add the "it's like an AI accountant that posts straight to your ERP, but with a measured safety number and a hard gate" one-liner (familiar-form anchor). — **Day 3 (Jul 1).**
- [ ] **B7 [I automate] — Add per-entry dollar impact + 3 citations (Problem Value gap).** Replace "six figures" with a per-entry / per-error dollar figure, and cite: DualEntry Accounting AI Benchmark 2026 (top model 77.3%, "fails ~1 in 5") https://www.dualentry.com/accounting-ai-benchmark ; single-control write false-success spikes to 45–48% (arXiv:2606.09863) https://arxiv.org/pdf/2606.09863 ; Simthetic seeded-error corpus as the detection-vs-write foil (arXiv:2606.02494) https://arxiv.org/html/2606.02494v1 . Map the gate to named controls (SOX 404 / COSO / ACFE error taxonomy: error of principle / commission / compensating). — **Day 3–4 (Jul 1 / 2).**
- [ ] **B8 [I automate] — Add a detectable open-source `LICENSE` at repo top level (MIT or Apache-2.0)** so GitHub renders the license badge in the **About** panel (Devpost requires it visible there, not just in the tree). — **Day 1 (Jun 29).** [USER: after I push, confirm the badge shows in the GitHub About panel.]
- [ ] **B9 [I automate] — Designate and label the "Proof of Alibaba Cloud Deployment" code file.** Point the submission at the file that calls Alibaba Cloud services: the Qwen `chat.completions` call in `ledgerpilot/planner.py` (base URL `dashscope-intl…`) plus the Responses-API MCP call in `ledgerpilot/odoo_client.py`. Add a `# Alibaba Cloud deployment proof` header comment + a README anchor linking directly to those lines. — **Day 4 (Jul 2).** Endpoint ref: https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope

**Credential-gated runs (start the moment A2/A3 land):**
- [ ] **B10 [I automate, needs A2 key] — Run `--live` and capture the MEASURED number.** Seed a few genuinely ambiguous tasks where `qwen3.7-max` plausibly errs, so the gate is *seen* catching a real LLM mistake. Report false-write rate with a Wilson or bootstrap 95% interval. This is the headline that converts the moat from framing into evidence (Innovation + Technical Depth, 60% of score). — **Day 4–5 (Jul 2 / 3).**
- [ ] **B11 [I automate, needs A3 Odoo] — Execute ONE real governed write end-to-end** through `XmlrpcOdooClient` into the ECS Odoo (real `account.move`), gated by reconciliation. Turns "governed write-back to a real ERP" from claim into artifact. Capture the resulting `move_id` + Odoo screenshot. — **Day 5–6 (Jul 3 / 5).**
- [ ] **B12 [I automate, needs B10] — Produce the ONE impact/adoption number** (CLAUDE.md #10–11): "Ran N live Qwen close proposals; the gate caught X balanced-but-wrong entries a naive trial-balance passed; measured false-write rate Z% (95% CI …)." This is the sentence that beats an invisible architecture moat. — **Day 5 (Jul 3).**

---

## (C) RECORDING + SUBMISSION ASSETS

- [ ] **C1 [I automate] — Write the 60–90s demo voiceover script FIRST (before any recording).** This is the focus test (CLAUDE.md #25). One arc: real close → Qwen proposes a balanced-but-wrong-account entry → gate blocks it → show the measured false-write number → one real governed write posts to Odoo. — **Day 3 (Jul 1).**
- [ ] **C2 [USER records narration + uploads; I assemble] — Produce the demo video, <3 min (target 75–90s), and upload PUBLIC to YouTube.** USER records ~80s of narration from C1; I assemble b-roll + captions + Ken Burns via the `demo-video` skill and hand back the MP4. Host: **YouTube, Vimeo, or Youku only** (rules). — **Day 6–8 (Jul 5–7).**
- [ ] **C3 [USER records; needs A3] — Record the SEPARATE "backend running on Alibaba Cloud" proof clip** (distinct from the demo): screen-record the LedgerPilot process on the ECS instance making a live `qwen3.7-max` call and writing to ECS-hosted Odoo. 30–60s, upload to the same host. This is a distinct required asset from C2. — **Day 7 (Jul 6).**
- [ ] **C4 [I automate] — Finalize the architecture diagram** (`docs/architecture.svg`) to show Qwen Cloud (Model Studio) → agent runtime on ECS → deterministic gate → Odoo, with provisioned vs planned services clearly distinguished (consistent with B5). — **Day 4 (Jul 2).**
- [ ] **C5 [I automate] — Draft the Devpost text description** (features + functionality, the uniqueness sentence, the measured number, named controls, honest limitations + path to production). — **Day 4 (Jul 2).**
- [ ] **C6 [I draft; USER publishes] — Optional blog post for the Blog Post Award** (10 × $500 cash + $500 credits, and it STACKS on a grand prize). I draft the "building LedgerPilot on Qwen Cloud" post (deterministic-gate thesis, live measured false-write rate, Simthetic-as-foil); USER publishes on dev.to / Medium / LinkedIn and grabs the URL. — **Day 8–9 (Jul 7 / 8).**

---

## (D) FINAL SUBMISSION CHECKLIST — mapped to exact Devpost requirements

Submit on Devpost with buffer by **Day 10 (Jul 8) EOD**, not on Jul 9. Rules: https://qwencloud-hackathon.devpost.com/rules · Home/form: https://qwencloud-hackathon.devpost.com/

- [ ] **D1 — Public, open-source repo, license detectable in the About section.** (B8 delivers the `LICENSE`; USER confirms the GitHub About badge renders.) Rules: *"public and open source… detectable and visible at the top of the repository page (in the About section)."*
- [ ] **D2 — Proof of Alibaba Cloud Deployment (BOTH forms, to be safe):** (i) a direct link to the code file that calls Alibaba Cloud APIs (B9 → `ledgerpilot/planner.py` / `ledgerpilot/odoo_client.py`), AND (ii) the separate short proof recording (C3). Rules phrase it as a code-file link; overview phrases it as a separate recording — submit both.
- [ ] **D3 — Architecture diagram** (C4). Rules: *"clear visual representation… how Qwen Cloud connects to your backend, database, and frontend."*
- [ ] **D4 — Demo video <3 min, PUBLIC on YouTube/Vimeo/Youku** (C2), link on the form. Must show the project functioning.
- [ ] **D5 — Text description** of features/functionality (C5).
- [ ] **D6 — Track identification: Autopilot Agent.** Rationale: LedgerPilot autonomously executes journal-entry writes to a system of record (Odoo) with a governance gate — the definition of an autopilot/autonomous-action agent. It is not memory-centric (MemoryAgent), media (AI Showrunner), multi-agent-social (Agent Society), or edge/on-device (EdgeAgent). Smallest defensible fit (CLAUDE.md #16).
- [ ] **D7 — Optional blog/social URL for the Blog Post Award** (C6).
- [ ] **D8 [USER] — Open the live Devpost submission form and verify the exact required fields BEFORE submitting.** The form is the binding surface and could not be read pre-auth. Reconcile any field differences against D1–D7. — **Day 9 (Jul 7 / 8).** https://qwencloud-hackathon.devpost.com/
- [ ] **D9 [USER] — Submit by Jul 8 EOD** (a full day before the Jul 9, 5:00pm EDT cutoff). Then re-open the submission and confirm every link resolves publicly (repo, license badge, both videos, diagram, blog).

---

### Critical-path summary
1. **Now:** A1 + A2 (voucher + key) — USER; B1 (R1 fix) — I start immediately in parallel.
2. **Day 2–3:** A3 (ECS + Odoo) — USER; B2–B7 + B9 — I do.
3. **Day 4–5:** B10 (live measured number) + B12 (impact number), the score-defining deliverables — I do, needs the key.
4. **Day 5–7:** B11 (real write) + C2/C3 (both videos) — needs ECS.
5. **Day 8:** submit early.

**If A1/A2 slip past Day 3, the submission collapses to the 40% (Problem Value + Presentation) buckets and cannot win a grand prize.** The voucher/key is the whole game; everything else I can carry.

Relevant files I will edit (all absolute): `C:\Users\Jon_A\OneDrive\Desktop\Projects\Time2\Qwen\ledgerpilot\writeback.py`, `...\ledgerpilot\gate.py`, `...\ledgerpilot\odoo_client.py`, `...\ledgerpilot\planner.py`, `...\ledgerpilot\ingest.py`, `...\eval\harness.py`, `...\eval\corpus.py`, `...\eval\scripted_planner.py`, `...\demo.py`, `...\README.md`, `...\ARCHITECTURE.md`, `...\docs\architecture.svg`, `...\config.py`, new `...\LICENSE`.
"""Build a self-contained web UI for the demo (b-roll friendly, no server).

Runs the REAL deterministic gate on a handful of close scenarios and bakes the
actual results into a single `web/index.html`. Open that file in a browser: pick
a scenario and watch the eight gate checks scan through, a verdict stamp land on
the document, and the governed write-back happen. The results are not faked; they
are this project's gate evaluating real entries.

The design is deliberate: a warm parchment journal voucher (the source document)
on a dark control desk, passing through the deterministic gate. Numbers are set in
a monospace ledger face; the only path from the document to the ledger runs through
the gate, which is the whole thesis made visual.

Run:  python webui.py    ->    web/index.html
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from ledgerpilot.chart_of_accounts import default_state
from ledgerpilot.gate import Gate
from ledgerpilot.models import GateDecision, JournalEntry, JournalLine, SourceDocument

GATE = Gate(state=default_state(reference=date(2026, 6, 30)), approval_threshold=Decimal("10000.00"))
OPEN = date(2026, 6, 20)
RENT_SRC = SourceDocument(
    document_id="INV-RENT-06", doc_type="invoice", gross_amount="4500.00",
    allowed_debit_accounts=["6100"], allowed_credit_accounts=["1000", "2000"],
)


def _line(acct, debit="0.00", credit="0.00", desc=""):
    return JournalLine(account_code=acct, description=desc, debit=debit, credit=credit)


def _scenarios():
    return [
        {
            "id": "clean",
            "tab": "Clean invoice",
            "doc": "INV-RENT-06 · Office rent · pay from bank",
            "note": "Qwen reads the invoice and books rent to Rent expense (6100), paid from Cash (1000). Every check holds.",
            "entry": JournalEntry(ref="JE-301", entry_date=OPEN, memo="June office rent",
                                  lines=[_line("6100", debit="4500.00", desc="Rent expense"),
                                         _line("1000", credit="4500.00", desc="Cash")],
                                  prepared_by="agent", approved_by="controller", source_doc_id="INV-RENT-06"),
            "source": RENT_SRC,
        },
        {
            "id": "wrong_account",
            "tab": "Wrong account",
            "doc": "INV-RENT-06 · Office rent · pay from bank",
            "note": "Qwen balances it perfectly, but books the rent to Bank fees (6900). Debits equal credits and every account is real.",
            "trap": "A trial balance passes this. Only reconciliation to the source invoice catches it.",
            "entry": JournalEntry(ref="JE-300", entry_date=OPEN, memo="June office rent (misposted)",
                                  lines=[_line("6900", debit="4500.00", desc="Rent, booked to the WRONG account"),
                                         _line("1000", credit="4500.00", desc="Cash")],
                                  prepared_by="agent", approved_by="controller", source_doc_id="INV-RENT-06"),
            "source": RENT_SRC,
        },
        {
            "id": "unbalanced",
            "tab": "Out of balance",
            "doc": "Utilities statement · pay from bank",
            "note": "A transposed digit: 1,230.00 debited, 1,320.00 credited. Debits and credits no longer tie.",
            "entry": JournalEntry(ref="JE-302", entry_date=OPEN, memo="Utilities (transposed digit)",
                                  lines=[_line("6200", debit="1230.00", desc="Utilities expense"),
                                         _line("1000", credit="1320.00", desc="Cash")],
                                  prepared_by="agent", approved_by="controller"),
            "source": None,
        },
        {
            "id": "escalate",
            "tab": "Large entry",
            "doc": "Server hardware · on account",
            "note": "Balanced, valid, and reconciled, but 45,000.00 is over the autonomous limit, so it is held for a human.",
            "entry": JournalEntry(ref="JE-303", entry_date=OPEN, memo="Server hardware purchase",
                                  lines=[_line("1500", debit="45000.00", desc="Fixed assets"),
                                         _line("2000", credit="45000.00", desc="Accounts payable")],
                                  prepared_by="agent", approved_by=None),
            "source": None,
            "approve_as": "cfo",
        },
    ]


def _fmt(value: Decimal) -> str:
    return f"{value:,.2f}"


def _writeback(decision: GateDecision) -> dict:
    if decision == GateDecision.APPROVED:
        return {"status": "written",
                "text": "Signed with an HMAC token and written to Odoo as a posted account.move."}
    if decision == GateDecision.NEEDS_HUMAN:
        return {"status": "escalated",
                "text": "Held for a human approver. No token issued, nothing posted."}
    return {"status": "refused",
            "text": "Refused. No token, no write. Nothing reaches the ledger."}


def _verdict(entry, source):
    result = GATE.evaluate(entry, source)
    return {
        "checks": [
            {"check": c.check, "passed": c.passed, "severity": c.severity.value, "detail": c.detail}
            for c in result.checks
        ],
        "decision": result.decision.value,
        "writeback": _writeback(result.decision),
    }, result.decision


def _serialize(scn):
    e = scn["entry"]
    source = scn.get("source")
    verdict, decision = _verdict(e, source)
    data = {
        "id": scn["id"], "tab": scn["tab"], "doc": scn["doc"], "note": scn["note"],
        "trap": scn.get("trap", ""),
        "ref": e.ref,
        "amount": _fmt(e.amount),
        "prepared_by": e.prepared_by,
        "approved_by": e.approved_by or "pending sign-off",
        "lines": [
            {"account": ln.account_code, "desc": ln.description,
             "debit": _fmt(ln.debit) if ln.debit > 0 else "",
             "credit": _fmt(ln.credit) if ln.credit > 0 else ""}
            for ln in e.lines
        ],
        **verdict,
    }
    # Track 4 requires a human-in-the-loop checkpoint. When an entry is held, bake
    # the post-approval verdict too, so a human can sign it in the UI and watch the
    # same gate approve and write it. Nothing is faked: this is the gate re-run with
    # the approver recorded.
    approve_as = scn.get("approve_as")
    if approve_as and decision == GateDecision.NEEDS_HUMAN:
        signed_verdict, _ = _verdict(e.model_copy(update={"approved_by": approve_as}), source)
        data["approved"] = {"by": approve_as, **signed_verdict}
    return data


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>LedgerPilot — the gate is the only path to a write</title>
<meta name="description" content="An autonomous month-end-close agent on Qwen Cloud. Qwen proposes journal entries; a deterministic gate is the only path to a write. Same model, same tasks: gate off, wrong entries hit the ledger; gate on, zero."/>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 36 36' fill='none' stroke='%23c9a24b' stroke-width='2.6' stroke-linecap='round' stroke-linejoin='round'%3E%3Cline x1='5' y1='12' x2='16' y2='12'/%3E%3Cline x1='5' y1='18' x2='16' y2='18'/%3E%3Cline x1='5' y1='24' x2='13' y2='24'/%3E%3Cline x1='20' y1='5' x2='20' y2='31' opacity='.6'/%3E%3Cpath d='M24 18 l3.5 3.5 l6.5 -8.5'/%3E%3C/svg%3E"/>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet"/>
<style>
  :root{
    --desk:#0e1113; --desk-2:#15191c; --panel:#14181b; --raised:#1a1f22;
    --paper:#f3efe4; --paper-2:#ebe5d6; --paper-ink:#211f19; --paper-mut:#6c6656; --paper-rule:rgba(33,31,25,.10);
    --ink:#e9e7e1; --mut:#8b938f; --dim:#5f6864; --line:#252b2e; --line-2:#2f3639;
    --brass:#c9a24b; --brass-dim:#8a7237;
    --pass:#43b074; --pass-dim:#1c4030; --pass-bg:rgba(67,176,116,.10);
    --fail:#d95468; --fail-dim:#4a2029; --fail-bg:rgba(217,84,104,.10);
    --hold:#d99a3a; --hold-bg:rgba(217,154,58,.10);
    --disp:"Fraunces",Georgia,"Times New Roman",serif;
    --mono:"JetBrains Mono",ui-monospace,"SF Mono","Cascadia Code","Roboto Mono",monospace;
    --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  }
  *{box-sizing:border-box}
  html{scroll-behavior:smooth}
  body{margin:0;background:var(--desk);color:var(--ink);font:15px/1.55 var(--sans);
    -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;overflow-x:hidden}
  /* faint control-desk vignette + grain */
  body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
    background:radial-gradient(120% 80% at 50% -10%,rgba(201,162,75,.06),transparent 60%),
      radial-gradient(100% 120% at 100% 110%,rgba(67,176,116,.04),transparent 55%)}
  .grain{position:fixed;inset:0;z-index:0;pointer-events:none;opacity:.035;mix-blend-mode:overlay;
    background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")}
  .wrap{position:relative;z-index:1;max-width:1160px;margin:0 auto;padding:34px 24px 72px}

  /* masthead */
  .masthead{display:flex;align-items:center;gap:16px;flex-wrap:wrap;padding-bottom:22px;border-bottom:1px solid var(--line)}
  .brand{display:flex;align-items:center;gap:13px}
  .mark{width:38px;height:38px;flex:0 0 38px;display:block}
  .word{font:600 25px/1 var(--disp);letter-spacing:-.4px}
  .tagline{font:400 12px/1.4 var(--mono);color:var(--mut);letter-spacing:.1px;margin-top:4px}
  .badges{margin-left:auto;display:flex;gap:9px;flex-wrap:wrap}
  .chip{font:500 11.5px/1 var(--mono);color:var(--mut);border:1px solid var(--line-2);
    padding:7px 11px;border-radius:7px;letter-spacing:.2px;white-space:nowrap;display:flex;align-items:center;gap:7px}
  .chip.live{color:var(--pass);border-color:var(--pass-dim)}
  .chip.live i{width:6px;height:6px;border-radius:50%;background:var(--pass);
    box-shadow:0 0 0 0 rgba(67,176,116,.5);animation:beat 2.2s ease-out infinite}
  @keyframes beat{0%{box-shadow:0 0 0 0 rgba(67,176,116,.45)}70%{box-shadow:0 0 0 7px rgba(67,176,116,0)}100%{box-shadow:0 0 0 0 rgba(67,176,116,0)}}

  /* lede + counterfactual */
  .lede{display:grid;grid-template-columns:1.15fr .95fr;gap:30px;align-items:center;margin:30px 0 8px}
  @media (max-width:840px){.lede{grid-template-columns:1fr;gap:22px}}
  .thesis{margin:0;font:400 20px/1.5 var(--disp);color:var(--ink);max-width:32ch;text-wrap:pretty}
  .thesis b{color:var(--brass);font-weight:600}
  /* The counterfactual is set as a ledger footing: a ruled column of figures with a
     total, the way a schedule is actually presented. Not a stat card. */
  .cf{position:relative;padding:2px 0 0}
  .cf-h{font:600 10px/1 var(--mono);letter-spacing:1.8px;text-transform:uppercase;color:var(--dim);
    border-bottom:1.5px solid var(--line-2);padding-bottom:8px}
  .cf-row{display:grid;grid-template-columns:1fr auto;align-items:baseline;gap:16px;
    padding:13px 0;border-bottom:1px solid var(--line)}
  .cf-k{font:500 12.5px/1.3 var(--mono);letter-spacing:.3px;color:var(--mut)}
  .cf-k span{display:block;font:400 11px/1.4 var(--sans);color:var(--dim);margin-top:3px;max-width:30ch}
  .cf-v{font:600 40px/.9 var(--disp);letter-spacing:-1px;font-variant-numeric:tabular-nums}
  .cf-row.off .cf-v{color:var(--fail)} .cf-row.on .cf-v{color:var(--pass)}
  .cf-row.on{border-bottom:2.5px double var(--line-2)}  /* the double rule of a total */
  .cf-f{font:400 10.5px/1.5 var(--mono);color:var(--dim);padding-top:9px;letter-spacing:.2px}

  /* Scenario picker: file tabs on a folder, not pills. Square, butted together,
     sitting on the rule that the document hangs from. */
  .tabs{display:flex;gap:2px;flex-wrap:wrap;margin:32px 0 0;border-bottom:1.5px solid var(--line-2);
    padding-left:2px}
  .tab{cursor:pointer;font:500 12.5px/1 var(--mono);color:var(--mut);background:transparent;
    border:none;border-bottom:2px solid transparent;padding:12px 15px;transition:color .16s,border-color .16s;
    letter-spacing:.2px;margin-bottom:-1.5px}
  .tab:hover{color:var(--ink)}
  .tab:focus-visible{outline:2px solid var(--brass);outline-offset:-2px}
  .tab.active{color:var(--brass);border-bottom-color:var(--brass);font-weight:600}

  /* stage: document -> seam -> gate */
  .stage{display:grid;grid-template-columns:minmax(0,1fr) 52px minmax(0,1.02fr);align-items:stretch}
  @media (max-width:840px){.stage{grid-template-columns:1fr;gap:16px}.seam{display:none}}

  /* the parchment voucher */
  .paper{background:linear-gradient(180deg,var(--paper),var(--paper-2));color:var(--paper-ink);
    border-radius:12px;padding:22px 24px 20px;position:relative;display:flex;flex-direction:column;
    box-shadow:0 1px 0 rgba(255,255,255,.25) inset,0 18px 40px -18px rgba(0,0,0,.7),0 2px 8px rgba(0,0,0,.3)}
  .paper::before{content:"";position:absolute;left:0;top:18px;bottom:18px;width:4px;border-radius:4px;background:var(--brass)}
  /* ruled continuation of the ledger page, kept below the entry so it never crosses text */
  .fill{flex:1 1 auto;min-height:44px;margin-top:12px;
    background-image:repeating-linear-gradient(transparent 0 27px,var(--paper-rule) 27px 28px)}
  .vhead{display:flex;justify-content:space-between;align-items:baseline;border-bottom:1.5px solid rgba(33,31,25,.22);padding-bottom:9px;margin-bottom:2px}
  .vhead .lbl{font:600 10.5px/1 var(--mono);letter-spacing:1.4px;text-transform:uppercase;color:var(--paper-mut)}
  .vhead .ref{font:600 13px/1 var(--mono);color:var(--paper-ink)}
  .doc{font:500 13.5px/1.45 var(--mono);color:var(--paper-ink);padding:12px 0 4px}
  .amt-big{font:500 15px/1 var(--mono)}
  .note{font:400 13px/1.5 var(--sans);color:#514c40;margin:2px 0 12px;max-width:52ch}
  .trap{display:inline-flex;align-items:center;gap:7px;font:500 11.5px/1.35 var(--sans);color:#8a3a24;
    background:rgba(190,90,50,.10);border:1px solid rgba(190,90,50,.28);border-radius:7px;padding:7px 10px;margin:0 0 12px}
  .trap::before{content:"⚠";font-size:12px}
  table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
  th{font:600 10px/1 var(--mono);letter-spacing:.6px;text-transform:uppercase;color:var(--paper-mut);
    text-align:left;padding:0 0 7px;border-bottom:1px solid rgba(33,31,25,.2)}
  th.r,td.r{text-align:right}
  td{font:500 13.5px/1 var(--mono);color:var(--paper-ink);padding:10px 0;border-bottom:1px solid var(--paper-rule)}
  td .d{font:400 11.5px/1.3 var(--sans);color:#6c6656;margin-top:3px}
  td.acct{width:64px}
  .vfoot{display:flex;gap:22px;margin-top:12px;padding-top:11px}
  .vfoot div{font:400 11px/1.4 var(--sans);color:var(--paper-mut)}
  .vfoot b{display:block;font:500 12.5px/1.3 var(--mono);color:var(--paper-ink);margin-top:2px}

  /* the trust-boundary seam */
  .seam{position:relative;display:flex;align-items:center;justify-content:center}
  .seam::before{content:"";position:absolute;top:8px;bottom:8px;width:1px;
    background:linear-gradient(180deg,transparent,var(--brass-dim) 18%,var(--brass-dim) 82%,transparent)}
  .seam-label{position:absolute;font:600 9.5px/1 var(--mono);letter-spacing:2px;text-transform:uppercase;
    color:var(--brass-dim);white-space:nowrap;transform:rotate(-90deg);
    background:var(--desk);padding:6px 0}
  .pulse{position:absolute;top:0;left:50%;width:7px;height:7px;margin-left:-3.5px;border-radius:50%;
    background:var(--brass);box-shadow:0 0 10px 2px rgba(201,162,75,.7);opacity:0}
  .pulse.run{animation:flow 1.15s cubic-bezier(.4,0,.5,1)}
  @keyframes flow{0%{top:4%;opacity:0}15%{opacity:1}85%{opacity:1}100%{top:96%;opacity:0}}

  /* The reviewer's column. Not a card: an auditor does not hand you a widget, they
     hand back your document with tick marks down the margin and a note on the one
     line that is wrong. Rules and type, no boxes. */
  .gate{padding:4px 2px 0 12px;display:flex;flex-direction:column}
  .ghead{display:flex;align-items:baseline;justify-content:space-between;
    border-bottom:1.5px solid var(--line-2);padding-bottom:9px;margin-bottom:2px}
  .ghead .t{font:600 10.5px/1 var(--mono);letter-spacing:1.8px;text-transform:uppercase;color:var(--brass)}
  .ghead .s{font:400 10.5px/1 var(--mono);color:var(--dim);letter-spacing:.3px}
  .checks{display:flex;flex-direction:column}
  /* the tick column is a fixed measure, so every tick lines up like a ruled margin */
  .check{display:grid;grid-template-columns:18px 1fr;gap:13px;align-items:baseline;
    padding:10px 0 9px;border-bottom:1px solid var(--line);opacity:0;
    transition:opacity .34s ease}
  .check.show{opacity:1}
  .tick{font:700 14px/1.2 var(--mono);color:var(--pass);text-align:center}
  .tick.bad{color:var(--fail)} .tick.warn{color:var(--hold)}
  .check.fail{border-bottom-color:var(--fail-dim)}
  .cn{font:500 13px/1.3 var(--sans);color:var(--ink)}
  .check.fail .cn{color:var(--fail)}
  .check.held .cn{color:var(--hold)}
  .cd{font:400 11.5px/1.5 var(--mono);color:var(--mut);margin-top:3px;letter-spacing:-.1px}
  /* the exception is written in red pen, hanging in the margin like a review note */
  .check.fail .cd{color:#e88a95;border-left:2px solid var(--fail);padding-left:9px;margin-left:-11px}
  .check.held .cd{color:#dcb26a;border-left-color:var(--hold)}
  .legend{font:400 10.5px/1.5 var(--mono);color:var(--dim);margin-top:11px;letter-spacing:.2px}
  .legend b{color:var(--pass);font-weight:700} .legend i{color:var(--fail);font-style:normal;font-weight:700}
  .legend u{color:var(--hold);text-decoration:none;font-weight:700}

  /* the verdict stamp */
  .verdict{margin-top:20px;padding-top:2px;display:flex;align-items:center;gap:18px}
  .stamp{flex:0 0 auto;border:2.5px solid currentColor;border-radius:10px;padding:9px 16px;
    font:700 22px/1 var(--disp);letter-spacing:1px;text-transform:uppercase;position:relative;
    opacity:0;transform:rotate(-16deg) scale(1.7)}
  .stamp .ss{display:block;font:500 9.5px/1 var(--mono);letter-spacing:1.5px;margin-top:5px;text-align:center;opacity:.85}
  .stamp.show{animation:stampIn .46s cubic-bezier(.2,1.3,.5,1) forwards}
  .stamp::after{content:"";position:absolute;inset:-7px;border:2px solid currentColor;border-radius:14px;opacity:0}
  .stamp.show::after{animation:ring .5s ease-out .12s}
  @keyframes stampIn{0%{opacity:0;transform:rotate(-16deg) scale(1.7)}
    65%{opacity:1;transform:rotate(-4deg) scale(.9)}100%{opacity:1;transform:rotate(-4deg) scale(1)}}
  @keyframes ring{0%{opacity:.55;transform:scale(.82)}100%{opacity:0;transform:scale(1.18)}}
  .stamp.approved{color:var(--pass)} .stamp.rejected{color:var(--fail)} .stamp.needs_human{color:var(--hold)}
  .wb{font:400 12.5px/1.5 var(--sans);color:var(--mut);opacity:0;transition:opacity .4s ease .1s;max-width:30ch}
  .wb.show{opacity:1} .wb b{color:var(--ink);font-weight:600}

  /* human-in-the-loop checkpoint */
  .hitl[hidden]{display:none}
  .hitl{margin-top:15px;padding-top:15px;border-top:1px dashed var(--line);
    display:flex;align-items:center;gap:14px;flex-wrap:wrap;opacity:0;transform:translateY(4px);
    transition:opacity .4s ease,transform .4s ease}
  .hitl.show{opacity:1;transform:none}
  .hitl .cap{font:400 12px/1.45 var(--sans);color:var(--mut);max-width:23ch}
  .hitl .cap b{color:var(--hold);font-weight:600}
  .approve{cursor:pointer;font:600 13px/1 var(--sans);color:#161207;background:var(--brass);
    border:1px solid var(--brass);padding:11px 16px;border-radius:9px;transition:.16s ease;
    display:inline-flex;align-items:center;gap:9px;white-space:nowrap}
  .approve:hover{filter:brightness(1.08)} .approve:active{transform:translateY(1px)}
  .approve:focus-visible{outline:2px solid var(--brass);outline-offset:3px}
  .approve svg{width:15px;height:15px;stroke:#161207;stroke-width:2.2;fill:none;stroke-linecap:round;stroke-linejoin:round}

  /* Proof band: a summary schedule ruled off at the foot of the page. */
  .proof{margin-top:34px;border-top:1.5px solid var(--line-2);display:grid;
    grid-template-columns:1.15fr 1fr 1fr 1.1fr}
  @media (max-width:840px){.proof{grid-template-columns:1fr 1fr}}
  .stat{padding:19px 22px 2px;border-right:1px solid var(--line)}
  .stat:first-child{padding-left:0}
  .stat:last-child{border-right:none}
  @media (max-width:840px){.stat{padding-left:0;border-right:none}}
  .stat .n{font:600 30px/1 var(--disp);letter-spacing:-.5px;font-variant-numeric:tabular-nums}
  .stat.feat .n{color:var(--pass)}
  .stat .l{font:400 11px/1.5 var(--sans);color:var(--mut);margin-top:8px;max-width:26ch}
  .repro{margin-top:14px;display:flex;align-items:center;gap:12px;flex-wrap:wrap;
    font:400 12px/1.5 var(--sans);color:var(--dim);border-top:1px solid var(--line);padding-top:16px}
  .repro code{font:500 12px/1 var(--mono);color:var(--brass);background:rgba(201,162,75,.08);
    border:1px solid var(--line-2);border-radius:6px;padding:5px 8px}

  @media (prefers-reduced-motion:reduce){
    *{animation-duration:.001ms!important;transition-duration:.001ms!important}
    .check{opacity:1;transform:none} .stamp{opacity:1;transform:rotate(-4deg)}
  }
</style>
</head>
<body>
<div class="grain" aria-hidden="true"></div>
<div class="wrap">
  <header class="masthead">
    <div class="brand">
      <svg class="mark" viewBox="0 0 36 36" fill="none" stroke="#c9a24b" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="5" y1="12" x2="16" y2="12"/><line x1="5" y1="18" x2="16" y2="18"/><line x1="5" y1="24" x2="13" y2="24"/><line x1="20" y1="5" x2="20" y2="31" opacity=".55"/><path d="M24 18 l3.5 3.5 l6.5 -8.5"/></svg>
      <div>
        <div class="word">LedgerPilot</div>
        <div class="tagline">autonomous month-end close · the gate is the only path to a write</div>
      </div>
    </div>
    <div class="badges">
      <span class="chip live"><i></i>backend live on Alibaba Cloud ECS</span>
      <span class="chip">Track 4 · Autopilot Agent</span>
    </div>
  </header>

  <section class="lede">
    <p class="thesis">Qwen drafts the journal entries. A deterministic gate of eight exact checks decides what reaches the ledger. <b>Same model, same 39 close tasks, same live ERP:</b></p>
    <div class="cf" role="img" aria-label="Gate off: 5 wrong entries posted. Gate on: 0 wrong entries.">
      <div class="cf-h">Wrong entries reaching the ledger</div>
      <div class="cf-row off">
        <div class="cf-k">Gate off<span>every proposal posted as drafted</span></div>
        <div class="cf-v">5</div>
      </div>
      <div class="cf-row on">
        <div class="cf-k">Gate on<span>same model, same 39 tasks, same ledger</span></div>
        <div class="cf-v">0</div>
      </div>
      <div class="cf-f">measured on a live Odoo · docs/counterfactual_proof.txt</div>
    </div>
  </section>

  <nav class="tabs" id="tabs" aria-label="close scenarios"></nav>

  <main class="stage">
    <article class="paper" id="paper" aria-label="source document and proposed entry">
      <div class="vhead"><span class="lbl">Source &amp; proposed entry</span><span class="ref" id="ref"></span></div>
      <div class="doc"><span id="doc"></span> · <span class="amt-big" id="amount"></span></div>
      <p class="note" id="note"></p>
      <div id="trap"></div>
      <table>
        <thead><tr><th class="acct">Acct</th><th>Description</th><th class="r">Debit</th><th class="r">Credit</th></tr></thead>
        <tbody id="lines"></tbody>
      </table>
      <div class="vfoot">
        <div>Prepared by<b id="prep"></b></div>
        <div>Approved by<b id="appr"></b></div>
      </div>
      <div class="fill" aria-hidden="true"></div>
    </article>

    <div class="seam" aria-hidden="true"><span class="seam-label">trust boundary</span><span class="pulse" id="pulse"></span></div>

    <section class="gate" aria-label="deterministic gate">
      <div class="ghead"><span class="t">Deterministic gate</span><span class="s">8 checks · no LLM</span></div>
      <div class="checks" id="checks"></div>
      <div class="legend"><b>✓</b> passed &nbsp; <i>✗</i> exception, refused &nbsp; <u>△</u> held for a human</div>
      <div class="verdict">
        <div class="stamp" id="stamp"></div>
        <div class="wb" id="wb"></div>
      </div>
      <div class="hitl" id="hitl" hidden>
        <button class="approve" id="approve" type="button"></button>
        <span class="cap"><b>Human-in-the-loop checkpoint.</b> The agent paused above the autonomous limit. A human signs; the same gate then approves and writes.</span>
      </div>
    </section>
  </main>

  <section class="proof" aria-label="measured results">
    <div class="stat feat"><div class="n">0</div><div class="l">wrong journal entries the gate let through, on live Qwen output</div></div>
    <div class="stat"><div class="n">8 / 8</div><div class="l">real Qwen mistakes caught (two models, 39 tasks)</div></div>
    <div class="stat"><div class="n">100%</div><div class="l">catch rate on the 204-case offline stress-test</div></div>
    <div class="stat"><div class="n">3</div><div class="l">real entries posted to a live Odoo, one written by Qwen through MCP</div></div>
  </section>
  <div class="repro">
    Every verdict above is this project's real gate evaluating a real entry.
    <span>Reproduce:</span> <code>python -m eval.harness</code> <code>python scripts/counterfactual.py</code>
  </div>
</div>

<script>
const SCENARIOS = /*SCENARIOS_JSON*/;
const $=id=>document.getElementById(id);
const nice={balance:'Balance',account_validity:'Account validity',no_self_contra:'No self-contra',
  positive_amounts:'Positive amounts',period_lock:'Period lock',segregation:'Segregation of duties',
  approval_threshold:'Approval threshold',reconciliation:'Reconcile to source'};
const stampWord={approved:['APPROVED','written to the ledger'],rejected:['REFUSED','nothing written'],
  needs_human:['HOLD','escalated to a human']};
const PEN='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4L19 9a2 2 0 0 0-3-3L5 17v3z"/><path d="M14 7l3 3"/></svg>';
const reduce=matchMedia('(prefers-reduced-motion:reduce)').matches;
let timers=[], current=null;

const tabs=$('tabs');
SCENARIOS.forEach((s,i)=>{const b=document.createElement('button');b.className='tab'+(i===0?' active':'');
  b.type='button';b.textContent=s.tab;
  b.onclick=()=>{document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
    b.classList.add('active');render(s);};
  tabs.appendChild(b);});

function paintPaper(s){
  $('ref').textContent=s.ref;
  $('doc').textContent=s.doc; $('amount').textContent=s.amount;
  $('note').textContent=s.note;
  $('trap').innerHTML=s.trap?`<div class="trap">${s.trap}</div>`:'';
  $('prep').textContent=s.prepared_by; $('appr').textContent=s.approved_by;
  $('lines').innerHTML=s.lines.map(l=>`<tr><td class="acct">${l.account}</td>
    <td>${l.desc?`<div class="d">${l.desc}</div>`:''}</td>
    <td class="r">${l.debit||'·'}</td><td class="r">${l.credit||'·'}</td></tr>`).join('');
}

// st = {checks, decision, writeback}; canApprove offers the human sign-off control.
function runGate(s, st, canApprove){
  timers.forEach(clearTimeout); timers=[];
  const checks=$('checks'); checks.innerHTML='';
  const stamp=$('stamp'), wb=$('wb'), hitl=$('hitl');
  stamp.className='stamp'; stamp.innerHTML=''; wb.className='wb'; wb.innerHTML='';
  hitl.hidden=true; hitl.classList.remove('show');

  const step=reduce?0:105, base=reduce?0:260;
  // A reviewer's tick down the margin: pass, exception, or held for a human.
  st.checks.forEach((c,i)=>{
    const row=document.createElement('div'); row.className='check';
    const cls=c.passed?'':(c.severity==='warning'?'warn':'bad');
    const mark=c.passed?'✓':(c.severity==='warning'?'△':'✗');
    if(!c.passed) row.classList.add(c.severity==='warning' ? 'fail held' : 'fail');
    row.innerHTML=`<div class="tick ${cls}">${mark}</div><div><div class="cn">${nice[c.check]||c.check}</div>
      <div class="cd">${c.detail}</div></div>`;
    checks.appendChild(row);
    timers.push(setTimeout(()=>row.classList.add('show'), base+step*i));
  });
  timers.push(setTimeout(()=>{
    const [w,sub]=stampWord[st.decision]||[st.decision,''];
    stamp.className='stamp show '+st.decision;
    stamp.innerHTML=`${w}<span class="ss">${sub}</span>`;
    wb.className='wb show'; wb.innerHTML='<b>Write-back.</b> '+st.writeback.text;
    if(canApprove){
      $('approve').innerHTML=PEN+'Sign as '+s.approved.by.toUpperCase()+' &amp; post';
      hitl.hidden=false; requestAnimationFrame(()=>hitl.classList.add('show'));
    }
  }, base+step*st.checks.length+120));
}

function render(s){
  current=s;
  paintPaper(s);
  const p=$('pulse'); p.classList.remove('run'); void p.offsetWidth; if(!reduce) p.classList.add('run');
  runGate(s, {checks:s.checks,decision:s.decision,writeback:s.writeback}, !!s.approved);
}

$('approve').onclick=()=>{
  const s=current; if(!s||!s.approved) return;
  $('appr').textContent=s.approved.by+' · signed';
  runGate(s, s.approved, false);
};

render(SCENARIOS[0]);
</script>
</body>
</html>
"""


def main():
    scenarios = [_serialize(s) for s in _scenarios()]
    out_dir = Path(__file__).resolve().parent / "web"
    out_dir.mkdir(exist_ok=True)
    html = HTML.replace("/*SCENARIOS_JSON*/", json.dumps(scenarios))
    out = out_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out}  ({len(html)} bytes, {len(scenarios)} scenarios)")


if __name__ == "__main__":
    main()

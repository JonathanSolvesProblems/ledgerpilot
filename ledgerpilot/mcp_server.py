"""LedgerPilot's Odoo MCP server: the deterministic gate, exposed as MCP tools.

=== ALIBABA CLOUD DEPLOYMENT PROOF ===
This server runs on the Alibaba Cloud ECS instance and is attached to Qwen on
Alibaba Cloud Model Studio as an **SSE MCP server** through the Responses API
(`tools=[{"type": "mcp", "server_protocol": "sse", ...}]`). Model Studio connects
out to this process and the model calls these tools itself.

Why the gate lives HERE, and not in the prompt
----------------------------------------------
Handing an LLM a tool that writes to a general ledger is exactly the thing this
project exists to prevent. So the model is the *caller*, never the *authority*:

  validate_write            pure, read-only. Runs all 8 deterministic checks and
                            reports the verdict. Safe for anyone to call.

  execute_approved_write    the only path to the ledger. Before it touches Odoo it
                            (1) verifies an HMAC approval token bound to the entry's
                            content hash, and (2) RE-RUNS the full gate, including
                            reconciliation against the source document.

The token is minted by LedgerPilot (which holds the signing key), not by the model.
The model only relays it. So if the model alters a single cent, the content hash
changes, the signature no longer verifies, and the write is refused. The trust
boundary survives a model-driven tool call, which is the entire point of putting the
gate behind the tool rather than in the instructions. `scripts/mcp_demo.py`
demonstrates exactly that: it asks the model to inflate an amount before writing,
and the server refuses.

Run (on the ECS box, behind the security group that opens 8080):
    python -m ledgerpilot.mcp_server            # serves SSE on 0.0.0.0:8080/sse
"""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from .chart_of_accounts import default_state
from .config import load_config
from .gate import Gate
from .models import GateDecision, JournalEntry, SourceDocument
from .odoo_client import OdooClientError, XmlrpcOdooClient
from .tokens import ApprovalToken, TokenError, verify_token
from .writeback import OdooWriteBack, WriteRefused

_CONFIG = load_config()
# require_source=True: the caller here is a language model choosing its own tool
# arguments, so it must not be able to disable reconciliation by simply omitting
# the source document. No evidence, no write.
_GATE = Gate(state=default_state(reference=date(2026, 6, 30)),
             approval_threshold=_CONFIG.approval_threshold,
             require_source=True)

mcp = FastMCP(
    "ledgerpilot-odoo",
    instructions=(
        "Governed write access to an Odoo general ledger. Call validate_write to "
        "check an entry, then execute_approved_write to post it. Amounts must be "
        "sent as strings. You cannot bypass the gate: the server re-validates every "
        "entry and verifies a signed approval token before writing."
    ),
    host="0.0.0.0",
    port=int(os.environ.get("LEDGERPILOT_MCP_PORT", "8080")),
)


# --- untrusted-input normalization ---------------------------------------
# These tools are called by a language model, so the payload is untrusted JSON.
# `money()` deliberately refuses floats, but JSON numbers deserialize to float, so
# amounts are coerced through str() first: Decimal(str(1280.0)) is exact for the
# decimal literal the model actually wrote, and no binary-float cent is ever lost.

def _as_amount(v: Any) -> str:
    if isinstance(v, (int, float, Decimal)):
        return str(v)
    return str(v or "0.00")


def _to_entry(d: dict) -> JournalEntry:
    lines = [
        {
            "account_code": str(ln.get("account_code", "")),
            "description": str(ln.get("description", "") or ""),
            "debit": _as_amount(ln.get("debit", "0.00")),
            "credit": _as_amount(ln.get("credit", "0.00")),
        }
        for ln in d.get("lines", [])
    ]
    return JournalEntry(
        ref=str(d.get("ref", "")),
        entry_date=d.get("entry_date"),
        memo=str(d.get("memo", "") or ""),
        lines=lines,
        prepared_by=str(d.get("prepared_by", "agent")),
        approved_by=d.get("approved_by"),
        source_doc_id=d.get("source_doc_id"),
    )


def _to_source(d: Optional[dict]) -> Optional[SourceDocument]:
    if not d:
        return None
    return SourceDocument(
        document_id=str(d.get("document_id", "")),
        doc_type=str(d.get("doc_type", "invoice")),
        gross_amount=_as_amount(d.get("gross_amount", "0.00")),
        allowed_debit_accounts=[str(a) for a in d.get("allowed_debit_accounts", [])],
        allowed_credit_accounts=[str(a) for a in d.get("allowed_credit_accounts", [])],
    )


def _verdict(entry: JournalEntry, source: Optional[SourceDocument]) -> dict:
    result = _GATE.evaluate(entry, source)
    return {
        "decision": result.decision.value,
        "entry_hash": result.entry_hash,
        "checks": [
            {"check": c.check, "passed": c.passed, "detail": c.detail}
            for c in result.checks
        ],
        "failed": [c.detail for c in result.failed_checks],
    }


# --- tools ----------------------------------------------------------------

@mcp.tool()
def validate_write(entry: dict, source: dict | None = None) -> dict:
    """Run the deterministic gate against a proposed journal entry. Read-only.

    Returns the decision (approved / needs_human / rejected), every check with its
    result, and the entry's content hash. Writes nothing. Amounts must be strings.
    """
    try:
        return _verdict(_to_entry(entry), _to_source(source))
    except Exception as exc:  # malformed model output should not crash the server
        return {"decision": "rejected", "error": f"{type(exc).__name__}: {exc}"}


@mcp.tool()
def execute_approved_write(
    entry: dict,
    approval_token: str,
    source: dict | None = None,
    confirm: bool = False,
) -> dict:
    """Post a gate-approved journal entry to the live Odoo ledger.

    Requires `confirm=true` and a valid HMAC approval token that was issued for
    this exact entry. The gate is re-run here before the write, so an entry that
    was altered after approval (even by one cent) is refused: its content hash no
    longer matches the token.
    """
    if not confirm:
        return {"written": False, "refused": "confirm=false; the caller must confirm the write."}

    try:
        je = _to_entry(entry)
        src = _to_source(source)
    except Exception as exc:
        return {"written": False, "refused": f"malformed entry: {type(exc).__name__}: {exc}"}

    # 1. Deterministic gate, re-run at write time (never trust a stale approval).
    verdict = _verdict(je, src)
    if verdict["decision"] != GateDecision.APPROVED.value:
        return {
            "written": False,
            "refused": f"gate says {verdict['decision']}",
            "failed_checks": verdict["failed"],
            "entry_hash": verdict["entry_hash"],
        }

    # 2. The token must authorize THIS exact entry. This is what makes tampering
    #    by the calling model detectable rather than merely discouraged.
    try:
        verify_token(_CONFIG.signing_key, je, ApprovalToken.from_str(approval_token))
    except TokenError as exc:
        return {
            "written": False,
            "refused": f"approval token rejected: {exc}",
            "entry_hash": je.content_hash(),
        }

    # 3. Write. Governance failures are a refusal; transport failures are an error.
    try:
        writer = OdooWriteBack(gate=_GATE, config=_CONFIG,
                               odoo_client=XmlrpcOdooClient(config=_CONFIG))
        receipt = writer.commit(je, ApprovalToken.from_str(approval_token), src)
    except (WriteRefused, TokenError) as exc:
        return {"written": False, "refused": str(exc)}
    except OdooClientError as exc:
        return {"written": False, "refused": f"the ledger could not be reached: {exc}"}

    return {
        "written": True,
        "move_id": receipt.odoo_move_id,
        "status": receipt.status,
        "entry_hash": receipt.entry_hash,
    }


if __name__ == "__main__":
    mcp.run(transport="sse")

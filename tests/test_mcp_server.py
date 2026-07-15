"""The MCP tools are called by a language model, so their input is untrusted.

These tests drive the tool functions directly (no network, no Odoo) and pin the
property the whole MCP design exists for: the model is the caller, never the
authority. It can ask for anything; it cannot get a wrong entry into the ledger.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from ledgerpilot import mcp_server
from ledgerpilot.chart_of_accounts import default_state
from ledgerpilot.gate import Gate
from ledgerpilot.models import GateDecision, JournalEntry, JournalLine
from ledgerpilot.tokens import issue_token

GATE = Gate(state=default_state(reference=date(2026, 6, 30)),
            approval_threshold=Decimal("10000.00"))

SOURCE = {
    "document_id": "INV-RENT-06", "doc_type": "invoice", "gross_amount": "4500.00",
    "allowed_debit_accounts": ["6100"], "allowed_credit_accounts": ["1000", "2000"],
}
ENTRY = {
    "ref": "LP-T-1", "entry_date": "2026-06-20", "memo": "June rent",
    "prepared_by": "agent", "approved_by": "controller", "source_doc_id": "INV-RENT-06",
    "lines": [
        {"account_code": "6100", "debit": "4500.00", "credit": "0.00", "description": "Rent"},
        {"account_code": "1000", "debit": "0.00", "credit": "4500.00", "description": "Cash"},
    ],
}


# FastMCP's @tool() returns the plain function, so the tools are callable directly.
_VALIDATE = getattr(mcp_server.validate_write, "fn", mcp_server.validate_write)
_EXECUTE = getattr(mcp_server.execute_approved_write, "fn", mcp_server.execute_approved_write)


def _validate(entry=None, source=None):
    return _VALIDATE(entry or ENTRY, source or SOURCE)


def _execute(entry, token, source=None, confirm=True):
    return _EXECUTE(entry, token, source or SOURCE, confirm)


def token_for(entry_dict) -> str:
    je = mcp_server._to_entry(entry_dict)
    src = mcp_server._to_source(SOURCE)
    result = GATE.evaluate(je, src)
    if result.decision != GateDecision.APPROVED:
        return "no-token"
    return issue_token(mcp_server._CONFIG.signing_key, je, result).to_str()


def test_validate_write_is_read_only_and_reports_every_check():
    out = _validate()
    assert out["decision"] == "approved"
    assert {c["check"] for c in out["checks"]} == {
        "balance", "account_validity", "no_self_contra", "positive_amounts",
        "period_lock", "segregation", "approval_threshold", "reconciliation",
    }


def test_amounts_arriving_as_json_numbers_do_not_crash():
    """`money()` refuses floats by design, but a model emits JSON numbers."""
    numeric = {
        **ENTRY,
        "lines": [
            {"account_code": "6100", "debit": 4500.00, "credit": 0},
            {"account_code": "1000", "debit": 0, "credit": 4500.00},
        ],
    }
    assert _validate(numeric)["decision"] == "approved"


def test_malformed_entry_is_refused_not_raised():
    out = _validate({"ref": "x", "lines": [{"account_code": "6100", "debit": "abc"}]})
    assert out["decision"] == "rejected"


def test_write_requires_confirm():
    out = _execute(ENTRY, token_for(ENTRY), confirm=False)
    assert out["written"] is False


INFLATED = {
    **ENTRY,
    "lines": [
        {"account_code": "6100", "debit": "9900.00", "credit": "0.00"},
        {"account_code": "1000", "debit": "0.00", "credit": "9900.00"},
    ],
}


def test_tampering_after_approval_is_refused_by_the_gate():
    """The scene the demo shows: the model inflates the amount before writing.

    Two independent defenses catch this, and it is worth pinning which fires first.
    With the source document present, reconciliation rejects it: 9,900 is not the
    4,500 on the invoice. The entry never even reaches the token check.
    """
    out = _execute(INFLATED, token_for(ENTRY))
    assert out["written"] is False
    assert "rejected" in out["refused"].lower()


def test_tampering_is_still_refused_when_the_model_hides_the_evidence():
    """...and if the model omits the source to dodge reconciliation, the token catches it.

    This is the important one. Reconciliation needs a source document, so a caller
    that simply leaves `source` out would otherwise switch off the gate's most
    important check. The MCP gate runs with require_source=True, so no evidence
    means no write, and the HMAC token is bound to the content hash regardless.
    """
    out = _EXECUTE(INFLATED, token_for(ENTRY), None, True)  # no source at all
    assert out["written"] is False


def test_a_model_cannot_disable_reconciliation_by_omitting_the_source():
    out = _EXECUTE(ENTRY, token_for(ENTRY), None, True)
    assert out["written"] is False
    assert "evidence" in out.get("failed_checks", [""])[0].lower()


def test_forged_approver_is_refused():
    """The model cannot promote itself to approver by editing the JSON."""
    token = token_for(ENTRY)
    out = _execute({**ENTRY, "approved_by": "cfo", "prepared_by": "mallory"}, token)
    assert out["written"] is False


def test_wrong_account_is_refused_by_reconciliation():
    """Balanced, real accounts, plausible. Only reconciliation catches it."""
    misposted = {
        **ENTRY,
        "lines": [
            {"account_code": "6900", "debit": "4500.00", "credit": "0.00"},
            {"account_code": "1000", "debit": "0.00", "credit": "4500.00"},
        ],
    }
    assert _validate(misposted)["decision"] == "rejected"
    out = _execute(misposted, "no-token")
    assert out["written"] is False


def test_garbage_token_is_refused_cleanly():
    out = _execute(ENTRY, "!!!not-a-token!!!")
    assert out["written"] is False
    assert "token" in out["refused"].lower()

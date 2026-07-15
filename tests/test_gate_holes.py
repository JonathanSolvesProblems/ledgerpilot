"""Regression tests for entries that LOOK valid and must still be refused.

Every case here was a real hole in the gate. Each one balances, uses accounts that
exist, and would survive a trial balance. They are the interesting failures: not
"the model produced garbage", but "the model produced something plausible".
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ledgerpilot.chart_of_accounts import default_state
from ledgerpilot.gate import Gate
from ledgerpilot.models import GateDecision, JournalEntry, JournalLine
from ledgerpilot.tokens import ApprovalToken, TokenError, issue_token, verify_token

SIGNING_KEY = "test-key"


def gate() -> Gate:
    return Gate(state=default_state(reference=date(2026, 6, 30)),
                approval_threshold=Decimal("10000.00"))


def entry(lines, **kw) -> JournalEntry:
    base = dict(
        ref="JE-X", entry_date=date(2026, 6, 20), memo="m",
        prepared_by="agent", approved_by="controller",
    )
    base.update(kw)
    return JournalEntry(lines=lines, **base)


def test_entry_with_no_lines_is_refused():
    """0 == 0 balances, so an empty entry used to pass all eight checks vacuously."""
    result = gate().evaluate(entry([]))
    assert result.decision == GateDecision.REJECTED


def test_entry_that_moves_no_value_is_refused():
    """Debit-only, credit-only, and all-zero entries are not double entry."""
    for lines in (
        [JournalLine(account_code="6100", debit="100.00")],
        [JournalLine(account_code="1000", credit="100.00")],
    ):
        assert gate().evaluate(entry(lines)).decision == GateDecision.REJECTED


def test_same_account_wash_entry_is_refused():
    """Dr 6100 5,000 / Cr 6100 5,000 balances and moves nothing. It is a wash."""
    result = gate().evaluate(entry([
        JournalLine(account_code="6100", debit="5000.00"),
        JournalLine(account_code="6100", credit="5000.00"),
    ]))
    assert result.decision == GateDecision.REJECTED
    assert any(c.check == "no_self_contra" and not c.passed for c in result.checks)


def test_gate_fails_closed_on_any_failing_check():
    """Only the approval threshold may fail without rejecting. Everything else blocks."""
    g = gate()
    clean = entry([
        JournalLine(account_code="6100", debit="500.00"),
        JournalLine(account_code="1000", credit="500.00"),
    ])
    assert g.evaluate(clean).decision == GateDecision.APPROVED
    for c in g.evaluate(clean).checks:
        assert c.passed, c


# --- the token must sign everything that reaches the ledger ----------------

def _approved_pair():
    g = gate()
    e = entry([
        JournalLine(account_code="6100", debit="4500.00", description="Rent"),
        JournalLine(account_code="1000", credit="4500.00", description="Cash"),
    ])
    return g, e, issue_token(SIGNING_KEY, e, g.evaluate(e))


def test_token_rejects_a_rewritten_narration():
    """`memo` becomes the Odoo narration, so it has to be inside the signature."""
    _, e, token = _approved_pair()
    tampered = e.model_copy(update={"memo": "Reversal of Q1 provision, see attached"})
    with pytest.raises(TokenError):
        verify_token(SIGNING_KEY, tampered, token)


def test_token_rejects_a_forged_approver():
    """approved_by IS the segregation-of-duties attestation. It cannot be free text."""
    _, e, token = _approved_pair()
    forged = e.model_copy(update={"approved_by": "cfo", "prepared_by": "mallory"})
    with pytest.raises(TokenError):
        verify_token(SIGNING_KEY, forged, token)


def test_token_rejects_a_rewritten_line_description():
    _, e, token = _approved_pair()
    lines = [
        e.lines[0].model_copy(update={"description": "Consulting"}),
        e.lines[1],
    ]
    with pytest.raises(TokenError):
        verify_token(SIGNING_KEY, e.model_copy(update={"lines": lines}), token)


def test_token_rejects_a_wrong_signing_key():
    """Nothing in the suite previously attempted an outright forgery."""
    _, e, token = _approved_pair()
    with pytest.raises(TokenError):
        verify_token("not-the-key", e, token)


@pytest.mark.parametrize("garbage", [
    "not-base64-at-all!!",
    "eyJhIjogMX0=",           # valid base64 + JSON, missing fields
    "WzEsIDIsIDNd",           # a JSON list: body["entry_hash"] used to raise TypeError
    "eyJlbnRyeV9oYXNoIjogMSwgImRlY2lzaW9uIjogImFwcHJvdmVkIiwgImlzc3VlZF9mb3JfcmVmIjogInIiLCAic2lnbmF0dXJlIjogMX0=",  # non-string fields
])
def test_malformed_tokens_raise_tokenerror_not_typeerror(garbage):
    """A model relays these over MCP, so every bad shape must be a domain error."""
    with pytest.raises(TokenError):
        ApprovalToken.from_str(garbage)

"""Unit tests for the planner's pure helpers (no API calls).

Covers the function-calling tool implementation (lookup_accounts) and the
proposal parser's tolerance for code-fenced JSON.
"""

from __future__ import annotations

import json

from ledgerpilot.chart_of_accounts import ACCOUNTS
from ledgerpilot.planner import lookup_accounts, parse_proposal


def test_lookup_accounts_matches_keywords():
    rows = json.loads(lookup_accounts(ACCOUNTS, "rent expense"))
    codes = {r["code"] for r in rows}
    assert "6100" in codes  # Rent expense
    # every returned row is a real chart account
    assert all(r["code"] in ACCOUNTS for r in rows)


def test_lookup_accounts_by_type():
    rows = json.loads(lookup_accounts(ACCOUNTS, "liability"))
    types = {r["type"] for r in rows}
    assert types == {"liability"}


def test_lookup_accounts_never_returns_empty():
    rows = json.loads(lookup_accounts(ACCOUNTS, "zzz-nomatch-keyword"))
    assert len(rows) > 0  # falls back to all postable accounts
    assert all(r["postable"] for r in rows)


def test_parse_proposal_plain_json():
    raw = ('{"ref":"JE-1","entry_date":"2026-06-15","memo":"rent",'
           '"lines":[{"account_code":"6100","debit":"4500.00","credit":"0.00"},'
           '{"account_code":"1000","debit":"0.00","credit":"4500.00"}],'
           '"rationale":"","confidence":0.9}')
    p = parse_proposal(raw)
    assert p.entry.total_debit == p.entry.total_credit
    assert p.entry.lines[0].account_code == "6100"


def test_parse_proposal_tolerates_code_fence():
    raw = ('```json\n{"ref":"JE-2","entry_date":"2026-06-15","memo":"x",'
           '"lines":[{"account_code":"6200","debit":"100.00","credit":"0.00"},'
           '{"account_code":"1000","debit":"0.00","credit":"100.00"}]}\n```')
    p = parse_proposal(raw)
    assert str(p.entry.total_debit) == "100.00"

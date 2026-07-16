"""Tests for the Odoo write clients (governed write-back backends)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from ledgerpilot.config import Config
from ledgerpilot.odoo_client import (
    OdooClientError,
    XmlrpcOdooClient,
    build_odoo_client,
)


def blank_config(**overrides) -> Config:
    base = dict(
        dashscope_api_key="", dashscope_base_url="", planner_model="qwen3.7-max",
        vision_model="qwen3-vl-plus", signing_key="k", approval_threshold=Decimal("10000.00"),
        odoo_url="", odoo_db="", odoo_username="", odoo_api_key="", odoo_mcp_server_url="",
    )
    base.update(overrides)
    return Config(**base)


def test_factory_returns_expected_types():
    assert isinstance(build_odoo_client(blank_config()), XmlrpcOdooClient)


def test_xmlrpc_client_requires_config():
    client = XmlrpcOdooClient(config=blank_config())
    with pytest.raises(OdooClientError):
        client.create_move({"ref": "X", "date": "2026-06-15", "narration": "", "line_ids": []})


# --- exercise the clients end-to-end with fake transports ------------------

SAMPLE_PAYLOAD = {
    "ref": "JE-1",
    "date": "2026-06-15",
    "narration": "rent",
    "line_ids": [
        (0, 0, {"account_code": "6100", "name": "Rent", "debit": 4500.0, "credit": 0.0}),
        (0, 0, {"account_code": "1000", "name": "Cash", "debit": 0.0, "credit": 4500.0}),
    ],
    "ledgerpilot_hash": "abc123",
}


class FakeServerProxy:
    """Minimal stand-in for Odoo's XML-RPC endpoints."""

    def __init__(self, url):
        self.url = url
        self.created = []
        self.posted = []

    def authenticate(self, db, user, key, ctx):
        return 7  # a uid

    def execute_kw(self, db, uid, key, model, method, args, kw=None):
        if model == "account.account" and method == "search":
            code = args[0][0][2]
            return [int(code)]  # pretend the account id equals its code
        if model == "account.journal" and method == "search":
            return [1]  # a general journal
        if model == "account.move" and method == "search":
            # No existing move with this hash (first write).
            return []
        if model == "account.move" and method == "create":
            self.created.append(args[0])
            return 4242
        if model == "account.move" and method == "action_post":
            self.posted.append(args[0])
            return True
        raise AssertionError(f"unexpected call {model}.{method}")


def test_xmlrpc_client_posts_a_move(monkeypatch):
    import ledgerpilot.odoo_client as oc

    proxies = []

    def fake_proxy(url):
        p = FakeServerProxy(url)
        proxies.append(p)
        return p

    monkeypatch.setattr(oc.xmlrpc_client, "ServerProxy", fake_proxy)
    client = XmlrpcOdooClient(config=blank_config(
        odoo_url="http://ecs-odoo:8069", odoo_db="lp", odoo_username="agent", odoo_api_key="k",
    ))
    move_id = client.create_move(SAMPLE_PAYLOAD)
    assert move_id == 4242
    # The object proxy is the second one created (common, then object).
    obj = proxies[-1]
    created = obj.created[0]
    assert created["ref"] == "JE-1"
    assert created["move_type"] == "entry"       # a journal entry, not an invoice
    assert created["journal_id"] == 1            # resolved general journal
    assert len(created["line_ids"]) == 2
    assert created["line_ids"][0][2]["account_id"] == 6100  # code resolved to id
    assert "ledgerpilot:abc123" in created["narration"]  # hash embedded for dedupe
    assert obj.posted == [[4242]]                # the move was posted, not left draft


class ExistingMoveProxy(FakeServerProxy):
    """A server where a move with the same hash already exists."""

    def execute_kw(self, db, uid, key, model, method, args, kw=None):
        if model == "account.move" and method == "search":
            return [999]  # already posted
        return super().execute_kw(db, uid, key, model, method, args, kw)


def test_xmlrpc_client_is_idempotent_server_side(monkeypatch):
    import ledgerpilot.odoo_client as oc

    proxies = []
    monkeypatch.setattr(oc.xmlrpc_client, "ServerProxy",
                        lambda url: proxies.append(ExistingMoveProxy(url)) or proxies[-1])
    client = XmlrpcOdooClient(config=blank_config(
        odoo_url="http://ecs-odoo:8069", odoo_db="lp", odoo_username="agent", odoo_api_key="k",
    ))
    move_id = client.create_move(SAMPLE_PAYLOAD)
    assert move_id == 999                 # returned the existing move
    assert proxies[-1].created == []      # never posted again


class DedupeSpyProxy(FakeServerProxy):
    """Records the search domains the client uses to look for an existing move."""

    def __init__(self, url):
        super().__init__(url)
        self.move_searches = []

    def execute_kw(self, db, uid, key, model, method, args, kw=None):
        if model == "account.move" and method == "search":
            self.move_searches.append(args[0])
            return []
        return super().execute_kw(db, uid, key, model, method, args, kw)


def _spy_client(monkeypatch):
    import ledgerpilot.odoo_client as oc

    proxies = []

    def fake_proxy(url):
        p = DedupeSpyProxy(url)
        proxies.append(p)
        return p

    monkeypatch.setattr(oc.xmlrpc_client, "ServerProxy", fake_proxy)
    client = XmlrpcOdooClient(config=blank_config(
        odoo_url="http://ecs-odoo:8069", odoo_db="lp", odoo_username="agent", odoo_api_key="k",
    ))
    client.create_move(SAMPLE_PAYLOAD)
    return proxies[-1]


def test_a_cancelled_move_never_suppresses_a_re_post(monkeypatch):
    """Both dedupe guards must ignore cancelled moves.

    A cancelled entry is not in the ledger. If either guard matched one, a
    legitimate re-post would be silently skipped and the caller handed the id of a
    move that no longer counts. This bit us for real: after cancelling a run, the
    hash guard matched the cancelled moves and two thirds of the next run never
    posted.
    """
    proxy = _spy_client(monkeypatch)
    dedupe_searches = [d for d in proxy.move_searches
                       if any("narration" in str(c) or "ref" in str(c) for c in d)]
    assert dedupe_searches, "expected the client to search before creating"
    for domain in dedupe_searches:
        assert ["state", "!=", "cancel"] in domain, (
            f"dedupe search {domain} does not exclude cancelled moves"
        )


class FlakyProxy(FakeServerProxy):
    """Fails the first execute_kw at the transport layer, like a dropped keep-alive."""

    calls = 0

    def execute_kw(self, db, uid, key, model, method, args, kw=None):
        FlakyProxy.calls += 1
        if FlakyProxy.calls == 1:
            from http.client import ResponseNotReady
            raise ResponseNotReady("Request-sent")
        return super().execute_kw(db, uid, key, model, method, args, kw)


def test_transport_failure_reconnects_and_retries(monkeypatch):
    """A dropped connection must not kill a long run mid-ledger."""
    import ledgerpilot.odoo_client as oc

    FlakyProxy.calls = 0
    monkeypatch.setattr(oc.xmlrpc_client, "ServerProxy", FlakyProxy)
    client = XmlrpcOdooClient(config=blank_config(
        odoo_url="http://ecs-odoo:8069", odoo_db="lp", odoo_username="agent", odoo_api_key="k",
    ))
    assert client.create_move(SAMPLE_PAYLOAD) == 4242  # survived the blip


def test_server_faults_are_not_retried(monkeypatch):
    """A Fault means the server answered and refused; retrying would just repeat it."""
    import ledgerpilot.odoo_client as oc

    class FaultingProxy(FakeServerProxy):
        seen = 0

        def execute_kw(self, db, uid, key, model, method, args, kw=None):
            FaultingProxy.seen += 1
            raise oc.xmlrpc_client.Fault(2, "Only posted entries can be reset to draft.")

    monkeypatch.setattr(oc.xmlrpc_client, "ServerProxy", FaultingProxy)
    client = XmlrpcOdooClient(config=blank_config(
        odoo_url="http://ecs-odoo:8069", odoo_db="lp", odoo_username="agent", odoo_api_key="k",
    ))
    with pytest.raises(oc.xmlrpc_client.Fault):
        client.create_move(SAMPLE_PAYLOAD)
    assert FaultingProxy.seen == 1, "a server Fault must not be retried"

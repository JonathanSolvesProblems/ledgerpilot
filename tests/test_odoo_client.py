"""Tests for the Odoo write clients (governed write-back backends)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from ledgerpilot.config import Config
from ledgerpilot.odoo_client import (
    ModelStudioMcpClient,
    OdooClientError,
    XmlrpcOdooClient,
    build_odoo_client,
)


def blank_config(**overrides) -> Config:
    base = dict(
        dashscope_api_key="", dashscope_base_url="", planner_model="qwen3-max",
        vision_model="qwen3-vl-plus", signing_key="k", approval_threshold=Decimal("10000.00"),
        odoo_url="", odoo_db="", odoo_username="", odoo_api_key="", odoo_mcp_server_url="",
    )
    base.update(overrides)
    return Config(**base)


def test_factory_returns_expected_types():
    assert isinstance(build_odoo_client(blank_config(), prefer="xmlrpc"), XmlrpcOdooClient)
    assert isinstance(build_odoo_client(blank_config(), prefer="mcp"), ModelStudioMcpClient)


def test_xmlrpc_client_requires_config():
    client = XmlrpcOdooClient(config=blank_config())
    with pytest.raises(OdooClientError):
        client.create_move({"ref": "X", "date": "2026-06-15", "narration": "", "line_ids": []})


def test_mcp_client_requires_server_url():
    client = ModelStudioMcpClient(config=blank_config(), mcp_server_url="")
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

    def authenticate(self, db, user, key, ctx):
        return 7  # a uid

    def execute_kw(self, db, uid, key, model, method, args, kw=None):
        if model == "account.account" and method == "search":
            code = args[0][0][2]
            return [int(code)]  # pretend the account id equals its code
        if model == "account.move" and method == "create":
            self.created.append(args[0])
            return 4242
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
    assert len(created["line_ids"]) == 2
    assert created["line_ids"][0][2]["account_id"] == 6100  # code resolved to id


class FakeResponses:
    def __init__(self, text):
        self._text = text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return type("R", (), {"output_text": self._text})()


class FakeOpenAI:
    def __init__(self, text):
        self.responses = FakeResponses(text)


def test_mcp_client_drives_responses_api_and_parses_move_id():
    client = ModelStudioMcpClient(
        config=blank_config(dashscope_api_key="k"),
        mcp_server_url="https://mcp.example/sse",
    )
    fake = FakeOpenAI('{"move_id": 99}')
    client._client = fake  # inject transport
    move_id = client.create_move(SAMPLE_PAYLOAD)
    assert move_id == 99
    # It must have attached the Odoo MCP server as an mcp tool.
    call = fake.responses.calls[0]
    assert any(t.get("type") == "mcp" and t.get("server_url", "").endswith("/sse")
               for t in call["tools"])
    assert "validate_write" in call["input"]
    assert "execute_approved_write" in call["input"]


def test_mcp_client_raises_on_unparseable_output():
    client = ModelStudioMcpClient(
        config=blank_config(dashscope_api_key="k"),
        mcp_server_url="https://mcp.example/sse",
    )
    client._client = FakeOpenAI("sorry I could not do that")
    with pytest.raises(OdooClientError):
        client.create_move(SAMPLE_PAYLOAD)

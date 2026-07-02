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

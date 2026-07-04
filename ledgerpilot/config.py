"""Runtime configuration, read from the environment.

Defaults target Alibaba Cloud Model Studio's OpenAI-compatible endpoint so the
planner can talk to Qwen models with the standard ``openai`` client.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


def _load_dotenv() -> None:
    """Populate os.environ from a local .env file if present.

    Lightweight, no dependency. Existing environment variables win, so real
    shell config is never overridden. Looks in the current directory and the
    two parents (covers running from repo root or a subdirectory).
    """
    for base in (Path.cwd(), *Path.cwd().parents[:2]):
        env_file = base / ".env"
        if not env_file.exists():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())
        break


@dataclass(frozen=True)
class Config:
    dashscope_api_key: str
    dashscope_base_url: str
    planner_model: str
    vision_model: str
    signing_key: str
    approval_threshold: Decimal

    # Alibaba Cloud Odoo (system of record)
    odoo_url: str
    odoo_db: str
    odoo_username: str
    odoo_api_key: str
    odoo_mcp_server_url: str


def load_config() -> Config:
    _load_dotenv()
    return Config(
        dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
        dashscope_base_url=os.environ.get(
            "DASHSCOPE_BASE_URL",
            "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        ),
        planner_model=os.environ.get("LEDGERPILOT_PLANNER_MODEL", "qwen3-max"),
        vision_model=os.environ.get("LEDGERPILOT_VISION_MODEL", "qwen3-vl-plus"),
        signing_key=os.environ.get("LEDGERPILOT_SIGNING_KEY", "dev-insecure-key"),
        approval_threshold=Decimal(
            os.environ.get("LEDGERPILOT_APPROVAL_THRESHOLD", "10000")
        ),
        odoo_url=os.environ.get("ODOO_URL", ""),
        odoo_db=os.environ.get("ODOO_DB", ""),
        odoo_username=os.environ.get("ODOO_USERNAME", ""),
        odoo_api_key=os.environ.get("ODOO_API_KEY", ""),
        odoo_mcp_server_url=os.environ.get("ODOO_MCP_SERVER_URL", ""),
    )

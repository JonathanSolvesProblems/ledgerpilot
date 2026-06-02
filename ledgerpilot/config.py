"""Runtime configuration, read from the environment.

Defaults target Alibaba Cloud Model Studio's OpenAI-compatible endpoint so the
planner can talk to Qwen models with the standard ``openai`` client.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal


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


def load_config() -> Config:
    return Config(
        dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
        dashscope_base_url=os.environ.get(
            "DASHSCOPE_BASE_URL",
            "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        ),
        planner_model=os.environ.get("LEDGERPILOT_PLANNER_MODEL", "qwen-max"),
        vision_model=os.environ.get("LEDGERPILOT_VISION_MODEL", "qwen3-vl-plus"),
        signing_key=os.environ.get("LEDGERPILOT_SIGNING_KEY", "dev-insecure-key"),
        approval_threshold=Decimal(
            os.environ.get("LEDGERPILOT_APPROVAL_THRESHOLD", "10000")
        ),
        odoo_url=os.environ.get("ODOO_URL", ""),
        odoo_db=os.environ.get("ODOO_DB", ""),
        odoo_username=os.environ.get("ODOO_USERNAME", ""),
        odoo_api_key=os.environ.get("ODOO_API_KEY", ""),
    )

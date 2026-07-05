"""The generative planner: turns an unstructured close task into a candidate entry.

Uses a Qwen3 model (qwen3.7-max) on Alibaba Cloud Model Studio through the
OpenAI-compatible endpoint, with a strict JSON schema for the proposed journal
entry. For harder cases, enable Qwen3 thinking mode (qwen3.7-max-thinking). The planner
is deliberately the *only* generative step in the write path, and its output is
treated as a proposal, never a write.

The model is asked to ground its proposal in the provided chart of accounts and
open period. It cannot invent account codes that pass the gate, so hallucinations
are caught downstream rather than silently posted.
"""

from __future__ import annotations

# === ALIBABA CLOUD DEPLOYMENT PROOF ===
# This file calls Alibaba Cloud Model Studio (DashScope) via the OpenAI-compatible
# endpoint (see `Planner.propose` -> client.chat.completions.create using
# config.dashscope_base_url). Together with ledgerpilot/odoo_client.py (Odoo on
# ECS + Responses-API MCP), these are the designated Proof of Alibaba Cloud
# Deployment code files for the hackathon submission.

import json
from datetime import date
from typing import Optional

from .chart_of_accounts import ACCOUNTS, LedgerState
from .config import Config, load_config
from .models import JournalEntry, JournalLine, Proposal

_SYSTEM = """You are LedgerPilot's accounting planner. You convert a described \
financial event into a single balanced double-entry journal entry.

Rules you MUST follow:
- Use only account codes from the provided chart of accounts.
- Total debits MUST equal total credits.
- Use positive amounts; express direction via the debit vs credit field.
- Date the entry inside an open period when possible.
- Never invent accounts. If unsure, pick the closest valid account.

Return ONLY JSON matching this schema:
{"ref": str, "entry_date": "YYYY-MM-DD", "memo": str,
 "lines": [{"account_code": str, "description": str,
            "debit": "0.00", "credit": "0.00"}],
 "rationale": str, "confidence": 0.0}
"""


def _accounts_brief(accounts: dict) -> str:
    return "\n".join(
        f"  {a.code}  {a.name} ({a.type.value}{'' if a.postable else ', non-postable'})"
        for a in accounts.values()
    )


def _open_periods_brief(state: LedgerState) -> str:
    return ", ".join(
        f"{p.year}-{p.month:02d}" for p in state.periods if p.is_open
    ) or "none"


def build_prompt(task: str, state: LedgerState, accounts: dict) -> list[dict]:
    user = (
        f"Chart of accounts:\n{_accounts_brief(accounts)}\n\n"
        f"Open periods: {_open_periods_brief(state)}\n\n"
        f"Financial event to record:\n{task}\n\n"
        "Produce the balanced journal entry as JSON."
    )
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]


def parse_proposal(raw: str) -> Proposal:
    """Parse the model's JSON into a Proposal (without trusting its validity)."""
    data = json.loads(raw)
    lines = [
        JournalLine(
            account_code=str(ln["account_code"]),
            description=ln.get("description", ""),
            debit=str(ln.get("debit", "0.00")),
            credit=str(ln.get("credit", "0.00")),
        )
        for ln in data["lines"]
    ]
    entry = JournalEntry(
        ref=data.get("ref", "AUTO"),
        entry_date=date.fromisoformat(data["entry_date"]),
        memo=data.get("memo", ""),
        lines=lines,
        prepared_by="agent",
        source_doc_id=data.get("source_doc_id"),
    )
    return Proposal(
        entry=entry,
        rationale=data.get("rationale", ""),
        confidence=float(data.get("confidence", 0.0)),
    )


class Planner:
    """Calls Qwen on Model Studio to draft a journal entry from a description."""

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config = config or load_config()
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            # Imported lazily so the gate/eval path has no hard dependency on it.
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.config.dashscope_api_key,
                base_url=self.config.dashscope_base_url,
            )
        return self._client

    def propose(
        self, task: str, state: LedgerState, accounts: dict | None = None
    ) -> Proposal:
        accounts = accounts if accounts is not None else ACCOUNTS
        client = self._ensure_client()
        messages = build_prompt(task, state, accounts)
        resp = client.chat.completions.create(
            model=self.config.planner_model,
            messages=messages,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        return parse_proposal(resp.choices[0].message.content)

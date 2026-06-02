"""Governed write-back to the Odoo system of record on Alibaba Cloud.

This is the only module that mutates the ledger, and it refuses to do so unless:
  1. the gate APPROVED the entry, and
  2. a valid HMAC approval token authorizes this exact entry, and
  3. the entry has not already been written (idempotency on content hash).

It mirrors the propose -> validate -> execute pattern exposed by the Odoo MCP
server (validate_write issues a checked plan; execute_approved_write commits it
behind ODOO_MCP_ENABLE_WRITES + confirm=true). The same governance lives on both
sides, so an approved write is auditable end to end.

This file is the designated "Proof of Alibaba Cloud Deployment" artifact: it
contains the calls that reach the Odoo instance running on Alibaba Cloud ECS.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .config import Config, load_config
from .gate import Gate
from .models import GateDecision, JournalEntry
from .tokens import ApprovalToken, issue_token, verify_token


class WriteRefused(Exception):
    """Raised when a write is blocked by the governance layer."""


@dataclass
class WriteReceipt:
    entry_hash: str
    odoo_move_id: Optional[int]
    status: str  # "written" | "idempotent_skip"
    detail: str


class OdooWriteBack:
    """Commits gate-approved entries to Odoo on Alibaba Cloud ECS.

    The Odoo client is injected so tests and the eval harness can run without a
    live ERP. In production it is an xmlrpc/jsonrpc client pointed at the
    ECS-hosted Odoo, or a thin wrapper over the Odoo MCP write tools.
    """

    def __init__(
        self,
        gate: Gate,
        config: Optional[Config] = None,
        odoo_client=None,
    ) -> None:
        self.gate = gate
        self.config = config or load_config()
        self.odoo = odoo_client
        # Idempotency ledger: content hashes already committed this run.
        self._written: dict[str, int] = {}

    def commit(self, entry: JournalEntry, token: ApprovalToken) -> WriteReceipt:
        # 1. Re-run the gate at write time. The token is necessary but not
        #    sufficient; we never trust a stale approval.
        result = self.gate.evaluate(entry)
        if result.decision != GateDecision.APPROVED:
            raise WriteRefused(
                f"Gate decision at write time is '{result.decision.value}', not approved."
            )

        # 2. Verify the token authorizes THIS exact entry.
        verify_token(self.config.signing_key, entry, token)

        # 3. Idempotency: never post the same content twice.
        h = entry.content_hash()
        if h in self._written:
            return WriteReceipt(
                entry_hash=h,
                odoo_move_id=self._written[h],
                status="idempotent_skip",
                detail="Entry already committed this run; skipped.",
            )

        # 4. Commit to Odoo on Alibaba Cloud ECS.
        move_id = self._write_to_odoo(entry)
        self._written[h] = move_id
        return WriteReceipt(
            entry_hash=h,
            odoo_move_id=move_id,
            status="written",
            detail="Committed account.move to Odoo.",
        )

    def _write_to_odoo(self, entry: JournalEntry) -> int:
        """Create an ``account.move`` in Odoo. Requires an injected client.

        The payload maps LedgerPilot lines to Odoo ``account.move.line`` records.
        In the MCP-backed path this goes through validate_write ->
        execute_approved_write with confirm=true.
        """
        if self.odoo is None:
            raise WriteRefused(
                "No Odoo client configured. Set ODOO_* env vars or inject a client. "
                "The Alibaba Cloud ECS Odoo instance is the write target."
            )
        move_lines = [
            (
                0,
                0,
                {
                    "account_code": ln.account_code,
                    "name": ln.description or entry.memo,
                    "debit": float(ln.debit),
                    "credit": float(ln.credit),
                },
            )
            for ln in entry.lines
        ]
        payload = {
            "ref": entry.ref,
            "date": entry.entry_date.isoformat(),
            "narration": entry.memo,
            "line_ids": move_lines,
            # Idempotency key surfaced to Odoo for dedupe on the server side too.
            "ledgerpilot_hash": entry.content_hash(),
        }
        return self.odoo.create_move(payload)


def approve_and_commit(
    entry: JournalEntry,
    gate: Gate,
    writer: OdooWriteBack,
    config: Optional[Config] = None,
) -> WriteReceipt:
    """End-to-end happy path: gate -> token -> governed write.

    Raises WriteRefused if the gate does not fully approve the entry.
    """
    config = config or load_config()
    result = gate.evaluate(entry)
    if result.decision != GateDecision.APPROVED:
        raise WriteRefused(
            f"Entry not approved ({result.decision.value}): "
            + "; ".join(c.detail for c in result.failed_checks)
        )
    token = issue_token(config.signing_key, entry, result)
    return writer.commit(entry, token)

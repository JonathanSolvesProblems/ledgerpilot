"""Governed write-back to the Odoo system of record.

This is the only module that mutates the ledger, and it refuses to do so unless:
  1. the gate APPROVED the entry, and
  2. a valid HMAC approval token authorizes this exact entry, and
  3. the entry has not already been written (in-run idempotency on content hash).

The write itself is delegated to an injected client (`ledgerpilot/odoo_client.py`),
which is what actually reaches the Odoo instance. This module owns the governance,
not the transport. The designated Proof of Alibaba Cloud Deployment code file is
`ledgerpilot/planner.py` (the Qwen calls on Model Studio); `odoo_client.py` posts
to a live Odoo (demonstrated on Odoo 19 / odoo.sh).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .config import Config, load_config
from .gate import Gate
from .models import GateDecision, JournalEntry, SourceDocument
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
    """Commits gate-approved entries to a live Odoo.

    The Odoo client is injected so tests and the eval harness can run without a
    live ERP. In production it is an xmlrpc/jsonrpc client pointed at the
    live Odoo, or a thin wrapper over the Odoo MCP write tools.
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

    def commit(
        self,
        entry: JournalEntry,
        token: ApprovalToken,
        source: Optional[SourceDocument] = None,
    ) -> WriteReceipt:
        # 1. Re-run the gate at write time, including reconciliation against the
        #    source document when one is supplied. The token is necessary but not
        #    sufficient; we never trust a stale approval, and the semantic
        #    reconciliation check must run on the exact path that mutates the
        #    ledger, not only at proposal time.
        result = self.gate.evaluate(entry, source)
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

        # 4. Commit to the live Odoo.
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
                "The live Odoo instance is the write target."
            )
        # Money is Decimal everywhere internally (models.py refuses to build it from
        # a float). Odoo's XML-RPC monetary fields require float, so this is the one
        # deliberate conversion, confined to the transport boundary and nowhere else.
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
    source: Optional[SourceDocument] = None,
) -> WriteReceipt:
    """End-to-end happy path: gate -> token -> governed write.

    When a source document is supplied it is reconciled against the entry on the
    exact path that writes to the ledger, so a balanced-but-wrong entry (right
    form, wrong account or amount) is refused here, not just at proposal time.

    Raises WriteRefused if the gate does not fully approve the entry.
    """
    config = config or load_config()
    result = gate.evaluate(entry, source)
    if result.decision != GateDecision.APPROVED:
        raise WriteRefused(
            f"Entry not approved ({result.decision.value}): "
            + "; ".join(c.detail for c in result.failed_checks)
        )
    token = issue_token(config.signing_key, entry, result)
    return writer.commit(entry, token, source)

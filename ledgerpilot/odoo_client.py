"""Odoo write client for the governed write-back path.

``XmlrpcOdooClient`` implements ``create_move(payload) -> int``: it resolves account
codes to Odoo ids, creates an ``account.move`` and posts it, so the result is an
official ledger record rather than a draft. Demonstrated against Odoo 19 on odoo.sh.

The write is idempotent on a sequential retry: the entry's content hash is embedded
in the move's narration and searched for before creating. That is a best-effort
guard, not an atomic one (see ``create_move``).

The MCP write path lives in ``ledgerpilot/mcp_server.py``, which exposes the gate
itself as MCP tools so a model can be given the write tool without being given the
authority to write anything wrong.
"""

from __future__ import annotations

from typing import Optional
from xmlrpc import client as xmlrpc_client

from .config import Config, load_config


class OdooClientError(Exception):
    """Raised when the Odoo backend cannot be reached or a write fails."""


class XmlrpcOdooClient:
    """Writes and posts account.move records to a live Odoo via XML-RPC.

    Targets a real Odoo instance (tested against Odoo 19 on odoo.sh). The write
    creates a journal entry (``move_type='entry'``) in a general journal and
    posts it, so it becomes an official ledger record, not a draft.
    """

    def __init__(self, config: Optional[Config] = None, post: bool = True) -> None:
        self.config = config or load_config()
        self.post = post
        self._uid: Optional[int] = None
        self._models = None
        self._account_ids: dict[str, int] = {}
        self._journal_id: Optional[int] = None

    def _connect(self) -> None:
        cfg = self.config
        if not (cfg.odoo_url and cfg.odoo_db and cfg.odoo_username and cfg.odoo_api_key):
            raise OdooClientError(
                "Odoo not configured. Set ODOO_URL/ODOO_DB/ODOO_USERNAME/ODOO_API_KEY "
                "to the target Odoo instance."
            )
        common = xmlrpc_client.ServerProxy(f"{cfg.odoo_url}/xmlrpc/2/common")
        uid = common.authenticate(cfg.odoo_db, cfg.odoo_username, cfg.odoo_api_key, {})
        if not uid:
            raise OdooClientError("Odoo authentication failed (check credentials).")
        self._uid = uid
        self._models = xmlrpc_client.ServerProxy(f"{cfg.odoo_url}/xmlrpc/2/object")

    def _ensure(self) -> None:
        if self._models is None:
            self._connect()

    def _kw(self, model, method, args, opts=None):
        """Call Odoo, reconnecting once if the transport (not the server) failed.

        `xmlrpc.client` reuses a single HTTP connection, so one dropped keep-alive
        poisons every later call on the proxy with ResponseNotReady, and a long run
        dies partway through with the ledger half-written. A server-side `Fault` is a
        real error and is re-raised untouched; only transport failures are retried,
        and only once, against a freshly authenticated proxy.
        """
        cfg = self.config
        last: Exception | None = None
        for attempt in (1, 2):
            try:
                return self._models.execute_kw(cfg.odoo_db, self._uid, cfg.odoo_api_key,
                                               model, method, args, opts or {})
            except xmlrpc_client.Fault:
                raise  # the server answered and said no; retrying changes nothing
            except Exception as exc:  # noqa: BLE001 - transport layer, many shapes
                last = exc
                if attempt == 1:
                    self._connect()
        raise OdooClientError(
            f"Odoo transport failed on {model}.{method} after a reconnect: {last}"
        ) from last

    def _account_id(self, code: str) -> int:
        if code in self._account_ids:
            return self._account_ids[code]
        ids = self._kw("account.account", "search", [[["code", "=", code]]], {"limit": 1})
        if not ids:
            raise OdooClientError(f"Account code {code} not found in Odoo.")
        self._account_ids[code] = ids[0]
        return ids[0]

    def _general_journal_id(self) -> int:
        if self._journal_id is None:
            ids = self._kw("account.journal", "search", [[["type", "=", "general"]]], {"limit": 1})
            if not ids:
                raise OdooClientError("No general journal found in Odoo.")
            self._journal_id = ids[0]
        return self._journal_id

    def create_move(self, payload: dict) -> int:
        """Create (and post) an account.move from the LedgerPilot write payload.

        Deduplicates on the entry's content hash embedded in the narration: a
        sequential re-run of the same entry returns the existing move instead of
        posting it twice. Note this search-then-create is not atomic, so it does
        not defend against two genuinely concurrent writers; a DB-level unique
        constraint would be required for that. In-run dedupe is handled upstream
        by OdooWriteBack.
        """
        self._ensure()
        lp_hash = payload.get("ledgerpilot_hash", "")
        ref = payload.get("ref", "")

        # Two independent dedupe guards, because they fail differently.
        #   content hash: exact. Catches a byte-identical retry.
        #   ref:          the business key of the entry (one invoice, one entry).
        #                 Catches a retry whose hash moved for a benign reason, e.g.
        #                 a memo edit or a change to what content_hash covers.
        # Neither is atomic (see the caveat below), so both are best-effort guards
        # against a sequential retry, not a substitute for a unique constraint.
        # Both guards must ignore cancelled moves. A cancelled entry is not in the
        # ledger, so letting one match here would suppress a legitimate re-post and
        # silently return the id of a move that no longer counts.
        if lp_hash:
            existing = self._kw("account.move", "search",
                                [[["narration", "like", f"ledgerpilot:{lp_hash}"],
                                  ["state", "!=", "cancel"]]], {"limit": 1})
            if existing:
                return int(existing[0])
        if ref:
            existing = self._kw("account.move", "search",
                                [[["ref", "=", ref], ["state", "!=", "cancel"]]], {"limit": 1})
            if existing:
                return int(existing[0])

        line_ids = [
            (0, 0, {
                "account_id": self._account_id(ln["account_code"]),
                "name": ln["name"],
                "debit": ln["debit"],
                "credit": ln["credit"],
            })
            for _, _, ln in payload["line_ids"]
        ]
        narration = payload["narration"]
        if lp_hash:
            narration = f"{narration} [ledgerpilot:{lp_hash}]"
        move_vals = {
            "move_type": "entry",
            "journal_id": self._general_journal_id(),
            "ref": payload["ref"],
            "date": payload["date"],
            "narration": narration,
            "line_ids": line_ids,
        }
        move_id = int(self._kw("account.move", "create", [move_vals]))
        if self.post:
            self._kw("account.move", "action_post", [[move_id]])
        return move_id


def build_odoo_client(config: Optional[Config] = None):
    """Factory for the ledger write client."""
    return XmlrpcOdooClient(config=config)

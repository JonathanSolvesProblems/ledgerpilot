"""HMAC-signed approval tokens binding a gate verdict to an exact entry.

A token is the only thing ``writeback.py`` will accept. It is signed over the
entry's content hash, so it cannot be transplanted onto a different (e.g.
tampered) entry: change a single cent and the hash changes and the signature
no longer verifies. This makes the write path tamper-evident and auditable.
"""

from __future__ import annotations

import base64
import hmac
import json
from dataclasses import dataclass
from hashlib import sha256

from .models import GateDecision, GateResult, JournalEntry


class TokenError(Exception):
    """Raised when a token is missing, malformed, or fails verification."""


@dataclass(frozen=True)
class ApprovalToken:
    entry_hash: str
    decision: str
    issued_for_ref: str
    signature: str

    def to_str(self) -> str:
        body = {
            "entry_hash": self.entry_hash,
            "decision": self.decision,
            "issued_for_ref": self.issued_for_ref,
            "signature": self.signature,
        }
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode()

    @classmethod
    def from_str(cls, token: str) -> "ApprovalToken":
        # A token arrives as untrusted text (a model relays it over MCP), so every
        # malformed shape has to surface as TokenError, never as a raw TypeError:
        # a JSON list decodes fine and then body["entry_hash"] raises TypeError,
        # and a non-string signature would blow up later inside compare_digest.
        try:
            raw = base64.urlsafe_b64decode(str(token).encode())
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise TokenError("Approval token is not an object.")
            fields = {
                k: body[k]
                for k in ("entry_hash", "decision", "issued_for_ref", "signature")
            }
            if not all(isinstance(v, str) for v in fields.values()):
                raise TokenError("Approval token fields must all be strings.")
            return cls(**fields)
        except TokenError:
            raise
        except (ValueError, KeyError, TypeError) as exc:
            raise TokenError(f"Malformed approval token: {exc}") from exc


def _sign(signing_key: str, entry_hash: str, decision: str, ref: str) -> str:
    msg = f"{entry_hash}|{decision}|{ref}".encode()
    return hmac.new(signing_key.encode(), msg, sha256).hexdigest()


def issue_token(
    signing_key: str, entry: JournalEntry, result: GateResult
) -> ApprovalToken:
    """Mint a token for an APPROVED gate result. Refuses anything else."""
    if result.decision != GateDecision.APPROVED:
        raise TokenError(
            f"Cannot issue write token for decision '{result.decision.value}'."
        )
    if result.entry_hash != entry.content_hash():
        raise TokenError("Gate result hash does not match the entry.")
    sig = _sign(signing_key, result.entry_hash, result.decision.value, entry.ref)
    return ApprovalToken(
        entry_hash=result.entry_hash,
        decision=result.decision.value,
        issued_for_ref=entry.ref,
        signature=sig,
    )


def verify_token(signing_key: str, entry: JournalEntry, token: ApprovalToken) -> None:
    """Raise TokenError unless the token validly authorizes writing ``entry``."""
    if token.decision != GateDecision.APPROVED.value:
        raise TokenError("Token does not carry an APPROVED decision.")
    if token.entry_hash != entry.content_hash():
        raise TokenError("Token hash does not match entry; entry was modified.")
    if token.issued_for_ref != entry.ref:
        raise TokenError("Token reference does not match entry.")
    expected = _sign(signing_key, token.entry_hash, token.decision, token.issued_for_ref)
    if not hmac.compare_digest(expected, token.signature):
        raise TokenError("Token signature invalid.")

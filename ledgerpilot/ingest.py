"""Multimodal ingestion: read invoices / bank statements with Qwen-VL.

Turns a scanned document (image or PDF page) into a structured, normalized
description the planner can reason over. This is the second generative step;
like the planner it produces a proposal, never a write. Its output feeds the
planner, whose entry is then validated by the deterministic gate.

Uses qwen3-vl-plus on Alibaba Cloud Model Studio via the OpenAI-compatible
endpoint. The client is created lazily so the gate/eval path stays dependency
free.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from .config import Config, load_config
from .models import money

_SYSTEM = """You read scanned financial documents (invoices, bank statements, \
receipts) and extract a normalized record. Return ONLY JSON:
{"doc_type": "invoice|statement|receipt",
 "counterparty": str,
 "document_id": str,
 "date": "YYYY-MM-DD",
 "currency": str,
 "net_amount": "0.00",
 "tax_amount": "0.00",
 "gross_amount": "0.00",
 "line_items": [{"description": str, "amount": "0.00"}]}
Amounts are strings with two decimals. Do not guess values that are not present."""


@dataclass
class ExtractedDocument:
    doc_type: str
    counterparty: str
    document_id: str
    date: str
    currency: str
    net_amount: Decimal
    tax_amount: Decimal
    gross_amount: Decimal
    line_items: list[dict]

    def to_task(self) -> str:
        """Render the extraction as a planner task description."""
        items = "; ".join(
            f"{li['description']} {li['amount']}" for li in self.line_items
        )
        return (
            f"{self.doc_type} {self.document_id} from {self.counterparty} dated "
            f"{self.date}: net {self.net_amount} {self.currency}, tax "
            f"{self.tax_amount}, gross {self.gross_amount}. Items: {items}."
        )


def parse_extraction(raw: str) -> ExtractedDocument:
    data = json.loads(raw)
    return ExtractedDocument(
        doc_type=data.get("doc_type", "invoice"),
        counterparty=data.get("counterparty", ""),
        document_id=data.get("document_id", ""),
        date=data.get("date", ""),
        currency=data.get("currency", "USD"),
        net_amount=money(data.get("net_amount", "0.00")),
        tax_amount=money(data.get("tax_amount", "0.00")),
        gross_amount=money(data.get("gross_amount", "0.00")),
        line_items=data.get("line_items", []),
    )


class DocumentIngestor:
    """Extracts structured records from document images using Qwen-VL."""

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config = config or load_config()
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.config.dashscope_api_key,
                base_url=self.config.dashscope_base_url,
            )
        return self._client

    def extract(self, image_url: str) -> ExtractedDocument:
        """Extract from a document image given a URL or data URI."""
        client = self._ensure_client()
        resp = client.chat.completions.create(
            model=self.config.vision_model,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract the record from this document."},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                },
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        return parse_extraction(resp.choices[0].message.content)

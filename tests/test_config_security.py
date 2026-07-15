"""The signing key is the only thing guarding a network-facing ledger write.

`load_config()` must refuse to hand back a config that would sign approval tokens
with the public development key while a live Odoo is configured. Without this, a
deployment that forgets one env var exposes an unauthenticated write endpoint.
"""

from __future__ import annotations

import pytest

from ledgerpilot import config as config_mod
from ledgerpilot.config import DEV_SIGNING_KEY, InsecureConfig, load_config


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch, tmp_path):
    # Run from a directory with no .env so the real one cannot leak a key in.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config_mod, "_load_dotenv", lambda: None)
    for k in ("LEDGERPILOT_SIGNING_KEY", "ODOO_URL", "ODOO_DB",
              "ODOO_USERNAME", "ODOO_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def test_live_erp_without_a_real_signing_key_is_refused(monkeypatch):
    monkeypatch.setenv("ODOO_URL", "https://demo.odoo.com")
    with pytest.raises(InsecureConfig):
        load_config()


def test_dev_key_is_fine_with_no_live_erp(monkeypatch):
    # Offline gate, demo and tests: no ODOO_URL, dev key is acceptable.
    cfg = load_config()
    assert cfg.signing_key == DEV_SIGNING_KEY
    assert cfg.odoo_url == ""


def test_live_erp_with_a_real_key_is_allowed(monkeypatch):
    monkeypatch.setenv("ODOO_URL", "https://demo.odoo.com")
    monkeypatch.setenv("LEDGERPILOT_SIGNING_KEY", "a-real-secret-key")
    cfg = load_config()
    assert cfg.signing_key == "a-real-secret-key"


def test_blank_signing_key_env_falls_back_and_is_refused(monkeypatch):
    # A blank line in .env (LEDGERPILOT_SIGNING_KEY=) sets it to "".
    monkeypatch.setenv("ODOO_URL", "https://demo.odoo.com")
    monkeypatch.setenv("LEDGERPILOT_SIGNING_KEY", "")
    with pytest.raises(InsecureConfig):
        load_config()

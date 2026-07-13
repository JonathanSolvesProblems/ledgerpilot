#!/usr/bin/env bash
# Produce the Proof of Alibaba Cloud Deployment transcript.
#
# Run ON the ECS instance. Everything below executes on Alibaba Cloud: the test
# suite, the deterministic gate stress-test, the live Qwen calls to Alibaba Cloud
# Model Studio, and the governed write to the live Odoo ERP. The instance identity
# is read from the ECS metadata service (169.254.169.254 / 100.100.100.200), which
# only answers on a real ECS instance, so the transcript cannot be produced from a
# laptop.
#
#     bash ecs_proof.sh > docs/ecs_proof.txt
set -u
cd /opt/ledgerpilot

M=http://100.100.100.200/latest/meta-data
echo "================================================================================"
echo " LedgerPilot: Proof of Alibaba Cloud Deployment"
echo " The backend below is RUNNING ON Alibaba Cloud ECS, not on a local machine."
echo "================================================================================"
echo "generated (UTC) : $(date -u '+%Y-%m-%d %H:%M:%S')"
echo "hostname        : $(hostname)"
echo "kernel          : $(uname -sr)"
echo "python          : $(.venv/bin/python -V 2>&1)"
echo
echo "--- Alibaba Cloud ECS instance metadata service ($M) ---"
echo "  instance-id   : $(curl -s $M/instance-id)"
echo "  region-id     : $(curl -s $M/region-id)"
echo "  zone-id       : $(curl -s $M/zone-id)"
echo "  instance-type : $(curl -s $M/instance/instance-type)"
echo "  image-id      : $(curl -s $M/image-id)"
echo "  public ipv4   : $(curl -s $M/eipv4)"
echo "  private ipv4  : $(curl -s $M/private-ipv4)"
echo
echo "--- Alibaba Cloud services this backend calls ---"
echo "  Model Studio  : $(grep -m1 '^DASHSCOPE_BASE_URL' .env | cut -d= -f2-)"
echo "  ECS OpenAPI   : scripts/deploy_ecs.py provisioned this instance"
echo

echo "================================================================================"
echo " 1. TEST SUITE (on ECS)"
echo "================================================================================"
.venv/bin/python -m pytest -q 2>&1 | tail -3
echo

echo "================================================================================"
echo " 2. DETERMINISTIC GATE STRESS-TEST, 204 synthetic cases (on ECS)"
echo "================================================================================"
.venv/bin/python -m eval.harness 2>&1 | tail -14
echo

echo "================================================================================"
echo " 3a. LIVE QWEN MEASUREMENT (on ECS -> Alibaba Cloud Model Studio)"
echo "     Flagship model. 39 natural-language close tasks. The planner uses"
echo "     function calling to look up account codes; the deterministic gate"
echo "     judges what it produced."
echo "================================================================================"
echo "model: ${FLAGSHIP_MODEL:-qwen3.7-max}"
LEDGERPILOT_PLANNER_MODEL="${FLAGSHIP_MODEL:-qwen3.7-max}" \
  .venv/bin/python -m eval.harness --live 2>&1 | tail -50
echo

echo "================================================================================"
echo " 3b. SAME MEASUREMENT ON A WEAKER MODEL (qwen-flash), on ECS"
echo "     The point of the gate is that it does not depend on the model being"
echo "     right. A cheaper model makes more mistakes; the gate must still let"
echo "     nothing wrong through."
echo "================================================================================"
echo "model: qwen-flash"
LEDGERPILOT_PLANNER_MODEL=qwen-flash \
  .venv/bin/python -m eval.harness --live 2>&1 | tail -50
echo

echo "================================================================================"
echo " 4. REAL GOVERNED WRITE TO A LIVE ODOO ERP (on ECS)"
echo "    gate -> HMAC approval token -> XML-RPC -> posted account.move"
echo "================================================================================"
.venv/bin/python scripts/real_odoo_write.py --scenario utilities
echo
echo "--- idempotency: byte-identical re-run from this same instance ---"
.venv/bin/python scripts/real_odoo_write.py --scenario utilities
echo
echo "--- independent check: how many moves actually exist with that ref? ---"
.venv/bin/python - <<'PY'
from ledgerpilot.config import load_config
from ledgerpilot.odoo_client import XmlrpcOdooClient

client = XmlrpcOdooClient(config=load_config())
client._ensure()  # open the XML-RPC session before querying
for ref in ("LP-RENT-2026-06", "LP-UTIL-2026-06"):
    n = client._kw("account.move", "search_count", [[["ref", "=", ref]]])
    print(f"  moves with ref {ref}: {n}   (1 = no double-post)")
total = client._kw("account.move", "search_count", [[["move_type", "=", "entry"]]])
print(f"  total journal entries in the live ledger: {total}")
PY
echo

echo "================================================================================"
echo " 5. WEB UI SERVED FROM THIS INSTANCE"
echo "================================================================================"
curl -s -o /dev/null -w "  http://127.0.0.1/ -> HTTP %{http_code}, %{size_download} bytes\n" http://127.0.0.1/
echo "  public URL    : http://$(curl -s $M/eipv4)/"
echo
echo "================================================================================"
echo " END OF PROOF"
echo "================================================================================"

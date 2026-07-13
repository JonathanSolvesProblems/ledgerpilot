#!/usr/bin/env bash
# Bring the LedgerPilot backend up on a fresh Alibaba Cloud ECS instance.
#
# Run ON the ECS box (scripts/deploy_ecs.py provisions it, this configures it):
#     bash ecs_bootstrap.sh
#
# Expects /opt/ledgerpilot/.env to already exist (scp'd separately; it holds the
# Model Studio and Odoo secrets and is never committed).
#
# Afterwards the machine is a working LedgerPilot backend: it can run the test
# suite, the offline gate stress-test, the live Qwen measurement against Alibaba
# Cloud Model Studio, and the governed write to the real Odoo. It also serves the
# gate's web UI on port 80 so the running backend is visible from a browser.
set -euo pipefail

REPO=https://github.com/JonathanSolvesProblems/ledgerpilot.git
DIR=/opt/ledgerpilot

echo "== packages =="
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git

echo "== source =="
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch --quiet origin
  git -C "$DIR" reset --quiet --hard origin/main
else
  # Keep any .env that was uploaded before the clone.
  mkdir -p "$DIR"
  git clone --quiet "$REPO" /tmp/lp
  cp -rn /tmp/lp/. "$DIR"/
  rm -rf /tmp/lp
fi
cd "$DIR"

echo "== python env =="
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e ".[dev]"
.venv/bin/python -c "import sys; print('python', sys.version.split()[0])"

echo "== web UI service (port 80) =="
.venv/bin/python webui.py
cat >/etc/systemd/system/ledgerpilot-ui.service <<'UNIT'
[Unit]
Description=LedgerPilot gate web UI
After=network.target

[Service]
WorkingDirectory=/opt/ledgerpilot/web
ExecStart=/usr/bin/python3 -m http.server 80
Restart=always

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now ledgerpilot-ui.service

echo
echo "== bootstrap complete =="
echo "backend installed at $DIR, web UI live on port 80"

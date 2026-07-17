#!/usr/bin/env bash
# Serve the gate's web UI over HTTPS on a real hostname, from the ECS instance.
#
# The page has to keep being served BY the Alibaba Cloud box: the whole point of the
# live URL is that the address bar is itself the deployment proof, and the page's own
# header claims the backend is live on ECS. Putting the static file on a CDN or a
# host like Vercel would make that claim false and throw away the eligibility asset,
# so this terminates TLS on the instance instead.
#
# Caddy is used rather than nginx + certbot because it obtains and renews the
# certificate by itself with no cron job and no renewal that silently lapses three
# months after the demo.
#
# Prerequisites:
#   1. An A record for $HOST pointing at this instance's public IP. Caddy proves
#      control of the name over port 80 (ACME http-01), so DNS must resolve BEFORE
#      this runs or the certificate order fails.
#   2. Ports 80 and 443 open in the security group (scripts/deploy_ecs.py does this).
#
# Note on region: Alibaba Cloud requires an ICP filing to serve a domain from
# mainland China regions. This instance is in ap-southeast-1 (Singapore), where that
# does not apply.
#
#   HOST=ledgerpilot.example.com bash scripts/setup_tls.sh
set -euo pipefail

HOST="${HOST:?set HOST to the hostname whose A record points at this box}"
ROOT=/opt/ledgerpilot/web
IP="$(curl -s http://100.100.100.200/latest/meta-data/eipv4 || true)"

echo "== host: $HOST -> $IP =="

resolved="$(getent hosts "$HOST" | awk '{print $1}' | head -1 || true)"
if [ -z "$resolved" ]; then
  echo "FATAL: $HOST does not resolve yet. Add the A record and wait for it to"
  echo "propagate, or Caddy's certificate order will fail and get rate-limited."
  exit 1
fi
if [ -n "$IP" ] && [ "$resolved" != "$IP" ]; then
  echo "FATAL: $HOST resolves to $resolved, but this box is $IP."
  exit 1
fi
echo "   DNS ok: $HOST -> $resolved"

if ! command -v caddy >/dev/null 2>&1; then
  echo "== installing caddy =="
  apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl gnupg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  apt-get update -qq
  apt-get install -y -qq caddy
fi
caddy version

# The python http.server currently holds :80; Caddy needs it for the UI and for the
# ACME challenge.
echo "== handing :80 over from the python server =="
systemctl disable --now ledgerpilot-ui.service 2>/dev/null || true

cat >/etc/caddy/Caddyfile <<EOF
# The hostname: automatic HTTPS, certificate obtained and renewed by Caddy.
$HOST {
	root * $ROOT
	file_server
	encode gzip
	header {
		Cache-Control "no-cache"
		X-Content-Type-Options "nosniff"
		Referrer-Policy "strict-origin-when-cross-origin"
	}
}

# The bare IP keeps working over plain HTTP, so anything already pointing at it
# (a recorded demo, a screenshot, a link in the docs) does not break. Caddy will not
# issue a certificate for an IP address, so this stays http.
http://$IP {
	root * $ROOT
	file_server
	encode gzip
	header Cache-Control "no-cache"
}
EOF

caddy validate --config /etc/caddy/Caddyfile
systemctl enable --now caddy
systemctl reload caddy 2>/dev/null || systemctl restart caddy
sleep 4

echo
echo "== result =="
systemctl is-active caddy | sed 's/^/   caddy: /'
curl -s -o /dev/null -w "   https://$HOST/  -> HTTP %{http_code}\n" "https://$HOST/" || true
curl -s -o /dev/null -w "   http://$IP/     -> HTTP %{http_code}\n" "http://$IP/" || true
echo
echo "The MCP server is untouched on :8080; Model Studio still reaches it over http."

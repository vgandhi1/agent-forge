#!/usr/bin/env bash
# Rewrites AGENTFORGE_OLLAMA_HOST in .env to the current WSL2 default-gateway IP.
# The gateway (Windows host) IP changes across WSL reboots in NAT networking,
# so a hardcoded .env value breaks. Re-run this after a reboot, or wire it into
# your shell startup. Safe to run anytime; only writes if the IP changed.
set -euo pipefail

cd "$(dirname "$0")"
ENV_FILE=".env"
PORT="${OLLAMA_PORT:-11434}"

[ -f "$ENV_FILE" ] || { echo "ERROR: $ENV_FILE not found in $(pwd)" >&2; exit 1; }

GW="$(ip route show default | awk '{print $3; exit}')"
[ -n "$GW" ] || { echo "ERROR: no default gateway found (ip route show default empty)" >&2; exit 1; }

NEW_URL="http://${GW}:${PORT}"
CUR="$(grep -E '^AGENTFORGE_OLLAMA_HOST=' "$ENV_FILE" | head -1 | cut -d= -f2- || true)"

if [ "$CUR" = "$NEW_URL" ]; then
  echo "OK: AGENTFORGE_OLLAMA_HOST already $NEW_URL"
else
  if grep -qE '^AGENTFORGE_OLLAMA_HOST=' "$ENV_FILE"; then
    # in-place rewrite, keep a one-time backup
    cp "$ENV_FILE" "$ENV_FILE.bak"
    sed -i -E "s#^AGENTFORGE_OLLAMA_HOST=.*#AGENTFORGE_OLLAMA_HOST=${NEW_URL}#" "$ENV_FILE"
  else
    printf '\nAGENTFORGE_OLLAMA_HOST=%s\n' "$NEW_URL" >> "$ENV_FILE"
  fi
  echo "UPDATED: AGENTFORGE_OLLAMA_HOST=$NEW_URL (was: ${CUR:-<unset>})"
fi

# verify reachability so a stale/wrong IP fails loud, not silent
if curl -s -m 4 "${NEW_URL}/api/tags" >/dev/null 2>&1; then
  echo "REACHABLE: ${NEW_URL}/api/tags responded"
else
  echo "WARN: ${NEW_URL} not reachable — is Ollama running on the Windows host? (firewall / OLLAMA_HOST=0.0.0.0)" >&2
  exit 2
fi

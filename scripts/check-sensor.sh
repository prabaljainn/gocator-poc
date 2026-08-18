#!/usr/bin/env bash
# Bench/field health check: network, sensor, environment. Run on the Spark.
#   ssh spark-lab-local 'bash ~/gocator-poc/scripts/check-sensor.sh'
SENSOR=${SENSOR:-192.168.1.10}
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ok(){ printf '  \033[32mOK\033[0m   %s\n' "$1"; }
bad(){ printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAILED=1; }

echo "== host =="
echo "  $(hostname) · $(uname -m) · $(. /etc/os-release && echo "$PRETTY_NAME")"

echo "== network =="
IFACE=$(ip -br addr | awk '$3 ~ /^192\.168\.1\./ {print $1; exit}')
if [ -n "$IFACE" ]; then
  ok "$IFACE on $(ip -br addr show "$IFACE" | awk '{print $3}')"
  # ponytail: /sys avoids needing sudo for ethtool; falls back to informational
  SPEED=$(cat "/sys/class/net/$IFACE/speed" 2>/dev/null)
  if [ "$SPEED" = "1000" ]; then ok "link 1000Mb/s"
  elif [ -n "$SPEED" ]; then bad "link ${SPEED}Mb/s — need 1000 for ~100Mbit/s of surfaces"
  else echo "  ..   link speed unreadable (run: sudo ethtool $IFACE)"; fi
else
  bad "no interface on the 192.168.1.0/24 sensor subnet"
fi

echo "== sensor $SENSOR =="
if ping -c 2 -W 2 "$SENSOR" >/dev/null 2>&1; then
  ok "ping ($(ping -c 3 -W 2 "$SENSOR" | awk -F'/' '/rtt/{print $5" ms avg"}'))"
else
  bad "unreachable — check power, cabling, and that it is still at $SENSOR"
fi
for p in 80:web 3190:control 3196:data; do
  port=${p%%:*}; name=${p##*:}
  timeout 2 bash -c "echo > /dev/tcp/$SENSOR/$port" 2>/dev/null \
    && ok "port $port ($name) open" || bad "port $port ($name) closed"
done

echo "== environment =="
if [ -x "$REPO/.venv/bin/python" ]; then
  OUT=$("$REPO/.venv/bin/python" "$REPO/detect.py" --selftest 2>&1 | tail -1)
  [[ "$OUT" == selftest\ ok* ]] && ok "detector — $OUT" || bad "detector selftest: $OUT"
else
  bad "no venv at $REPO/.venv — see docs/setup-dgx.md"
fi
[ -f "$HOME/gosdk/GO_SDK/lib/linux_arm64/libGoSdk.so" ] \
  && ok "GoSDK built" \
  || echo "  ..   GoSDK not built yet — live acquisition blocked (docs/setup-dgx.md Phase 4)"
DISK=$(df -h "$REPO" | awk 'NR==2{print $4}')
echo "  ..   disk free: $DISK"

echo
[ -n "$FAILED" ] && { echo "some checks FAILED — see docs/setup-dgx.md"; exit 1; }
echo "all checks passed"

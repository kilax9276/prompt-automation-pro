#!/usr/bin/env bash
# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
#
# Activate or roll back slice 1 as one operation.
#
# Run under setsid: this script stops the platform manager, and the manager is
# the parent of whatever executes directives on this host. A restart driven
# from inside that process tree kills its own output and leaves the stand in an
# unknown state, which is exactly what happened once already. Detached, the
# script survives its parent and records the outcome in a file either way.
#
#   setsid bash rollout_slice1.sh activate > /tmp/pap2/rollout.log 2>&1 < /dev/null &
#   setsid bash rollout_slice1.sh rollback > /tmp/pap2/rollout.log 2>&1 < /dev/null &
set -uo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT"
MODE="${1:-}"
case "$MODE" in
  activate) CONSOLE_REL="4.5.0-s1"; RECEIVER_REL="2.11.0-s1" ;;
  rollback) CONSOLE_REL="4.4.0";    RECEIVER_REL="2.10.0"    ;;
  *) echo "ERROR::ROLLOUT_BAD_MODE=${MODE}"; exit 2 ;;
esac

say() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }
ports() { (ss -ltn 2>/dev/null || netstat -ltn) | grep -c ":$1"; }

say "mode=${MODE} console=${CONSOLE_REL} receiver=${RECEIVER_REL}"
echo "RET_VALUE::ROLLOUT_MODE=${MODE}"

# Both markers move before the stop, so the manager can only ever come back on
# a complete, self-consistent pair. A stop between two marker writes would be a
# window in which a crash restarts a mixed set.
python3 activate_console_release.py "${CONSOLE_REL}" --root "${ROOT}" || { echo "ERROR::CONSOLE_ACTIVATE_FAILED"; exit 3; }
python3 activate_receiver_release.py "${RECEIVER_REL}" --root "${ROOT}" || { echo "ERROR::RECEIVER_ACTIVATE_FAILED"; exit 3; }

PMPID="$(cat runtime/platform-manager.pid 2>/dev/null || true)"
if [ -n "${PMPID}" ] && [ -d "/proc/${PMPID}" ]; then
  say "stopping platform manager pid=${PMPID}"
  kill "${PMPID}" 2>/dev/null || true
  for _ in $(seq 1 40); do [ -d "/proc/${PMPID}" ] || break; sleep 0.5; done
  [ -d "/proc/${PMPID}" ] && { say "manager did not stop, sending KILL"; kill -9 "${PMPID}" 2>/dev/null || true; sleep 2; }
fi
pkill -f "${ROOT}/console_releases/" 2>/dev/null || true
pkill -f "${ROOT}/server.py" 2>/dev/null || true
pkill -f "${ROOT}/receivers/" 2>/dev/null || true
sleep 3
say "stopped: 8867=$(ports 8867) 8871=$(ports 8871)"

say "starting platform"
bash start_platform.sh
RC=$?
echo "RET_VALUE::START_RC=${RC}"

sleep 3
echo "RET_VALUE::PORT_8867=$(ports 8867)"
echo "RET_VALUE::PORT_8871=$(ports 8871)"
RH="$(python3 -c "import json,urllib.request;print(json.loads(urllib.request.urlopen('http://127.0.0.1:8867/health',timeout=5).read().decode()).get('version'))" 2>/dev/null || echo NONE)"
CH="$(python3 -c "import json,urllib.request;print(json.loads(urllib.request.urlopen('http://127.0.0.1:8871/health',timeout=5).read().decode()).get('version'))" 2>/dev/null || echo NONE)"
echo "RET_VALUE::HEALTH_RECEIVER_VERSION=${RH}"
echo "RET_VALUE::HEALTH_CONSOLE_VERSION=${CH}"
RP="$( (ss -ltnpH 2>/dev/null || ss -ltnp) | grep ':8867' | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)"
CP="$( (ss -ltnpH 2>/dev/null || ss -ltnp) | grep ':8871' | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)"
echo "RET_VALUE::LIVE_RECEIVER_CMD=$(tr '\0' ' ' < "/proc/${RP}/cmdline" 2>/dev/null | cut -c1-180)"
echo "RET_VALUE::LIVE_CONSOLE_CMD=$(tr '\0' ' ' < "/proc/${CP}/cmdline" 2>/dev/null | cut -c1-180)"

if [ "${RH}" = "${RECEIVER_REL}" ] && [ "${CH}" = "${CONSOLE_REL}" ] && [ "$(ports 8867)" = "1" ] && [ "$(ports 8871)" = "1" ]; then
  echo "RET_VALUE::ROLLOUT_RESULT=OK"
else
  echo "RET_VALUE::ROLLOUT_RESULT=MISMATCH"
fi
echo "RET_VALUE::ROLLOUT_DONE=1"

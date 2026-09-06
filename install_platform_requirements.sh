#!/usr/bin/env bash
# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION-platform")"
RELEASE="$ROOT/console_releases/$VERSION"
VENDOR="$RELEASE/vendor"
if [[ ! -f "$RELEASE/console_server.py" ]]; then
  echo "ERROR::CONSOLE_RELEASE_NOT_FOUND=$RELEASE" >&2
  exit 1
fi
if python3 -c 'import aiohttp' >/dev/null 2>&1; then
  python3 -c 'import aiohttp; print("RET_VALUE::AIOHTTP_PRESENT=1"); print("RET_VALUE::AIOHTTP_VERSION="+aiohttp.__version__)'
else
  mkdir -p "$VENDOR"
  python3 -m pip install --target "$VENDOR" -r "$ROOT/requirements-console.txt"
fi
PYTHONPATH="$VENDOR${PYTHONPATH:+:$PYTHONPATH}" python3 -c 'import aiohttp; print("RET_VALUE::PLATFORM_DEPS_OK=1")'
echo "RET_VALUE::CONSOLE_RELEASE=$VERSION"

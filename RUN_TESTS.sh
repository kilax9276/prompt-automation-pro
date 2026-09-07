#!/usr/bin/env bash
# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
#
# Both suites must target the same console release in one process: each test
# file puts its release directory on sys.path and imports profile_store, and
# Python caches the module, so mixing releases in a single run silently tests
# whichever imported first. Slice 1 acceptance is deliberately re-run against
# the slice-2 release — that is the regression check.
set -euo pipefail
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
export PAP_CONSOLE_RELEASE="${PAP_CONSOLE_RELEASE:-4.5.0-s2}"
export PAP_RECEIVER_RELEASE="${PAP_RECEIVER_RELEASE:-2.11.0-s1}"
rm -rf console_releases/*/__pycache__ tests/__pycache__
echo "RET_VALUE::CONSOLE_RELEASE=${PAP_CONSOLE_RELEASE}"
echo "RET_VALUE::RECEIVER_RELEASE=${PAP_RECEIVER_RELEASE}"
python3 -m pytest tests/ -v -p no:cacheprovider
echo "RET_VALUE::TESTS_RC=$?"

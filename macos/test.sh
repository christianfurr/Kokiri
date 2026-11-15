#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -I scripts/prepare_sparkle.py
swift test --jobs "${KOKIRI_BUILD_JOBS:-2}"

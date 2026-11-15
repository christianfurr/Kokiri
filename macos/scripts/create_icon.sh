#!/bin/bash
set -euo pipefail
KOKIRI_MASTER="${1:?original PNG path required}"
KOKIRI_ICON="${2:?destination icns path required}"
KOKIRI_ICONSET="$(mktemp -d "${TMPDIR:-/tmp}/kokiri-icon.XXXXXX")/Kokiri.iconset"
trap 'rm -rf "$(dirname "$KOKIRI_ICONSET")"' EXIT
mkdir -p "$KOKIRI_ICONSET" "$(dirname "$KOKIRI_ICON")"
for KOKIRI_SIZE in 16 32 128 256 512; do
  /usr/bin/sips -z "$KOKIRI_SIZE" "$KOKIRI_SIZE" "$KOKIRI_MASTER" --out "$KOKIRI_ICONSET/icon_${KOKIRI_SIZE}x${KOKIRI_SIZE}.png" >/dev/null
  KOKIRI_RETINA=$((KOKIRI_SIZE * 2))
  /usr/bin/sips -z "$KOKIRI_RETINA" "$KOKIRI_RETINA" "$KOKIRI_MASTER" --out "$KOKIRI_ICONSET/icon_${KOKIRI_SIZE}x${KOKIRI_SIZE}@2x.png" >/dev/null
done
/usr/bin/iconutil -c icns "$KOKIRI_ICONSET" -o "$KOKIRI_ICON"

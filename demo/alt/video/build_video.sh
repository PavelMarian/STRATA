#!/usr/bin/env bash
# Full cut: wait for the voice-over, record the scenes to its durations, assemble the mp4.
#   bash build_video.sh <voice out dir> <base url> <out.mp4>
set -euo pipefail
VOICE="${1:?voice dir}"; BASE="${2:?base url}"; OUT="${3:?out.mp4}"
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/../../.." && pwd)"
until [ -f "$VOICE/durations.json" ]; do sleep 15; done
echo "voice ready: $(cat "$VOICE/durations.json" | tr -d '\n ')"
while pgrep -f "record.mjs.*rec_test" >/dev/null; do sleep 5; done
curl -s http://127.0.0.1:9334/json/version >/dev/null 2>&1 || { setsid google-chrome --headless=new --no-sandbox --disable-gpu --hide-scrollbars --window-size=1920,1080 --remote-debugging-port=9334 about:blank >/dev/null 2>&1 & sleep 3; }
REC="$ROOT/build/rec_final"; rm -rf "$REC"
node "$HERE/record.mjs" "$BASE" "$VOICE/durations.json" "$REC"
bash "$HERE/assemble.sh" "$REC" "$VOICE" "$OUT"

#!/usr/bin/env bash
# Assemble a static Hugging Face Space from demo/: the project page becomes index.html,
# the workbench becomes workbench.html, and the STRATA sources the live page needs sit next to it.
#   bash demo/build_space.sh [out dir]      (default: build/space)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/build/space}"
rm -rf "$OUT"; mkdir -p "$OUT/strata" "$OUT/examples/olist" "$OUT/data/olist"
A="$ROOT/demo"
sed -e 's#href="index.html"#href="workbench.html"#g' "$A/about.html" > "$OUT/index.html"
sed -e 's#location.href = "live.html"#location.href = "live.html"#' "$A/index.html" > "$OUT/workbench.html"
sed -e 's#location.href = "index.html"#location.href = "workbench.html"#' -e 's#const SRC = "../";#const SRC = "./";#' "$A/live.html" > "$OUT/live.html"
cp "$A/end.html" "$A/data.js" "$A/timeline.js" "$A/live_glue.py" "$A/strata.png" "$OUT/"
cp "$A/data/olist/"*.csv "$OUT/data/olist/"
cp "$ROOT/strata/"*.py "$OUT/strata/"
cp "$ROOT/examples/olist/schema.json" "$OUT/examples/olist/"
cat > "$OUT/README.md" <<'MD'
---
title: STRATA demo
emoji: 🪨
colorFrom: blue
colorTo: gray
sdk: static
pinned: false
license: mit
---
STRATA: layer-by-layer point-in-time checking of ML pipelines written by coding agents.
`index.html` is the project page, `workbench.html` the demo over recorded runs, `live.html` runs
STRATA in the browser (Pyodide) with a model of your choice through OpenRouter.
MD
grep -q 'const SRC = "./";' "$OUT/live.html" && grep -q 'workbench.html' "$OUT/index.html" && echo "space assembled in $OUT" && du -sh "$OUT"

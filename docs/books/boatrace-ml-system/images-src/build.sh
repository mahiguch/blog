#!/bin/sh
# 使い方: ./build.sh <name>   → <name>.html を撮って ../../../../images/boatrace-ml-system/<name>.png に書く
set -e
cd "$(dirname "$0")"
OUT="$(cd ../../../../images/boatrace-ml-system && pwd)"
NP="$(npm root -g)/@mermaid-js/mermaid-cli/node_modules:$(npm root -g)"
for n in "$@"; do
  NODE_PATH="$NP" node shoot.js "$n.html" "$OUT/$n.png"
  echo "$n: $(file "$OUT/$n.png" | sed -E 's/.*, ([0-9]+ x [0-9]+),.*/\1/') $(du -h "$OUT/$n.png" | cut -f1)"
done

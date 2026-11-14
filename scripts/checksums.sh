#!/usr/bin/env bash
# Write or check SHA256SUMS for the evaluation results and the frozen test sets.
#   scripts/checksums.sh write    regenerate the manifest (do this only when results legitimately change)
#   scripts/checksums.sh check    verify nothing has been edited since (CI runs this)
set -euo pipefail
cd "$(dirname "$0")/.."
files() { find results evals -type f \( -name '*.json' -o -name '*.jsonl' -o -name '*.md' -o -name '*.txt' \) | LC_ALL=C sort; }
case "${1:-check}" in
  write) files | xargs sha256sum > SHA256SUMS; echo "wrote SHA256SUMS ($(wc -l < SHA256SUMS) files)";;
  check) sha256sum --check --quiet SHA256SUMS && echo "all $(wc -l < SHA256SUMS) files match";;
  *) echo "usage: $0 write|check" >&2; exit 2;;
esac

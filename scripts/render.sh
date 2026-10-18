#!/usr/bin/env bash
# Regenerate figures and the browser report without repeating the optimization.
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
output_dir="${1:-output/demo}"
if [[ $# -gt 0 ]]; then
    shift
fi
exec "$script_dir/container.sh" python3 render_results.py \
    --input "$output_dir/final.pvd" \
    --history "$output_dir/history.csv" \
    --summary "$output_dir/summary.json" \
    --surface-style isosurface --threshold 0.8 --smooth-iterations 30 --camera low \
    --output-dir "$output_dir" \
    "$@"

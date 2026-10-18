#!/usr/bin/env bash
# Container-side workflow. No mesh-size or optimizer overrides are applied.
set -euo pipefail
output_dir="${1:-output/demo}"
ranks="${BRIDGE_MPI_RANKS:-1}"
if [[ ! "$ranks" =~ ^[1-9][0-9]*$ ]]; then
    printf '%s\n' 'BRIDGE_MPI_RANKS must be a positive integer.' >&2
    exit 2
fi
mkdir -p "$output_dir"
gmsh -3 /workspace/bridge.geo -format msh2 -o "$output_dir/bridge.msh" -nt 1 -v 2
cd "$output_dir"
mpiexec -n "$ranks" python3 -u /workspace/bridge.py --output_dir . 2>&1 | tee run.log
python3 /workspace/render_results.py \
    --input final.pvd --history history.csv --summary summary.json \
    --surface-style isosurface --threshold 0.8 --smooth-iterations 30 --camera low \
    --output-dir .

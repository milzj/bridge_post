#!/usr/bin/env bash
# Run the original model and optimizer with the user-authorized coarser mesh.
# BRIDGE_MESH_SCALE=2 (default) doubles the original 0.015 mesh size to 0.03.
# Set BRIDGE_MESH_SCALE=1 to generate the original-resolution mesh.
# Two MPI processes are used by default; BRIDGE_MPI_RANKS=1 selects serial.
# The optional argument is an output folder.
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ $# -gt 1 ]]; then
    printf '%s\n' 'Usage: ./scripts/run.sh [OUTPUT_DIRECTORY]' >&2
    exit 2
fi
exec "$script_dir/container.sh" bash scripts/run_in_container.sh "${1:-output/demo}"

#!/usr/bin/env bash
# Container-side workflow. Only mesh resolution is changed, as authorized.
# Default: BRIDGE_MESH_SCALE=2 gives size 0.03 instead of the original 0.015.
# BRIDGE_MESH_SCALE=1 restores the original mesh; all model/MMA settings stay fixed.
set -euo pipefail
output_dir="${1:-output/demo}"
ranks="${BRIDGE_MPI_RANKS:-2}"
if [[ ! "$ranks" =~ ^[1-9][0-9]*$ ]]; then
    printf '%s\n' 'BRIDGE_MPI_RANKS must be a positive integer.' >&2
    exit 2
fi
mkdir -p "$output_dir"
mesh_scale="${BRIDGE_MESH_SCALE:-2}"
python3 - "$mesh_scale" "$output_dir/mesh-settings.json" <<'PYMESH'
import json
import math
from pathlib import Path
import sys
scale = float(sys.argv[1])
if not math.isfinite(scale) or scale < 1:
    raise SystemExit('BRIDGE_MESH_SCALE must be finite and at least 1 (1 = original mesh).')
settings = dict(original_mesh_size=0.015, mesh_scale=scale, mesh_size=0.015*scale,
                mesh_note=('User-authorized coarser mesh for local resources; all other model '
                           'and optimizer settings retain their original values.' if scale != 1 else
                           'Original mesh specification.'))
Path(sys.argv[2]).write_text(json.dumps(settings, indent=2)+'\n')
print(f"MESH NOTE: scale={scale:g}; size={settings['mesh_size']:g}; original size=0.015", flush=True)
print(settings['mesh_note'], flush=True)
PYMESH
gmsh -3 /workspace/bridge.geo -clscale "$mesh_scale" -format msh2 -o "$output_dir/bridge.msh" -nt 1 -v 2
cd "$output_dir"
mpiexec -n "$ranks" python3 -u /workspace/bridge.py --output_dir . 2>&1 | tee run.log
python3 /workspace/render_results.py \
    --input final.pvd --history history.csv --summary summary.json \
    --surface-style isosurface --threshold 0.8 --smooth-iterations 30 --camera low \
    --output-dir .

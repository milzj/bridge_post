#!/usr/bin/env bash
# All arguments are forwarded to the bridge solver.
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ $# -eq 0 ]]; then
    set -- --output-dir output/demo
fi
exec "$script_dir/container.sh" python3 bridge.py "$@"

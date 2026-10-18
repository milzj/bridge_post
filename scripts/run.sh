#!/usr/bin/env bash
# Run the original mesh and optimizer; the optional argument is an output folder.
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ $# -gt 1 ]]; then
    printf '%s\n' 'Usage: ./scripts/run.sh [OUTPUT_DIRECTORY]' >&2
    exit 2
fi
exec "$script_dir/container.sh" bash scripts/run_in_container.sh "${1:-output/demo}"

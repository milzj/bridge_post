#!/usr/bin/env bash
# Open the saved report in the host browser, outside Docker.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
output_dir="${1:-output/demo}"
if [[ "$output_dir" != /* ]]; then
    output_dir="$BRIDGE_REPO_DIR/$output_dir"
fi
report_path="$output_dir/report.html"
if [[ ! -f "$report_path" ]]; then
    printf 'Report not found: %s\nRun ./scripts/run.sh first, or supply the output directory.\n' "$report_path" >&2
    exit 1
fi
if command -v open >/dev/null 2>&1; then
    exec open "$report_path"
elif command -v xdg-open >/dev/null 2>&1; then
    exec xdg-open "$report_path"
else
    printf 'Open this file in a web browser: %s\n' "$report_path"
fi

#!/usr/bin/env bash
# Check source faithfulness, dependencies, and the completed run, including its recorded mesh reduction.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
exec "$BRIDGE_REPO_DIR/scripts/container.sh" python3 tests/verify_model.py \
    --output-dir "${1:-output/demo}"

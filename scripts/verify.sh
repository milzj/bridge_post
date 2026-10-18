#!/usr/bin/env bash
# Small end-to-end run, including a finite-difference check of both sensitivities.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
"$BRIDGE_REPO_DIR/scripts/container.sh" python3 tests/verify_model.py
exec "$BRIDGE_REPO_DIR/scripts/run.sh" \
    --mesh-size 0.15 \
    --max-iterations 3 \
    --verify-gradient \
    --output-dir output/verification \
    "$@"

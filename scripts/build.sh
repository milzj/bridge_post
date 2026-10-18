#!/usr/bin/env bash
# Build the reproducible Firedrake environment. Run from any directory.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
bridge_check_docker

build_args=(build --pull --tag "$BRIDGE_IMAGE")
if [[ -n "${BRIDGE_PLATFORM:-}" ]]; then
    build_args+=(--platform "$BRIDGE_PLATFORM")
fi
docker "${build_args[@]}" "$BRIDGE_REPO_DIR"

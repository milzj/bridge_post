#!/usr/bin/env bash
# Shared setup for the host-side Docker helpers. Source this file; do not run it.
set -euo pipefail

BRIDGE_REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
BRIDGE_IMAGE="${BRIDGE_IMAGE:-bridge-post:2026.10.0}"

bridge_check_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        printf '%s\n' 'Docker is required. Install Docker Desktop on macOS or Docker Engine on Linux.' >&2
        printf '%s\n' 'See https://docs.docker.com/get-started/get-docker/' >&2
        exit 1
    fi
    if ! docker info >/dev/null 2>&1; then
        printf '%s\n' 'Cannot connect to Docker. Start Docker Desktop, or start the Docker Engine service on Linux.' >&2
        printf '%s\n' 'If Docker is already running, check that your user can run: docker info' >&2
        exit 1
    fi
}

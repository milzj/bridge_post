#!/usr/bin/env bash
# Run a command in the image with this checkout mounted read/write at /workspace.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
bridge_check_docker

if ! docker image inspect "$BRIDGE_IMAGE" >/dev/null 2>&1; then
    printf 'Image %s is missing. Run %s/scripts/build.sh first.\n' "$BRIDGE_IMAGE" "$BRIDGE_REPO_DIR" >&2
    exit 1
fi
if [[ $# -eq 0 ]]; then
    printf '%s\n' 'Usage: ./scripts/container.sh COMMAND [ARGUMENT ...]' >&2
    exit 2
fi

run_args=(run --rm --init
    --user "$(id -u):$(id -g)"
    --mount "type=bind,source=$BRIDGE_REPO_DIR,target=/workspace"
    --workdir /workspace
    --env PYTHONDONTWRITEBYTECODE=1
    --env XDG_CACHE_HOME=/tmp/bridge-cache
    --env PYOP2_CACHE_DIR=/tmp/bridge-pyop2
    --env FIREDRAKE_TSFC_KERNEL_CACHE_DIR=/tmp/bridge-tsfc
    --env MPLCONFIGDIR=/tmp/bridge-matplotlib
    --env "OMP_NUM_THREADS=${BRIDGE_THREADS:-1}"
    --env "OPENBLAS_NUM_THREADS=${BRIDGE_THREADS:-1}"
    --env "MKL_NUM_THREADS=${BRIDGE_THREADS:-1}")
run_args+=(--env "BRIDGE_MPI_RANKS=${BRIDGE_MPI_RANKS:-1}")
if [[ -n "${BRIDGE_PLATFORM:-}" ]]; then
    run_args+=(--platform "$BRIDGE_PLATFORM")
fi
if [[ -n "${BRIDGE_MEMORY:-}" ]]; then
    run_args+=(--memory "$BRIDGE_MEMORY")
fi
if [[ -n "${BRIDGE_CPUS:-}" ]]; then
    run_args+=(--cpus "$BRIDGE_CPUS")
fi
if [[ -t 0 && -t 1 ]]; then
    run_args+=(-it)
fi
exec docker "${run_args[@]}" "$BRIDGE_IMAGE" "$@"

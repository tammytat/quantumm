#!/usr/bin/env bash
# =============================================================================
# Build the Quantum TechHub Python sandbox image (Linux / macOS / WSL shell).
#
#   ./scripts/build_sandbox_image.sh
#   ./scripts/build_sandbox_image.sh quantumm/python-ds:3.12
# =============================================================================
set -euo pipefail

IMAGE="${1:-quantumm/python-ds:3.12}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DOCKERFILE="$PROJECT_ROOT/Dockerfile.python-ds"

if ! command -v docker >/dev/null 2>&1; then
    echo "Error: docker not found on PATH. Install Docker (or run scripts/build_sandbox_image.ps1 on Windows)." >&2
    exit 1
fi

if [ ! -f "$DOCKERFILE" ]; then
    echo "Error: Dockerfile not found at $DOCKERFILE" >&2
    exit 1
fi

echo "Building $IMAGE from $DOCKERFILE ..."
docker build -f "$DOCKERFILE" -t "$IMAGE" "$PROJECT_ROOT"
echo "Done. Learner code will now run inside $IMAGE."

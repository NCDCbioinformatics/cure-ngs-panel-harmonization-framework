#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -n "${CONTAINER_ENGINE:-}" ]; then
  ENGINE="$CONTAINER_ENGINE"
elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  ENGINE="docker"
elif command -v podman >/dev/null 2>&1 && podman info >/dev/null 2>&1; then
  ENGINE="podman"
elif command -v docker >/dev/null 2>&1; then
  ENGINE="docker"
else
  ENGINE="podman"
fi
IMAGE="${CURE_NGS_IMAGE:-ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.1-core}"

command -v "$ENGINE" >/dev/null 2>&1 || {
  echo "ERROR: Docker or Podman is required." >&2
  exit 2
}

echo "CURE-NGS beginner tutorial"
echo "Container engine: $ENGINE"
echo "Image: $IMAGE"

if [ "${CURE_NGS_SKIP_PULL:-0}" = "1" ]; then
  echo "Using the image already available on this machine."
else
  echo "Downloading the public, version-pinned core image..."
  "$ENGINE" pull "$IMAGE"
fi

export CONTAINER_ENGINE="$ENGINE"
export CURE_NGS_IMAGE="$IMAGE"
export CURE_NGS_SKIP_BUILD=1
export CURE_NGS_OUTPUT_ROOT="$ROOT_DIR/tutorial-output"
export CURE_NGS_COMPLETION_MESSAGE="Beginner six-component tutorial passed"

bash "$ROOT_DIR/scripts/run_reviewer_demo.sh"

echo
echo "Next: read docs/BEGINNER_TUTORIAL.md to understand each command and output."
echo "The optional full-annotation section explains the external GRCh37/VEP data."

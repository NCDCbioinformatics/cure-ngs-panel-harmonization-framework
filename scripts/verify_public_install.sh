#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${CURE_NGS_VERSION:-0.2.3}"
CORE_IMAGE="${CURE_NGS_CORE_IMAGE:-ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:${VERSION}-core}"
FULL_IMAGE="${CURE_NGS_FULL_IMAGE:-ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:${VERSION}}"

if [ -n "${CONTAINER_ENGINE:-}" ]; then
  ENGINE="$CONTAINER_ENGINE"
elif command -v docker >/dev/null 2>&1; then
  ENGINE="docker"
elif command -v podman >/dev/null 2>&1; then
  ENGINE="podman"
else
  echo "ERROR: Docker or Podman is not installed." >&2
  echo "See docs/INSTALLATION.md for the clean-Ubuntu installation commands." >&2
  exit 2
fi

if ! ENGINE_INFO="$("$ENGINE" info 2>&1)"; then
  echo "ERROR: $ENGINE is installed, but its daemon/socket is not accessible." >&2
  echo "$ENGINE_INFO" >&2
  if [[ "${ENGINE_INFO,,}" == *"permission denied"* ]]; then
    echo >&2
    echo "The current Linux/WSL user cannot access the Docker socket." >&2
    echo "Run once:" >&2
    echo "  sudo groupadd -f docker" >&2
    echo '  sudo usermod -aG docker "$USER"' >&2
    echo "  newgrp docker" >&2
    echo "  docker info" >&2
    echo "For WSL, close its terminals and run 'wsl --shutdown' in Windows PowerShell if needed." >&2
    echo "Do not use chmod 777 on /var/run/docker.sock." >&2
  else
    echo "Run '$ENGINE info' and resolve that error before downloading CURE-NGS." >&2
    echo "Native Ubuntu Docker: sudo systemctl enable --now docker" >&2
    echo "WSL Docker Engine without systemd: sudo service docker start" >&2
  fi
  exit 2
fi

VERSIONS_FILE="$(mktemp)"
trap 'rm -f "$VERSIONS_FILE"' EXIT

echo "CURE-NGS public installation verification"
echo "Container engine: $ENGINE"
"$ENGINE" version

echo
echo "[1/6] Pulling the public core image (no registry login is required)"
"$ENGINE" pull "$CORE_IMAGE"

echo
echo "[2/6] Pulling the public full VEP/vcf2maf image"
"$ENGINE" pull "$FULL_IMAGE"

echo
echo "[3/6] Recording immutable repository digests"
echo "Core: $CORE_IMAGE"
"$ENGINE" image inspect --format '{{.RepoDigests}}' "$CORE_IMAGE"
echo "Full: $FULL_IMAGE"
"$ENGINE" image inspect --format '{{.RepoDigests}}' "$FULL_IMAGE"

echo
echo "[4/6] Checking the core image and its preflight command"
"$ENGINE" run --rm --network none "$CORE_IMAGE" --version | grep -F "$VERSION"
"$ENGINE" run --rm --network none "$CORE_IMAGE" doctor --profile core

echo
echo "[5/6] Checking the full image and pinned external tools"
"$ENGINE" run --rm --network none "$FULL_IMAGE" versions | tee "$VERSIONS_FILE"
grep -Fq "\"version\": \"$VERSION\"" "$VERSIONS_FILE"
grep -Fq 'bcftools 1.13' "$VERSIONS_FILE"
grep -Fq 'samtools 1.13' "$VERSIONS_FILE"
grep -Fq 'ensembl-vep          : 116.1' "$VERSIONS_FILE"
grep -Fq '"revision": "754d68ab4ad3eba29199c5a62e0061745aed7e7e"' "$VERSIONS_FILE"

echo
echo "[6/6] Running the complete six-component beginner tutorial"
CONTAINER_ENGINE="$ENGINE" \
  CURE_NGS_IMAGE="$CORE_IMAGE" \
  CURE_NGS_SKIP_PULL=1 \
  bash "$ROOT_DIR/scripts/run_beginner_tutorial.sh"

echo
echo "CURE-NGS public installation verified"
echo "Tutorial results: $ROOT_DIR/tutorial-output"

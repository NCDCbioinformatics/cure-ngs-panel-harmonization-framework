#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${CURE_NGS_VERSION:-0.2.4}"
IMAGE="${CURE_NGS_FULL_IMAGE:-ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:${VERSION}}"
OUTPUT_DIR="${CURE_NGS_OUTPUT_ROOT:-$ROOT_DIR/tutorial-output}"
REFERENCE_DIR="${1:-${CURE_NGS_REFERENCE_DIR:-}}"
FASTA_RELATIVE="${CURE_NGS_FASTA_RELATIVE:-vep/homo_sapiens/116_GRCh37/Homo_sapiens.GRCh37.75.dna.primary_assembly.fa.gz}"
VEP_RELATIVE="${CURE_NGS_VEP_RELATIVE:-vep}"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/run_full_annotation_tutorial.sh /absolute/reference-store

The reference store must contain a VEP 116 GRCh37 cache and its matching
Ensembl FASTA. The default expected paths below the store are:
  vep/homo_sapiens/116_GRCh37/info.txt
  vep/homo_sapiens/116_GRCh37/Homo_sapiens.GRCh37.75.dna.primary_assembly.fa.gz
  vep/homo_sapiens/116_GRCh37/Homo_sapiens.GRCh37.75.dna.primary_assembly.fa.gz.fai

Override a non-default FASTA path with CURE_NGS_FASTA_RELATIVE. The value must
be relative to the reference-store directory. See docs/REFERENCE_DATA.md.
EOF
}

if [ -z "$REFERENCE_DIR" ]; then
  usage >&2
  exit 2
fi
if [ ! -d "$REFERENCE_DIR" ]; then
  echo "ERROR: Reference directory does not exist: $REFERENCE_DIR" >&2
  exit 2
fi
REFERENCE_DIR="$(cd "$REFERENCE_DIR" && pwd)"
if [[ "$FASTA_RELATIVE" = /* || "$VEP_RELATIVE" = /* ]]; then
  echo "ERROR: CURE_NGS_FASTA_RELATIVE and CURE_NGS_VEP_RELATIVE must be relative paths." >&2
  exit 2
fi

if [ -n "${CONTAINER_ENGINE:-}" ]; then
  ENGINE="$CONTAINER_ENGINE"
elif command -v docker >/dev/null 2>&1; then
  ENGINE="docker"
elif command -v podman >/dev/null 2>&1; then
  ENGINE="podman"
else
  echo "ERROR: Docker or Podman is required." >&2
  exit 2
fi
if ! ENGINE_INFO="$("$ENGINE" info 2>&1)"; then
  echo "ERROR: $ENGINE is installed but its daemon/socket is not accessible." >&2
  echo "$ENGINE_INFO" >&2
  exit 2
fi

FASTA_HOST="$REFERENCE_DIR/$FASTA_RELATIVE"
VEP_HOST="$REFERENCE_DIR/$VEP_RELATIVE"
CACHE_HOST="$VEP_HOST/homo_sapiens/116_GRCh37"
for required in "$FASTA_HOST" "$FASTA_HOST.fai" "$CACHE_HOST/info.txt"; do
  if [ ! -s "$required" ]; then
    echo "ERROR: Required VEP/FASTA file is missing or empty: $required" >&2
    echo "Run the corrected installation command in docs/REFERENCE_DATA.md." >&2
    exit 2
  fi
done
if ! find "$CACHE_HOST" -mindepth 2 -type f -size +0c -print -quit | grep -q .; then
  echo "ERROR: VEP cache has no chromosome payload below: $CACHE_HOST" >&2
  exit 2
fi

mkdir -p "$OUTPUT_DIR" "$OUTPUT_DIR/full-annotation-config"
CONFIG_DIR="$OUTPUT_DIR/full-annotation-config"
CONFIG_PATH="$CONFIG_DIR/reference-config.grch37-vep116.json"
WORKSPACE="$OUTPUT_DIR/NGS_VCF_FULL_RUN"
INPUT_VCF="$OUTPUT_DIR/component-test-data/inputs/test_b37.vcf"

echo "CURE-NGS real VEP/vcf2maf tutorial"
echo "Container engine: $ENGINE"
echo "Image: $IMAGE"
echo "Reference store: $REFERENCE_DIR"
echo "Selected FASTA: $FASTA_RELATIVE"
echo "Output workspace: $WORKSPACE"

if [ "${CURE_NGS_SKIP_PULL:-0}" != "1" ]; then
  "$ENGINE" pull "$IMAGE"
fi

if [ ! -s "$INPUT_VCF" ]; then
  echo "Exporting the public 25-variant GRCh37 input..."
  "$ENGINE" run --rm --network none \
    --user "$(id -u):$(id -g)" \
    --volume "$OUTPUT_DIR:/data/output" \
    "$IMAGE" export-tutorial-data /data/output/component-test-data
fi

echo "Creating a single-reference config for only the installed resources..."
"$ENGINE" run --rm --network none \
  --user "$(id -u):$(id -g)" \
  --volume "$CONFIG_DIR:/config" \
  "$IMAGE" init-reference-config \
  /config/reference-config.grch37-vep116.json \
  --reference-root /references \
  --cache-version 116 \
  --assembly GRCh37 \
  --fasta "$FASTA_RELATIVE" \
  --fasta-label Ensembl_GRCh37_primary \
  --fasta-contig-style numeric \
  --vep-data "$VEP_RELATIVE" \
  --output-contig-style numeric \
  --force

echo "Running the content-aware reference preflight..."
"$ENGINE" run --rm --network none \
  --volume "$REFERENCE_DIR:/references:ro" \
  --volume "$CONFIG_DIR:/config:ro" \
  "$IMAGE" doctor-bundle \
  --reference-config /config/reference-config.grch37-vep116.json \
  --reference-root /references \
  | tee "$OUTPUT_DIR/reference-bundle.preflight.json"

mkdir -p "$WORKSPACE/VCF_ALL"
cp "$INPUT_VCF" "$WORKSPACE/VCF_ALL/test_b37.vcf"

echo "Running normalization plus real VEP 116/vcf2maf annotation..."
"$ENGINE" run --rm --network none --read-only \
  --user "$(id -u):$(id -g)" \
  --tmpfs /tmp:size=2g,mode=1777 \
  --security-opt no-new-privileges:true \
  --volume "$REFERENCE_DIR:/references:ro" \
  --volume "$CONFIG_DIR:/config:ro" \
  --volume "$OUTPUT_DIR:/data/output" \
  "$IMAGE" batch-vcf-to-maf \
  --workspace-root /data/output/NGS_VCF_FULL_RUN \
  --reference-config /config/reference-config.grch37-vep116.json \
  --reference-root /references \
  --source-assembly GRCh37 \
  --target-assembly GRCh37 \
  --jobs 1 --forks 1 --overwrite

MAF_PATH="$WORKSPACE/VCF_ALL_MAF/test_b37.maf"
if [ ! -s "$MAF_PATH" ]; then
  echo "ERROR: Annotated MAF was not created: $MAF_PATH" >&2
  exit 2
fi
INPUT_ROWS="$(awk 'BEGIN {n=0} !/^#/ && NF {n++} END {print n}' "$INPUT_VCF")"
MAF_ROWS="$(awk 'BEGIN {n=-1} !/^#/ && NF {n++} END {print n}' "$MAF_PATH")"
if [ "$INPUT_ROWS" -ne 25 ] || [ "$MAF_ROWS" -ne "$INPUT_ROWS" ]; then
  echo "ERROR: Expected 25 input variants and 25 MAF rows; observed input=$INPUT_ROWS MAF=$MAF_ROWS" >&2
  exit 2
fi

echo
echo "PASS: real VEP/vcf2maf annotation produced $MAF_ROWS MAF rows."
echo "MAF: $MAF_PATH"
echo "Logs: $WORKSPACE/VCF_ALL_LOG"
echo "Temporary files: $WORKSPACE/VCF_ALL_TMP"
echo "Reference preflight: $OUTPUT_DIR/reference-bundle.preflight.json"

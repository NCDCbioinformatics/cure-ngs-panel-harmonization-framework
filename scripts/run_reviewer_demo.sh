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
IMAGE="${CURE_NGS_IMAGE:-cure-ngs-harmonizer:reviewer-core}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
OUTPUT_ROOT="${CURE_NGS_OUTPUT_ROOT:-$ROOT_DIR/reviewer-output}"
OUTPUT_DIR="$OUTPUT_ROOT/$RUN_ID"
COMPLETION_MESSAGE="${CURE_NGS_COMPLETION_MESSAGE:-Reviewer demonstration passed}"

command -v "$ENGINE" >/dev/null 2>&1 || {
  echo "ERROR: container engine not found: $ENGINE" >&2
  exit 2
}

SECURITY_OPT="no-new-privileges:true"
if "$ENGINE" --version 2>/dev/null | grep -qi podman; then
  SECURITY_OPT="no-new-privileges"
fi

mkdir -p "$OUTPUT_DIR"
chmod 0777 "$OUTPUT_DIR"

if [ "${CURE_NGS_SKIP_BUILD:-0}" = "1" ]; then
  echo "[1/10] Using prebuilt core image $IMAGE"
else
  echo "[1/10] Building pinned core image"
  "$ENGINE" build \
    --file "$ROOT_DIR/docker/Dockerfile.core" \
    --tag "$IMAGE" \
    "$ROOT_DIR"
fi

run_cure_ngs() {
  "$ENGINE" run --rm --network none --read-only \
    --tmpfs /tmp:size=256m,mode=1777 \
    --security-opt "$SECURITY_OPT" \
    --mount "type=bind,source=$ROOT_DIR/examples,target=/examples,readonly" \
    --mount "type=bind,source=$OUTPUT_DIR,target=/data/output" \
    "$IMAGE" "$@"
}

verify_sha256() {
  local checksum_file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum --check "$checksum_file"
  elif command -v shasum >/dev/null 2>&1; then
    shasum --algorithm 256 --check "$checksum_file"
  else
    echo "ERROR: sha256sum or shasum is required." >&2
    exit 2
  fi
}

echo "[2/10] Checking pinned executables"
run_cure_ngs versions >"$OUTPUT_DIR/versions.json"
run_cure_ngs doctor --profile core >"$OUTPUT_DIR/doctor.json"
grep -q '"status": "READY"' "$OUTPUT_DIR/doctor.json"

echo "[3/10] Inspecting the public GRCh37 vcf2maf fixture"
(cd "$ROOT_DIR/examples/public/vcf2maf" && verify_sha256 checksums.sha256)
run_cure_ngs inspect-vcf \
  /examples/public/vcf2maf/test_b37.vcf --assembly GRCh37 \
  >"$OUTPUT_DIR/public-vcf-inspection.json"
grep -q '"record_count": 25' "$OUTPUT_DIR/public-vcf-inspection.json"

echo "[4/10] Splitting, left-aligning, and deduplicating a GRCh37 VCF"
run_cure_ngs normalize-vcf \
  /examples/synthetic/normalize.grch37.vcf \
  /data/output/normalized.grch37.vcf \
  --reference-fasta /examples/synthetic/tiny.grch37.fa \
  --assembly GRCh37
test "$(grep -vc '^#' "$OUTPUT_DIR/normalized.grch37.vcf")" -eq 4

echo "[5/10] Replaying HGVS-to-minimal-MAF without network access"
run_cure_ngs hgvs-table-to-minimal-maf \
  /examples/synthetic/hgvs_to_minimal_input.tsv \
  /data/output/from-hgvs.grch37.maf \
  --failed /data/output/from-hgvs.failed.tsv \
  --reference-fasta /examples/synthetic/tiny.grch37.fa \
  --assembly GRCh37 \
  --response-cache /examples/synthetic/rest-cache \
  --offline-replay
grep -q $'GENE\tsynthetic_sample_001\tchr1\t10\t10\tC\tT\tGRCh37' \
  "$OUTPUT_DIR/from-hgvs.grch37.maf"

echo "[6/10] Converting minimal MAF to a reference-valid VCF"
mkdir -p "$OUTPUT_DIR/from-minimal"
chmod 0777 "$OUTPUT_DIR/from-minimal"
run_cure_ngs minimal-maf-to-vcf \
  /examples/synthetic/minimal.grch37.maf \
  /data/output/from-minimal \
  --reference-fasta /examples/synthetic/tiny.grch37.fa \
  --assembly GRCh37
test "$(grep -vc '^#' "$OUTPUT_DIR/from-minimal/synthetic_sample_001.from_minimal_maf.vcf")" -eq 3

echo "[7/10] Testing gene, fusion, and tabular HGVS normalization"
run_cure_ngs normalize-gene P53 \
  --gtf /examples/synthetic/genes.gtf \
  --hgnc /examples/synthetic/hgnc.tsv >"$OUTPUT_DIR/gene.json"
grep -q '"matched_symbol": "TP53"' "$OUTPUT_DIR/gene.json"
run_cure_ngs normalize-fusion EML4-ALK \
  --gtf /examples/synthetic/genes.gtf \
  --hgnc /examples/synthetic/hgnc.tsv >"$OUTPUT_DIR/fusion.json"
grep -q '"normalized": "EML4--ALK"' "$OUTPUT_DIR/fusion.json"
run_cure_ngs normalize-hgvs-table \
  /examples/synthetic/hgvs_input.csv \
  /data/output/hgvs.normalized.csv --delimiter comma
grep -q 'c.818G>A' "$OUTPUT_DIR/hgvs.normalized.csv"

echo "[8/10] Calculating exact cross-route concordance"
mkdir -p "$OUTPUT_DIR/concordance"
chmod 0777 "$OUTPUT_DIR/concordance"
run_cure_ngs compare-maf-routes /data/output/concordance \
  --reference-maf /examples/synthetic/concordance_direct.grch37.maf \
  --query-maf /examples/synthetic/concordance_report.grch37.maf \
  --reference-require-any HGVSc \
  --reference-fasta /examples/synthetic/tiny.grch37.fa
grep -q '"exact_set_agreement_percent": 100.0' \
  "$OUTPUT_DIR/concordance/concordance_summary.json"

echo "[9/10] Exercising restored V1.3.3 batch handling for an empty panel VCF"
mkdir -p "$OUTPUT_DIR/batch"
chmod 0777 "$OUTPUT_DIR/batch"
run_cure_ngs batch-vcf-to-maf \
  /examples/synthetic/batch-input /data/output/batch \
  --reference-config /examples/synthetic/reference-config.reviewer.json \
  --jobs 1
grep -q 'VALID_EMPTY' "$OUTPUT_DIR/batch/vcf2maf_batch_summary.json"
test -s "$OUTPUT_DIR/batch/empty.grch37.maf.manifest.json"

echo "[10/10] $COMPLETION_MESSAGE"
echo "Container /data/output was saved to the local host directory below."
echo "Local results (host): $OUTPUT_DIR"

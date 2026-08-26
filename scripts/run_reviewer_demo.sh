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
  echo "[1/11] Using prebuilt core image $IMAGE"
else
  echo "[1/11] Building pinned core image"
  "$ENGINE" build \
    --file "$ROOT_DIR/docker/Dockerfile.core" \
    --tag "$IMAGE" \
    "$ROOT_DIR"
fi

run_cure_ngs() {
  "$ENGINE" run --rm --network none --read-only \
    --tmpfs /tmp:size=256m,mode=1777 \
    --security-opt "$SECURITY_OPT" \
    --mount "type=bind,source=$OUTPUT_DIR,target=/data/output" \
    "$IMAGE" "$@"
}

echo "[2/11] Checking pinned executables"
run_cure_ngs versions >"$OUTPUT_DIR/versions.json"
run_cure_ngs doctor --profile core >"$OUTPUT_DIR/doctor.json"
grep -q '"status": "READY"' "$OUTPUT_DIR/doctor.json"

echo "[3/11] Exporting and verifying the original six-component test bundle"
run_cure_ngs verify-tutorial-data >"$OUTPUT_DIR/component-test-data.verification.json"
grep -q '"file_count": 11' "$OUTPUT_DIR/component-test-data.verification.json"
run_cure_ngs export-tutorial-data /data/output/component-test-data \
  >"$OUTPUT_DIR/component-test-data.export.json"
run_cure_ngs export-v1.3.3-example /data/output/KOSMOS_VCF \
  >"$OUTPUT_DIR/KOSMOS_VCF.reference-export.json"

echo "[4/11] Inspecting the non-empty public GRCh37 VCF and reference MAF"
run_cure_ngs inspect-vcf \
  /opt/cure-ngs/examples/component-tests/inputs/test_b37.vcf --assembly GRCh37 \
  >"$OUTPUT_DIR/public-vcf-inspection.json"
grep -q '"record_count": 25' "$OUTPUT_DIR/public-vcf-inspection.json"
VCF_RECORDS="$(grep -vc '^#' "$OUTPUT_DIR/component-test-data/inputs/test_b37.vcf")"
MAF_ROWS="$(grep -v '^#' "$OUTPUT_DIR/component-test-data/expected/test_b37.maf" | tail -n +2 | wc -l | tr -d ' ')"
test "$VCF_RECORDS" -eq 25
test "$MAF_ROWS" -eq 25
test "$(grep -vc '^#' "$OUTPUT_DIR/KOSMOS_VCF/VCF_ALL/test_b37.vcf")" -eq 25
test "$(grep -v '^#' "$OUTPUT_DIR/KOSMOS_VCF/VCF_ALL_MAF/test_b37.maf" | tail -n +2 | wc -l | tr -d ' ')" -eq 25
test -s "$OUTPUT_DIR/KOSMOS_VCF/VCF_ALL_LOG/vcf2maf_batch_log.tsv"
test -d "$OUTPUT_DIR/KOSMOS_VCF/VCF_ALL_TMP"

echo "[5/11] Splitting, left-aligning, and deduplicating a GRCh37 VCF"
run_cure_ngs normalize-vcf \
  /opt/cure-ngs/examples/synthetic/normalize.grch37.vcf \
  /data/output/normalized.grch37.vcf \
  --reference-fasta /opt/cure-ngs/examples/synthetic/tiny.grch37.fa \
  --assembly GRCh37
test "$(grep -vc '^#' "$OUTPUT_DIR/normalized.grch37.vcf")" -eq 4

echo "[6/11] Replaying HGVS-to-minimal-MAF without network access"
run_cure_ngs hgvs-table-to-minimal-maf \
  /opt/cure-ngs/examples/synthetic/hgvs_to_minimal_input.tsv \
  /data/output/from-hgvs.grch37.maf \
  --failed /data/output/from-hgvs.failed.tsv \
  --reference-fasta /opt/cure-ngs/examples/synthetic/tiny.grch37.fa \
  --assembly GRCh37 \
  --response-cache /opt/cure-ngs/examples/synthetic/rest-cache \
  --offline-replay
grep -q $'GENE\tsynthetic_sample_001\tchr1\t10\t10\tC\tT\tGRCh37' \
  "$OUTPUT_DIR/from-hgvs.grch37.maf"

echo "[7/11] Converting minimal MAF to a reference-valid VCF"
mkdir -p "$OUTPUT_DIR/from-minimal"
chmod 0777 "$OUTPUT_DIR/from-minimal"
run_cure_ngs minimal-maf-to-vcf \
  /opt/cure-ngs/examples/synthetic/minimal.grch37.maf \
  /data/output/from-minimal \
  --reference-fasta /opt/cure-ngs/examples/synthetic/tiny.grch37.fa \
  --assembly GRCh37
test "$(grep -vc '^#' "$OUTPUT_DIR/from-minimal/synthetic_sample_001.from_minimal_maf.vcf")" -eq 3

echo "[8/11] Running original gene, fusion, and HGVS-table examples"
run_cure_ngs normalize-gene C11ORF30 \
  --gtf /opt/cure-ngs/examples/synthetic/genes.gtf \
  --hgnc /opt/cure-ngs/examples/synthetic/hgnc.tsv >"$OUTPUT_DIR/gene.json"
grep -q '"matched_symbol": "EMSY"' "$OUTPUT_DIR/gene.json"
run_cure_ngs normalize-fusion ALK-EML4 \
  --gtf /opt/cure-ngs/examples/synthetic/genes.gtf \
  --hgnc /opt/cure-ngs/examples/synthetic/hgnc.tsv >"$OUTPUT_DIR/fusion.json"
grep -q '"normalized": "ALK--EML4"' "$OUTPUT_DIR/fusion.json"
run_cure_ngs normalize-hgvs-table \
  /opt/cure-ngs/examples/component-tests/inputs/hgvs_to_minimal_maf_test.xlsx \
  /data/output/hgvs_to_minimal_maf_test.current.normalized.xlsx \
  >"$OUTPUT_DIR/hgvs-original-summary.json"
grep -q '"rows": 2625' "$OUTPUT_DIR/hgvs-original-summary.json"

echo "[9/11] Calculating exact cross-route concordance"
mkdir -p "$OUTPUT_DIR/concordance"
chmod 0777 "$OUTPUT_DIR/concordance"
run_cure_ngs compare-maf-routes /data/output/concordance \
  --reference-maf /opt/cure-ngs/examples/synthetic/concordance_direct.grch37.maf \
  --query-maf /opt/cure-ngs/examples/synthetic/concordance_report.grch37.maf \
  --reference-require-any HGVSc \
  --reference-fasta /opt/cure-ngs/examples/synthetic/tiny.grch37.fa
grep -q '"exact_set_agreement_percent": 100.0' \
  "$OUTPUT_DIR/concordance/concordance_summary.json"

echo "[10/11] Executing the V1.3.3 four-directory workspace contract"
mkdir -p "$OUTPUT_DIR/KOSMOS_VCF_RUNTIME_TEST/VCF_ALL"
cp "$ROOT_DIR/examples/synthetic/batch-input/empty.grch37.vcf" \
  "$OUTPUT_DIR/KOSMOS_VCF_RUNTIME_TEST/VCF_ALL/"
chmod -R 0777 "$OUTPUT_DIR/KOSMOS_VCF_RUNTIME_TEST"
run_cure_ngs batch-vcf-to-maf \
  --workspace-root /data/output/KOSMOS_VCF_RUNTIME_TEST \
  --reference-config /opt/cure-ngs/examples/synthetic/reference-config.reviewer.json \
  --jobs 1
grep -q 'NCDC_batch_vcf2maf_V.1.3.3' \
  "$OUTPUT_DIR/KOSMOS_VCF_RUNTIME_TEST/VCF_ALL_LOG/vcf2maf_batch_summary.json"
grep -q $'status\tmessage\tfinal_vcf' \
  "$OUTPUT_DIR/KOSMOS_VCF_RUNTIME_TEST/VCF_ALL_LOG/vcf2maf_batch_log.tsv"
grep -q $'SUCCESS\tVCF has no variants; created empty MAF header' \
  "$OUTPUT_DIR/KOSMOS_VCF_RUNTIME_TEST/VCF_ALL_LOG/vcf2maf_batch_log.tsv"
test -s "$OUTPUT_DIR/KOSMOS_VCF_RUNTIME_TEST/VCF_ALL_MAF/empty.grch37.maf"
test -s "$OUTPUT_DIR/KOSMOS_VCF_RUNTIME_TEST/VCF_ALL_LOG/manifests/empty.grch37.maf.manifest.json"

printf 'component\toriginal_input_rows\treference_output_rows\tquick_test\n' >"$OUTPUT_DIR/component-test-summary.tsv"
printf 'panel_VCF_vcf2maf_pipeline\t25\t25\tnon-empty VCF inspected; full MAF included\n' >>"$OUTPUT_DIR/component-test-summary.tsv"
printf 'HGVS_to_minimal_MAF_pipeline\t2625\t2113\toffline synthetic HGVS conversion passed\n' >>"$OUTPUT_DIR/component-test-summary.tsv"
printf 'minimal_MAF_to_annotated_MAF_pipeline\t2113\t2054\tminimal-MAF-to-VCF conversion passed\n' >>"$OUTPUT_DIR/component-test-summary.tsv"
printf 'gene_name_harmonization\t324\t324\tC11ORF30 to EMSY passed\n' >>"$OUTPUT_DIR/component-test-summary.tsv"
printf 'gene_fusion_normalizer\t274\tNA\tALK-EML4 to ALK--EML4 passed\n' >>"$OUTPUT_DIR/component-test-summary.tsv"
printf 'hgvs_normerlizer\t2625\t2625\tfull original XLSX normalization passed\n' >>"$OUTPUT_DIR/component-test-summary.tsv"

echo "[11/11] $COMPLETION_MESSAGE"
echo "Container /data/output was saved to the local host directory below."
echo "Local results (host): $OUTPUT_DIR"
echo "Non-empty VCF reference MAF: $OUTPUT_DIR/component-test-data/expected/test_b37.maf"
echo "Paper/V1.3.3 folder example: $OUTPUT_DIR/KOSMOS_VCF"
echo "Executed V1.3.3 runtime tree: $OUTPUT_DIR/KOSMOS_VCF_RUNTIME_TEST"

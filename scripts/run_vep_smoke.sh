#!/usr/bin/env bash
# Real VEP/vcf2maf execution against a synthetic coding transcript.
# This is an option/consequence/MAF regression, NOT human-cache validation.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${CURE_NGS_FULL_IMAGE:-cure-ngs:full-test}"
OUTPUT="${1:-$ROOT_DIR/ci-output/vep-smoke}"
mkdir -p "$OUTPUT"
OUTPUT="$(cd "$OUTPUT" && pwd)"
RUN_OUTPUT="$(mktemp -d "$OUTPUT/run.XXXXXX")"
docker run --rm --network none --read-only --user "$(id -u):$(id -g)" \
  --tmpfs /tmp:size=256m,mode=1777 --security-opt no-new-privileges:true \
  --volume "$ROOT_DIR/tests/fixtures/synthetic:/fixtures:ro" \
  --volume "$RUN_OUTPUT:/work" --entrypoint /bin/bash "$IMAGE" -lc '
    set -euo pipefail
    cp /fixtures/vep-smoke.fa /work/reference.fa
    samtools faidx /work/reference.fa
    bgzip -c /fixtures/vep-smoke.gff > /work/transcripts.gff.gz
    tabix -p gff /work/transcripts.gff.gz
    printf "gff /work/transcripts.gff.gz\ncache 0\n" > /work/vep.ini
    mkdir -p /work/cache/homo_sapiens/116_GRCh37/1 /work/tmp
    # An explicitly synthetic empty cache satisfies offline startup. The
    # consequence is calculated from the tiny GFF, not a human cache.
    printf "species\thomo_sapiens\nassembly\tGRCh37\nsource_sift\tsynthetic-no-predictions\nsource_polyphen\tsynthetic-no-predictions\n" > /work/cache/homo_sapiens/116_GRCh37/info.txt
    python3 -m cure_ngs.cli annotate-vcf /fixtures/vep-smoke.vcf /work/smoke.maf \
      --reference-fasta /work/reference.fa --assembly GRCh37 \
      --vep-path /opt/vep/src/ensembl-vep --vep-data /work/cache \
      --vep-config /work/vep.ini --cache-version 116 --forks 1 \
      --temporary-directory /work/tmp --vcf-tumor-id TUMOR --tumor-id smoke \
      > /work/vcf2maf.stdout.log 2> /work/vcf2maf.stderr.log
    python3 -c "import csv; rows=list(csv.DictReader((l for l in open(\"/work/smoke.maf\") if not l.startswith(\"#\")),delimiter=chr(9))); assert len(rows)==1, rows; assert rows[0][\"Variant_Classification\"]==\"Missense_Mutation\", rows; assert rows[0][\"Tumor_Sample_Barcode\"]==\"smoke\", rows; print(\"PASS: real VEP116/vcf2maf produced one missense MAF row\")"
  '

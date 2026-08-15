# Container image

The primary image is based on the digest-pinned official Ensembl VEP 116.1 image.
It also contains checksum-verified Picard 3.1.1 and vcf2maf revision
`754d68ab4ad3eba29199c5a62e0061745aed7e7e`, plus bcftools 1.13 and samtools
1.13. Reference FASTA files and the VEP cache are mounted read-only.

`docker/Dockerfile.core` is a smaller image for fast preprocessing tests without
VEP, Picard, or vcf2maf.

Build and smoke test with Docker or Podman:

```bash
docker build --build-arg SOURCE_REVISION="$(git rev-parse HEAD)" \
  -f docker/Dockerfile -t cure-ngs-harmonizer:0.1.0 .
docker run --rm cure-ngs-harmonizer:0.1.0 versions
```

`SOURCE_REVISION` is stored in the OCI `org.opencontainers.image.revision`
label. GitHub Actions supplies the triggering commit SHA automatically.

The table normalizers are included in the same non-root image. For example:

```bash
docker run --rm \
  --volume "$PWD/input:/data/input:ro" \
  --volume "$PWD/output:/data/output" \
  cure-ngs-harmonizer:0.1.0 \
  normalize-hgvs-table /data/input/report.csv /data/output/report.normalized.csv \
  --delimiter comma
```

Run normalization with read-only inputs and references:

```bash
docker run --rm \
  --volume "$PWD/input:/data/input:ro" \
  --volume "$PWD/output:/data/output" \
  --volume "$PWD/references:/references:ro" \
  cure-ngs-harmonizer:0.1.0 \
  normalize-vcf /data/input/sample.vcf /data/output/sample.normalized.vcf.gz \
  --reference-fasta /references/hg19.fa --assembly GRCh37
```

For the end-to-end `vcf-to-maf` command, the target assembly defaults to
GRCh37/hg19 to match the current CURE-NGS Korean clinical-panel deployment.
Use `--target-assembly GRCh38` explicitly for a GRCh38-native or migration run.

The image runs as UID/GID 10001. Python table dependencies are exact-version and
wheel-hash pinned in `requirements-runtime.txt`; bioinformatics executable and
resource locks are stored under `resources/`.

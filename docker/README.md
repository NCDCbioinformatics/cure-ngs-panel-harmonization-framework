# Container image

The primary image is based on the digest-pinned official Ensembl VEP 116.1 image.
It also contains checksum-verified Picard 3.1.1 and vcf2maf revision
`754d68ab4ad3eba29199c5a62e0061745aed7e7e`, plus bcftools 1.13 and samtools
1.13. Reference FASTA files and the VEP cache are mounted read-only.

For a clean-host installation, authoritative resource download links, expected
directory layout, index creation, cache compatibility, and `doctor` preflight
commands are documented in [`docs/REFERENCE_DATA.md`](../docs/REFERENCE_DATA.md).
Do not copy paths from an author's workstation into the image.

For the portable successor to `NCDC_batch_vcf2maf_V.1.3.3`, copy
[`references/reference-config.example.json`](../references/reference-config.example.json)
into the mounted reference directory, edit only its relative resource list,
and run `doctor-bundle` before `batch-vcf-to-maf`. The image also includes the
template at `/opt/cure-ngs/reference-config.example.json`.

`docker/Dockerfile.core` is a smaller image for fast preprocessing tests without
VEP, Picard, or vcf2maf.

Pull the public release images without registry login and retain their complete
GHCR names:

```bash
CORE_IMAGE=ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.4-core
FULL_IMAGE=ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.4
docker pull "$CORE_IMAGE"
docker pull "$FULL_IMAGE"
docker run --rm "$CORE_IMAGE" doctor --profile core
docker run --rm "$FULL_IMAGE" versions
```

The same image download includes the original six-component public test
bundle. Export it to a local folder with:

```bash
mkdir -p tutorial-data
docker run --rm --user "$(id -u):$(id -g)" \
  --volume "$PWD/tutorial-data:/data/output" \
  "$CORE_IMAGE" export-tutorial-data /data/output/component-test-data
```

This produces non-empty VCF/MAF examples, the original XLSX/CSV files, and a
SHA-256/source manifest under `tutorial-data/component-test-data/`.

Create the exact manuscript/V1.3.3 four-directory example at the same time:

```bash
docker run --rm --user "$(id -u):$(id -g)" \
  --volume "$PWD/tutorial-data:/data/output" \
  "$CORE_IMAGE" export-v1.3.3-example /data/output/NGS_VCF
```

The exported MAF is explicitly marked as a validated bundled reference output,
not a new VEP run.

The short local name `cure-ngs-harmonizer:0.2.4` is used below only for an
image built from source with that tag. It is not an alias automatically created
by `docker pull ghcr.io/ncdcbioinformatics/...`.

Build and smoke test with Docker or Podman:

```bash
docker build --build-arg SOURCE_REVISION="$(git rev-parse HEAD)" \
  -f docker/Dockerfile -t cure-ngs-harmonizer:0.2.4 .
docker run --rm cure-ngs-harmonizer:0.2.4 versions
docker run --rm cure-ngs-harmonizer:0.2.4 doctor --profile core
```

`SOURCE_REVISION` is stored in the OCI `org.opencontainers.image.revision`
label. GitHub Actions supplies the triggering commit SHA automatically.

The table normalizers are included in the same non-root image. For example:

```bash
docker run --rm \
  --volume "$PWD/input:/data/input:ro" \
  --volume "$PWD/output:/data/output" \
  cure-ngs-harmonizer:0.2.4 \
  normalize-hgvs-table /data/input/report.csv /data/output/report.normalized.csv \
  --delimiter comma
```

Run normalization with read-only inputs and references:

```bash
docker run --rm \
  --volume "$PWD/input:/data/input:ro" \
  --volume "$PWD/output:/data/output" \
  --volume "$PWD/references:/references:ro" \
  cure-ngs-harmonizer:0.2.4 \
  normalize-vcf /data/input/sample.vcf /data/output/sample.normalized.vcf.gz \
  --reference-fasta /references/hg19.fa --assembly GRCh37
```

Run a heterogeneous directory with ordered FASTA and liftover-chain fallback:

```bash
mkdir -p "$PWD/NGS_VCF/VCF_ALL"
# Copy input VCF/gVCF files into NGS_VCF/VCF_ALL.
docker run --rm --read-only --tmpfs /tmp:size=2g,mode=1777 \
  --user "$(id -u):$(id -g)" \
  --volume "$PWD/NGS_VCF:/data/NGS_VCF" \
  --volume "$PWD/references:/references:ro" \
  cure-ngs-harmonizer:0.2.4 batch-vcf-to-maf \
  --workspace-root /data/NGS_VCF \
  --reference-config /references/reference-config.json --jobs 4
```

This automatically creates `VCF_ALL_LOG`, `VCF_ALL_MAF`, and `VCF_ALL_TMP`.
The MAF directory contains only `*.maf`; the exact nine-column compatibility
TSV, structured summary, and manifests are kept under `VCF_ALL_LOG`.

For the end-to-end `vcf-to-maf` command, the target assembly defaults to
GRCh37/hg19 to match the current CURE-NGS Korean clinical-panel deployment.
Use `--target-assembly GRCh38` explicitly for a GRCh38-native or migration run.

The image runs as UID/GID 10001. Python table dependencies are exact-version and
wheel-hash pinned in `requirements-runtime.txt`; bioinformatics executable and
resource locks are stored under `resources/`.

Run the small, network-disabled reviewer walkthrough with:

```bash
bash scripts/run_reviewer_demo.sh
```

# Use CURE-NGS on another computer: Docker-only workflow

> 0.2.6 is an unpublished hotfix candidate. The pull commands below describe
> the intended release interface, not a currently available registry tag.
> Do not use the broken 0.2.5 full image for real annotation.
> [Current verification scope](ANNOTATION_HOTFIX.md).

## What must be installed on the other computer?

Only a working Docker engine is needed to run the image. Git, Python, Perl,
Java, bcftools, SAMtools, Picard, VEP, and vcf2maf do **not** need to be installed
on the host. Git is optional for developers and the repository-based tutorial.
The full image contains the programs and their pinned dependencies.
The smaller `-core` image cannot perform VEP/vcf2maf annotation or Picard liftover.

The tested platform is Ubuntu 22.04.5 x86-64 under an independent WSL2
distribution. Published workflows currently build Linux/amd64 images, not native
ARM64 images. macOS/ARM emulation and Podman have not passed this validation.
Install Docker using its [official Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/)
or [Docker Desktop instructions](https://docs.docker.com/desktop/).
First confirm both commands succeed:

```bash
docker info
docker run --rm hello-world
```

For socket permission or daemon errors, resolve
[the host setup](INSTALLATION.md#clean-ubuntu-2204-or-2404) first.
Do not change the Docker socket to world-writable.

## 1. Download and test the full image, with no repository clone

For a locally supplied candidate image archive instead of a public release,
use `docker load --input cure-ngs-harmonizer-0.2.6-candidate.tar`, then set
`IMAGE=cure-ngs-harmonizer:0.2.6-candidate` and skip `docker pull`.
The same self-test and user-reference commands apply. Record the archive
SHA-256 and candidate source revision. Loading a candidate is not evidence
that the public registry has been updated or human-cache validation completed.

After the verified hotfix has been published, run these commands in Linux/WSL
bash. `OUTPUT` is a host directory; results remain there after container removal.

```bash
IMAGE=ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.6
docker pull "$IMAGE"
docker image inspect --format '{{.RepoDigests}}' "$IMAGE"
OUTPUT="$PWD/cure-ngs-output"
mkdir -p "$OUTPUT"
docker run --rm --network none --read-only \
  --user "$(id -u):$(id -g)" \
  --tmpfs /tmp:size=256m,mode=1777 \
  --security-opt no-new-privileges:true \
  --mount "type=bind,source=$OUTPUT,target=/data/output" \
  "$IMAGE" self-test /data/output/self-test
find "$OUTPUT/self-test" -name self-test-report.json -print
```

Expected: exit code 0 and JSON `"status": "PASS"`. Each run gets a separate
`run-...` directory. It contains actual generated outputs, logs, a report,
the public component data, and a sample VCF in `NGS_VCF/VCF_ALL/`.
The full self-test executes all six capabilities, actual Picard liftover,
and actual VEP/vcf2maf coding-transcript annotation. Parallel jobs use identical
internal filenames and sample prefixes; a changed-allele rerun checks stale output.
Only the output directory is mounted; no host source, Python or reference
installation is used. No network access is required after image download.

**Scope:** the real-tool annotation uses a tiny synthetic transcript/reference,
not the complete human cache. Exported historical expected MAFs are labeled
reference outputs, not newly computed human annotations. A self-test PASS does
not prove that the user's human references or inputs are valid.

## 2. Select your real reference assets

Large biological resources remain outside the image and are mounted read-only.
The program does not search the whole PC or use the authors' paths.

- A GRCh37/hg19 FASTA matching the input assembly and its genuine `.fai` index.
- The species/assembly-matched **VEP release 116** human cache for VEP 116.1.
- For GRCh38-to-GRCh37 liftover only: the chain file, target FASTA and sequence
  dictionary; retain reference naming consistency.
- For real gene/fusion harmonization: user-selected HGNC and matching GTF data.
  HGVS resolution uses its documented REST source or a prepared offline cache.

Download sources, indexing commands, expected layouts, and cache details are
listed in [REFERENCE_DATA.md](REFERENCE_DATA.md). Allow ample storage for the
compressed archive, extracted cache, genomes, image, and working files; the
cache archive alone is about 23 GiB. At least 100 GiB free is a practical
planning starting point, not a guarantee for large batches.
Never relabel an old 102/106 cache as 116.

Example selected host reference layout (paths are illustrative):

```text
/srv/ngs-references/
|-- grch37/hg19.fa
|-- grch37/hg19.fa.fai
`-- vep/homo_sapiens/116_GRCh37/...
```

Set your actual path and create a configuration using the image itself:

```bash
REFERENCE_DIR=/srv/ngs-references
mkdir -p "$OUTPUT/config"
docker run --rm --network none --user "$(id -u):$(id -g)" \
  --mount "type=bind,source=$OUTPUT/config,target=/config" \
  "$IMAGE" init-reference-config /config/reference-config.json \
  --reference-root /references --assembly GRCh37 \
  --fasta grch37/hg19.fa --vep-data vep --cache-version 116
docker run --rm --network none \
  --mount "type=bind,source=$REFERENCE_DIR,target=/references,readonly" \
  --mount "type=bind,source=$OUTPUT/config,target=/config,readonly" \
  "$IMAGE" doctor-bundle \
  --reference-config /config/reference-config.json --reference-root /references
```

Read the selected paths and warnings in the report. Do not start a batch unless
preflight is READY. This checks structure/tools/selected assets; actual batch
processing also checks genomic REF against the FASTA.
The single-reference example does not remove the original multi-reference/
chain fallback: omit `--fasta` when generating the legacy three-FASTA/two-chain
template, then edit its candidates to your own selected assets. See
[reference configuration](REFERENCE_DATA.md).

## 3. Run your own VCFs and keep the original layout

Set `INPUT_DIR` to the actual host folder containing your VCFs.
Input and reference mounts are read-only; only the output mount is writable.
GRCh37 remains the default target. This example explicitly selects GRCh37
inputs; use GRCh38 only for genuinely GRCh38 inputs and configure liftover assets.

```bash
INPUT_DIR=/srv/my-panel-vcfs
mkdir -p "$OUTPUT/NGS_VCF"
docker run --rm --network none --read-only \
  --user "$(id -u):$(id -g)" \
  --tmpfs /tmp:size=256m,mode=1777 \
  --security-opt no-new-privileges:true \
  --mount "type=bind,source=$INPUT_DIR,target=/data/output/NGS_VCF/VCF_ALL,readonly" \
  --mount "type=bind,source=$OUTPUT,target=/data/output" \
  --mount "type=bind,source=$REFERENCE_DIR,target=/references,readonly" \
  "$IMAGE" batch-vcf-to-maf --workspace-root /data/output/NGS_VCF \
  --reference-config /data/output/config/reference-config.json \
  --reference-root /references --source-assembly GRCh37 \
  --target-assembly GRCh37 --jobs 4
```

Your VCFs remain in `INPUT_DIR`. The container sees them under `VCF_ALL`.
Generated files remain under:

```text
cure-ngs-output/NGS_VCF/
|-- VCF_ALL_LOG/   # statuses, logs, manifests and summary
|-- VCF_ALL_MAF/   # per-input MAFs
`-- VCF_ALL_TMP/   # isolated processing/annotation files and excluded records
```

Inspect the summary and per-input statuses, not just the existence of a MAF.
SV-only files intentionally produce `NO_SUPPORTED_SMALL_VARIANTS`, not a
successful small-variant annotation. A true ANNOVAR table is not converted by
pretending it is a VCF. Invalid inputs or incompatible reference assets fail
with diagnostics; the image cannot promise that every malformed file is usable.
Successful sanitation is staged and audited; original inputs are not edited.

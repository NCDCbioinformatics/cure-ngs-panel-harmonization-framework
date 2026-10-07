# CURE-NGS 0.2.6: executable annotation hotfix

This release corrects the real VEP/vcf2maf failures in the 0.2.5 full image.
Do not use the old full image for non-empty annotation input. Historical
release assets and historical reference MAFs remain unchanged for provenance.

## Corrections

- Pin vcf2maf 1.6.22, compatible with VEP 116.1, instead of passing the
  removed `--af_esp` option. New annotations use the upstream `gnomADe_*`
  column names.
- Isolate temporary files by input, fallback attempt, and invocation.
  Parallel samples and changed-input reruns cannot reuse one another's VEP
  files; validate MAFs before publishing them atomically.
- Repair recognized legacy VCF metadata, empty INFO, safely parse literal
  dictionary INFO, and uppercase plain sequence alleles in staged copies.
  Preserve original input bytes and local sanitation audit sidecars.
- Reject actual ANNOVAR tables explicitly rather than guessing VCF columns.
  Preserve symbolic/SV-only records separately and report
  `NO_SUPPORTED_SMALL_VARIANTS`, not successful small-variant annotation.
- Verify cache species, assembly, and VEP major version. Large reference
  genomes, matched VEP caches, and optional liftover chains stay outside the
  image, under a directory explicitly selected by the user.
- Use checksum-pinned official NCBI non-primary contig aliases for VEP
  lookup. Preserve known non-primary variants absent from the selected
  cache in a separate VCF, excluding them from MAF with explicit reason,
  count, and checksum. Require exact eligible-input/MAF row accounting;
  unexpected omissions fail without replacing a previous valid result.
- Preserve the selected cache's existing synonyms when adding official
  aliases. Check mitochondrial sequence identity against NC_012920.1;
  UCSC hg19's older chrM is not interchangeable with Ensembl GRCh37 MT.
  Incompatible mitochondrial variants remain in the excluded VCF with an
  explicit reference-identity reason, without changing coordinates or alleles.
- Add image-contained `self-test`: no repository clone, host Python, or
  human-reference download is required for the software regression checks.

## Verification

On 7 October 2026, the local suite passed 146 tests with 78.44% combined
statement/branch coverage. Latest release locks for all six historical
components were reconfirmed. Latest full/core image-contained self-tests and
six-component beginner tutorials passed in an independent Ubuntu 22.04.5
WSL2 installation, running as host UID/GID 1000 with a read-only image and
container networking disabled.

Beginner Tutorial Section 13 also performed **new, actual** VEP 116/vcf2maf
annotation with the official GRCh37 human cache: 25 public input variants
produced 25 MAF rows on the host output mount. This is distinct from copying
the bundled historical reference MAF. Supplied clinical input files and
their per-variant results are not release assets.

Image publication is gated on executable tests. This release page is
created only after both image variants publish successfully and anonymous
public installation verification passes.

## Install on another computer

Only a working Docker engine is required on the host. The full image includes
Python, Perl, Java, bcftools, SAMtools, Picard, VEP, and vcf2maf. Tested images
target Linux/amd64; the smaller core image does not provide full annotation.

```bash
IMAGE=ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.6
docker pull "$IMAGE"
mkdir -p "$PWD/cure-ngs-output"
docker run --rm --network none --read-only \
  --user "$(id -u):$(id -g)" \
  --tmpfs /tmp:size=256m,mode=1777 \
  --security-opt no-new-privileges:true \
  --volume "$PWD/cure-ngs-output:/data/output" \
  "$IMAGE" self-test /data/output --profile full
```

Core image: `ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.6-core`.

For actual human annotation, install the external matching FASTA/index and
VEP 116 cache, choose their host root explicitly, generate/edit the reference
configuration, and pass `doctor-bundle` before analysis. GRCh37/hg19 remains
the default target. See:

- [Docker-only first use](DOCKER_ONLY_QUICKSTART.md)
- [Reference downloads and installation](REFERENCE_DATA.md)
- [Beginner tutorial and real annotation](BEGINNER_TUTORIAL.md)
- [Batch workflow, fallback references and output layout](V1.3.3_BATCH_WORKFLOW.md)
- [Corrections and verification scope](ANNOTATION_HOTFIX.md)

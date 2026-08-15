# Troubleshooting

Run `cure-ngs doctor` before investigating a long workflow failure. Its JSON
output is suitable for attaching to a GitHub issue together with `cure-ngs
versions` and the input VCF header with sensitive fields removed.

## Permission denied under `/data/output`

The image runs without root privileges. On Linux, make the bind-mounted output
directory writable by UID/GID 10001 or override the Compose UID/GID with the
current host identity. Do not make reference or input mounts writable merely to
work around an output permission error.

## FASTA index is missing

Create `<reference>.fai` with `samtools faidx`. Liftover also requires the
Picard sequence dictionary next to the target FASTA, for example `hg19.dict`.

## REF mismatch during normalization

The declared assembly and coordinate system do not guarantee identical FASTA
content. Confirm the file provenance, chromosome naming, decoy content, and
that the input caller used the same reference. Do not bypass REF validation.

## VEP cache not found or incompatible

VEP 116.1 requires a release-116 cache. The expected directory is
`<vep-data>/homo_sapiens/116_GRCh37` or `116_GRCh38`. Mount the parent directory
as `--vep-data`; do not pass the assembly subdirectory itself.

## Every liftover record was rejected

Check chain direction first. A GRCh38 input targeting GRCh37 requires
`hg38ToHg19`, not `hg19ToHg38`. Also verify that the target FASTA and dictionary
use contigs compatible with the chain.

## Multiple samples in one VCF

Supply `--vcf-tumor-id` and, for matched-normal data, `--vcf-normal-id`.
Output display IDs are independently controlled with `--tumor-id` and
`--normal-id`. The software will not guess tumor/normal roles.

## HGVS online results cannot be reproduced

Keep the complete response-cache directory from the first run and replay with
`--offline-replay`. A missing entry is reported as `REST_CACHE_MISS`; a changed
entry is rejected by its SHA-256 check.

## Empty VCF

An empty but structurally valid VCF can occur after a panel caller finds no
reportable variants or after upstream filtering. CURE-NGS records this as a
valid empty result. A file without a valid VCF header is still rejected.

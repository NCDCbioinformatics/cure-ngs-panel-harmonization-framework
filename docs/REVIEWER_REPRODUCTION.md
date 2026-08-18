# Reviewer reproduction checklist

This checklist separates a fast software-verification run from the optional
large-resource end-to-end annotation run.

Readers using the framework for the first time should begin with the
[six-component beginner tutorial](BEGINNER_TUTORIAL.md), which explains the
same public and synthetic examples command by command.

## A. Deterministic software test

1. Clone the repository and record `git rev-parse HEAD`.
2. Install Docker using the links in `docs/INSTALLATION.md`.
3. Run `bash scripts/run_reviewer_demo.sh` or the PowerShell equivalent.
4. Confirm the final `Reviewer demonstration passed` message.
5. Inspect `reviewer-output/<run-id>/versions.json` and `doctor.json`.
6. Inspect `reviewer-output/<run-id>/batch/vcf2maf_batch_summary.json` and its
   per-file manifest.

This run uses only original synthetic fixtures plus one attributed public
vcf2maf VCF. Container networking is disabled. It tests all six component
function groups without downloading a human genome.

## B. Full VCF-to-MAF annotation test

1. Build `docker/Dockerfile`.
2. Install a GRCh37 FASTA and matching VEP 116 cache by following
   `docs/REFERENCE_DATA.md`.
3. Run `doctor --profile vcf-to-maf`; require `READY`.
4. Run the public `examples/public/vcf2maf/test_b37.vcf` with explicit tumor
   and normal sample IDs.
5. Retain the MAF and generated manifest. Record the resource checksums.

The public VCF contains 25 records and was used in the authors' local testing.
Exact annotation columns can change when annotation databases change; the
container/cache pair and manifest therefore define the reproducible result.

## Expected deterministic assertions

- public GRCh37 VCF: 25 records
- synthetic normalized VCF: 4 unique biallelic records
- offline HGVS route: one cache hit, zero network fetches, one MAF row
- minimal-MAF route: three VCF records
- gene alias `P53`: resolves to `TP53`
- fusion `EML4-ALK`: resolves directionally to `EML4--ALK`
- cross-route synthetic concordance: 100% exact set agreement
- restored V1.3.3 batch route: one empty GRCh37 VCF is reported as
  `VALID_EMPTY`, with a deterministic MAF and provenance manifest

The empty fixture tests batch discovery, assembly handling, sample-tag
derivation, empty-input behavior, reporting, and manifest generation without a
multi-gigabyte reference download. The full heterogeneous batch route and its
external reference-bundle layout are documented in
[`V1.3.3_BATCH_WORKFLOW.md`](V1.3.3_BATCH_WORKFLOW.md).

## Reporting a reproducibility problem

Include:

- repository commit SHA
- container image ID and OCI revision label
- `versions` output
- `doctor` output
- command manifest
- operating system and container-engine version
- a minimized, non-identifying input that reproduces the problem

Do not attach patient VCFs or report screenshots to a public issue.

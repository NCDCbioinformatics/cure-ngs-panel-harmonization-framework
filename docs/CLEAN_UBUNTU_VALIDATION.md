# Clean Ubuntu installation validation

This record documents the current external-user validation of CURE-NGS
`v0.2.3`. The check uses public release artifacts and a fresh GitHub-hosted
Ubuntu runner; it does not rely on an author workstation, a pre-pulled
CURE-NGS image, or GHCR credentials.

## Current validation record

| Property | Value |
| --- | --- |
| Validation date | 2026-08-31 |
| Operating system | GitHub-hosted Ubuntu 22.04 LTS runner |
| Architecture | x86-64 / `linux/amd64` |
| Source | merge commit `7e1cd90eba207de24845486512f09a5d0444ea18` |
| Release | [`v0.2.3`](https://github.com/NCDCbioinformatics/cure-ngs-panel-harmonization-framework/releases/tag/v0.2.3) |
| Public verification | [Public Image Verification run 33350796468](https://github.com/NCDCbioinformatics/cure-ngs-panel-harmonization-framework/actions/runs/33350796468) |
| Verification job | `clean-public-install`, PASS in 44 seconds |
| Complete workflow | PASS in 49 seconds |
| Registry login | None; both pulls were anonymous |

The workflow checked out `main`, ran `scripts/verify_public_install.sh`, and
uploaded the generated `tutorial-output/` directory even when a test failed.
The successful artifact was named `public-image-tutorial-output` with artifact
digest
`sha256:736f6a95d061007fab15fe5f05f469203aeff89180d064e91a3ad90f58d45e08`.

## Public image pull results

Both release tags resolved anonymously from GHCR and were then pulled and run
by Docker:

| Image | Published OCI manifest digest | Result |
| --- | --- | --- |
| `ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.3-core` | `sha256:3d18365aa2d154b4033e936ff5535e7b83cda3595fdc56d2a419939df7512bd4` | PASS |
| `ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.3` | `sha256:a6a92b4f631c3a63bbcd99c67d840d449406f6fa430ae1e809b3b4f106ef0437` | PASS |

The full image reported CURE-NGS 0.2.3, Python 3.10.12, bcftools 1.13,
SAMtools 1.13, Ensembl VEP 116.1, Picard 3.1.1, Java 17, Perl 5.34, and
the pinned vcf2maf revision
`754d68ab4ad3eba29199c5a62e0061745aed7e7e`.

## Functional results

| Check | Result |
| --- | --- |
| Anonymous core image pull | PASS |
| Anonymous full VEP/vcf2maf image pull | PASS |
| Core image `--version` | PASS; reports 0.2.3 |
| Core `doctor --profile core` | PASS |
| Full-image dependency inventory | PASS; all pinned versions matched |
| Six-component beginner tutorial | PASS, all stages |
| Public VCF fixture | PASS; 25 source variants and validated 25-row reference MAF |
| VCF sanitation fixture | PASS; left alignment and multiallelic splitting exercised |
| Structured HGVS to minimal MAF | PASS with frozen offline response cache |
| Minimal MAF to VCF | PASS |
| Gene-symbol normalization | PASS |
| Direction-preserving fusion normalization | PASS |
| HGVS-table separator regression | PASS |
| Cross-route concordance | PASS; explicit quantitative summary generated |
| Empty but valid VCF handling | PASS; auditable `VALID_EMPTY` result |
| V1.3.3 manuscript workspace export | PASS; `VCF_ALL`, `VCF_ALL_LOG`, `VCF_ALL_MAF`, and `VCF_ALL_TMP` created |

The associated `v0.2.3` tag tests and pull-request checks also passed before
the release and container images were published. Component-release locks,
Python 3.10/3.11/3.12 tests, container regression tests, repository-health
checks, and link checks were all included in that release gate.

## Repeat the public-install check

On a clean Ubuntu host, install and start Docker as described in
[Installation and deployment](INSTALLATION.md#clean-ubuntu-2204-or-2404), then
run:

```bash
git clone --branch v0.2.3 --depth 1 \
  https://github.com/NCDCbioinformatics/cure-ngs-panel-harmonization-framework.git
cd cure-ngs-panel-harmonization-framework
bash scripts/verify_public_install.sh
```

This command:

1. verifies that Docker or Podman is running and the current user can access
   its socket;
2. pulls both fully qualified `v0.2.3` GHCR images without logging in;
3. records their immutable repository digests;
4. runs the core preflight checks;
5. validates the pinned full-image tools; and
6. runs the complete six-component beginner tutorial.

Results are written to `tutorial-output/` in the cloned repository.

## Scope of the clean-host check

The repository test data are synthetic or attributed public fixtures and do
not require human genome resources. A true VEP/vcf2maf annotation run also
requires the user's GRCh37 FASTA and indexes, VEP 116 GRCh37 cache, and any
needed liftover chain. These multi-gigabyte resources are intentionally not
embedded in either image. Acquisition, explicit host-path mounting,
configuration, and `doctor-bundle` validation are documented in
[Reference and annotation data](REFERENCE_DATA.md) and the
[V1.3.3 batch workflow guide](V1.3.3_BATCH_WORKFLOW.md).

The earlier from-zero Docker Engine installation audit for `v0.2.1` remains
available in the repository's release history. This page tracks the currently
supported public distribution.

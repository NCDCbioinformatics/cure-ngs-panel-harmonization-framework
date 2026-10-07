# NCDCbioinformatics account version audit

Audit date: 2026-10-07

The unified **v0.2.6** release and both images are public. The corrected
software was tested before publication; the published images were then
downloaded without registry credentials in the independent Ubuntu installation.
See [ANNOTATION_HOTFIX.md](ANNOTATION_HOTFIX.md) for execution scope and
[CLEAN_UBUNTU_VALIDATION.md](CLEAN_UBUNTU_VALIDATION.md) for verification evidence.

This audit checks the publication-facing README surfaces of all 13 repositories owned by
the `NCDCbioinformatics` account. Its purpose is to keep publication-facing
CURE-NGS installation instructions synchronized with the supported unified
distribution.

## Current unified distribution

- Release: [`v0.2.6`](https://github.com/NCDCbioinformatics/cure-ngs-panel-harmonization-framework/releases/tag/v0.2.6)
- Full image: `ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.6`
- Core image: `ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.6-core`
- Public-install evidence: [successful image publication and anonymous-install release gate](https://github.com/NCDCbioinformatics/cure-ngs-panel-harmonization-framework/actions/runs/37556396608)
- Immutable image source: `33dc1e7360cb8a3ebcb972628bac8beed2687148`

The old v0.2.5 image inventory/pull-only evidence did not establish successful
real VEP annotation. Do not use its full image for non-empty annotation input.
The old release remains unchanged for historical provenance.

## Publication-facing repositories synchronized

| Repository | Audited surface |
| --- | --- |
| `cure-ngs-panel-harmonization-framework` | Compose tag, dependency-lock status, current clean-install record |
| `panel_VCF_vcf2maf_pipeline` | Full/core image tags, build tag, reference-bundle commands, V1.3.3 workspace command |
| `HGVS_to_minimal_MAF_pipeline` | Core image pull/build/run commands |
| `minimal_MAF_to_annotated_MAF_pipeline` | Core/full image pull/build/run commands |
| `gene_name_harmonization` | Core image pull/build/run commands |
| `gene_fusion_normalizer` | Core image pull/build/run commands |
| `hgvs_normerlizer` | Core image pull/build/run commands |
| `NCDCbioinformatics` profile | Current release badge, public pulls, tutorial and validation links |

All seven component/profile README updates were published by ordinary
fast-forward pushes, after checking that only README content changed and the
remote default branch had not diverged. The current default-branch commit was
read back after each publication; none still advertises an old unified image.
The HGVS repository's Python 3.10/3.12 regression CI passed before its update.

| Component/profile repository | Verified documentation commit |
| --- | --- |
| `panel_VCF_vcf2maf_pipeline` | `071958de4fda3babf42b4d568ee5b6e1105f3d58` |
| `HGVS_to_minimal_MAF_pipeline` | `fd1aa52ccfd22d3ccaa9c290367521d4b5ea6f5a` |
| `minimal_MAF_to_annotated_MAF_pipeline` | `523c4a3a38f224bf078c492298b81efca2d4fb06` |
| `gene_name_harmonization` | `c401d10bd4b83e2d5b4e8ad83c55b769d3bae62e` |
| `gene_fusion_normalizer` | `5155f4a99fb1b2f2e30784e0233ff662e861e087` |
| `hgvs_normerlizer` | `00a7dc1a5ecfe98b2b632e04d12d9f6319bb68be` |
| `NCDCbioinformatics` profile | `6b8e83f8ccde9de4cfa60bc4e268b7a6fb3448ce` |

## Intentionally unchanged identifiers

Component release names such as `gene_normalizer_human_0.2.1`,
`gene_fusion_normalizer_0.2.1`, and `hgvsnorm-cli-0.2.2.tar` are not stale
CURE-NGS distribution references. They are the latest historical component
releases and remain frozen in `resources/components.lock.json` for provenance.
Reference-resource baseline labels are likewise not Docker release numbers.

The current default-branch READMEs of the five non-CURE repositories
(`EOBC`, `K-CORE-NCDC`, `ncc-backend`, `ncc-frontend`, and
`synthetic-data-set`) were fetched and searched on 7 October, but not rewritten.
They contain no outdated CURE-NGS image installation commands; the K-CORE
overview retains its generic CURE-NGS project description.
Their own project/package version strings are unrelated to the CURE-NGS
Docker distribution.

## Audit rule

Reviewer-facing commands must use the fully qualified GHCR name and an
immutable release tag. A short local image such as
`cure-ngs-harmonizer:0.2.6` is appropriate only immediately after a documented
local build. Public pull/run examples use `ghcr.io/ncdcbioinformatics/...` so
Docker never falls back to an unrelated Docker Hub namespace.

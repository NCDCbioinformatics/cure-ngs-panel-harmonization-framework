# NCDCbioinformatics account version audit

Audit date: 2026-09-04

This audit checks the public default branches of all 13 repositories owned by
the `NCDCbioinformatics` account. Its purpose is to keep publication-facing
CURE-NGS installation instructions synchronized with the supported unified
distribution.

## Current unified distribution

- Release: [`v0.2.5`](https://github.com/NCDCbioinformatics/cure-ngs-panel-harmonization-framework/releases/tag/v0.2.5)
- Full image: `ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.5`
- Core image: `ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.5-core`
- Public-install evidence: [successful v0.2.5 clean Ubuntu workflow](https://github.com/NCDCbioinformatics/cure-ngs-panel-harmonization-framework/actions/runs/33842778908)

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

## Intentionally unchanged identifiers

Component release names such as `gene_normalizer_human_0.2.1`,
`gene_fusion_normalizer_0.2.1`, and `hgvsnorm-cli-0.2.2.tar` are not stale
CURE-NGS distribution references. They are the latest historical component
releases and remain frozen in `resources/components.lock.json` for provenance.
Reference-resource baseline labels are likewise not Docker release numbers.

The five non-CURE repositories (`EOBC`, `K-CORE-NCDC`, `ncc-backend`,
`ncc-frontend`, and `synthetic-data-set`) were searched but not rewritten.
Their own project/package version strings are unrelated to the CURE-NGS
Docker distribution.

## Audit rule

Reviewer-facing commands must use the fully qualified GHCR name and an
immutable release tag. A short local image such as
`cure-ngs-harmonizer:0.2.5` is appropriate only immediately after a documented
local build. Public pull/run examples use `ghcr.io/ncdcbioinformatics/...` so
Docker never falls back to an unrelated Docker Hub namespace.

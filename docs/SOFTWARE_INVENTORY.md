# Software Inventory

## Supported revision release

- Project: CURE-NGS Harmonizer
- Package: `cure-ngs-harmonizer` 0.1.0
- Command: `cure-ngs`
- Maintainer account: `NCDCbioinformatics`
- Primary target: Linux; Windows development is supported for platform-neutral
  commands and WSL/Docker is used for external bioinformatics tools
- License: MIT
- Runtime user: non-root UID/GID 10001
- Clinical status: research harmonization and validation software; not a direct
  clinical diagnostic device
- Default target assembly: GRCh37/hg19 for the current CURE-NGS Korean
  clinical-panel deployment; GRCh38 is an explicit supported alternative

## Exact container baseline

| Component | Pinned version or revision |
| --- | --- |
| Python runtime | 3.10.12 |
| bcftools | 1.13 |
| SAMtools | 1.13 |
| Ensembl VEP | 116.1, digest-pinned base image |
| Picard | 3.1.1, SHA-256 validated JAR |
| vcf2maf | `754d68ab4ad3eba29199c5a62e0061745aed7e7e` |
| openpyxl | 3.1.5, wheel hash pinned |
| et-xmlfile | 2.0.0, wheel hash pinned |

The complete executable and resource locks are in `resources/`, while the exact
image recipes are under `docker/`.

## Verification baseline

- 65 automated tests pass inside the Linux core container.
- Branch-aware coverage is 77.10%; CI enforces at least 70%.
- Synthetic tests include CSV delimiter regression, VCF assembly inference,
  multiallelic splitting, left alignment, REF validation, empty-VCF behavior,
  HGVS/gene/fusion normalization, negative-strand insertion mapping, frozen REST
  replay, manifest hashing, and canonical route concordance.
- Full HGVS conversion was replayed with `--network none`, 2,003 cache hits, and
  zero fetched responses; output hashes matched the host result.

## Historical component repositories

The six repositories linked from the project README preserve development
provenance. The consolidated package in this repository is the supported revision
release and contains tests spanning all component functions.

For journal metadata, use the exact repository URL:
`https://github.com/NCDCbioinformatics/cure-ngs-panel-harmonization-framework`.

# Software Inventory

This document summarizes the software metadata that journal editors commonly request for bioinformatics methods papers.

## Summary

- Project name: CURE-NGS panel harmonization framework
- Maintainer account: `NCDCbioinformatics`
- Primary operating system target: Linux
- Secondary execution path: Windows via WSL
- Primary languages: Bash shell, Python
- Reuse policy: MIT License
- Non-academic restrictions: None

## Component repositories

| Repository | Purpose | Operating system target | Main language(s) | Notes |
| --- | --- | --- | --- | --- |
| `panel_VCF_vcf2maf_pipeline` | Normalize panel VCF inputs and generate MAF outputs | Linux | Bash shell | Depends on bcftools, Picard, VEP, and vcf2maf |
| `HGVS_to_minimal_MAF_pipeline` | Convert HGVS-formatted inputs into minimal MAF | Linux | Bash shell, Python | Uses Ensembl REST resources and Python packages |
| `minimal_MAF_to_annotated_MAF_pipeline` | Convert minimal MAF into annotated MAF | Linux | Bash shell, Python | Depends on vcf2maf and a GRCh37 reference FASTA |
| `gene_name_harmonization` | Harmonize gene symbols across naming variants | Linux or macOS; Windows via Python environment | Python | Utility package for gene nomenclature cleanup |
| `gene_fusion_normalizer` | Normalize and split fusion gene notation | Linux or macOS; Windows via Python environment | Python | Utility package for fusion-gene normalization |
| `hgvs_normerlizer` | Normalize heterogeneous HGVS notation | Linux or macOS; Windows via Python environment | Python | Utility package for HGVS cleanup |

## External requirements

- `bcftools`
- `samtools`
- `Picard`
- `Ensembl VEP`
- `vcf2maf`
- Python 3 with packages required by the individual utilities

## Editorial note

For manuscript metadata, use the exact umbrella repository URL rather than the top-level GitHub account URL.

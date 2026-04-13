# CURE-NGS Panel Harmonization Framework

This repository is a publication-facing umbrella repository for the manuscript "Multi-Institutional Harmonization Framework for Heterogeneous Panel-Based NGS in Precision Oncology."

Its purpose is to provide one stable project home page for manuscript metadata, reproducibility notes, software inventory, and links to the component repositories maintained under the `NCDCbioinformatics` account.

## Scope

The framework harmonizes heterogeneous panel-based NGS inputs into research-ready, provenance-aware outputs centered on Mutation Annotation Format (MAF) generation.

Supported input routes:

- native VCF or gVCF files
- structured HGVS tables
- report-derived variant annotations obtained by manual abstraction or OCR

Major workflow layers:

1. VCF normalization, reference-build handling, and VCF-to-MAF conversion
2. HGVS normalization and HGVS-to-minimal-MAF conversion
3. Minimal-MAF re-annotation and downstream harmonization

## Component repositories

| Repository | Role in the framework | Primary implementation |
| --- | --- | --- |
| [panel_VCF_vcf2maf_pipeline](https://github.com/NCDCbioinformatics/panel_VCF_vcf2maf_pipeline) | VCF preprocessing, build harmonization, and VCF-to-MAF conversion | Bash shell with external bioinformatics tools |
| [HGVS_to_minimal_MAF_pipeline](https://github.com/NCDCbioinformatics/HGVS_to_minimal_MAF_pipeline) | HGVS-driven minimal MAF generation | Bash shell and Python |
| [minimal_MAF_to_annotated_MAF_pipeline](https://github.com/NCDCbioinformatics/minimal_MAF_to_annotated_MAF_pipeline) | Minimal-MAF-to-annotated-MAF conversion | Bash shell and Python |
| [gene_name_harmonization](https://github.com/NCDCbioinformatics/gene_name_harmonization) | Gene symbol normalization utility | Python |
| [gene_fusion_normalizer](https://github.com/NCDCbioinformatics/gene_fusion_normalizer) | Fusion gene name normalization utility | Python |
| [hgvs_normerlizer](https://github.com/NCDCbioinformatics/hgvs_normerlizer) | HGVS nomenclature normalization utility | Python |

## Software environment

- Operating systems: Linux environments are the primary supported target; Windows users can operate through WSL when needed.
- Programming languages: Bash shell and Python.
- External requirements: `bcftools`, `samtools`, `Picard`, `Ensembl VEP`, `vcf2maf`, and standard Python packages used by individual component tools.

## Data and code availability

This manuscript describes a methodological and software framework. No new patient-level CURE-NGS dataset is publicly released through this repository. Patient-level data are not distributed here.

Public code availability is provided through this umbrella repository together with the component repositories listed above. See [docs/MANUSCRIPT_DECLARATIONS.md](docs/MANUSCRIPT_DECLARATIONS.md) for manuscript-ready wording and [docs/SOFTWARE_INVENTORY.md](docs/SOFTWARE_INVENTORY.md) for software metadata.

## License

This umbrella repository is prepared for release under the MIT License. If your institution prefers Apache-2.0 or another license, replace `LICENSE` before public release and align the component repositories to the same policy.

## Citation

See [CITATION.cff](CITATION.cff).

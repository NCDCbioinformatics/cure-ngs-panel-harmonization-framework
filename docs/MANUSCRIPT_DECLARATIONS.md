# Manuscript-Ready Declarations

Update the broken metadata URL so that it points to the exact umbrella repository URL for this manuscript, not only to the account home page.

Recommended project name:

`CURE-NGS panel harmonization framework`

Recommended project home page:

`https://github.com/NCDCbioinformatics/cure-ngs-panel-harmonization-framework`

## Availability of data and materials

Project name: CURE-NGS panel harmonization framework

Project home page: https://github.com/NCDCbioinformatics/cure-ngs-panel-harmonization-framework

Operating system(s): Linux; Windows users can run the workflow through WSL where needed

Programming language: Bash, Python

Other requirements: bcftools, SAMtools, Picard, Ensembl VEP, vcf2maf, and standard Python dependencies used by individual utilities

License: MIT License

Any restrictions to use by non-academics: None

## Data Availability declaration

Data Availability declaration: This manuscript describes a methodological and software framework developed during the pre-accrual phase of CURE-NGS. No new patient-level clinical or genomic dataset is publicly released as part of this study, and no individual-level patient data are deposited in the project repository. Public release of consortium-scale CURE-NGS data was not possible at the time of manuscript preparation. The repository provides public non-clinical software fixtures from all six components, derived non-empty reference outputs, source URLs, checksums, documentation, and reproducibility metadata. These generic test materials are distributed for software verification and are not patient-level source data.

## Code Availability declaration

Code Availability declaration: All code described in this manuscript is publicly available through the umbrella repository at https://github.com/NCDCbioinformatics/cure-ngs-panel-harmonization-framework, which links to the following component repositories:

- https://github.com/NCDCbioinformatics/panel_VCF_vcf2maf_pipeline
- https://github.com/NCDCbioinformatics/HGVS_to_minimal_MAF_pipeline
- https://github.com/NCDCbioinformatics/minimal_MAF_to_annotated_MAF_pipeline
- https://github.com/NCDCbioinformatics/gene_name_harmonization
- https://github.com/NCDCbioinformatics/gene_fusion_normalizer
- https://github.com/NCDCbioinformatics/hgvs_normerlizer

The consolidated release baseline is resolved from the latest published GitHub
Release in each of these six repositories. Release IDs, tags, immutable commit
SHAs, asset sizes, and SHA-256 digests are recorded in
`resources/components.lock.json` and checked against GitHub by CI.

## Author Contribution declaration

Author Contribution declaration: Jaewoo Ahn and Phillip Park contributed to the study concept and design. Jaewoo Ahn, Phillip Park, and Yeonho Choi developed software and prepared visualizations. Jaewoo Ahn, Seonjae Kim, and Na Yeon Oh curated the data and project materials. Jaewoo Ahn and Phillip Park performed platform testing and validation. Jaewoo Ahn and Phillip Park wrote the original draft. Jaewoo Ahn, Phillip Park, Yeonho Choi, Kui Son Choi, Sun-Young Kong, Seog-Yun Park, Hyoeun Shim, Sangmi Lee, Jeonghee Yun, Seonjae Kim, Na Yeon Oh, Jaihong Han, and Keun Seok Lee reviewed and edited the manuscript. Keun Seok Lee acquired funding. Jaihong Han and Keun Seok Lee supervised the study. All authors read and approved the final manuscript.

## Competing Interest declaration

Competing Interest declaration: The authors declare no competing financial or non-financial interests.

## Consent to Publish declaration

Consent to Publish declaration: not applicable.

## Consent to Participate declaration

Consent to Participate declaration: not applicable.

## Ethics declaration

Ethics declaration: not applicable.

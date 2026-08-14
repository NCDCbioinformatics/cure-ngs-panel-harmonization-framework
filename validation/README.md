# Technical validation results

This directory contains aggregate validation results used in the revised
manuscript. The 12 labels are technical caller, file-route, and genome-build
fixtures; they are **not patient samples**. Row-level source variants and local
filesystem paths are intentionally excluded.

The primary comparison is the `hgvs-evaluable-subset`: direct-route variants
with a nonempty `HGVSc`, `HGVSp`, or `HGVSp_Short` field. Variant keys include
the fixture identifier, chromosome, normalized VCF position, REF, and ALT after
multiallelic splitting, reference validation, and `bcftools norm` left
normalization.

## Reported result

| Metric | Value |
| --- | ---: |
| Direct-route evaluable unique variants | 2,149 |
| Report-HGVS unique variants | 2,108 |
| Concordant | 2,095 |
| Direct only | 54 |
| Report only | 13 |
| Sensitivity | 97.49% |
| Positive predictive value | 99.38% |
| Jaccard agreement | 96.90% |
| F1 | 98.43% |

The 54 direct-only variants comprise 40 unresolved HGVS mappings, 13 variants
paired with alternative-locus mappings caused by gene-symbol HGVS expressions
without transcript accession/version identifiers, and the second allele from one
combined multiallelic source row.

`concordance_summary.json` contains aggregate provenance and metric definitions;
`concordance_by_fixture.tsv` contains both the all-input and HGVS-evaluable
analysis sets. `Supplementary_Table_3_Concordance.xlsx` contains the same counts,
formula-driven metrics, definitions, and release metadata in the journal
supplement format. `Figure4_concordance.png` is generated from the TSV by
`scripts/create_concordance_figure.py`.

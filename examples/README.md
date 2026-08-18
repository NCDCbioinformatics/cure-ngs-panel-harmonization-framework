# Reviewer examples

This directory contains two complementary, non-clinical test sets.

1. `synthetic/` is an original, self-contained GRCh37 fixture set. It is tiny
   enough to run in continuous integration and exercises the functions mapped
   from all six historical component repositories. The miniature FASTA is not
   a biological reference and must never be used for research or clinical data.
2. `public/vcf2maf/` contains the public GRCh37 VCF used in the authors' local
   caller-format testing. The local file is byte-identical to the fixture at the
   pinned vcf2maf revision. Its upstream source and Apache-2.0 terms are recorded
   next to the file.

First-time users should start with the fully explained tutorial:

```bash
bash scripts/run_beginner_tutorial.sh
```

See [`docs/BEGINNER_TUTORIAL.md`](../docs/BEGINNER_TUTORIAL.md) for every input,
command, expected result, output file, and the optional full VEP annotation
stage. The shorter reviewer verification entry point is:

```bash
bash scripts/run_reviewer_demo.sh
```

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_reviewer_demo.ps1
```

The beginner launcher pulls the released core image and writes results under
`tutorial-output/`; the reviewer script builds a core image from the checked-out
source and writes under `reviewer-output/`. No external reference download and
no network access inside the example containers are required. Full
VEP/vcf2maf validation is a separate step because the official human FASTA and
VEP cache are several gigabytes; see `docs/REFERENCE_DATA.md`.

## Component coverage

| Historical component | Reviewer example |
| --- | --- |
| `panel_VCF_vcf2maf_pipeline` | GRCh37 VCF inspection/normalization and restored batch empty-VCF handling |
| `HGVS_to_minimal_MAF_pipeline` | frozen synthetic Ensembl REST-cache replay |
| `minimal_MAF_to_annotated_MAF_pipeline` | minimal MAF to per-sample VCF conversion; full annotation is documented separately |
| `gene_name_harmonization` | GTF/HGNC-backed alias normalization |
| `gene_fusion_normalizer` | directional fusion normalization |
| `hgvs_normerlizer` | CSV HGVS normalization regression |

Expected properties are asserted by the scripts rather than by comparing
absolute paths or run manifests, which intentionally vary by host.

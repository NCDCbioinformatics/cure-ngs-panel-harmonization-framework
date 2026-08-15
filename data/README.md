# Data Availability Note

No patient-level clinical or genomic data are distributed in this repository.

This project repository provides:

- synthetic software-test fixtures under `tests/fixtures/synthetic/`
- a self-contained synthetic reviewer walkthrough under `examples/synthetic/`
- one public MSKCC vcf2maf GRCh37 fixture under `examples/public/vcf2maf/`,
  with pinned source, checksum, and Apache-2.0 notice
- aggregate technical-validation results under `validation/`
- workflow, container, and manuscript-facing documentation
- provenance links to the public historical component repositories

The 12 validation labels are technical caller/file-route/genome-build fixtures,
not patients. Row-level controlled benchmark records and local filesystem paths
are not distributed. The manuscript describes a framework-development phase
conducted before consortium-scale CURE-NGS data accrual and public release.

The public vcf2maf fixture is not a CURE-NGS clinical sample. The original
synthetic fixtures use invented identifiers and miniature artificial sequences
that are not valid human reference resources.

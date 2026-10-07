# Official non-primary sequence aliases

These NCBI assembly reports are public reference metadata, not patient data:

- GRCh37.p13 (GCF_000001405.25): https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/000/001/405/GCF_000001405.25_GRCh37.p13/GCF_000001405.25_GRCh37.p13_assembly_report.txt
- GRCh38.p14 (GCF_000001405.40): https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/000/001/405/GCF_000001405.40_GRCh38.p14/GCF_000001405.40_GRCh38.p14_assembly_report.txt

Retrieved 2026-10-07. Line endings are normalized to LF; the LF SHA-256
digests are pinned and checked in `cure_ngs.contig_synonyms.REPORTS`.
Only official aliases are used. GenBank and RefSeq accessions are equated
only where the assembly report marks their sequences as identical (`=`).
The primary chromosomes are left to the selected VEP cache's own synonyms.
This is sequence-name lookup, not liftover or coordinate reconstruction.

When no custom VEP configuration is supplied, known non-primary sequences
absent from the selected cache are preserved verbatim in a separate VCF
and excluded from the annotated MAF. Unknown names and primary chromosomes
are not silently excluded. MAF record accounting must pass before publication.

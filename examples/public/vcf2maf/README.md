# Public vcf2maf fixture

`test_b37.vcf` is the public GRCh37 fixture used in the authors' local
VCF-to-MAF test set. The authors' archived test copy was verified
byte-for-byte against:

`https://github.com/mskcc/vcf2maf/blob/754d68ab4ad3eba29199c5a62e0061745aed7e7e/tests/test_b37.vcf`

Provenance:

- upstream project: MSKCC `vcf2maf`
- pinned revision: `754d68ab4ad3eba29199c5a62e0061745aed7e7e`
- Git blob ID: `7531a738f38e440d0ed9ea75a651b51cd198a939`
- local and repository SHA-256: recorded in `checksums.sha256`
- license: Apache License 2.0; see `LICENSE.Apache-2.0`
- clinical status: public software fixture, not CURE-NGS patient data

The other caller-format files used locally (`test_delly.vcf`,
`test_mutect.vcf`, `test_strelka.vcf`, and others) were also verified as exact
copies of the public files in the same pinned upstream `tests/` directory. They
are linked rather than duplicated here to keep the reviewer download small.

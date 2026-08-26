# License and Redistribution Notice

The `LICENSE` file in this repository applies to original code and original documentation authored for this project.

Additional caution for sample materials:

- Example inputs, benchmark files, spreadsheet templates, or demonstration outputs included in this repository may incorporate formats, records, or derivatives associated with third-party sources.
- Those materials should be reviewed against the original source terms before external redistribution or reuse outside normal research evaluation.
- When in doubt, keep the code under MIT and treat bundled non-code test materials as requiring separate provenance review.

Specific redistributed material:

- `examples/public/vcf2maf/test_b37.vcf` is copied unchanged from the MSKCC
  vcf2maf repository at revision
  `754d68ab4ad3eba29199c5a62e0061745aed7e7e`. It is distributed under the
  Apache License 2.0 reproduced in the same example directory. Its checksum and
  upstream Git blob ID are recorded there.
- `examples/component-tests/` redistributes the authors' public component test
  files and derived reference outputs with generic test identifiers. The
  directory's manifest records each source URL, SHA-256 digest, and row count.
  The vcf2maf fixtures retain their Apache-2.0 attribution in
  `LICENSE.MSKCC-vcf2maf.Apache-2.0`.
- `examples/synthetic/` and `tests/fixtures/synthetic/` are original artificial
  software fixtures. They contain no CURE-NGS patient data and are not human
  reference datasets.

This notice is included to reduce ambiguity for manuscript review and public reuse.

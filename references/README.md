# External references

Large reference and annotation resources are not committed to Git. Place them
under this directory or set `CURE_NGS_REFERENCE_DIR` to an institutional
read-only resource directory. Follow `docs/REFERENCE_DATA.md` for authoritative
download links, layout, indexing, cache compatibility, and preflight checks.

Copy `reference-config.example.json` to `reference-config.json` and keep all
paths relative to the selected reference root. Its ordered candidate lists
reproduce the original NCDC V1.3.3 FASTA and chain fallback without embedding
workstation paths in code. Remove candidates that are not installed, then run:

```bash
cure-ngs doctor-bundle --reference-config /references/reference-config.json
```

The full batch behavior and Docker command are documented in
[`docs/V1.3.3_BATCH_WORKFLOW.md`](../docs/V1.3.3_BATCH_WORKFLOW.md).

Never commit patient data, licensed clinical databases, or local credentials
under this directory.

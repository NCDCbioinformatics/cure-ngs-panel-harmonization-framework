# Annotation and batch-processing hotfix

This 0.2.6 source revision corrects failures reproduced against the 0.2.5
full image. Old release assets remain unchanged for provenance. A source
version, an image build, a synthetic smoke test, and real human-cache
annotation are separate checks; none substitutes for the others.

## Corrected failures

| Failure | Correction and evidence |
| --- | --- |
| `Unexpected extra command-line parameter(s): --af_esp` | Pin upstream vcf2maf 1.6.22 at `f6d0c40cbe4578f4a4abb450b5da33e81900cc00`, with verified archive/script SHA-256. The old image fails the coding-transcript smoke test; the corrected image produces a real missense MAF row. |
| Colliding `reference-1.normalized.vep.vcf` outputs | Every sample, fallback attempt, and annotation invocation gets a unique temporary directory. Root-level logs also include full input stems and job identifiers. A barrier-based parallel regression uses identical internal basenames and identical eight-character sample prefixes to detect contamination. |
| Old VEP outputs reused on rerun | Direct `annotate-vcf` calls also create a fresh invocation directory. MAFs are checked for build, structure, and tumor barcode before atomic publication; invalid partial MAFs cannot replace an existing valid result. |
| Missing `##fileformat` in a genuine legacy VCF | Add the missing declaration only after recognizing fixed VCF columns; preserve original input and write a sanitation JSON audit. |
| Python/JSON dictionary text in INFO | Parse literal dictionaries without code execution, reject duplicate/unsafe keys or nested containers, encode reserved value delimiters, and retain the exact original INFO in a local sidecar. Never use `origAlt` to reconstruct genomic ALT. |
| Empty INFO in the original public GRCh37 fixture | Write `.` in the staged VCF and audit the change. Input bytes remain unchanged. |
| A real ANNOVAR multianno table renamed `.vcf` | Reject explicitly with a schema-specific message. A tabular annotation report is not a VCF; no column/allele guessing is performed. A genuine VCF missing only its metadata declaration is repairable. |
| SV/breakend-only input mistaken for a successful small-variant MAF | Preserve excluded records in a VCF sidecar, emit `NO_SUPPORTED_SMALL_VARIANTS`, and do not run VEP or label the file as successfully annotated. A mixed SV/small-variant input retains supported sequence-resolved records. |
| Windows checkout changes reference offsets/cache hashes | Enforce LF on indexed FASTA and hashed JSON fixtures in Git attributes. Export fixture content without metadata operations that Windows/WSL bind mounts can reject. |
| Older cache paired with VEP 116 | Verify executable/cache major version and cache species/assembly before annotation. Do not rename cache 102/106 to 116. |

Upstream change notes:
https://github.com/mskcc/vcf2maf/releases/tag/v1.6.22

The new MAF schema uses `gnomADe_*` columns. Historical frozen expected MAFs
with `gnomAD_*` columns are retained as historical outputs, not silently
relabeled as newly generated annotations.

## Local verification scope, 2026-10-01

- All six latest component Release locks were checked against GitHub.
- Linux unit/integration suite: 125 passed; branch-aware coverage 76.94%.
- Actual VEP 116/vcf2maf coding-transcript smoke test: PASS, one missense row.
- Six-component offline beginner tutorial: PASS after Windows/WSL fixes.
- Independent official Ubuntu 22.04.5 WSL2 distribution, initially without
  Git/Docker/images: cold full-image build, anonymous hello-world pull, real
  coding-transcript annotation, and six-component tutorial passed. The latter
  two also passed as host UID/GID 1000, with read-only image/network isolation.
  This is an independent clean WSL2 installation, not a standalone Hyper-V VM.
- Supplied VCF preprocessing: 25 inputs, 21 sequence-resolved routes passed;
  four SV-only inputs retained separately. Real bcftools REF validation,
  left alignment, splitting, duplicate removal, and Picard liftover were run.
- Full supplied-data VEP116/GRCh37 annotation: **pending the official human
  cache download and subsequent run**. Preprocessing PASS is not annotation PASS.

Clinical inputs, identifiers, local paths, per-variant results, and private
logs are not published. Aggregate summaries can be reported without the data.

## Reproduce the lightweight real-tool regression

```bash
docker build -f docker/Dockerfile -t cure-ngs:full-test .
CURE_NGS_FULL_IMAGE=cure-ngs:full-test bash scripts/run_vep_smoke.sh
```

Each invocation writes to a fresh `ci-output/vep-smoke/run.*` folder.
The synthetic GFF and explicitly synthetic empty cache exercise actual VEP
and the public CLI; they do not assert a complete human VEP cache or clinical
annotation accuracy. `--inhibit-vep` and precomputed MAF copying are not used.

For real human annotation, acquire the release-matched cache in
[REFERENCE_DATA.md](REFERENCE_DATA.md), run `doctor-bundle`, and then execute
[the full annotation tutorial](BEGINNER_TUTORIAL.md#13-optional-complete-real-vepvcf2maf-annotation).

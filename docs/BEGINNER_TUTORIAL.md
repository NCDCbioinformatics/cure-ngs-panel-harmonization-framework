# Beginner tutorial: run all six CURE-NGS components

This tutorial starts with a new machine and uses the original non-clinical test
files collected from all six component repositories. The files are embedded in
both Docker images and are automatically copied to a normal local output
folder. The deterministic part needs Docker or Podman, Git, and about 2 GB of
free disk space. It does not need Python, a human reference genome, a VEP
cache, patient data, or a GitHub login.

The examples are deliberately tiny. `tiny.grch37.fa` is a software fixture,
not a biological reference, and must never be used for research or clinical
analysis.

## What will be exercised

| Historical component repository | Unified command in this tutorial | Expected result |
| --- | --- | --- |
| `panel_VCF_vcf2maf_pipeline` | `inspect-vcf`, `normalize-vcf`, `batch-vcf-to-maf` | Original 25-record VCF and non-empty 25-row MAF; sanitation smoke test; empty edge case kept separate |
| `HGVS_to_minimal_MAF_pipeline` | `hgvs-table-to-minimal-maf` | Original 2,625-row workbook and 2,113-row reference minimal MAF; one deterministic offline replay |
| `minimal_MAF_to_annotated_MAF_pipeline` | `minimal-maf-to-vcf` | Original 2,113-row minimal MAF and 2,054-row annotated reference MAF; 3-row conversion smoke test |
| `gene_name_harmonization` | `normalize-gene` | Original 324-row CSV is exported; its `C11ORF30` example resolves to `EMSY` |
| `gene_fusion_normalizer` | `normalize-fusion` | Original 274-row CSV is exported; its first `ALK-EML4` example resolves to `ALK--EML4` |
| `hgvs_normerlizer` | `normalize-hgvs-table` | The complete original 2,625-row XLSX is normalized and saved locally |

The final step compares the VCF-derived and report/HGVS-derived routes and
expects 100% exact agreement for the synthetic truth set.

## 1. Install prerequisites

Install Git and start Docker Desktop or Docker Engine. Confirm that the daemon
is reachable:

```bash
git --version
docker info
```

Docker Desktop users must enable WSL integration for their Linux distribution.
See [Installation and deployment](INSTALLATION.md) if `docker info` cannot
reach the server.

## 2. Clone the canonical repository

```bash
git clone https://github.com/NCDCbioinformatics/cure-ngs-panel-harmonization-framework.git
cd cure-ngs-panel-harmonization-framework
git rev-parse HEAD
```

The last command records the exact source revision used for the tutorial.

## 3. Fastest route: one command

Linux, macOS, or WSL:

```bash
bash scripts/run_beginner_tutorial.sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_beginner_tutorial.ps1
```

The launcher downloads the public `0.2.3-core` image, runs all six component
groups without container network access, checks every expected result, and
writes outputs to a new timestamped directory under `tutorial-output/`.
Success ends with:

```text
Beginner six-component tutorial passed
Local results (host): /.../cure-ngs-panel-harmonization-framework/tutorial-output/<run-id>
```

That printed path is an ordinary local folder, not a location trapped inside
Docker. List it from the repository root:

```bash
ls -lah tutorial-output/
```

On WSL, open the same local folder in Windows Explorer with:

```bash
explorer.exe "$(wslpath -w "$PWD/tutorial-output")"
```

The rest of this page expands the same workflow command by command.

## 4. Prepare a reusable container command

The following section uses a Bash shell. Start in the cloned repository:

```bash
IMAGE=ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.3-core
REPO="$PWD"
OUTPUT_DIR="$REPO/tutorial-output/manual"

docker pull "$IMAGE"
mkdir -p "$OUTPUT_DIR"

cure_ngs() {
  docker run --rm --network none --read-only \
    --user "$(id -u):$(id -g)" \
    --tmpfs /tmp:size=256m,mode=1777 \
    --security-opt no-new-privileges:true \
    --mount "type=bind,source=$OUTPUT_DIR,target=/data/output" \
    "$IMAGE" "$@"
}
```

**Nothing has been analyzed yet.** The block only defines a reusable shell
function, similar to a temporary shortcut. Seeing the continuation prompt `>`
while entering the block and then getting the normal `$` prompt after `}` is
expected. Confirm the function and run one real command:

```bash
type cure_ngs
echo "Local output directory: $OUTPUT_DIR"
cure_ngs --version
```

The expected version is `0.2.3`. The bind mount means:

| Docker path | Local host path | Purpose |
| --- | --- | --- |
| `/data/output` | `$OUTPUT_DIR` | persistent results on the user's computer |

The image's immutable test inputs are under
`/opt/cure-ngs/examples/component-tests`. This is intentional: downloading the
image also downloads the test data. The next command exports a verified copy
to the host:

```bash
cure_ngs verify-tutorial-data \
  | tee "$OUTPUT_DIR/component-test-data.verification.json"
cure_ngs export-tutorial-data /data/output/component-test-data \
  | tee "$OUTPUT_DIR/component-test-data.export.json"
cure_ngs export-v1.3.3-example /data/output/NGS_VCF \
  | tee "$OUTPUT_DIR/NGS_VCF.reference-export.json"
```

The local directory `$OUTPUT_DIR/component-test-data/` now contains the five
files linked in the review response, the minimal-MAF fixture for the sixth
component, and three non-empty historical reference outputs. SHA-256 values,
source URLs, row counts, and privacy notes are in its `manifest.json` and
`README.md`.

The second export creates the exact top-level layout shown in the manuscript
and used by `NCDC_batch_vcf2maf_V.1.3.3_github`:

```text
$OUTPUT_DIR/NGS_VCF/
|-- VCF_ALL/
|   `-- test_b37.vcf
|-- VCF_ALL_LOG/
|   |-- vcf2maf_batch_log.tsv
|   `-- reference-output.json
|-- VCF_ALL_MAF/
|   `-- test_b37.maf
`-- VCF_ALL_TMP/
```

`VCF_ALL/test_b37.vcf` is copied automatically and has 25 records;
`VCF_ALL_MAF/test_b37.maf` has 25 data rows. The
`REFERENCE_OUTPUT` status and `reference-output.json` make clear that this MAF
is the validated bundled historical result; the export command does not claim
to have rerun VEP. Section 13 shows the real annotation command.

Therefore, when a command writes `/data/output/result.maf` inside the
container, the user receives `$OUTPUT_DIR/result.maf` locally. The container is
removed after each command, but files in the bind-mounted output directory
remain. `--network none` proves that the deterministic tutorial does not
silently call an external service.

Check the pinned programs:

```bash
cure_ngs versions | tee "$OUTPUT_DIR/versions.json"
cure_ngs doctor --profile core | tee "$OUTPUT_DIR/doctor.json"
grep '"status": "READY"' "$OUTPUT_DIR/doctor.json"
```

Do not continue if the core doctor does not report `READY`.

## 5. Component 1: panel VCF preprocessing

First inspect the attributed public GRCh37 VCF. Its `TUMOR` and `NORMAL`
columns and all 25 records are already in the repository:

```bash
cure_ngs inspect-vcf \
  /opt/cure-ngs/examples/component-tests/inputs/test_b37.vcf \
  --assembly GRCh37 \
  | tee "$OUTPUT_DIR/public-vcf-inspection.json"

grep '"record_count": 25' "$OUTPUT_DIR/public-vcf-inspection.json"

grep -vc '^#' "$OUTPUT_DIR/component-test-data/inputs/test_b37.vcf"
grep -v '^#' "$OUTPUT_DIR/component-test-data/expected/test_b37.maf" \
  | tail -n +2 | wc -l
```

Both final commands must print `25`. Therefore the primary VCF example is no
longer an empty VCF. The corresponding non-empty annotated MAF is immediately
visible at `component-test-data/expected/test_b37.maf`. It is labelled as a
historical reference output because regenerating VEP annotations requires the
external data described in Section 13.

Now split multiallelic records, left-align indels, validate REF alleles, and
remove exact duplicates from a synthetic VCF:

```bash
cure_ngs normalize-vcf \
  /opt/cure-ngs/examples/synthetic/normalize.grch37.vcf \
  /data/output/normalized.grch37.vcf \
  --reference-fasta /opt/cure-ngs/examples/synthetic/tiny.grch37.fa \
  --assembly GRCh37

grep -vc '^#' "$OUTPUT_DIR/normalized.grch37.vcf"
```

The last command must print `4`. The adjacent
`normalized.grch37.vcf.manifest.json` records inputs, hashes, parameters, tool
versions, and the exact output.

The restored V1.3.3 batch entry point also treats a valid empty panel VCF as an
auditable negative result. This separate runtime test proves that Docker itself
creates the four directories, places the MAF only in `VCF_ALL_MAF`, writes the
nine-column legacy-compatible log to `VCF_ALL_LOG`, keeps manifests under the
log directory, and reserves `VCF_ALL_TMP` for processed/temporary files:

```bash
mkdir -p "$OUTPUT_DIR/NGS_VCF_RUNTIME_TEST/VCF_ALL"
cp examples/synthetic/batch-input/empty.grch37.vcf \
  "$OUTPUT_DIR/NGS_VCF_RUNTIME_TEST/VCF_ALL/"
cure_ngs batch-vcf-to-maf \
  --workspace-root /data/output/NGS_VCF_RUNTIME_TEST \
  --reference-config /opt/cure-ngs/examples/synthetic/reference-config.reviewer.json \
  --jobs 1

find "$OUTPUT_DIR/NGS_VCF_RUNTIME_TEST" -maxdepth 3 -type f -print
grep $'SUCCESS\tVCF has no variants; created empty MAF header' \
  "$OUTPUT_DIR/NGS_VCF_RUNTIME_TEST/VCF_ALL_LOG/vcf2maf_batch_log.tsv"
```

## 6. Component 2: HGVS table to minimal MAF

The example includes a frozen, hashed Ensembl REST response. Offline replay
makes the result deterministic and sends no patient or variant data over the
network:

```bash
cure_ngs hgvs-table-to-minimal-maf \
  /opt/cure-ngs/examples/synthetic/hgvs_to_minimal_input.tsv \
  /data/output/from-hgvs.grch37.maf \
  --failed /data/output/from-hgvs.failed.tsv \
  --reference-fasta /opt/cure-ngs/examples/synthetic/tiny.grch37.fa \
  --assembly GRCh37 \
  --response-cache /opt/cure-ngs/examples/synthetic/rest-cache \
  --offline-replay

grep 'synthetic_sample_001' "$OUTPUT_DIR/from-hgvs.grch37.maf"
```

Expected summary fields include one cache hit, zero fetched responses, one
output row, and zero failed rows.

## 7. Component 3: minimal MAF toward annotated MAF

Convert SNV, insertion, and deletion rows into a reference-valid per-sample
VCF. This is the deterministic first half of the re-annotation component:

```bash
mkdir -p "$OUTPUT_DIR/from-minimal"
cure_ngs minimal-maf-to-vcf \
  /opt/cure-ngs/examples/synthetic/minimal.grch37.maf \
  /data/output/from-minimal \
  --reference-fasta /opt/cure-ngs/examples/synthetic/tiny.grch37.fa \
  --assembly GRCh37

grep -vc '^#' \
  "$OUTPUT_DIR/from-minimal/synthetic_sample_001.from_minimal_maf.vcf"
```

The expected count is `3`. The final VEP/vcf2maf annotation half needs the
official multi-gigabyte FASTA and VEP cache, so it is completed in the optional
full-data section below rather than pretending that the tiny fixture is a real
human genome.

## 8. Component 4: gene-name harmonization

```bash
cure_ngs normalize-gene C11ORF30 \
  --gtf /opt/cure-ngs/examples/synthetic/genes.gtf \
  --hgnc /opt/cure-ngs/examples/synthetic/hgnc.tsv \
  | tee "$OUTPUT_DIR/gene.json"

grep '"matched_symbol": "EMSY"' "$OUTPUT_DIR/gene.json"
```

The original token is retained in the JSON while the approved HGNC symbol is
reported separately.

## 9. Component 5: gene-fusion normalization

```bash
cure_ngs normalize-fusion ALK-EML4 \
  --gtf /opt/cure-ngs/examples/synthetic/genes.gtf \
  --hgnc /opt/cure-ngs/examples/synthetic/hgnc.tsv \
  | tee "$OUTPUT_DIR/fusion.json"

grep '"normalized": "ALK--EML4"' "$OUTPUT_DIR/fusion.json"
```

The double hyphen is the canonical directional fusion separator; gene order is
not silently reversed.

## 10. Component 6: tabular HGVS normalization

```bash
cure_ngs normalize-hgvs-table \
  /opt/cure-ngs/examples/component-tests/inputs/hgvs_to_minimal_maf_test.xlsx \
  /data/output/hgvs_to_minimal_maf_test.current.normalized.xlsx \
  | tee "$OUTPUT_DIR/hgvs-original-summary.json"

grep '"rows": 2625' "$OUTPUT_DIR/hgvs-original-summary.json"
```

Inspect both `hgvs_to_minimal_maf_test.current.normalized.xlsx` and its
manifest. This is an actual result produced from the full original 2,625-row
test workbook, not a one-row substitute. The original sample ID is preserved;
only the selected HGVS columns are normalized.

## 11. Compare the two input routes

```bash
mkdir -p "$OUTPUT_DIR/concordance"
cure_ngs compare-maf-routes /data/output/concordance \
  --reference-maf /opt/cure-ngs/examples/synthetic/concordance_direct.grch37.maf \
  --query-maf /opt/cure-ngs/examples/synthetic/concordance_report.grch37.maf \
  --reference-require-any HGVSc \
  --reference-fasta /opt/cure-ngs/examples/synthetic/tiny.grch37.fa

grep '"exact_set_agreement_percent": 100.0' \
  "$OUTPUT_DIR/concordance/concordance_summary.json"
```

The output directory contains aggregate JSON, per-sample metrics, discordant
variants, canonical VCFs, and a provenance manifest. The synthetic example has
three concordant variants and no discordant variants.

## 12. Output checklist

At minimum, the manual run should contain:

```text
tutorial-output/manual/
|-- versions.json
|-- doctor.json
|-- component-test-data/
|   |-- manifest.json
|   |-- inputs/
|   |   |-- MSKCC_VCCF_test.zip
|   |   |-- gene_name_test.csv
|   |   |-- gene_split_test.csv
|   |   |-- hgvs_to_minimal_maf_test.xlsx
|   |   |-- minimal_maf_test_normalized.xlsx
|   |   `-- minimal_maf_from_hgvs_vep_V2.maf
|   `-- expected/
|       |-- test_b37.maf
|       |-- minimal_maf_test_normalized.xlsx
|       `-- minimal_maf_from_hgvs_vep_V2.vcf2maf.maf
|-- component-test-summary.tsv
|-- NGS_VCF/
|   |-- VCF_ALL/test_b37.vcf
|   |-- VCF_ALL_LOG/vcf2maf_batch_log.tsv
|   |-- VCF_ALL_MAF/test_b37.maf
|   `-- VCF_ALL_TMP/
|-- NGS_VCF_RUNTIME_TEST/
|   |-- VCF_ALL/empty.grch37.vcf
|   |-- VCF_ALL_LOG/
|   |   |-- vcf2maf_batch_log.tsv
|   |   |-- vcf2maf_batch_summary.json
|   |   `-- manifests/empty.grch37.maf.manifest.json
|   |-- VCF_ALL_MAF/empty.grch37.maf
|   `-- VCF_ALL_TMP/.cure-ngs-work/
|-- public-vcf-inspection.json
|-- normalized.grch37.vcf
|-- normalized.grch37.vcf.manifest.json
|-- from-hgvs.grch37.maf
|-- from-hgvs.grch37.maf.manifest.json
|-- from-minimal/
|   `-- synthetic_sample_001.from_minimal_maf.vcf
|-- gene.json
|-- fusion.json
|-- hgvs_to_minimal_maf_test.current.normalized.xlsx
|-- hgvs_to_minimal_maf_test.current.normalized.xlsx.manifest.json
`-- concordance/
    |-- concordance_summary.json
    |-- concordance_by_sample.tsv
    |-- concordance_discordant.tsv
    `-- concordance.manifest.json
```

## 13. Optional: complete real VEP/vcf2maf annotation

This step is not self-contained because the official human FASTA and VEP cache
are too large and licensing/version requirements make them inappropriate for a
small Git repository. Follow [Reference and annotation data](REFERENCE_DATA.md)
to prepare a GRCh37 FASTA, `.fai`, Picard `.dict`, VEP 116 GRCh37 cache, and
the optional GRCh38-to-GRCh37 chains.

Select the external directory and require a successful content-aware preflight:

```bash
FULL_IMAGE=ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.3
REFERENCE_DIR=/path/to/your/reference-store
CONFIG_DIR="$REPO/config"

docker pull "$FULL_IMAGE"
docker run --rm \
  --volume "$REFERENCE_DIR:/references:ro" \
  --volume "$CONFIG_DIR:/config:ro" \
  "$FULL_IMAGE" doctor-bundle \
  --reference-config /config/reference-config.json \
  --reference-root /references \
  | tee "$OUTPUT_DIR/reference-bundle.preflight.json"
```

Continue only if the report says `READY`. Replace the example FASTA path below
with the matching path from the verified config, then finish annotation of the
minimal-MAF-derived VCF:

```bash
docker run --rm --read-only --tmpfs /tmp:size=2g,mode=1777 \
  --user "$(id -u):$(id -g)" \
  --volume "$REFERENCE_DIR:/references:ro" \
  --volume "$OUTPUT_DIR:/data/output" \
  "$FULL_IMAGE" annotate-vcf \
  /data/output/from-minimal/synthetic_sample_001.from_minimal_maf.vcf \
  /data/output/from-minimal.annotated.maf \
  --reference-fasta /references/grch37/hg19.fa \
  --assembly GRCh37 \
  --cache-version 116 \
  --vep-data /references/vep \
  --vcf-tumor-id synthetic_sample_001 \
  --tumor-id synthetic_sample_001
```

The same verified resources can annotate the 25-record public VCF end to end
while producing the exact manuscript/V1.3.3 directory structure:

```bash
mkdir -p "$OUTPUT_DIR/NGS_VCF_FULL_RUN/VCF_ALL"
cp "$OUTPUT_DIR/component-test-data/inputs/test_b37.vcf" \
  "$OUTPUT_DIR/NGS_VCF_FULL_RUN/VCF_ALL/"

docker run --rm --read-only --tmpfs /tmp:size=2g,mode=1777 \
  --user "$(id -u):$(id -g)" \
  --volume "$REFERENCE_DIR:/references:ro" \
  --volume "$CONFIG_DIR:/config:ro" \
  --volume "$OUTPUT_DIR:/data/output" \
  "$FULL_IMAGE" batch-vcf-to-maf \
  --workspace-root /data/output/NGS_VCF_FULL_RUN \
  --reference-config /config/reference-config.json \
  --reference-root /references --jobs 1

find "$OUTPUT_DIR/NGS_VCF_FULL_RUN" -maxdepth 3 -type f -print
```

The MAF is written to `VCF_ALL_MAF/test_b37.maf`; the legacy-compatible TSV and
JSON summary are written to `VCF_ALL_LOG`; vcf2maf/VEP temporary VCF and
stdout/stderr files are written to `VCF_ALL_TMP`. Retain the MAF, manifests,
preflight JSON, and logs together. If VEP 116 is
paired with a VEP 102 cache, `doctor-bundle` intentionally reports
`NOT_READY`; do not bypass that compatibility failure.

## Common first-run problems

- `failed to connect to the docker API`: start Docker Desktop/Engine and rerun
  `docker info`.
- `denied` while pulling GHCR: confirm the repository spelling and use the
  lowercase public image path shown above; no login is required.
- output permission error: use the supplied launcher, or retain the
  `--user "$(id -u):$(id -g)"` option in the manual Bash command.
- `NOT_READY` from `doctor-bundle`: read the named failed check. Do not proceed
  until the FASTA build, contig style, chain direction, and VEP/cache release
  all match.
- patient data: never add it under `examples/`, commit it, or attach it to a
  public GitHub issue.

For a reproducibility report, include the commit SHA, image tag/digest,
`versions.json`, `doctor.json`, relevant manifest, and a minimized
non-identifying input.

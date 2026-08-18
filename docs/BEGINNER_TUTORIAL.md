# Beginner tutorial: run all six CURE-NGS components

This tutorial starts with a new machine and uses only the non-clinical example
data committed to this repository. The deterministic part needs Docker or
Podman, Git, and about 2 GB of free disk space. It does not need Python, a human
reference genome, a VEP cache, patient data, or a GitHub login.

The examples are deliberately tiny. `tiny.grch37.fa` is a software fixture,
not a biological reference, and must never be used for research or clinical
analysis.

## What will be exercised

| Historical component repository | Unified command in this tutorial | Expected result |
| --- | --- | --- |
| `panel_VCF_vcf2maf_pipeline` | `inspect-vcf`, `normalize-vcf`, `batch-vcf-to-maf` | 25 public input records; 4 normalized synthetic records; auditable empty-VCF result |
| `HGVS_to_minimal_MAF_pipeline` | `hgvs-table-to-minimal-maf` | 1 minimal-MAF row replayed from the frozen REST response |
| `minimal_MAF_to_annotated_MAF_pipeline` | `minimal-maf-to-vcf` | 3 reference-valid variants for one sample |
| `gene_name_harmonization` | `normalize-gene` | `P53` resolves to `TP53` |
| `gene_fusion_normalizer` | `normalize-fusion` | `EML4-ALK` resolves to directional `EML4--ALK` |
| `hgvs_normerlizer` | `normalize-hgvs-table` | malformed case/parentheses are normalized with an audit manifest |

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

The launcher downloads the public `0.2.1-core` image, runs all six component
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
IMAGE=ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.1-core
REPO="$PWD"
OUTPUT_DIR="$REPO/tutorial-output/manual"

docker pull "$IMAGE"
mkdir -p "$OUTPUT_DIR"

cure_ngs() {
  docker run --rm --network none --read-only \
    --user "$(id -u):$(id -g)" \
    --tmpfs /tmp:size=256m,mode=1777 \
    --security-opt no-new-privileges:true \
    --mount "type=bind,source=$REPO/examples,target=/examples,readonly" \
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

The expected version is `0.2.1`. The bind mounts mean:

| Docker path | Local host path | Purpose |
| --- | --- | --- |
| `/examples` | `$REPO/examples` | read-only inputs committed to GitHub |
| `/data/output` | `$OUTPUT_DIR` | persistent results on the user's computer |

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
  /examples/public/vcf2maf/test_b37.vcf \
  --assembly GRCh37 \
  | tee "$OUTPUT_DIR/public-vcf-inspection.json"

grep '"record_count": 25' "$OUTPUT_DIR/public-vcf-inspection.json"
```

Now split multiallelic records, left-align indels, validate REF alleles, and
remove exact duplicates from a synthetic VCF:

```bash
cure_ngs normalize-vcf \
  /examples/synthetic/normalize.grch37.vcf \
  /data/output/normalized.grch37.vcf \
  --reference-fasta /examples/synthetic/tiny.grch37.fa \
  --assembly GRCh37

grep -vc '^#' "$OUTPUT_DIR/normalized.grch37.vcf"
```

The last command must print `4`. The adjacent
`normalized.grch37.vcf.manifest.json` records inputs, hashes, parameters, tool
versions, and the exact output.

The restored V1.3.3 batch entry point also treats a valid empty panel VCF as an
auditable negative result:

```bash
mkdir -p "$OUTPUT_DIR/batch"
cure_ngs batch-vcf-to-maf \
  /examples/synthetic/batch-input /data/output/batch \
  --reference-config /examples/synthetic/reference-config.reviewer.json \
  --jobs 1

grep 'VALID_EMPTY' "$OUTPUT_DIR/batch/vcf2maf_batch_summary.json"
```

## 6. Component 2: HGVS table to minimal MAF

The example includes a frozen, hashed Ensembl REST response. Offline replay
makes the result deterministic and sends no patient or variant data over the
network:

```bash
cure_ngs hgvs-table-to-minimal-maf \
  /examples/synthetic/hgvs_to_minimal_input.tsv \
  /data/output/from-hgvs.grch37.maf \
  --failed /data/output/from-hgvs.failed.tsv \
  --reference-fasta /examples/synthetic/tiny.grch37.fa \
  --assembly GRCh37 \
  --response-cache /examples/synthetic/rest-cache \
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
  /examples/synthetic/minimal.grch37.maf \
  /data/output/from-minimal \
  --reference-fasta /examples/synthetic/tiny.grch37.fa \
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
cure_ngs normalize-gene P53 \
  --gtf /examples/synthetic/genes.gtf \
  --hgnc /examples/synthetic/hgnc.tsv \
  | tee "$OUTPUT_DIR/gene.json"

grep '"matched_symbol": "TP53"' "$OUTPUT_DIR/gene.json"
```

The original token is retained in the JSON while the approved HGNC symbol is
reported separately.

## 9. Component 5: gene-fusion normalization

```bash
cure_ngs normalize-fusion EML4-ALK \
  --gtf /examples/synthetic/genes.gtf \
  --hgnc /examples/synthetic/hgnc.tsv \
  | tee "$OUTPUT_DIR/fusion.json"

grep '"normalized": "EML4--ALK"' "$OUTPUT_DIR/fusion.json"
```

The double hyphen is the canonical directional fusion separator; gene order is
not silently reversed.

## 10. Component 6: tabular HGVS normalization

```bash
cure_ngs normalize-hgvs-table \
  /examples/synthetic/hgvs_input.csv \
  /data/output/hgvs.normalized.csv \
  --delimiter comma

grep 'c.818G>A' "$OUTPUT_DIR/hgvs.normalized.csv"
```

Inspect both `hgvs.normalized.csv` and its manifest. The original sample ID is
preserved; only the selected HGVS columns are normalized.

## 11. Compare the two input routes

```bash
mkdir -p "$OUTPUT_DIR/concordance"
cure_ngs compare-maf-routes /data/output/concordance \
  --reference-maf /examples/synthetic/concordance_direct.grch37.maf \
  --query-maf /examples/synthetic/concordance_report.grch37.maf \
  --reference-require-any HGVSc \
  --reference-fasta /examples/synthetic/tiny.grch37.fa

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
|-- public-vcf-inspection.json
|-- normalized.grch37.vcf
|-- normalized.grch37.vcf.manifest.json
|-- from-hgvs.grch37.maf
|-- from-hgvs.grch37.maf.manifest.json
|-- from-minimal/
|   `-- synthetic_sample_001.from_minimal_maf.vcf
|-- gene.json
|-- fusion.json
|-- hgvs.normalized.csv
|-- hgvs.normalized.csv.manifest.json
|-- batch/
|   |-- vcf2maf_batch_summary.json
|   `-- empty.grch37.maf.manifest.json
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
FULL_IMAGE=ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.1
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

The same verified resources can annotate the 25-record public VCF end to end:

```bash
docker run --rm --read-only --tmpfs /tmp:size=2g,mode=1777 \
  --user "$(id -u):$(id -g)" \
  --volume "$REPO/examples:/examples:ro" \
  --volume "$REFERENCE_DIR:/references:ro" \
  --volume "$OUTPUT_DIR:/data/output" \
  "$FULL_IMAGE" vcf-to-maf \
  /examples/public/vcf2maf/test_b37.vcf \
  /data/output/public-test-b37.maf \
  --source-assembly GRCh37 \
  --source-reference /references/grch37/hg19.fa \
  --target-assembly GRCh37 \
  --cache-version 116 \
  --vep-data /references/vep \
  --vcf-tumor-id TUMOR --tumor-id tutorial-tumor \
  --vcf-normal-id NORMAL --normal-id tutorial-normal
```

Retain the resulting MAF, manifest, and preflight JSON together. If VEP 116 is
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

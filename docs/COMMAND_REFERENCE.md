# Command reference and workflows

The supported interface is the unified `cure-ngs` command. The six historical
repositories are provenance baselines; reviewers do not need to install six
independent Python or shell environments.

## Container invocation pattern

```bash
docker run --rm --read-only --tmpfs /tmp:size=2g,mode=1777 \
  --security-opt no-new-privileges:true \
  --volume "$PWD/input:/data/input:ro" \
  --volume "$PWD/output:/data/output" \
  --volume "$PWD/references:/references:ro" \
  ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.4 COMMAND OPTIONS
```

All paths passed to `COMMAND` are container paths, not host paths. Replace the
three host directories without editing source code.

## Export the six-component test data

Both image variants contain the original public inputs and non-empty reference
outputs used by the component repositories. Copy them to the host and verify
their SHA-256 manifest:

```bash
mkdir -p output
docker run --rm --user "$(id -u):$(id -g)" \
  --volume "$PWD/output:/data/output" \
  ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.4-core \
  verify-tutorial-data

docker run --rm --user "$(id -u):$(id -g)" \
  --volume "$PWD/output:/data/output" \
  ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.4-core \
  export-tutorial-data /data/output/component-test-data
```

The exported `manifest.json` maps each file to its source component and records
row counts. `expected/test_b37.maf` contains 25 annotated rows; the valid-empty
VCF test is stored and reported separately.

## VCF or gVCF route

For a directory of heterogeneous institutional VCF/gVCF files, use the restored
V1.3.3 batch entry point. The reference config controls ordered FASTA and chain
fallbacks while GRCh37 remains the default target:

```bash
cure-ngs init-reference-config reference-config.json \
  --reference-root /references --cache-version 116 \
  --fasta vep/homo_sapiens/116_GRCh37/Homo_sapiens.GRCh37.75.dna.primary_assembly.fa.gz \
  --fasta-label Ensembl_GRCh37_primary \
  --fasta-contig-style numeric --vep-data vep

cure-ngs doctor-bundle \
  --reference-config reference-config.json \
  --reference-root /references

cure-ngs batch-vcf-to-maf --workspace-root /data/NGS_VCF \
  --reference-config reference-config.json \
  --reference-root /references \
  --jobs 4 --sample-tag-length 8
```

With `--fasta`, `init-reference-config` creates a minimal config containing only
that explicit FASTA and no liftover profile. This is the recommended first-run
mode. Omit `--fasta` to create the original three-FASTA/two-chain GRCh37
fallback layout. The command never overwrites an existing config unless
`--force` is given. In Docker, select the host directory with the left side of
`--volume HOST_DIRECTORY:/references:ro`; `/references` is the corresponding
in-container root.

`--workspace-root` creates/uses `VCF_ALL`, `VCF_ALL_LOG`, `VCF_ALL_MAF`, and
`VCF_ALL_TMP`. It writes MAFs only to `VCF_ALL_MAF`, the exact nine-column
V1.3.3/manuscript TSV plus JSON summary to `VCF_ALL_LOG`, manifests to
`VCF_ALL_LOG/manifests`, and processing artifacts to `VCF_ALL_TMP`. The older
explicit `input_directory output_directory` form remains supported for generic
automation. The batch command supports legacy
GINS-column repair, missing sample headers, gVCF filtering, assembly detection,
GRCh38-to-GRCh37 liftover fallback, multiple GRCh37 FASTA candidates, empty
VCFs, missing vendor-tag declarations, numeric database-facing chromosome
normalization, and safe parallel work directories. See the
[full V1.3.3 batch guide](V1.3.3_BATCH_WORKFLOW.md).

Inspect input structure and inferred assembly:

```bash
cure-ngs inspect-vcf sample.vcf
```

If the VCF lacks reliable assembly metadata, declare it explicitly:

```bash
cure-ngs inspect-vcf sample.vcf --assembly GRCh37
```

Normalize against the exact FASTA. This splits multiallelic positions into
unique records, left-aligns indels, validates REF alleles, and removes exact
duplicates:

```bash
cure-ngs normalize-vcf sample.vcf sample.normalized.vcf.gz \
  --reference-fasta /references/grch37/hg19.fa \
  --assembly GRCh37
```

End-to-end GRCh37-native VCF to MAF:

```bash
cure-ngs vcf-to-maf sample.vcf sample.maf \
  --source-assembly GRCh37 \
  --source-reference /references/grch37/hg19.fa \
  --target-assembly GRCh37 \
  --cache-version 116 \
  --vep-data /references/vep \
  --vcf-tumor-id TUMOR \
  --tumor-id sample-tumor \
  --vcf-normal-id NORMAL \
  --normal-id sample-normal \
  --forks 4
```

For a GRCh38 input targeting GRCh37, add the target FASTA, chain, and Picard:

```bash
cure-ngs vcf-to-maf sample.grch38.vcf sample.grch37.maf \
  --source-assembly GRCh38 \
  --source-reference /references/grch38/hg38.fa \
  --target-assembly GRCh37 \
  --target-reference /references/grch37/hg19.fa \
  --chain /references/liftover/hg38ToHg19.over.chain.gz \
  --picard-jar /opt/picard/picard.jar \
  --cache-version 116 \
  --vep-data /references/vep \
  --vcf-tumor-id TUMOR \
  --tumor-id sample-tumor
```

Multisample VCFs require explicit `--vcf-tumor-id`; never infer tumor/normal
roles from column order. Empty VCFs are accepted as valid negative panel results
and produce auditable empty outputs rather than being treated as corrupt files.

## Structured HGVS or report-derived route

Normalize HGVS fields while retaining original cells and an audit trail:

```bash
cure-ngs normalize-hgvs-table report.csv report.normalized.csv \
  --delimiter comma
```

Required columns for HGVS-to-minimal-MAF conversion are `sample ID`, `Gene`,
`HGVSc`, `HGVSp`, and `HGVSp_short`. The first online run writes each Ensembl
REST response and its hash to a cache:

```bash
cure-ngs hgvs-table-to-minimal-maf report.tsv minimal.maf \
  --failed minimal.failed.tsv \
  --reference-fasta /references/grch37/hg19.fa \
  --assembly GRCh37 \
  --response-cache /data/output/ensembl-rest-cache
```

Replay the same run without network access:

```bash
cure-ngs hgvs-table-to-minimal-maf report.tsv minimal.replay.maf \
  --failed minimal.replay.failed.tsv \
  --reference-fasta /references/grch37/hg19.fa \
  --assembly GRCh37 \
  --response-cache /data/input/ensembl-rest-cache \
  --offline-replay
```

Rows with missing, ambiguous, or reference-inconsistent mappings are written to
the failure table; they are never silently selected.

## Minimal MAF re-annotation route

Convert minimal MAF alleles into one VCF per complete sample identifier:

```bash
cure-ngs minimal-maf-to-vcf minimal.maf per-sample-vcfs \
  --reference-fasta /references/grch37/hg19.fa \
  --assembly GRCh37
```

Then normalize and annotate each VCF:

```bash
cure-ngs annotate-vcf per-sample-vcfs/sample.vcf sample.annotated.maf \
  --reference-fasta /references/grch37/hg19.fa \
  --assembly GRCh37 \
  --cache-version 116 \
  --vep-data /references/vep \
  --tumor-id sample
```

## Gene and fusion normalization

```bash
cure-ngs normalize-gene P53 \
  --gtf /references/genes/gencode.v19.annotation.gtf.gz \
  --hgnc /references/genes/hgnc_complete_set.txt

cure-ngs normalize-fusion EML4-ALK \
  --gtf /references/genes/gencode.v19.annotation.gtf.gz \
  --hgnc /references/genes/hgnc_complete_set.txt
```

Fuzzy matching is disabled by default. Direction is retained in fusion output,
and ambiguous aliases/splits are reported rather than guessed.

## Concordance

```bash
cure-ngs compare-maf-routes concordance-output \
  --reference-maf direct-route.maf \
  --query-maf report-route.maf \
  --reference-require-any HGVSc \
  --reference-fasta /references/grch37/hg19.fa
```

Outputs include aggregate JSON, per-sample TSV, discordant variants, canonical
VCFs when a FASTA is provided, and a provenance manifest.

## Exit codes and manifests

- `0`: successful command or environment ready
- `2`: invalid input, missing resource, external command failure, or failed
  environment preflight

Transformation commands write a `*.manifest.json` file containing input and
output hashes, parameters, external versions, and executed commands. Retain the
manifest with every reported result.

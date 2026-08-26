# Reference and annotation data

The container deliberately excludes genome FASTA files, VEP caches, chain
files, and current gene nomenclature tables. These resources are large,
release-specific, or updated independently. They must be downloaded from their
authoritative providers, mounted read-only, and recorded with each run.

For the restored multi-file NCDC V1.3.3 workflow, paths and ordered fallback
candidates are declared in
[`references/reference-config.example.json`](../references/reference-config.example.json).
See the [batch workflow guide](V1.3.3_BATCH_WORKFLOW.md) for the complete mapping
from the original shell script.

## What each workflow requires

| Workflow | Required external data |
| --- | --- |
| VCF inspection or HGVS text normalization | none |
| VCF normalization | matching FASTA and `.fai` |
| VCF to annotated MAF | matching FASTA, `.fai`, and VEP 116 GRCh37 or GRCh38 cache |
| GRCh38 to GRCh37 liftover | both assembly FASTAs, target `.fai` and `.dict`, and the source-to-target chain |
| Minimal MAF to VCF | matching FASTA and `.fai` |
| Gene/fusion normalization | GTF with `gene_id`/`gene_name` and HGNC complete-set TSV |
| HGVS table to minimal MAF | matching FASTA plus writable REST response cache; network is needed only for uncached expressions |

## Recommended directory layout

```text
references/
|-- reference-config.json
|-- grch37/
|   |-- hg19.fa
|   |-- hg19.fa.fai
|   |-- hg19.dict
|   |-- Homo_sapiens_assembly19.fasta
|   |-- Homo_sapiens_assembly19.fasta.fai
|   |-- Homo_sapiens_assembly19.dict
|   |-- Homo_sapiens.GRCh37.dna.toplevel.fa
|   |-- Homo_sapiens.GRCh37.dna.toplevel.fa.fai
|   `-- Homo_sapiens.GRCh37.dna.toplevel.dict
|-- grch38/
|   |-- hg38.fa
|   |-- hg38.fa.fai
|   `-- hg38.dict
|-- vep/
|   `-- homo_sapiens/
|       |-- 116_GRCh37/
|       `-- 116_GRCh38/
|-- liftover/
|   |-- hg38ToHg19.over.chain.gz
|   `-- hg19ToHg38.over.chain.gz
`-- genes/
    |-- gencode.v19.annotation.gtf.gz
    `-- hgnc_complete_set.txt
```

Only install the assembly resources needed by the institution. GRCh37/hg19 is
the CURE-NGS panel default. GRCh38 remains supported explicitly.

The single-file command needs one FASTA. The batch command can declare the
original three GRCh37 candidates and will try them in order for each VCF. These
files are alternatives, not sequences that are merged together. Remove a
candidate from the JSON config if the institution does not install it.

## 1. Choose and record a FASTA

For UCSC-style `chr` contigs, the official hg19 sequence is available from the
[UCSC hg19 downloads](https://hgdownload.soe.ucsc.edu/goldenPath/hg19/bigZips/):

```bash
mkdir -p references/grch37
curl --fail --location \
  https://hgdownload.soe.ucsc.edu/goldenPath/hg19/bigZips/hg19.fa.gz \
  --output references/grch37/hg19.fa.gz
gzip --decompress --keep references/grch37/hg19.fa.gz
```

An Ensembl GRCh37 FASTA may instead be installed together with the VEP cache.
Do not silently mix FASTAs across runs. `hg19`, GRCh37, b37, and hs37d5 share a
coordinate system but can differ in contig names and decoy/alternate content.
The REF allele must match the exact FASTA used for normalization.

Create the required indexes with tools already in the full image:

```bash
docker run --rm --user "$(id -u):$(id -g)" \
  --volume "$PWD/references:/references" \
  --entrypoint samtools ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.2 \
  faidx /references/grch37/hg19.fa

docker run --rm --user "$(id -u):$(id -g)" \
  --volume "$PWD/references:/references" \
  --entrypoint java ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.2 \
  -jar /opt/picard/picard.jar CreateSequenceDictionary \
  R=/references/grch37/hg19.fa O=/references/grch37/hg19.dict
```

PowerShell users can omit `--user "$(id -u):$(id -g)"`.

## 2. Install a VEP cache matching the image

The image uses Ensembl VEP 116.1. Ensembl recommends matching the cache release
to the VEP release. The release-specific [Ensembl VEP 116
documentation](https://github.com/Ensembl/ensembl-vep/blob/release/116/README.md)
explains cache installation and compatibility, and the official [Ensembl VEP
repository](https://github.com/Ensembl/ensembl-vep#docker) documents the
maintained Docker image.

Install the GRCh37 cache and FASTA through the official VEP image:

```bash
mkdir -p references/vep
docker run --rm -it \
  --volume "$PWD/references/vep:/data" \
  ensemblorg/ensembl-vep:release_116.1 \
  INSTALL.pl -a cf -s homo_sapiens -y GRCh37
```

For GRCh38, replace `GRCh37` with `GRCh38`. Before analysis, confirm that the
mounted tree contains `homo_sapiens/116_GRCh37` or
`homo_sapiens/116_GRCh38`. A cache from VEP 102 is retained only as historical
benchmark provenance and must not be presented as a VEP 116 reproducibility
run.

## 3. Install liftover chains only when builds differ

Use a chain in the same direction as the conversion:

- GRCh38 to GRCh37/hg19:
  [UCSC `hg38ToHg19.over.chain.gz`](https://hgdownload.soe.ucsc.edu/goldenPath/hg38/liftOver/hg38ToHg19.over.chain.gz)
- GRCh37/hg19 to GRCh38:
  [UCSC `hg19ToHg38.over.chain.gz`](https://hgdownload.soe.ucsc.edu/goldenPath/hg19/liftOver/hg19ToHg38.over.chain.gz)

```bash
mkdir -p references/liftover
curl --fail --location \
  https://hgdownload.soe.ucsc.edu/goldenPath/hg38/liftOver/hg38ToHg19.over.chain.gz \
  --output references/liftover/hg38ToHg19.over.chain.gz
```

Liftover is not performed for a GRCh37-native input targeting GRCh37.

## 4. Install GTF and HGNC resources

For GRCh37 gene coordinates, GENCODE release 19 is available from the
[GENCODE GRCh37 release page](https://www.gencodegenes.org/human/release_19.html):

```bash
mkdir -p references/genes
curl --fail --location \
  https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_19/gencode.v19.annotation.gtf.gz \
  --output references/genes/gencode.v19.annotation.gtf.gz
```

The current complete HGNC set is available from the
[HGNC downloads page](https://hgnc.genenames.org/download/):

```bash
curl --fail --location \
  https://storage.googleapis.com/public-download-files/hgnc/tsv/tsv/hgnc_complete_set.txt \
  --output references/genes/hgnc_complete_set.txt
```

Because HGNC is updated regularly, record the download date and SHA-256 in the
run manifest or institutional resource lock. Use an archived HGNC snapshot when
exact long-term replay is required.

## 5. Run preflight checks

Check the entire configured bundle, including all FASTA indexes, Picard
dictionaries, chain candidates, chain-to-reference labels, and the matching VEP
cache. In addition to file existence, the check verifies primary chromosome
lengths, observed contig styles, chain direction, chain/target-FASTA style
compatibility, VEP species and assembly metadata, and chromosome 1 cache data.
The installed VEP major release must also equal the configured cache version.

```bash
REFERENCE_DIR=/path/to/your/reference-store
mkdir -p config

docker run --rm --user "$(id -u):$(id -g)" \
  --volume "$PWD/config:/config" \
  ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.2 init-reference-config \
  /config/reference-config.json \
  --reference-root /references --cache-version 116

docker run --rm \
  --volume "$REFERENCE_DIR:/references:ro" \
  --volume "$PWD/config:/config:ro" \
  ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.2 doctor-bundle \
  --reference-config /config/reference-config.json \
  --reference-root /references \
  | tee reference-bundle.preflight.json
```

If the data live on a NAS or a different disk, mount that directory at
`/references` and pass `--reference-root /references`. The user-controlled
`REFERENCE_DIR` is the only host tree that the program can inspect. Host paths
never need to be embedded in the image.

GRCh37 VCF-to-MAF environment:

```bash
docker run --rm \
  --volume "$PWD/references:/references:ro" \
  ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.2 doctor \
  --profile vcf-to-maf \
  --assembly GRCh37 \
  --reference-fasta /references/grch37/hg19.fa \
  --vep-data /references/vep \
  --cache-version 116
```

Gene and fusion resources:

```bash
docker run --rm \
  --volume "$PWD/references:/references:ro" \
  ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.2 doctor \
  --profile gene \
  --gtf /references/genes/gencode.v19.annotation.gtf.gz \
  --hgnc /references/genes/hgnc_complete_set.txt
```

The command exits non-zero and reports each missing or incompatible item when
the environment is not ready.

## Checksums and provenance

`resources/resources.lock.json` preserves exact hashes for the authors'
historical audited resources. Institutions using a different legitimate FASTA
or refreshed nomenclature table should compute and retain their own hashes:

```bash
sha256sum references/grch37/hg19.fa \
  references/grch37/hg19.fa.fai \
  references/liftover/hg38ToHg19.over.chain.gz
```

Do not replace a resource while reusing an old output manifest.

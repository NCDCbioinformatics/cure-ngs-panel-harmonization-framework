# Clean Ubuntu installation validation

## 0.2.6 real annotation audit, 2026-10-07

An independent official Ubuntu 22.04.5 x86-64 WSL2 installation was set up
initially without Docker, Git, or CURE-NGS images. This is a separate WSL2
installation, not a standalone Hyper-V VM. Execution used host UID/GID 1000,
a read-only container, no container network, and explicit read-only reference
mounts. No clinical inputs or individual results are published.

The official VEP 116 GRCh37 human cache passed its official checksum and
gzip integrity checks. Both `--jobs 1` and `--jobs 4` processed 25 supplied
VCFs with zero failed files: 21 actual small-variant MAFs, 16,286 MAF rows
per run, and four SV-only files preserved without claiming annotation.
Four variants were separately preserved and excluded from MAF: two known
non-primary cache-unavailable variants and two incompatible legacy hg19 chrM
variants. Exact eligible-input/MAF accounting, all-column serial/parallel
MAF agreement, preserved-VCF record agreement, manifest sidecar checksums,
and unchanged hashes for all 25 original inputs passed.

The Linux unit/integration suite passed 146 tests with 78.44% combined
statement/branch coverage. See [the complete correction scope](ANNOTATION_HOTFIX.md)
and the [privacy-safe aggregate record](../validation/cure_ngs_0.2.6_verification.json).
Image-contained self-tests and executable tutorials are separate release
gates. Public availability is announced on the release page only after both
images publish and anonymous installation passes; local builds alone do not
establish anonymous registry availability.

## Published 0.2.6 image verification, 2026-10-07

[Release v0.2.6](https://github.com/NCDCbioinformatics/cure-ngs-panel-harmonization-framework/releases/tag/v0.2.6)
was created after the [image publication and anonymous-install release gate](https://github.com/NCDCbioinformatics/cure-ngs-panel-harmonization-framework/actions/runs/37556396608)
passed. In the independent Ubuntu installation described above, a new empty
`DOCKER_CONFIG` was then used to pull both published images without GHCR login.
Both images identify source commit
`33dc1e7360cb8a3ebcb972628bac8beed2687148`; its software code is identical to
the tested software revision in the aggregate record. Post-release documentation
updates do not change or move this immutable release tag.

| Published image | Verified OCI manifest digest |
| --- | --- |
| `ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.6` | `sha256:41fb1201379777de923bf4e8af41fed1630b3f2939d098bba9301028801e8b61` |
| `ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.6-core` | `sha256:02c335b4af071e573e8c0559f2946d727be3edf42ca9953c47924153499a238d` |

The downloaded images passed the executable public-install script, the
six-component beginner tutorial, image-contained tests, and actual synthetic
VEP/Picard/vcf2maf regressions. Section 13 was repeated with the real official
human cache and produced 25 new MAF rows on the local output bind mount.
A separate synthetic mitochondrial variant against an NC_012920.1-compatible
reference produced one MAF row without exclusion: the compatibility safeguard
does not reject all mitochondrial variants.

The published full image also repeated the supplied 25-file analysis at
`--jobs 4` and `--jobs 1`, with zero failed files in both runs: 21 non-empty
small-variant MAFs and 16,286 rows per run. The four SV-only files retained
their explicit `NO_SUPPORTED_SMALL_VARIANTS` status and separate preserved
VCFs; their header-only MAFs are not counted as successful annotation.
The four separately excluded alleles had the same explicit reasons reported
above. Every MAF column value and every preserved VCF record agreed between
serial and parallel runs, and between the pre-publication local image and
the published image. All 25 original input hashes were rechecked unchanged
after the public-image runs. This verifies execution and determinism, not
independent biological truth or clinical accuracy.

The published full image was additionally exported, SHA-256 verified, loaded
into a second Docker daemon in another Ubuntu installation, and passed its
image-contained full self-test without source/reference mounts. The portable
archive was 468,492,800 bytes with SHA-256
`17de0e53868bc84901c1b280ff02fb82929b9352dde9e449f9ee7fea72102b05`.
This is an image-transfer check, not a claim that the second installation
was initially blank. Clinical inputs, identifiers, per-variant results and
private logs are not public artifacts; only the
[aggregate verification record](../validation/cure_ngs_0.2.6_verification.json)
is published.

## Historical 0.2.5 pull-only record

> Historical scope correction (2026-10-01): the 0.2.5 record below verified
> pulls, tool inventory, preprocessing, frozen outputs, and the core tutorial.
> It did **not** validate real human-cache VEP annotation. The old full image
> combines VEP 116 with a vcf2maf revision that passes deprecated `--af_esp`
> and fails on non-empty annotation input. Do not interpret the old PASS rows
> as end-to-end VEP validation. See [the annotation hotfix](ANNOTATION_HOTFIX.md).

This historical record documents the external-user validation of CURE-NGS
`v0.2.5`. The check uses public release artifacts and a fresh GitHub-hosted
Ubuntu runner; it does not rely on an author workstation, a pre-pulled
CURE-NGS image, or GHCR credentials.

### Historical validation record

| Property | Value |
| --- | --- |
| Validation date | 2026-09-04 |
| Operating system | GitHub-hosted Ubuntu 22.04 LTS runner |
| Architecture | x86-64 / `linux/amd64` |
| Source | main commit `e07baded2d7eb5727dcd147f6d92e40fa27af20c` |
| Release | [`v0.2.5`](https://github.com/NCDCbioinformatics/cure-ngs-panel-harmonization-framework/releases/tag/v0.2.5) |
| Public verification | [Public Image Verification run 33843399076](https://github.com/NCDCbioinformatics/cure-ngs-panel-harmonization-framework/actions/runs/33843399076) |
| Verification job | `clean-public-install`, PASS in 49 seconds |
| Complete workflow | PASS in 54 seconds |
| Registry login | None; both pulls were anonymous |

The workflow checked out `main`, ran `scripts/verify_public_install.sh`, and
uploaded the generated `tutorial-output/` directory even when a test failed.
The successful artifact was named `public-image-tutorial-output` with artifact
digest
`sha256:937a61faad787613e943670995b26a703c30134803d0c0c8f394c339c9115cd8`.

## Public image pull results

Both release tags resolved anonymously from GHCR and were then pulled and run
by Docker:

| Image | Published OCI manifest digest | Result |
| --- | --- | --- |
| `ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.5-core` | `sha256:90c735f26f1b5cf13393391f3a9ed314beae0c12f579658dbb7e12bb50cdc2da` | PASS |
| `ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.5` | `sha256:0bd13de82e94f10fe1eb70e0979eed71ea6c22f178e00e7007459f081b91da9b` | PASS |

The full image reported CURE-NGS 0.2.5, Python 3.10.12, bcftools 1.13,
SAMtools 1.13, Ensembl VEP 116.1, Picard 3.1.1, Java 17, Perl 5.34, and
the pinned vcf2maf revision
`754d68ab4ad3eba29199c5a62e0061745aed7e7e`.

## Functional results

| Check | Result |
| --- | --- |
| Anonymous core image pull | PASS |
| Anonymous full VEP/vcf2maf image pull | PASS |
| Core image `--version` | PASS; reports 0.2.5 |
| Core `doctor --profile core` | PASS |
| Full-image dependency inventory | PASS; all pinned versions matched |
| Six-component beginner tutorial | PASS, all stages |
| Public VCF fixture | PASS; 25 source variants and validated 25-row reference MAF |
| VCF sanitation fixture | PASS; left alignment and multiallelic splitting exercised |
| Structured HGVS to minimal MAF | PASS with frozen offline response cache |
| Minimal MAF to VCF | PASS |
| Gene-symbol normalization | PASS |
| Direction-preserving fusion normalization | PASS |
| HGVS-table separator regression | PASS |
| Cross-route concordance | PASS; explicit quantitative summary generated |
| Empty but valid VCF handling | PASS; auditable `VALID_EMPTY` result |
| V1.3.3 manuscript workspace export | PASS; `VCF_ALL`, `VCF_ALL_LOG`, `VCF_ALL_MAF`, and `VCF_ALL_TMP` created |

The associated `v0.2.5` tag tests passed before the release and container
images were published, and the current-main checks passed again afterward.
Component-release locks, Python 3.10/3.11/3.12 tests, container regression
tests, repository-health checks, and link checks were included in those gates.

## Repeat the public-install check

On a clean Ubuntu host, install and start Docker as described in
[Installation and deployment](INSTALLATION.md#clean-ubuntu-2204-or-2404), then
run:

```bash
git clone --branch v0.2.5 --depth 1 \
  https://github.com/NCDCbioinformatics/cure-ngs-panel-harmonization-framework.git
cd cure-ngs-panel-harmonization-framework
bash scripts/verify_public_install.sh
```

This command:

1. verifies that Docker or Podman is running and the current user can access
   its socket;
2. pulls both fully qualified `v0.2.5` GHCR images without logging in;
3. records their immutable repository digests;
4. runs the core preflight checks;
5. validates the pinned full-image tools; and
6. runs the complete six-component beginner tutorial.

Results are written to `tutorial-output/` in the cloned repository.

## Scope of the clean-host check

The repository test data are synthetic or attributed public fixtures and do
not require human genome resources. A true VEP/vcf2maf annotation run also
requires the user's GRCh37 FASTA and indexes, VEP 116 GRCh37 cache, and any
needed liftover chain. These multi-gigabyte resources are intentionally not
embedded in either image. Acquisition, explicit host-path mounting,
configuration, and `doctor-bundle` validation are documented in
[Reference and annotation data](REFERENCE_DATA.md) and the
[V1.3.3 batch workflow guide](V1.3.3_BATCH_WORKFLOW.md).

The earlier from-zero Docker Engine installation audit for `v0.2.1` remains
available in the repository's release history. Historical pull-only records
do not substitute for the 0.2.6 real annotation audit above.

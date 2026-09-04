# Six-Component Release Baseline

The consolidated CURE-NGS package is anchored to the latest published,
non-draft, non-prerelease GitHub Release from each of the six historical
component repositories as observed on 15 August 2026 and reconfirmed on
4 September 2026. It does not silently use an arbitrary later commit from a
repository's default branch.

| Repository | Latest audited release | Release commit |
| --- | --- | --- |
| `panel_VCF_vcf2maf_pipeline` | `NCDC_batch_vcf2maf_V.1.3.3_github` | `25eef0406d4f8aeeb90c32d31d267bb158ceff94` |
| `HGVS_to_minimal_MAF_pipeline` | `minimal_maf_vep_hg38tohg19_V.1.0.3` | `68cb277a5596f9e4a7ac7c61e43ba52ddb787632` |
| `minimal_MAF_to_annotated_MAF_pipeline` | `minimal_maf_to_vep_maf_V.1.0.2` | `ce331cf3e5d41f17cd91e2bbc6f805135097a895` |
| `gene_name_harmonization` | `gene_normalizer_human` (release name `gene_normalizer_human_0.2.1`) | `bc3eeee054b96cbe3047c609513ccfaf232b0fa6` |
| `gene_fusion_normalizer` | `gene_fusion_normalizer` (release name `gene_fusion_normalizer_0.2.1`) | `6fd6c563425614ba6d91cc6a65d0561c0e9a6f98` |
| `hgvs_normerlizer` | `hgvsnorm-cli-0.2.2.tar` | `91ee579a312d5841adf42c894e80d1fdb1f37f86` |

`resources/components.lock.json` additionally records each GitHub release ID,
release name, publication timestamp, asset URL, byte size, and SHA-256 digest.
The digests were independently confirmed by downloading all seven release
assets during the revision audit. CI calls
`scripts/verify_component_releases.py --check-latest`; this fails if a newer
release appears or if a locked release identity, commit, asset list, size, or
GitHub-provided digest changes. Maintainers can add `--verify-downloads` to
stream all assets and independently recompute their SHA-256 values.

## Integration interpretation

The release assets define the historical behavioral baseline. Their functions
are exposed through the consolidated `cure-ngs` interface and are covered by
synthetic regression tests. Subsequent revision fixes—including explicit
multiallelic decomposition and left alignment, fail-closed assembly handling,
the CSV separator regression test, provenance manifests, and containerized
execution—are maintained in the consolidated package rather than by silently
editing old release artifacts.

The `gene_name_harmonization` and `gene_fusion_normalizer` GitHub releases and
asset filenames are labelled 0.2.1, while the archived `pyproject.toml` and
`version.py` files still report 0.2.0. The lock records the complete GitHub
release identity and this discrepancy rather than rewriting upstream metadata.
The latest `hgvs_normerlizer` 0.2.2 asset uses `args.sep` for both reading and
writing delimited files; the reviewer-reported `args.spep` path is not present
in that release asset or in the consolidated implementation.

# Clean Ubuntu installation validation

This record documents a from-zero external-user check of release 0.2.1. It is
intended to make the installation claim auditable rather than relying on an
author workstation that already has images, Python packages, or registry
credentials.

## Isolated environment

Validation date: 2026-08-21

| Property | Value |
| --- | --- |
| Operating system | Ubuntu 22.04 LTS (`ubuntu:22.04`) |
| Architecture | x86-64 |
| Container engine | Docker CE 29.7.2 from Docker's official Ubuntu apt repository |
| Docker state | dedicated nested daemon using a new empty `vfs` image store |
| Registry state | no `/root/.docker` authentication configuration |
| Source checkout | fresh public clone, commit `c5fc966166420b6e8c100e2e944946a13229e950` |
| Preinstalled CURE-NGS assets | none |

The official Docker repository/key setup and package installation documented in
`INSTALLATION.md` were executed in this empty environment. The dedicated daemon
did not share the host Docker socket, image cache, or credential store. `docker
image ls` was empty before the first pull. Because the validation environment
was itself a container and did not boot systemd, its Docker daemon was started
directly with the `vfs` storage driver; a normal Ubuntu VM uses the documented
`systemctl enable --now docker` command.

## Public image pull results

Both release tags downloaded anonymously from GHCR:

| Image | Published manifest digest | Clean-daemon size | Result |
| --- | --- | ---: | --- |
| `ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.1-core` | `sha256:b917874acc80d286695b290b9ae39cb6d65e9bc05549b79614e80b60bf678472` | 147 MB | PASS |
| `ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.1` | `sha256:a18baab0cf97fa427d9e83b8e6a2aa1b399a1080eb6dce4ec723c6cf40915ab2` | 1.24 GB | PASS |

The installed full image reported CURE-NGS 0.2.1, Python 3.10.12, bcftools
1.13, SAMtools 1.13, Ensembl VEP 116.1, Picard 3.1.1, Java 17.0.19, Perl
5.34.0, and pinned vcf2maf revision
`754d68ab4ad3eba29199c5a62e0061745aed7e7e`.

## Functional results

| Check | Result |
| --- | --- |
| Official Docker apt-repository installation | PASS; Docker CE 29.7.2 and Compose 5.5.0 installed |
| Anonymous first pull with an empty image store | PASS for core and full images |
| Core image `--version` | PASS |
| Full image dependency inventory | PASS |
| Public VCF fixture input | 25 records processed |
| VCF sanitation fixture | 4 normalized records |
| Structured HGVS to minimal MAF | PASS |
| Minimal MAF to VCF | 3 records |
| Gene-symbol normalization | PASS |
| Direction-preserving fusion normalization | PASS |
| HGVS-table normalization | PASS |
| Cross-route concordance | 100% on the included deterministic fixture |
| Empty but valid VCF handling | `VALID_EMPTY` |
| Six-component beginner tutorial | PASS, all 10 stages |
| Native automated suite | 88 tests passed; 74.69% branch-aware coverage |
| Fresh core image build | PASS with `--no-cache` |
| Tutorial using the freshly built core image | PASS, all 10 stages |

Ubuntu 22.04 initially supplied pip 22.0.2. That version could install pinned
runtime requirements but could not perform this project's PEP 660 editable
install because it did not invoke the backend's `build_editable` hook. After
upgrading the virtual environment to the documented pip 25.0.1, the editable
install and all 88 tests passed. The clean-install documentation now includes
that required upgrade.

The no-cache source build ran inside a deliberately bridge-disabled nested
daemon. Because build containers in that artificial setup had no DNS, the
build was run with `docker build --network=host`; the resulting image and
tutorial passed. A normal Docker installation uses its default build network
and does not require that option.

## Repeat the public-install check

On a clean Ubuntu host, install and start Docker as described in
[Installation and deployment](INSTALLATION.md#clean-ubuntu-2204-or-2404), then
run:

```bash
git clone https://github.com/NCDCbioinformatics/cure-ngs-panel-harmonization-framework.git
cd cure-ngs-panel-harmonization-framework
bash scripts/verify_public_install.sh
```

This command pulls both fully qualified GHCR images, records their repository
digests, verifies the pinned full-image tools, and runs the entire six-component
tutorial. Results are written to `tutorial-output/` in the cloned repository.

## Scope of the clean-host check

The repository test data are synthetic or attributed public fixtures and do not
require human genome resources. A true VEP/vcf2maf annotation run additionally
requires the user's GRCh37 FASTA, indexes, VEP 116 GRCh37 cache, and any needed
liftover chain. Those multi-gigabyte resources are intentionally not embedded
in either image. Their acquisition, explicit host-path mounting, configuration,
and `doctor-bundle` validation are documented in
[Reference and annotation data](REFERENCE_DATA.md) and the
[V1.3.3 batch workflow guide](V1.3.3_BATCH_WORKFLOW.md).

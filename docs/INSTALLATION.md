# Installation and deployment

This guide is written for a reviewer or external institution starting from a
clean computer. CURE-NGS does not require the host institution to reproduce the
authors' Python environment. The recommended runtime is the version-pinned
Docker/OCI image built from this repository.

## 1. Install Docker or Podman on the host

Required:

- a 64-bit Linux, macOS, or Windows host
- [Git](https://git-scm.com/downloads)
- [Docker Engine](https://docs.docker.com/engine/install/) on Linux, or
  [Docker Desktop](https://docs.docker.com/desktop/) on Windows/macOS
- Docker Compose v2 when using `compose.yaml`; it is included with Docker
  Desktop, and the Linux installation options are described in the
  [Compose installation guide](https://docs.docker.com/compose/install/)
- outbound HTTPS while building the image and downloading reference resources

Recommended for the full VEP/vcf2maf route:

- 4 or more CPU cores
- 8 GB or more RAM; increase this for large panels or high VEP fork counts
- at least 30 GB free storage for the image, GRCh37 FASTA, VEP cache, and
  working files

Docker or Podman may be used. Commands below use `docker`; substitute `podman`
where appropriate. Linux is the primary supported runtime. On Windows, use
Docker Desktop with the WSL 2 backend and store large reference data inside the
WSL filesystem when possible for better I/O performance.

Verify the installation before downloading CURE-NGS:

```bash
docker version
docker run --rm hello-world
```

## 2. Obtain a reproducible source revision

```bash
git clone https://github.com/NCDCbioinformatics/cure-ngs-panel-harmonization-framework.git
cd cure-ngs-panel-harmonization-framework
git rev-parse HEAD
```

For a manuscript analysis, record the release tag or full commit SHA in the
methods and keep the generated `*.manifest.json` file with the output. Do not
run an unrecorded moving branch for a final analysis.

## 3. Build or pull the images

The full image contains VEP, vcf2maf, Picard, bcftools, SAMtools, Perl, Java,
and the Python application. It does not contain the large genome resources.

```bash
docker build \
  --build-arg SOURCE_REVISION="$(git rev-parse HEAD)" \
  --file docker/Dockerfile \
  --tag cure-ngs-harmonizer:0.1.0 .
```

The core image is smaller and is sufficient for the network-free reviewer
walkthrough, normalization, table processing, and concordance:

```bash
docker build \
  --build-arg SOURCE_REVISION="$(git rev-parse HEAD)" \
  --file docker/Dockerfile.core \
  --tag cure-ngs-harmonizer:0.1.0-core .
```

Confirm that the image starts and inspect every detected tool:

```bash
docker run --rm cure-ngs-harmonizer:0.1.0 versions
docker run --rm cure-ngs-harmonizer:0.1.0 --help
```

Tagged releases are configured to publish immutable full and core images to
GitHub Container Registry. After the `0.1.0` release workflow completes, they
can be obtained without a local build:

```bash
docker pull ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.1.0
docker pull ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.1.0-core
```

Verify that the package is visible on the repository's Packages page before
using these pull commands. A `No packages published` message means that the
release workflow has not published the images yet; build from the tagged source
instead.

## 4. Reviewer test without large downloads

This deterministic test builds the core image and exercises functions mapped
from all six historical components. It disables container networking during
all test runs.

```bash
bash scripts/run_reviewer_demo.sh
```

The script automatically selects a working Docker or Podman engine. Set
`CONTAINER_ENGINE=docker` or `CONTAINER_ENGINE=podman` to override detection.

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_reviewer_demo.ps1
```

Expected final message: `Reviewer demonstration passed`.

## 5. Configure institutional paths

Copy the environment template and edit only host paths and, on Linux, the
runtime UID/GID if required:

```bash
cp .env.example .env
mkdir -p workspace/output references
docker compose run --rm cure-ngs versions
```

Compose mounts input and reference directories read-only. Outputs are the only
normal writable bind mount. The container itself is read-only and runs without
root privileges or additional privileges.

Linux bind mounts must be writable by the selected runtime user. The default is
UID/GID 10001. Either grant that identity access to the output directory or set
`CURE_NGS_UID=$(id -u)` and `CURE_NGS_GID=$(id -g)` in `.env`.

## 6. Prepare external resources

Continue with [Reference and annotation data](REFERENCE_DATA.md). After the
files are mounted, do not start a long analysis until `cure-ngs doctor` reports
`READY` for the intended profile.

## 7. Native Python installation

Native installation is intended for developers and platform-neutral commands,
not as the primary reproducible deployment route:

```bash
python -m pip install --require-hashes --requirement requirements-runtime.txt
python -m pip install --no-deps --editable .
cure-ngs --help
```

Supported Python versions are 3.10 through 3.12. External tools remain the
user's responsibility outside the container.

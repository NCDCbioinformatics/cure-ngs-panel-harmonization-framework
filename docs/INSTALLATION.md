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

### Clean Ubuntu 22.04 or 24.04

The following commands implement Docker's official apt-repository installation
on a newly installed Ubuntu host. Run them in Ubuntu, not in Windows
PowerShell:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt-get update
sudo apt-get install -y \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run --rm hello-world
```

Docker works through `sudo` at this point. Non-root Docker access is required
to run this repository's tutorial and verification scripts as written. Add the
current user to the Docker group, then start a new group session:

```bash
sudo groupadd -f docker
sudo usermod -aG docker "$USER"
newgrp docker
id -nG
ls -l /var/run/docker.sock
docker info
```

The output of `id -nG` must include `docker`, and `docker info` must show both
the Client and Server sections. If `sudo docker info` succeeds but `docker
info` returns `permission denied ... /var/run/docker.sock`, the daemon is
healthy and only the current user's group membership is missing or has not yet
been refreshed. Log out and back in if `newgrp docker` is not retained.

Membership in the Docker group grants root-level host privileges. On a managed
institutional server, ask the administrator whether `sudo`, rootless Docker,
or Podman is the approved method instead.

WSL 2 is a different case. If Docker Desktop provides the daemon, enable WSL
integration for the Ubuntu distribution and do not install a second daemon
inside it. If Docker Engine was intentionally installed inside WSL and systemd
is disabled, use `sudo service docker start`. In either case, do not continue
until both `docker info` and `docker run --rm hello-world` succeed. If a WSL
terminal still has the old group membership, close all WSL terminals, run
`wsl --shutdown` in Windows PowerShell, and reopen Ubuntu.

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
FULL_IMAGE=ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.5
docker build \
  --build-arg SOURCE_REVISION="$(git rev-parse HEAD)" \
  --file docker/Dockerfile \
  --tag "$FULL_IMAGE" .
```

The core image is smaller and is sufficient for the network-free reviewer
walkthrough, normalization, table processing, and concordance:

```bash
CORE_IMAGE=ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.5-core
docker build \
  --build-arg SOURCE_REVISION="$(git rev-parse HEAD)" \
  --file docker/Dockerfile.core \
  --tag "$CORE_IMAGE" .
```

Confirm that the image starts and inspect every detected tool:

```bash
FULL_IMAGE=ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.5
docker run --rm "$FULL_IMAGE" versions
docker run --rm "$FULL_IMAGE" --help
```

Tagged releases publish immutable full and core images to GitHub Container
Registry. They can be obtained without a local build:

```bash
CORE_IMAGE=ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.5-core
FULL_IMAGE=ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.5
docker pull "$CORE_IMAGE"
docker pull "$FULL_IMAGE"
docker run --rm "$CORE_IMAGE" --version
docker run --rm "$FULL_IMAGE" versions
```

These public images do not require `docker login`. Keep the complete
`ghcr.io/ncdcbioinformatics/...` name in subsequent `docker run` commands; the
short name `cure-ngs-harmonizer:0.2.5` is a separate local/Docker Hub name.

Both images also contain the public six-component test bundle. Confirm it is
present and export an ordinary host-side copy before using the beginner
tutorial:

```bash
mkdir -p tutorial-data
docker run --rm "$CORE_IMAGE" verify-tutorial-data
docker run --rm --user "$(id -u):$(id -g)" \
  --volume "$PWD/tutorial-data:/data/output" \
  "$CORE_IMAGE" export-tutorial-data /data/output/component-test-data
```

The exported directory includes original VCF/XLSX/CSV inputs, SHA-256
provenance, and non-empty historical MAF outputs. Large hg19/GRCh37 and VEP
resources remain external.

Run the public-install validator to pull both images, inspect their repository
digests and dependency versions, run the core preflight, and execute the entire
six-component tutorial:

```bash
bash scripts/verify_public_install.sh
```

Expected final message: `CURE-NGS public installation verified`.

The validator also exercises the Section 13 single-reference configuration and
`doctor-bundle` path with a structural fixture. The actual VEP annotation is a
separate opt-in run because the real GRCh37 cache is approximately 25 GB; see
[Beginner tutorial Section 13](BEGINNER_TUTORIAL.md#13-optional-complete-real-vepvcf2maf-annotation).

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
sudo apt-get install -y python3-venv
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip==25.0.1
python -m pip install --require-hashes --requirement requirements-runtime.txt
python -m pip install --requirement requirements-test.txt
python -m pip install --no-deps --editable .
cure-ngs --help
python -m pytest --cov=cure_ngs --cov-fail-under=70
```

Supported Python versions are 3.10 through 3.12. External tools remain the
user's responsibility outside the container. Ubuntu 22.04's original pip
22.0.2 cannot perform this project's PEP 660 editable install, which is why the
explicit pip upgrade is required.

# Troubleshooting

Run `cure-ngs doctor` before investigating a long workflow failure. Its JSON
output is suitable for attaching to a GitHub issue together with `cure-ngs
versions` and the input VCF header with sensitive fields removed.

## Permission denied for `/var/run/docker.sock`

An error such as `permission denied while trying to connect to the Docker
daemon socket at unix:///var/run/docker.sock` occurs before Docker contacts
GHCR. It is a host-user permission problem, not a CURE-NGS image, registry
login, or image-tag failure.

First confirm that the daemon works with administrator access, then grant the
current Linux/WSL user non-root Docker access:

```bash
sudo docker info
sudo groupadd -f docker
sudo usermod -aG docker "$USER"
newgrp docker
id -nG
ls -l /var/run/docker.sock
docker info
```

`id -nG` must contain `docker`; the socket is normally owned by `root:docker`;
and the final `docker info` must show a Server section without `sudo`. On WSL,
if the terminal retains the old group list, close all WSL terminals, run
`wsl --shutdown` in Windows PowerShell, reopen Ubuntu, and repeat `docker
info`.

Do not use `chmod 777 /var/run/docker.sock`: it grants every local user control
of a root-equivalent daemon and is reset when Docker recreates the socket.
Membership in the `docker` group is itself root-equivalent; on a managed server
use the institution's approved `sudo`, rootless Docker, or Podman policy.

## Docker cannot connect to its socket

First run `docker info`. If the client section appears but the server cannot be
reached, CURE-NGS has not started yet and image commands cannot work. On native
Ubuntu with systemd:

```bash
sudo systemctl enable --now docker
docker info
```

For Docker Engine installed inside WSL without systemd, use `sudo service
docker start`. If Docker Desktop supplies the WSL daemon, enable integration
for that distribution instead of starting a second daemon. A path such as
`~/.docker/run/docker.sock` in the error may also indicate a stale context or
`DOCKER_HOST`; inspect `docker context ls`, use the intended context, and unset
an incorrect `DOCKER_HOST`.

## GHCR pull is denied or the image cannot be found

Release 0.2.5 is public; `docker login ghcr.io` is not required. Use the exact,
lowercase, fully qualified name:

```bash
CORE_IMAGE=ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.5-core
FULL_IMAGE=ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.5
docker pull "$CORE_IMAGE"
docker pull "$FULL_IMAGE"
```

Do not pull the GHCR name and then run only
`cure-ngs-harmonizer:0.2.5`; that short name can make Docker query Docker Hub.
Run `bash scripts/verify_public_install.sh` to test both public images and the
complete tutorial. If the exact commands still fail, save the output of
`docker info`, `docker context ls`, and `docker pull "$CORE_IMAGE"` for the
GitHub issue. Do not include credentials or access tokens.

## Pull fails with a network, TLS, or DNS error

The initial download needs outbound HTTPS access to `ghcr.io` and its backing
blob-storage endpoints. Test the same command from an unrestricted network or
ask the institutional proxy/firewall administrator to allow those endpoints.
Registry authentication does not fix a DNS timeout, certificate error, or
blocked HTTPS connection.

## Permission denied under `/data/output`

The image runs without root privileges. On Linux, make the bind-mounted output
directory writable by UID/GID 10001 or override the Compose UID/GID with the
current host identity. Do not make reference or input mounts writable merely to
work around an output permission error.

## FASTA index is missing

Create `<reference>.fai` with `samtools faidx`. Liftover also requires the
Picard sequence dictionary next to the target FASTA, for example `hg19.dict`.

## REF mismatch during normalization

The declared assembly and coordinate system do not guarantee identical FASTA
content. Confirm the file provenance, chromosome naming, decoy content, and
that the input caller used the same reference. Do not bypass REF validation.

## VEP cache not found or incompatible

VEP 116.1 requires a release-116 cache. The expected directory is
`<vep-data>/homo_sapiens/116_GRCh37` or `116_GRCh38`. Mount the parent directory
as `--vep-data`; do not pass the assembly subdirectory itself.

## Every liftover record was rejected

Check chain direction first. A GRCh38 input targeting GRCh37 requires
`hg38ToHg19`, not `hg19ToHg38`. Also verify that the target FASTA and dictionary
use contigs compatible with the chain.

## Multiple samples in one VCF

Supply `--vcf-tumor-id` and, for matched-normal data, `--vcf-normal-id`.
Output display IDs are independently controlled with `--tumor-id` and
`--normal-id`. The software will not guess tumor/normal roles.

## HGVS online results cannot be reproduced

Keep the complete response-cache directory from the first run and replay with
`--offline-replay`. A missing entry is reported as `REST_CACHE_MISS`; a changed
entry is rejected by its SHA-256 check.

## Empty VCF

An empty but structurally valid VCF can occur after a panel caller finds no
reportable variants or after upstream filtering. CURE-NGS records this as a
valid empty result. A file without a valid VCF header is still rejected.

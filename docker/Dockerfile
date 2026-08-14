FROM docker.io/ensemblorg/ensembl-vep:release_116.1@sha256:6972667883d89b9fa55e5cbe94f1b4c259ebc6bbd178310cef78f617e055eb75

ARG DEBIAN_FRONTEND=noninteractive
ARG PICARD_VERSION=3.1.1
ARG PICARD_SHA256=15c79f51fd0ac001049f9dd7b9bac1dbdf759dcb0230a89c7f6d1f246e8bbab4
ARG VCF2MAF_REVISION=754d68ab4ad3eba29199c5a62e0061745aed7e7e
ARG VCF2MAF_ARCHIVE_SHA256=e2f1d754a95ed30ec0193c743273e446ac8fbef8b5ab4027d458fa66f85711ed
ARG SOURCE_REVISION=uncommitted

USER root

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        bcftools=1.13-1 \
        ca-certificates \
        curl \
        libhts3=1.13+ds-2build1 \
        openjdk-17-jre-headless \
        python3=3.10.6-1~22.04.1 \
        python3-pip=22.0.2+dfsg-1ubuntu0.7 \
        samtools=1.13-4 \
        tini \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/picard /opt/vcf2maf

COPY requirements-runtime.txt /opt/cure-ngs/requirements-runtime.txt

RUN python3 -m pip install \
        --disable-pip-version-check \
        --no-cache-dir \
        --no-deps \
        --require-hashes \
        --requirement /opt/cure-ngs/requirements-runtime.txt

RUN curl --fail --location --retry 3 --connect-timeout 15 --max-time 180 \
        --output /opt/picard/picard.jar \
        "https://github.com/broadinstitute/picard/releases/download/${PICARD_VERSION}/picard.jar" \
    && echo "${PICARD_SHA256}  /opt/picard/picard.jar" | sha256sum --check --strict \
    && curl --fail --location --retry 3 --connect-timeout 15 --max-time 120 \
        --output /tmp/vcf2maf.tar.gz \
        "https://github.com/mskcc/vcf2maf/archive/${VCF2MAF_REVISION}.tar.gz" \
    && echo "${VCF2MAF_ARCHIVE_SHA256}  /tmp/vcf2maf.tar.gz" | sha256sum --check --strict \
    && tar --extract --gzip --file /tmp/vcf2maf.tar.gz \
        --directory /opt/vcf2maf --strip-components=1 \
    && rm /tmp/vcf2maf.tar.gz

RUN groupadd --gid 10001 cure-ngs \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin cure-ngs \
    && mkdir -p /opt/cure-ngs /data/input /data/output /references \
    && chown -R 10001:10001 /data/output

COPY src /opt/cure-ngs/src
COPY resources /opt/cure-ngs/resources

ENV LC_ALL=C.UTF-8 \
    LANG=C.UTF-8 \
    PICARD_JAR=/opt/picard/picard.jar \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/cure-ngs/src \
    PYTHONUNBUFFERED=1 \
    TZ=UTC \
    VCF2MAF_PATH=/opt/vcf2maf/vcf2maf.pl \
    VCF2MAF_REVISION=754d68ab4ad3eba29199c5a62e0061745aed7e7e \
    VEP_CACHE_DIR=/references/vep

LABEL org.opencontainers.image.title="CURE-NGS Harmonizer" \
      org.opencontainers.image.description="Reproducible panel NGS variant harmonization" \
      org.opencontainers.image.version="0.1.0-vep116.1" \
      org.opencontainers.image.source="https://github.com/NCDCbioinformatics/cure-ngs-panel-harmonization-framework" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.licenses="MIT"

USER 10001:10001
WORKDIR /data

ENTRYPOINT ["/usr/bin/tini", "--", "python3", "-m", "cure_ngs.cli"]
CMD ["--help"]

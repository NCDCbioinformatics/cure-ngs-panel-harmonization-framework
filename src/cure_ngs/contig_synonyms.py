"""Official, assembly-specific sequence aliases; never infer coordinates."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from .models import Assembly
from .fasta import FastaReference
from .vcf import _open_text


REPORTS = {
    Assembly.GRCH37: (
        "GRCh37.p13_assembly_report.txt",
        "911ad5d1d808f81d2a6d40817aa448fb927e6d7491a2a1b599c483acb1e97542",
    ),
    Assembly.GRCH38: (
        "GRCh38.p14_assembly_report.txt",
        "43ef1f3e3898ef4cc6ddc0db92e03d9b016ddf79e8314040f350fd1f93e3665f",
    ),
}

# NCBI NC_012920.1, uppercase sequence without FASTA header/whitespace.
# https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=nuccore&id=NC_012920.1&rettype=fasta&retmode=text
RCRS_LENGTH = 16569
RCRS_SEQUENCE_SHA256 = "f156ff3f65bbcc80c7ebb9936dceb96b1477b4f8f535c4e1dbe7baea225cbc66"


def assembly_contig_aliases(assembly: Assembly) -> dict[str, str]:
    filename, expected = REPORTS[assembly]
    report = files("cure_ngs").joinpath("data", "contig_synonyms", filename)
    payload = report.read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(payload).hexdigest() != expected:
        raise ValueError(f"NCBI assembly report checksum mismatch: {filename}")
    aliases: dict[str, str] = {}
    for line in payload.decode("utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        columns = line.split("\t")
        if len(columns) != 10:
            raise ValueError(f"Invalid NCBI assembly report row: {filename}")
        canonical = columns[4]  # Ensembl non-primary sequences use GenBank IDs.
        if columns[1] == "assembled-molecule" or canonical == "na":
            continue
        synonyms = [columns[0], columns[9]]
        if columns[5] == "=":  # Do not equate different GenBank/RefSeq sequences.
            synonyms.append(columns[6])
        for alias in synonyms:
            if alias in ("na", canonical):
                continue
            if alias in aliases and aliases[alias] != canonical:
                raise ValueError(f"Conflicting NCBI contig alias: {alias}")
            aliases[alias] = canonical
    return aliases


def write_default_vep_config(directory: Path, assembly: Assembly, cache_directory: Path | None = None) -> Path:
    synonyms = directory / "assembly-contig-synonyms.tsv"
    aliases = assembly_contig_aliases(assembly)
    # An explicit synonyms option replaces VEP's default cache synonyms. Keep
    # the selected cache's entire list, including primary/mitochondrial names.
    cache_synonyms = cache_directory / "chr_synonyms.txt" if cache_directory else None
    existing = cache_synonyms.read_text(encoding="utf-8") if cache_synonyms and cache_synonyms.is_file() else ""
    synonyms.write_text(
        existing.rstrip("\n") + ("\n" if existing else "")
        + "".join(f"{canonical}\t{alias}\n" for alias, canonical in sorted(aliases.items())),
        encoding="utf-8",
    )
    config = directory / "default-vep.config"
    config.write_text(f"synonyms {synonyms}\n", encoding="utf-8")
    return config


@dataclass(frozen=True)
class CacheContigPartition:
    annotation_vcf: Path
    eligible_records: int
    excluded_records: int
    excluded_vcf: Path | None
    audit: Path


def partition_cache_contigs(
    input_vcf: Path, directory: Path, cache_directory: Path, assembly: Assembly,
    reference_fasta: Path | None = None,
) -> CacheContigPartition:
    """Retain known non-primary sequences without cache features in a sidecar.

    Primary chromosomes and unknown contig names are never silently excluded.
    All records remain verbatim; aliases only configure VEP's sequence lookup.
    """
    aliases = assembly_contig_aliases(assembly)
    known_non_primary = set(aliases.values())
    eligible_vcf = directory / "cache-eligible.vcf"
    excluded_vcf = directory / "excluded-cache-unsupported-contigs.vcf"
    eligible_count = excluded_count = 0
    excluded_contigs: Counter[tuple[str, str, str]] = Counter()
    mito_compatible: dict[str, bool] = {}
    mito_reference_evidence: dict[str, dict[str, object]] = {}
    with _open_text(input_vcf) as source, eligible_vcf.open("w", encoding="utf-8", newline="") as eligible, excluded_vcf.open("w", encoding="utf-8", newline="") as excluded:
        for line in source:
            if line.startswith("#"):
                eligible.write(line)
                excluded.write(line)
            elif line.strip():
                chromosome = line.split("\t", 1)[0]
                canonical = aliases.get(chromosome, chromosome)
                reason = None
                if chromosome in {"M", "MT", "chrM", "chrMT"} and reference_fasta is not None:
                    if chromosome not in mito_compatible:
                        reference = FastaReference(reference_fasta)
                        name = chromosome if chromosome in reference.entries else reference.resolve_contig(chromosome)
                        entry = reference.entries[name]
                        sequence_sha256 = hashlib.sha256(reference.fetch(name, 1, entry.length, resolve_aliases=False).encode("ascii")).hexdigest()
                        mito_compatible[chromosome] = entry.length == RCRS_LENGTH and sequence_sha256 == RCRS_SEQUENCE_SHA256
                        mito_reference_evidence[chromosome] = {"length": entry.length, "sequence_sha256": sequence_sha256}
                    if not mito_compatible[chromosome]:
                        reason = "MITOCHONDRIAL_REFERENCE_INCOMPATIBLE_WITH_GRCH_RCRS"
                        canonical = "MT"
                if reason is None and canonical in known_non_primary and not (cache_directory / canonical).is_dir():
                    reason = "NO_FEATURE_DIRECTORY_IN_SELECTED_VEP_CACHE"
                if reason is not None:
                    excluded.write(line)
                    excluded_count += 1
                    excluded_contigs[(chromosome, canonical, reason)] += 1
                else:
                    eligible.write(line)
                    eligible_count += 1
    if not excluded_count:
        excluded_vcf.unlink()
    audit = directory / "cache-contig-accounting.json"
    filename, report_sha256 = REPORTS[assembly]
    audit.write_text(json.dumps({
        "schema_version": "1.0",
        "policy": "Preserve known non-primary contigs absent from the selected VEP cache and incompatible mitochondrial references in a separate VCF; exclude from MAF",
        "assembly": assembly.value,
        "assembly_report": filename,
        "assembly_report_lf_sha256": report_sha256,
        "input_records": eligible_count + excluded_count,
        "annotation_input_records": eligible_count,
        "excluded_contig_records": excluded_count,
        "excluded_contigs": [
            {"source_contig": source, "canonical_contig": canonical, "records": count,
             "reason": reason}
            for (source, canonical, reason), count in sorted(excluded_contigs.items())
        ],
        "mitochondrial_reference": mito_reference_evidence,
        "expected_mitochondrial_reference": {"accession": "NC_012920.1", "length": RCRS_LENGTH,
                                              "sequence_sha256": RCRS_SEQUENCE_SHA256},
        "coordinates_ref_alt_changed": False,
    }, indent=2) + "\n", encoding="utf-8")
    return CacheContigPartition(eligible_vcf, eligible_count, excluded_count,
                               excluded_vcf if excluded_count else None, audit)

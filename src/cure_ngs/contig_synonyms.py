"""Official, assembly-specific sequence aliases; never infer coordinates."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from .models import Assembly
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


def write_default_vep_config(directory: Path, assembly: Assembly) -> Path:
    synonyms = directory / "assembly-contig-synonyms.tsv"
    aliases = assembly_contig_aliases(assembly)
    synonyms.write_text(
        "".join(f"{canonical}\t{alias}\n" for alias, canonical in sorted(aliases.items())),
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
) -> CacheContigPartition:
    """Retain known non-primary sequences without cache features in a sidecar.

    Primary chromosomes and unknown contig names are never silently excluded.
    All records remain verbatim; aliases only configure VEP's sequence lookup.
    """
    aliases = assembly_contig_aliases(assembly)
    known_non_primary = set(aliases.values())
    eligible_vcf = directory / "cache-eligible.vcf"
    excluded_vcf = directory / "excluded-no-cache-contigs.vcf"
    eligible_count = excluded_count = 0
    excluded_contigs: Counter[tuple[str, str]] = Counter()
    with _open_text(input_vcf) as source, eligible_vcf.open("w", encoding="utf-8", newline="") as eligible, excluded_vcf.open("w", encoding="utf-8", newline="") as excluded:
        for line in source:
            if line.startswith("#"):
                eligible.write(line)
                excluded.write(line)
            elif line.strip():
                chromosome = line.split("\t", 1)[0]
                canonical = aliases.get(chromosome, chromosome)
                if canonical in known_non_primary and not (cache_directory / canonical).is_dir():
                    excluded.write(line)
                    excluded_count += 1
                    excluded_contigs[(chromosome, canonical)] += 1
                else:
                    eligible.write(line)
                    eligible_count += 1
    if not excluded_count:
        excluded_vcf.unlink()
    audit = directory / "cache-contig-accounting.json"
    filename, report_sha256 = REPORTS[assembly]
    audit.write_text(json.dumps({
        "schema_version": "1.0",
        "policy": "Preserve known non-primary contigs absent from the selected VEP cache in a separate VCF; exclude from MAF",
        "assembly": assembly.value,
        "assembly_report": filename,
        "assembly_report_lf_sha256": report_sha256,
        "input_records": eligible_count + excluded_count,
        "annotation_input_records": eligible_count,
        "excluded_contig_records": excluded_count,
        "excluded_contigs": [
            {"source_contig": source, "canonical_contig": canonical, "records": count,
             "reason": "NO_FEATURE_DIRECTORY_IN_SELECTED_VEP_CACHE"}
            for (source, canonical), count in sorted(excluded_contigs.items())
        ],
        "coordinates_ref_alt_changed": False,
    }, indent=2) + "\n", encoding="utf-8")
    return CacheContigPartition(eligible_vcf, eligible_count, excluded_count,
                               excluded_vcf if excluded_count else None, audit)

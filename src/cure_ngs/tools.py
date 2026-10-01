from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .vcf import sanitize_vcf


_PLAIN_ALLELE = re.compile(r"^[ACGTNacgtn]+$")


def partition_small_variant_records(input_path: Path, supported_path: Path, excluded_path: Path) -> dict[str, int]:
    """Retain excluded records verbatim; never invent linear alleles for SVs.

    Mixed symbolic/sequence ALT records are conservatively excluded whole.
    gVCF records are handled by the separate gVCF extraction route.
    """
    supported = excluded = 0
    with input_path.open(encoding="utf-8-sig") as reader, supported_path.open("w", encoding="utf-8", newline="\n") as small, excluded_path.open("w", encoding="utf-8", newline="\n") as other:
        for line in reader:
            if line.startswith("#"):
                small.write(line)
                other.write(line)
                continue
            fields = line.rstrip("\r\n").split("\t")
            if _PLAIN_ALLELE.fullmatch(fields[3]) and all(_PLAIN_ALLELE.fullmatch(alt) for alt in fields[4].split(",")):
                small.write(line)
                supported += 1
            else:
                other.write(line)
                excluded += 1
    return {"supported_records": supported, "excluded_records": excluded}


def filter_plain_small_variant_records(
    input_path: str | Path, output_path: str | Path
) -> dict[str, int]:
    """Remove breakends/symbolic or vendor-encoded ALT values before norm."""

    source = Path(input_path)
    destination = Path(output_path)
    kept = 0
    removed = 0
    with source.open("r", encoding="utf-8-sig") as reader, destination.open(
        "w", encoding="utf-8", newline="\n"
    ) as writer:
        for line_number, line in enumerate(reader, start=1):
            if line.startswith("#") or not line.strip():
                writer.write(line.rstrip("\r\n") + "\n")
                continue
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) < 5:
                raise ValueError(
                    f"VCF record has fewer than 5 columns at line {line_number}"
                )
            alleles = fields[4].split(",")
            if _PLAIN_ALLELE.fullmatch(fields[3]) and all(
                _PLAIN_ALLELE.fullmatch(allele) for allele in alleles
            ):
                writer.write(line.rstrip("\r\n") + "\n")
                kept += 1
            else:
                removed += 1
    return {"kept_records": kept, "removed_unsupported_alleles": removed}


def tool_version(executable: str) -> str:
    result = subprocess.run(
        [executable, "--version"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    lines = (result.stdout or result.stderr).splitlines()
    return next(line.strip() for line in lines if line.strip())


@dataclass(frozen=True)
class NormalizationRun:
    commands: tuple[tuple[str, ...], ...]
    tool_version: str
    summaries: tuple[dict[str, int], ...]


def normalize_vcf(
    input_path: str | Path,
    output_path: str | Path,
    *,
    reference_fasta: str | Path,
    bcftools: str = "bcftools",
) -> NormalizationRun:
    input_path = Path(input_path)
    output_path = Path(output_path)
    reference_fasta = Path(reference_fasta)
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    if not reference_fasta.is_file():
        raise FileNotFoundError(reference_fasta)
    reference_index = Path(f"{reference_fasta}.fai")
    if not reference_index.is_file():
        raise FileNotFoundError(
            f"FASTA index is missing: {reference_index}; run samtools faidx first"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_type = "z" if output_path.name.lower().endswith(".gz") else "v"
    with tempfile.TemporaryDirectory(
        prefix=".cure-ngs-normalize-", dir=output_path.parent
    ) as temporary_directory:
        sanitized_path = Path(temporary_directory) / "sanitized.vcf"
        sanitize_vcf(input_path, sanitized_path)
        reheadered_path = Path(temporary_directory) / "reheadered.vcf"
        reheader_command = [
            bcftools,
            "reheader",
            "--fai",
            str(reference_index),
            "--output",
            str(reheadered_path),
            str(sanitized_path),
        ]
        subprocess.run(
            reheader_command, check=True, capture_output=True, text=True
        )
        prefiltered_path = Path(temporary_directory) / "small-variants.pre-norm.vcf"
        prefilter_command = [
            bcftools,
            "view",
            "--types",
            "snps,indels,mnps",
            "--output-type",
            "v",
            "--output",
            str(prefiltered_path),
            str(reheadered_path),
        ]
        subprocess.run(
            prefilter_command, check=True, capture_output=True, text=True
        )
        plain_small_variant_path = Path(temporary_directory) / "small-variants.vcf"
        allele_filter_summary = filter_plain_small_variant_records(
            prefiltered_path, plain_small_variant_path
        )
        split_path = Path(temporary_directory) / "split.vcf.gz"
        split_command = [
            bcftools,
            "norm",
            "--fasta-ref",
            str(reference_fasta),
            "--check-ref",
            "e",
            "--multiallelics",
            "-any",
            "--output-type",
            "z",
            "--output",
            str(split_path),
            str(plain_small_variant_path),
        ]
        split_result = subprocess.run(
            split_command, check=True, capture_output=True, text=True
        )

        small_variant_path = Path(temporary_directory) / "small-variants.vcf.gz"
        filter_command = [
            bcftools,
            "view",
            "--types",
            "snps,indels,mnps",
            "--output-type",
            "z",
            "--output",
            str(small_variant_path),
            str(split_path),
        ]
        subprocess.run(filter_command, check=True, capture_output=True, text=True)

        deduplicate_command = [
            bcftools,
            "norm",
            "--rm-dup",
            "exact",
            "--output-type",
            output_type,
            "--output",
            str(output_path),
            str(small_variant_path),
        ]
        deduplicate_result = subprocess.run(
            deduplicate_command, check=True, capture_output=True, text=True
        )

    return NormalizationRun(
        commands=(
            tuple(reheader_command),
            tuple(prefilter_command),
            tuple(split_command),
            tuple(filter_command),
            tuple(deduplicate_command),
        ),
        tool_version=tool_version(bcftools),
        summaries=(
            {},
            allele_filter_summary,
            parse_bcftools_norm_summary(split_result.stderr),
            {},
            parse_bcftools_norm_summary(deduplicate_result.stderr),
        ),
    )


def parse_bcftools_norm_summary(stderr: str) -> dict[str, int]:
    match = re.search(
        r"Lines\s+total/split/realigned/skipped:\s*"
        r"(\d+)/(\d+)/(\d+)/(\d+)",
        stderr,
    )
    if not match:
        return {}
    total, split, realigned, skipped = (int(value) for value in match.groups())
    return {
        "total": total,
        "split": split,
        "realigned": realigned,
        "skipped": skipped,
    }

from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .vcf import sanitize_vcf


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
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_type = "z" if output_path.name.lower().endswith(".gz") else "v"
    with tempfile.TemporaryDirectory(
        prefix=".cure-ngs-normalize-", dir=output_path.parent
    ) as temporary_directory:
        sanitized_path = Path(temporary_directory) / "sanitized.vcf"
        sanitize_vcf(input_path, sanitized_path)
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
            str(sanitized_path),
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
            tuple(split_command),
            tuple(filter_command),
            tuple(deduplicate_command),
        ),
        tool_version=tool_version(bcftools),
        summaries=(
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

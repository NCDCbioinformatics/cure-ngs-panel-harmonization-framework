from __future__ import annotations

import gzip
import re
from pathlib import Path
from typing import Iterable, TextIO

from .models import (
    Assembly,
    AssemblyDetectionError,
    InspectionStatus,
    VcfFormatError,
    VcfInspection,
)


_ASSEMBLY_PATTERNS: dict[Assembly, tuple[re.Pattern[str], ...]] = {
    Assembly.GRCH37: (
        re.compile(
            r"(?<![A-Za-z0-9])(?:grch\s*37|hg\s*19|build[\s_-]*37|b37)"
            r"(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
    ),
    Assembly.GRCH38: (
        re.compile(
            r"(?<![A-Za-z0-9])(?:grch\s*38|hg\s*38|build[\s_-]*38|b38)"
            r"(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
    ),
}

_CHR1_LENGTHS = {
    249_250_621: Assembly.GRCH37,
    248_956_422: Assembly.GRCH38,
}


def _open_text(path: Path) -> TextIO:
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", newline=None)
    return path.open("r", encoding="utf-8-sig", newline=None)


def _assembly_evidence(header_lines: Iterable[str]) -> dict[Assembly, list[str]]:
    evidence: dict[Assembly, list[str]] = {
        Assembly.GRCH37: [],
        Assembly.GRCH38: [],
    }
    for line in header_lines:
        if line.startswith(("##reference=", "##assembly=", "##contig=<")):
            for assembly, patterns in _ASSEMBLY_PATTERNS.items():
                if any(pattern.search(line) for pattern in patterns):
                    evidence[assembly].append(f"header:{line.rstrip()}")

        if line.startswith("##contig=<"):
            assembly_match = re.search(r"(?:^|,)assembly=(?:GRCh)?(37|38)(?:,|>)", line)
            if assembly_match:
                assembly = (
                    Assembly.GRCH37
                    if assembly_match.group(1) == "37"
                    else Assembly.GRCH38
                )
                evidence[assembly].append(f"contig-assembly:{assembly.value}")
            contig_match = re.search(r"(?:^|[,<])ID=(?:chr)?1(?:,|>)", line)
            length_match = re.search(r"(?:^|,)length=(\d+)(?:,|>)", line)
            if contig_match and length_match:
                assembly = _CHR1_LENGTHS.get(int(length_match.group(1)))
                if assembly:
                    evidence[assembly].append(
                        f"contig-1-length:{length_match.group(1)}"
                    )
    return evidence


def detect_assembly(
    header_lines: Iterable[str], *, required: bool = True
) -> tuple[Assembly | None, tuple[str, ...]]:
    evidence = _assembly_evidence(header_lines)
    detected = [assembly for assembly, items in evidence.items() if items]
    if len(detected) > 1:
        details = "; ".join(
            f"{assembly.value}={len(evidence[assembly])}" for assembly in detected
        )
        raise AssemblyDetectionError(f"Conflicting assembly evidence: {details}")
    if not detected:
        if required:
            raise AssemblyDetectionError(
                "Genome assembly could not be determined; supply --assembly explicitly"
            )
        return None, ()
    assembly = detected[0]
    return assembly, tuple(evidence[assembly])


def inspect_vcf(
    path: str | Path,
    *,
    assembly_override: Assembly | None = None,
    require_assembly: bool = True,
) -> VcfInspection:
    vcf_path = Path(path)
    if not vcf_path.is_file():
        raise FileNotFoundError(vcf_path)

    header_lines: list[str] = []
    column_header: list[str] | None = None
    record_count = 0
    alt_count = 0
    multiallelic_count = 0
    symbolic_count = 0

    with _open_text(vcf_path) as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.rstrip("\r\n")
            if line.startswith("##"):
                header_lines.append(line)
                continue
            if line.startswith("#CHROM"):
                if column_header is not None:
                    raise VcfFormatError("VCF contains more than one #CHROM header")
                column_header = line.split("\t")
                if len(column_header) < 8:
                    raise VcfFormatError("#CHROM header has fewer than 8 columns")
                continue
            if not line:
                if column_header is not None:
                    raise VcfFormatError(
                        f"Blank data line at line {line_number} is not valid VCF"
                    )
                continue
            if line.startswith("#"):
                raise VcfFormatError(f"Unexpected header at line {line_number}")
            if column_header is None:
                raise VcfFormatError("Variant record encountered before #CHROM header")

            fields = line.split("\t")
            if len(fields) < 8:
                raise VcfFormatError(
                    f"Variant record at line {line_number} has fewer than 8 columns"
                )
            if len(fields) != len(column_header):
                raise VcfFormatError(
                    f"Column count mismatch at line {line_number}: "
                    f"expected {len(column_header)}, found {len(fields)}"
                )
            try:
                position = int(fields[1])
            except ValueError as exc:
                raise VcfFormatError(
                    f"Invalid POS at line {line_number}: {fields[1]!r}"
                ) from exc
            if position < 1:
                raise VcfFormatError(f"POS must be positive at line {line_number}")
            if not fields[3] or fields[3] == ".":
                raise VcfFormatError(f"Missing REF at line {line_number}")

            alleles = fields[4].split(",")
            if not fields[4] or fields[4] == "." or any(not allele for allele in alleles):
                raise VcfFormatError(f"Missing ALT at line {line_number}")
            record_count += 1
            alt_count += len(alleles)
            multiallelic_count += int(len(alleles) > 1)
            symbolic_count += sum(
                allele.startswith("<")
                or allele == "*"
                or "[" in allele
                or "]" in allele
                for allele in alleles
            )

    if column_header is None:
        raise VcfFormatError("VCF is missing the #CHROM header")

    detected, evidence = detect_assembly(
        header_lines, required=require_assembly and assembly_override is None
    )
    if assembly_override is not None:
        if detected is not None and detected != assembly_override:
            raise AssemblyDetectionError(
                f"--assembly {assembly_override.value} conflicts with detected "
                f"{detected.value}"
            )
        assembly = assembly_override
        evidence = evidence or ("explicit-override",)
    else:
        assembly = detected

    sample_names = tuple(column_header[9:]) if len(column_header) > 9 else ()
    return VcfInspection(
        path=str(vcf_path.resolve()),
        status=(
            InspectionStatus.VALID_EMPTY
            if record_count == 0
            else InspectionStatus.VALID
        ),
        assembly=assembly,
        assembly_evidence=evidence,
        sample_names=sample_names,
        record_count=record_count,
        alternate_allele_count=alt_count,
        multiallelic_record_count=multiallelic_count,
        symbolic_allele_count=symbolic_count,
    )


def sanitize_vcf(input_path: str | Path, output_path: str | Path) -> Path:
    """Write an uncompressed UTF-8 VCF with LF line endings after validation."""
    source = Path(input_path)
    destination = Path(output_path)
    inspect_vcf(source, require_assembly=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _open_text(source) as reader, destination.open(
        "w", encoding="utf-8", newline="\n"
    ) as writer:
        for raw_line in reader:
            writer.write(raw_line.rstrip("\r\n") + "\n")
    return destination


def derive_sample_id(path: str | Path) -> str:
    """Return a full filename-derived sample ID without lossy truncation."""
    name = Path(path).name
    lower = name.lower()
    for suffix in (".vcf.gz", ".g.vcf.gz", ".vcf", ".g.vcf"):
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return Path(name).stem

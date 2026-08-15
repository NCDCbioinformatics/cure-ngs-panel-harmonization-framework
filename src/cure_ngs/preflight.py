from __future__ import annotations

import csv
import gzip
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .fasta import FastaReference
from .models import Assembly
from .runtime import runtime_versions


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _file_check(name: str, value: str | Path | None) -> PreflightCheck:
    if value is None:
        return PreflightCheck(name, "FAIL", "path was not supplied")
    path = Path(value)
    if not path.is_file():
        return PreflightCheck(name, "FAIL", f"file not found: {path}")
    return PreflightCheck(name, "PASS", str(path.resolve()))


def _directory_check(name: str, value: str | Path | None) -> PreflightCheck:
    if value is None:
        return PreflightCheck(name, "FAIL", "path was not supplied")
    path = Path(value)
    if not path.is_dir():
        return PreflightCheck(name, "FAIL", f"directory not found: {path}")
    return PreflightCheck(name, "PASS", str(path.resolve()))


def _tool_check(name: str, versions: dict[str, object]) -> PreflightCheck:
    payload = versions.get(name)
    if not isinstance(payload, dict):
        return PreflightCheck(name, "FAIL", "tool was not reported")
    if payload.get("status") != "available":
        return PreflightCheck(
            name,
            "FAIL",
            str(payload.get("error") or payload.get("executable") or "unavailable"),
        )
    detail = str(payload.get("version") or payload.get("revision") or "available")
    return PreflightCheck(name, "PASS", detail)


def _reference_checks(
    reference_fasta: str | Path | None, *, assembly: Assembly
) -> list[PreflightCheck]:
    base = _file_check("reference_fasta", reference_fasta)
    if base.status == "FAIL":
        return [base]
    assert reference_fasta is not None
    try:
        reference = FastaReference(reference_fasta)
    except (OSError, ValueError) as exc:
        return [base, PreflightCheck("reference_fai", "FAIL", str(exc))]

    checks = [
        base,
        PreflightCheck(
            "reference_fai",
            "PASS",
            str(Path(f"{reference.path}.fai").resolve()),
        ),
    ]
    try:
        chromosome_one = reference.resolve_contig("1")
    except KeyError as exc:
        checks.append(PreflightCheck("reference_assembly", "FAIL", str(exc)))
        return checks

    expected_length = {
        Assembly.GRCH37: 249_250_621,
        Assembly.GRCH38: 248_956_422,
    }[assembly]
    observed_length = reference.entries[chromosome_one].length
    if observed_length == expected_length:
        checks.append(
            PreflightCheck(
                "reference_assembly",
                "PASS",
                f"{assembly.value}; {chromosome_one} length={observed_length}",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                "reference_assembly",
                "FAIL",
                f"declared {assembly.value}, but {chromosome_one} length is "
                f"{observed_length}; expected {expected_length}",
            )
        )
    contig_style = "UCSC chr-prefixed" if chromosome_one.startswith("chr") else "numeric"
    checks.append(PreflightCheck("reference_contig_style", "PASS", contig_style))
    return checks


def _vep_cache_check(
    vep_data: str | Path | None, *, cache_version: int, assembly: Assembly
) -> list[PreflightCheck]:
    base = _directory_check("vep_data", vep_data)
    if base.status == "FAIL":
        return [base]
    assert vep_data is not None
    cache = Path(vep_data) / "homo_sapiens" / f"{cache_version}_{assembly.value}"
    if not cache.is_dir():
        return [
            base,
            PreflightCheck(
                "vep_cache",
                "FAIL",
                f"expected cache directory not found: {cache}",
            ),
        ]
    info = cache / "info.txt"
    detail = str(cache.resolve())
    if info.is_file():
        detail += "; info.txt present"
    return [base, PreflightCheck("vep_cache", "PASS", detail)]


def _reference_dictionary_check(
    reference_fasta: str | Path | None,
) -> PreflightCheck:
    if reference_fasta is None:
        return PreflightCheck("reference_dict", "FAIL", "reference was not supplied")
    reference = Path(reference_fasta)
    dictionary = reference.with_suffix(".dict")
    if not dictionary.is_file():
        return PreflightCheck(
            "reference_dict",
            "FAIL",
            f"Picard sequence dictionary not found: {dictionary}",
        )
    return PreflightCheck("reference_dict", "PASS", str(dictionary.resolve()))


def _hgnc_check(path_value: str | Path | None) -> PreflightCheck:
    base = _file_check("hgnc", path_value)
    if base.status == "FAIL":
        return base
    assert path_value is not None
    try:
        with Path(path_value).open("r", encoding="utf-8-sig", newline="") as handle:
            fields = csv.DictReader(handle, delimiter="\t").fieldnames or []
    except (OSError, UnicodeError) as exc:
        return PreflightCheck("hgnc", "FAIL", str(exc))
    required = {"symbol", "alias_symbol", "prev_symbol"}
    missing = sorted(required - set(fields))
    if missing:
        return PreflightCheck(
            "hgnc", "FAIL", f"missing columns: {', '.join(missing)}"
        )
    return base


def _gtf_check(path_value: str | Path | None) -> PreflightCheck:
    base = _file_check("gtf", path_value)
    if base.status == "FAIL":
        return base
    assert path_value is not None
    opener = gzip.open if str(path_value).lower().endswith(".gz") else open
    try:
        with opener(path_value, "rt", encoding="utf-8-sig") as handle:
            found_gene = False
            for line in handle:
                if line.startswith("#"):
                    continue
                fields = line.rstrip("\r\n").split("\t")
                if len(fields) == 9 and fields[2] == "gene":
                    found_gene = 'gene_id "' in fields[8] and 'gene_name "' in fields[8]
                    break
    except (OSError, UnicodeError) as exc:
        return PreflightCheck("gtf", "FAIL", str(exc))
    if not found_gene:
        return PreflightCheck(
            "gtf", "FAIL", "no gene feature with gene_id and gene_name was found"
        )
    return base


def check_environment(
    *,
    profile: str,
    assembly: Assembly,
    reference_fasta: str | Path | None = None,
    vep_data: str | Path | None = None,
    cache_version: int = 116,
    chain: str | Path | None = None,
    gtf: str | Path | None = None,
    hgnc: str | Path | None = None,
    bcftools: str = "bcftools",
    samtools: str = "samtools",
    vep: str = "vep",
    perl: str = "perl",
    java: str = "java",
    picard_jar: str | Path | None = None,
    vcf2maf: str | Path | None = None,
    versions: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return a machine-readable readiness report for a deployment profile."""

    if cache_version < 1:
        raise ValueError("VEP cache version must be positive")
    supported = {"core", "vcf-to-maf", "liftover", "gene", "all"}
    if profile not in supported:
        raise ValueError(f"Unknown doctor profile: {profile}")

    picard_value = str(picard_jar) if picard_jar else os.environ.get("PICARD_JAR")
    vcf2maf_value = str(vcf2maf) if vcf2maf else os.environ.get("VCF2MAF_PATH")
    observed_versions = versions or runtime_versions(
        bcftools=bcftools,
        samtools=samtools,
        vep=vep,
        perl=perl,
        java=java,
        picard_jar=picard_value,
        vcf2maf=vcf2maf_value,
    )
    checks: list[PreflightCheck] = []
    if profile in {"core", "vcf-to-maf", "liftover", "all"}:
        checks.extend(
            [
                _tool_check("bcftools", observed_versions),
                _tool_check("samtools", observed_versions),
            ]
        )

    if profile in {"vcf-to-maf", "all"}:
        checks.extend(
            [
                _tool_check("vep", observed_versions),
                _tool_check("perl", observed_versions),
                _tool_check("vcf2maf", observed_versions),
            ]
        )
        checks.extend(_reference_checks(reference_fasta, assembly=assembly))
        checks.extend(
            _vep_cache_check(
                vep_data, cache_version=cache_version, assembly=assembly
            )
        )

    if profile in {"liftover", "all"}:
        checks.extend(
            [
                _tool_check("java", observed_versions),
                _tool_check("picard", observed_versions),
                _file_check("liftover_chain", chain),
            ]
        )
        if profile == "liftover":
            checks.extend(_reference_checks(reference_fasta, assembly=assembly))
        checks.append(_reference_dictionary_check(reference_fasta))

    if profile in {"gene", "all"}:
        checks.extend([_gtf_check(gtf), _hgnc_check(hgnc)])

    failed = sum(check.status == "FAIL" for check in checks)
    return {
        "status": "READY" if failed == 0 else "NOT_READY",
        "profile": profile,
        "assembly": assembly.value,
        "failed_checks": failed,
        "checks": [check.to_dict() for check in checks],
        "versions": observed_versions,
    }

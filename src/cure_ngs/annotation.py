from __future__ import annotations

import csv
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from .models import Assembly, InspectionStatus
from .provenance import sha256_file
from .vcf import inspect_vcf


@dataclass(frozen=True)
class AnnotationRun:
    command: tuple[str, ...]
    status: str
    input_records: int
    output_rows: int
    assembly: str
    tumor_id: str
    vcf_tumor_id: str | None
    normal_id: str | None
    vcf_normal_id: str | None
    cache_version: int
    vcf2maf_sha256: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def inspect_maf(path: str | Path) -> tuple[tuple[str, ...], int]:
    maf_path = Path(path)
    if not maf_path.is_file():
        raise FileNotFoundError(maf_path)
    with maf_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(
            (line for line in handle if line.strip() and not line.startswith("#")),
            delimiter="\t",
        )
        try:
            header = tuple(next(reader))
        except StopIteration as exc:
            raise ValueError("MAF has no header") from exc
        required = {
            "NCBI_Build",
            "Chromosome",
            "Start_Position",
            "Reference_Allele",
            "Tumor_Seq_Allele2",
            "Tumor_Sample_Barcode",
        }
        missing = sorted(required - set(header))
        if missing:
            raise ValueError(f"MAF is missing columns: {', '.join(missing)}")
        rows = 0
        for line_number, row in enumerate(reader, start=3):
            if len(row) != len(header):
                raise ValueError(
                    f"MAF column count mismatch at data line {line_number}: "
                    f"expected {len(header)}, found {len(row)}"
                )
            rows += 1
    return header, rows


def _resolve_samples(
    sample_names: tuple[str, ...],
    *,
    tumor_id: str | None,
    vcf_tumor_id: str | None,
    normal_id: str | None,
    vcf_normal_id: str | None,
) -> tuple[str, str | None, str | None, str | None]:
    if vcf_tumor_id is not None and vcf_tumor_id not in sample_names:
        raise ValueError(f"VCF tumor sample {vcf_tumor_id!r} is not in the VCF header")
    if vcf_normal_id is not None and vcf_normal_id not in sample_names:
        raise ValueError(f"VCF normal sample {vcf_normal_id!r} is not in the VCF header")
    if vcf_tumor_id is not None and vcf_tumor_id == vcf_normal_id:
        raise ValueError("Tumor and normal VCF sample IDs must differ")

    if vcf_tumor_id is None:
        if len(sample_names) == 1:
            vcf_tumor_id = sample_names[0]
        elif len(sample_names) > 1:
            raise ValueError(
                "VCF has multiple samples; supply --vcf-tumor-id explicitly"
            )
    resolved_tumor_id = tumor_id or vcf_tumor_id
    if not resolved_tumor_id:
        raise ValueError(
            "Tumor ID is required for a VCF without a genotype sample column"
        )
    resolved_normal_id = normal_id or vcf_normal_id
    if normal_id and not vcf_normal_id:
        raise ValueError("--normal-id requires --vcf-normal-id")
    return resolved_tumor_id, vcf_tumor_id, resolved_normal_id, vcf_normal_id


def annotate_vcf(
    input_path: str | Path,
    output_path: str | Path,
    *,
    reference_fasta: str | Path,
    assembly: Assembly,
    cache_version: int,
    vep_data: str | Path,
    vcf2maf: str | Path | None = None,
    vep_path: str | Path | None = None,
    tumor_id: str | None = None,
    vcf_tumor_id: str | None = None,
    normal_id: str | None = None,
    vcf_normal_id: str | None = None,
    forks: int = 1,
    temporary_directory: str | Path | None = None,
    stdout_log: str | Path | None = None,
    stderr_log: str | Path | None = None,
) -> AnnotationRun:
    if forks < 1:
        raise ValueError("VEP forks must be at least 1")
    input_path = Path(input_path)
    output_path = Path(output_path)
    reference_fasta = Path(reference_fasta)
    vep_data = Path(vep_data)
    vcf2maf_value = vcf2maf or os.environ.get("VCF2MAF_PATH")
    if not vcf2maf_value:
        raise ValueError("vcf2maf path is required")
    vcf2maf_path = Path(vcf2maf_value)
    vep_executable = shutil.which("vep")
    if vep_path is None and vep_executable:
        vep_path = Path(vep_executable).parent
    if vep_path is None:
        raise ValueError("VEP executable directory is required")
    vep_path = Path(vep_path)

    for path in (input_path, reference_fasta, vcf2maf_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    if not vep_data.is_dir():
        raise FileNotFoundError(vep_data)
    if not (vep_path / "vep").is_file():
        raise FileNotFoundError(vep_path / "vep")

    inspection = inspect_vcf(input_path, assembly_override=assembly)
    resolved_tumor_id, resolved_vcf_tumor, resolved_normal_id, resolved_vcf_normal = (
        _resolve_samples(
            inspection.sample_names,
            tumor_id=tumor_id,
            vcf_tumor_id=vcf_tumor_id,
            normal_id=normal_id,
            vcf_normal_id=vcf_normal_id,
        )
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = Path(temporary_directory or output_path.parent / f".{output_path.name}.tmp")
    tmp_path.mkdir(parents=True, exist_ok=True)
    command = [
        "perl",
        str(vcf2maf_path),
        "--input-vcf",
        str(input_path),
        "--output-maf",
        str(output_path),
        "--tumor-id",
        resolved_tumor_id,
        "--vep-path",
        str(vep_path),
        "--vep-data",
        str(vep_data),
        "--ref-fasta",
        str(reference_fasta),
        "--species",
        "homo_sapiens",
        "--ncbi-build",
        assembly.value,
        "--cache-version",
        str(cache_version),
        "--vep-forks",
        str(forks),
        "--tmp-dir",
        str(tmp_path),
    ]
    if resolved_vcf_tumor:
        command.extend(["--vcf-tumor-id", resolved_vcf_tumor])
    if resolved_normal_id and resolved_vcf_normal:
        command.extend(
            [
                "--normal-id",
                resolved_normal_id,
                "--vcf-normal-id",
                resolved_vcf_normal,
            ]
        )

    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if stdout_log is not None:
        stdout_path = Path(stdout_log)
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
    if stderr_log is not None:
        stderr_path = Path(stderr_log)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.write_text(completed.stderr or "", encoding="utf-8")
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(
            completed.returncode,
            command,
            output=completed.stdout,
            stderr=completed.stderr,
        )
    header, output_rows = inspect_maf(output_path)
    if inspection.record_count > 0 and output_rows == 0:
        raise ValueError(
            "Annotation produced zero MAF rows from a non-empty VCF"
        )
    build_index = header.index("NCBI_Build")
    if output_rows:
        with output_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(
                (line for line in handle if line.strip() and not line.startswith("#")),
                delimiter="\t",
            )
            next(reader)
            observed_builds = {row[build_index] for row in reader}
        if observed_builds != {assembly.value}:
            raise ValueError(
                f"Annotated MAF build mismatch: expected {assembly.value}, "
                f"observed {sorted(observed_builds)}"
            )

    return AnnotationRun(
        command=tuple(command),
        status=(
            InspectionStatus.VALID_EMPTY.value
            if inspection.record_count == 0
            else "SUCCESS"
        ),
        input_records=inspection.record_count,
        output_rows=output_rows,
        assembly=assembly.value,
        tumor_id=resolved_tumor_id,
        vcf_tumor_id=resolved_vcf_tumor,
        normal_id=resolved_normal_id,
        vcf_normal_id=resolved_vcf_normal,
        cache_version=cache_version,
        vcf2maf_sha256=sha256_file(vcf2maf_path),
    )


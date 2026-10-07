from __future__ import annotations

import csv
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from functools import lru_cache
from uuid import uuid4

from .models import Assembly, InspectionStatus
from .contig_synonyms import partition_cache_contigs, write_default_vep_config
from .provenance import sha256_file
from .vcf import inspect_vcf


@lru_cache(maxsize=32)
def _vep_major(vep_executable: str) -> int:
    result = subprocess.run([vep_executable, "--help"], check=True, capture_output=True, text=True)
    match = re.search(r"ensembl-vep\s*:\s*(\d+)", result.stdout + result.stderr, re.IGNORECASE)
    if not match:
        raise ValueError("Cannot verify the VEP executable version")
    return int(match.group(1))


def validate_annotation_configuration(vep_path: Path, vcf2maf_path: Path, vep_data: Path, assembly: Assembly, cache_version: int) -> None:
    major = _vep_major(str(vep_path / "vep"))
    if major != cache_version:
        raise ValueError(f"VEP/cache version mismatch: VEP {major}, configured cache {cache_version}. Install the matching {major}_{assembly.value} cache; do not rename an older cache directory.")
    if major >= 114 and " --af_esp" in vcf2maf_path.read_text(encoding="utf-8"):
        raise ValueError("Incompatible vcf2maf: deprecated --af_esp with recent VEP. Use the pinned vcf2maf 1.6.22 or later.")
    info = vep_data / "homo_sapiens" / f"{cache_version}_{assembly.value}" / "info.txt"
    if not info.is_file():
        raise FileNotFoundError(f"VEP cache metadata missing: {info}")
    metadata = dict(line.rstrip("\n").split("\t", 1) for line in info.read_text().splitlines() if "\t" in line)
    if metadata.get("species") != "homo_sapiens" or metadata.get("assembly") != assembly.value:
        raise ValueError(f"VEP cache species/assembly mismatch: {info}")


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
    annotation_input_records: int | None = None
    excluded_contig_records: int = 0
    excluded_contigs_vcf: str | None = None
    contig_exclusion_audit: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def annotation_outputs(output_maf: str | Path, annotation: dict[str, object]) -> dict[str, str | Path]:
    """Include preserved records and accounting in hash-verified manifests."""
    outputs: dict[str, str | Path] = {"annotated_maf": output_maf}
    for key in ("excluded_contigs_vcf", "contig_exclusion_audit"):
        if annotation.get(key):
            outputs[key] = str(annotation[key])
    return outputs


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
    vep_config: str | Path | None = None,
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
    validate_annotation_configuration(vep_path, vcf2maf_path, vep_data, assembly, cache_version)

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
    tmp_root = Path(temporary_directory or output_path.parent / f".{output_path.name}.tmp")
    # vcf2maf may reuse an existing .vep.vcf. Isolate every invocation, including
    # direct annotate-vcf calls and reruns with the same explicit temporary dir.
    tmp_path = tmp_root / f"run-{uuid4().hex}"
    tmp_path.mkdir(parents=True, exist_ok=True)
    annotation_input = input_path
    annotation_input_records = inspection.record_count
    excluded_contig_records = 0
    excluded_contigs_vcf = contig_exclusion_audit = None
    # An explicit custom VEP configuration is passed unchanged. Its annotation
    # sources may not be cache directories, so do not apply the default policy.
    if vep_config is None:
        cache_directory = vep_data / "homo_sapiens" / f"{cache_version}_{assembly.value}"
        vep_config = write_default_vep_config(tmp_path, assembly, cache_directory)
        partition = partition_cache_contigs(input_path, tmp_path,
            cache_directory, assembly, reference_fasta)
        annotation_input = partition.annotation_vcf
        annotation_input_records = partition.eligible_records
        excluded_contig_records = partition.excluded_records
        excluded_contigs_vcf = str(partition.excluded_vcf) if partition.excluded_vcf else None
        contig_exclusion_audit = str(partition.audit)
        if annotation_input_records + excluded_contig_records != inspection.record_count:
            raise ValueError("VCF contig partition failed record accounting")
    command = [
        "perl",
        str(vcf2maf_path),
        "--input-vcf",
        str(annotation_input),
        "--output-maf",
        str(tmp_path / "annotated.maf"),
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
    if vep_config is not None:
        if not Path(vep_config).is_file():
            raise FileNotFoundError(vep_config)
        command.extend(["--vep-config", str(vep_config)])
    if resolved_normal_id and resolved_vcf_normal:
        command.extend(
            [
                "--normal-id",
                resolved_normal_id,
                "--vcf-normal-id",
                resolved_vcf_normal,
            ]
        )

    no_cache_supported = annotation_input_records == 0 and excluded_contig_records > 0
    staged_maf = tmp_path / "annotated.maf"
    if no_cache_supported:
        # Not an annotation success and not a genuinely empty input. Preserve
        # every excluded allele in the sidecar without inventing gene labels.
        staged_maf.write_text("# No variants annotated: see excluded-cache-unsupported-contigs.vcf\n"
            "NCBI_Build\tChromosome\tStart_Position\tReference_Allele\tTumor_Seq_Allele2\tTumor_Sample_Barcode\n", encoding="utf-8")
        completed = subprocess.CompletedProcess(command, 0, "", "No cache-supported variants; no VEP annotation performed\n")
    else:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    stdout_path = Path(stdout_log or tmp_path / "vcf2maf.stdout.log")
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_path.write_text(completed.stdout or "", encoding="utf-8")
    stderr_path = Path(stderr_log or tmp_path / "vcf2maf.stderr.log")
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.write_text(completed.stderr or "", encoding="utf-8")
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(
            completed.returncode,
            command,
            output=completed.stdout,
            stderr=completed.stderr,
        )
    header, output_rows = inspect_maf(staged_maf)
    if output_rows != annotation_input_records:
        raise ValueError(
            f"Annotation record accounting failed: expected {annotation_input_records} MAF rows, "
            f"observed {output_rows}; {excluded_contig_records} records explicitly preserved separately. "
            f"No output published. Inspect VEP warnings and contig/cache compatibility: {stderr_path}"
        )
    build_index = header.index("NCBI_Build")
    if output_rows:
        with staged_maf.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(
                (line for line in handle if line.strip() and not line.startswith("#")),
                delimiter="\t",
            )
            next(reader)
            rows = list(reader)
            observed_builds = {row[build_index] for row in rows}
        if observed_builds != {assembly.value}:
            raise ValueError(
                f"Annotated MAF build mismatch: expected {assembly.value}, "
                f"observed {sorted(observed_builds)}"
            )
        barcode_index = header.index("Tumor_Sample_Barcode")
        observed_barcodes = {row[barcode_index] for row in rows}
        if observed_barcodes != {resolved_tumor_id}:
            raise ValueError(f"Annotated MAF tumor ID mismatch: expected {resolved_tumor_id}, observed {sorted(observed_barcodes)}")

    # Publish only validated MAFs, atomically and on the destination filesystem.
    publish_path = output_path.with_name(f".{output_path.name}.{uuid4().hex}.partial")
    shutil.copyfile(staged_maf, publish_path)
    publish_path.replace(output_path)

    return AnnotationRun(
        command=() if no_cache_supported else tuple(command),
        status=(
            "NO_CACHE_SUPPORTED_VARIANTS" if no_cache_supported else (
                InspectionStatus.VALID_EMPTY.value if inspection.record_count == 0 else "SUCCESS"
            )
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
        annotation_input_records=annotation_input_records,
        excluded_contig_records=excluded_contig_records,
        excluded_contigs_vcf=excluded_contigs_vcf,
        contig_exclusion_audit=contig_exclusion_audit,
    )


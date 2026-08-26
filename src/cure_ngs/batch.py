from __future__ import annotations

import bz2
import csv
import gzip
import json
import lzma
import os
import re
import shutil
import subprocess
import tarfile
import zipfile
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import BinaryIO, Iterable, TextIO

from .annotation import AnnotationRun, annotate_vcf
from .fasta import FastaReference
from .liftover import LiftoverRun, liftover_vcf
from .models import Assembly, AssemblyDetectionError, VcfInspection
from .provenance import write_manifest
from .reference_bundle import ReferenceBundle, ResourceCandidate
from .tools import normalize_vcf
from .vcf import inspect_vcf


MAF_HEADER = (
    "Hugo_Symbol",
    "Entrez_Gene_Id",
    "Center",
    "NCBI_Build",
    "Chromosome",
    "Start_Position",
    "End_Position",
    "Strand",
    "Variant_Classification",
    "Variant_Type",
    "Reference_Allele",
    "Tumor_Seq_Allele1",
    "Tumor_Seq_Allele2",
    "dbSNP_RS",
    "dbSNP_Val_Status",
    "Tumor_Sample_Barcode",
    "Matched_Norm_Sample_Barcode",
)

_NORMAL_WORDS = re.compile(
    r"(?:norm|normal|control|blood|bld|wbc|germ)", re.IGNORECASE
)
_LOG_FIELDS = (
    "datetime_utc",
    "vcf_path",
    "sample_tag",
    "source_assembly",
    "target_assembly",
    "is_gvcf",
    "has_normal",
    "status",
    "message",
    "chosen_reference",
    "chosen_chain",
    "output_maf",
    "manifest",
)
_V133_LOG_FIELDS = (
    "datetime",
    "vcf_path",
    "sample_tag8",
    "ref_info",
    "is_gvcf",
    "has_normal",
    "status",
    "message",
    "final_vcf",
)
_SAMPLE_LOCKS_GUARD = Lock()
_SAMPLE_LOCKS: dict[tuple[str, str], Lock] = {}


def _sample_lock(directory: Path, sample_tag: str) -> Lock:
    key = (str(directory.resolve()), sample_tag)
    with _SAMPLE_LOCKS_GUARD:
        return _SAMPLE_LOCKS.setdefault(key, Lock())


@dataclass(frozen=True)
class V133Workspace:
    """Filesystem contract used by NCDC_batch_vcf2maf_V.1.3.3."""

    root: Path
    input_directory: Path
    log_directory: Path
    maf_directory: Path
    temporary_directory: Path
    manifest_directory: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "root": str(self.root.resolve()),
            "VCF_ALL": str(self.input_directory.resolve()),
            "VCF_ALL_LOG": str(self.log_directory.resolve()),
            "VCF_ALL_MAF": str(self.maf_directory.resolve()),
            "VCF_ALL_TMP": str(self.temporary_directory.resolve()),
            "manifests": str(self.manifest_directory.resolve()),
        }


def prepare_v133_workspace(root: str | Path) -> V133Workspace:
    """Create the four paper/V1.3.3 directories under a portable root."""

    workspace_root = Path(root)
    workspace = V133Workspace(
        root=workspace_root,
        input_directory=workspace_root / "VCF_ALL",
        log_directory=workspace_root / "VCF_ALL_LOG",
        maf_directory=workspace_root / "VCF_ALL_MAF",
        temporary_directory=workspace_root / "VCF_ALL_TMP",
        manifest_directory=workspace_root / "VCF_ALL_LOG" / "manifests",
    )
    for directory in (
        workspace.input_directory,
        workspace.log_directory,
        workspace.maf_directory,
        workspace.temporary_directory,
        workspace.manifest_directory,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return workspace


@dataclass(frozen=True)
class SampleAssignment:
    tumor_id: str
    vcf_tumor_id: str | None
    normal_id: str | None
    vcf_normal_id: str | None

    @property
    def has_normal(self) -> bool:
        return self.vcf_normal_id is not None


@dataclass(frozen=True)
class BatchItemResult:
    input_path: str
    output_maf: str
    manifest: str | None
    status: str
    message: str
    sample_tag: str
    source_assembly: str | None
    target_assembly: str
    is_gvcf: bool
    has_normal: bool
    chosen_reference: str | None
    chosen_chain: str | None
    final_vcf: str | None
    attempts: tuple[dict[str, str], ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class BatchRun:
    status: str
    input_directory: str
    output_directory: str
    total: int
    succeeded: int
    failed: int
    log_tsv: str
    summary_json: str
    items: tuple[BatchItemResult, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _is_vcf_name(name: str) -> bool:
    lower = name.lower()
    return any(
        lower.endswith(suffix)
        for suffix in (
            ".vcf",
            ".vcf.gz",
            ".g.vcf",
            ".g.vcf.gz",
            ".vcf.vep",
            ".vcf.bz2",
            ".vcf.xz",
            ".vcf.zip",
            ".vcf.tar",
            ".vcf.tar.gz",
            ".vcf.tgz",
            ".vcf.7z",
            ".vcf.rar",
        )
    )


def discover_vcf_inputs(directory: str | Path) -> tuple[Path, ...]:
    root = Path(directory)
    if not root.is_dir():
        raise NotADirectoryError(root)
    return tuple(
        sorted(
            (path for path in root.rglob("*") if path.is_file() and _is_vcf_name(path.name)),
            key=lambda path: str(path.relative_to(root)).casefold(),
        )
    )


def safe_output_stem(path: str | Path) -> str:
    name = Path(path).name
    lowered = name.lower()
    for suffix in (
        ".vcf.tar.gz",
        ".g.vcf.gz",
        ".vcf.gz",
        ".vcf.bz2",
        ".vcf.xz",
        ".vcf.zip",
        ".vcf.tar",
        ".vcf.tgz",
        ".vcf.7z",
        ".vcf.rar",
        ".vcf.vep",
        ".g.vcf",
        ".vcf",
    ):
        if lowered.endswith(suffix):
            name = name[: -len(suffix)]
            break
    name = re.sub(r"[\s()]+", "_", name).strip("._")
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name or "sample"


def _read_compressed(path: Path) -> TextIO:
    magic = path.read_bytes()[:6]
    if magic.startswith(b"\x1f\x8b"):
        return gzip.open(path, "rt", encoding="utf-8-sig", errors="strict")
    if magic.startswith(b"BZh"):
        return bz2.open(path, "rt", encoding="utf-8-sig", errors="strict")
    if magic.startswith(b"\xfd7zXZ\x00"):
        return lzma.open(path, "rt", encoding="utf-8-sig", errors="strict")
    return path.open("r", encoding="utf-8-sig", errors="strict")


def _archive_member_name(names: Iterable[str]) -> str:
    candidates = [
        name
        for name in names
        if not name.endswith("/")
        and any(name.lower().endswith(suffix) for suffix in (".vcf", ".vcf.gz"))
    ]
    if not candidates:
        raise ValueError("Archive does not contain a .vcf or .vcf.gz file")
    return sorted(candidates, key=str.casefold)[0]


def _copy_binary_vcf(reader: BinaryIO, output: Path, *, gzipped: bool) -> None:
    if gzipped:
        with gzip.GzipFile(fileobj=reader, mode="rb") as decompressed:
            raw = decompressed.read()
    else:
        raw = reader.read()
    text = raw.decode("utf-8-sig")
    output.write_text(
        "\n".join(text.splitlines()) + ("\n" if text else ""),
        encoding="utf-8",
        newline="\n",
    )


def stage_vcf_input(input_path: str | Path, output_path: str | Path) -> Path:
    """Safely convert a supported text/compressed/archive input to UTF-8/LF VCF."""

    source = Path(input_path)
    output = Path(output_path)
    if not source.is_file():
        raise FileNotFoundError(source)
    output.parent.mkdir(parents=True, exist_ok=True)

    if zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as archive:
            if "[Content_Types].xml" in archive.namelist() and any(
                name.startswith("xl/") for name in archive.namelist()
            ):
                raise ValueError("Spreadsheet input is not a VCF")
            member = _archive_member_name(archive.namelist())
            with archive.open(member) as reader:
                _copy_binary_vcf(reader, output, gzipped=member.lower().endswith(".gz"))
        return output

    if tarfile.is_tarfile(source):
        with tarfile.open(source, mode="r:*") as archive:
            member_name = _archive_member_name(item.name for item in archive.getmembers())
            member = archive.getmember(member_name)
            reader = archive.extractfile(member)
            if reader is None:
                raise ValueError(f"Could not read archive member: {member_name}")
            with reader:
                _copy_binary_vcf(
                    reader, output, gzipped=member_name.lower().endswith(".gz")
                )
        return output

    if source.suffix.lower() in {".7z", ".rar"}:
        seven_zip = shutil.which("7z")
        if seven_zip is None:
            raise ValueError("7z is required to read .7z or .rar VCF archives")
        listing = subprocess.run(
            [seven_zip, "l", "-slt", str(source)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        names = [
            line.removeprefix("Path = ")
            for line in listing.stdout.splitlines()
            if line.startswith("Path = ")
        ][1:]
        member = _archive_member_name(names)
        extracted = subprocess.run(
            [seven_zip, "e", "-so", str(source), member],
            check=True,
            capture_output=True,
        ).stdout
        if member.lower().endswith(".gz"):
            extracted = gzip.decompress(extracted)
        text = extracted.decode("utf-8-sig")
        output.write_text(
            "\n".join(text.splitlines()) + ("\n" if text else ""),
            encoding="utf-8",
            newline="\n",
        )
        return output

    with _read_compressed(source) as reader:
        text = reader.read()
    output.write_text(
        "\n".join(text.splitlines()) + ("\n" if text else ""),
        encoding="utf-8",
        newline="\n",
    )
    return output


def repair_vcf_structure(
    input_path: str | Path, output_path: str | Path, *, fallback_sample: str
) -> Path:
    """Repair the two legacy header defects accepted by V1.3.3."""

    source = Path(input_path)
    destination = Path(output_path)
    lines = source.read_text(encoding="utf-8-sig").splitlines()
    try:
        header_index = next(
            index for index, line in enumerate(lines) if line.startswith("#CHROM")
        )
    except StopIteration as exc:
        raise ValueError("VCF is missing the #CHROM header") from exc
    header = lines[header_index].split("\t")
    data_index = next(
        (
            index
            for index in range(header_index + 1, len(lines))
            if lines[index] and not lines[index].startswith("#")
        ),
        None,
    )
    data_columns = len(lines[data_index].split("\t")) if data_index is not None else len(header)

    gins_layout = len(header) >= 4 and header[2:4] == ["REF", "ALT"]
    if gins_layout:
        header = header[:2] + ["ID"] + header[2:4] + ["QUAL"] + header[4:]
        lines[header_index] = "\t".join(header)
        for index in range(header_index + 1, len(lines)):
            if not lines[index] or lines[index].startswith("#"):
                continue
            fields = lines[index].split("\t")
            if len(fields) < 5:
                raise ValueError(f"Nonstandard VCF record has fewer than 5 columns at line {index + 1}")
            fields[0] = re.sub(r"^chr", "", fields[0], flags=re.IGNORECASE)
            reference = "N" if fields[2] in {".", "<REF>"} else fields[2]
            lines[index] = "\t".join(
                fields[:2] + [".", reference, fields[3], "."] + fields[4:]
            )
    elif data_index is not None and len(header) == 8 and data_columns >= 10:
        lines[header_index] = "\t".join(header + ["FORMAT", fallback_sample])
    elif (
        data_index is not None
        and len(header) == 9
        and header[-1] == "FORMAT"
        and data_columns >= 10
    ):
        lines[header_index] = "\t".join(header + [fallback_sample])

    header_index = next(
        index for index, line in enumerate(lines) if line.startswith("#CHROM")
    )
    _inject_missing_vcf_definitions(lines, header_index)

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return destination


def _inject_missing_vcf_definitions(lines: list[str], header_index: int) -> None:
    """Add conservative declarations for caller-specific tags omitted by vendors."""

    declared_info: set[str] = set()
    declared_format: set[str] = set()
    declared_filter: set[str] = set()
    for line in lines[:header_index]:
        for prefix, target in (
            ("##INFO=<ID=", declared_info),
            ("##FORMAT=<ID=", declared_format),
            ("##FILTER=<ID=", declared_filter),
        ):
            if line.startswith(prefix):
                value = line[len(prefix) :]
                target.add(re.split(r"[,>]", value, maxsplit=1)[0])

    observed_info: dict[str, bool] = {}
    observed_format: set[str] = set()
    observed_filter: set[str] = set()
    for line in lines[header_index + 1 :]:
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) < 8:
            continue
        if fields[6] not in {".", "PASS"}:
            observed_filter.update(item for item in fields[6].split(";") if item)
        if fields[7] != ".":
            for item in fields[7].split(";"):
                if not item:
                    continue
                key, separator, _value = item.partition("=")
                if key:
                    observed_info[key] = observed_info.get(key, False) or bool(separator)
        if len(fields) >= 9 and fields[8] not in {"", "."}:
            observed_format.update(item for item in fields[8].split(":") if item)

    additions: list[str] = []
    for key in sorted(set(observed_info) - declared_info):
        if observed_info[key]:
            additions.append(
                f'##INFO=<ID={key},Number=.,Type=String,'
                'Description="Definition added by CURE-NGS sanitation">'
            )
        else:
            additions.append(
                f'##INFO=<ID={key},Number=0,Type=Flag,'
                'Description="Definition added by CURE-NGS sanitation">'
            )
    for key in sorted(observed_format - declared_format):
        number = "1" if key == "GT" else "."
        additions.append(
            f'##FORMAT=<ID={key},Number={number},Type=String,'
            'Description="Definition added by CURE-NGS sanitation">'
        )
    for key in sorted(observed_filter - declared_filter):
        additions.append(
            f'##FILTER=<ID={key},Description="Definition added by CURE-NGS sanitation">'
        )
    lines[header_index:header_index] = additions


def _contig_style_from_reference(reference: Path) -> str:
    fasta = FastaReference(reference)
    return "ucsc" if any(name.startswith("chr") for name in fasta.entries) else "numeric"


def rewrite_contigs(
    input_path: str | Path, output_path: str | Path, *, style: str
) -> Path:
    if style not in {"ucsc", "numeric"}:
        raise ValueError("contig style must be ucsc or numeric")
    source = Path(input_path)
    destination = Path(output_path)
    output_lines: list[str] = []
    for line in source.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("##contig=<ID="):
            prefix, value = line.split("ID=", maxsplit=1)
            contig, remainder = re.split(r"(?=[,>])", value, maxsplit=1)
            contig = _rewrite_contig_name(contig, style)
            line = f"{prefix}ID={contig}{remainder}"
        elif line and not line.startswith("#"):
            fields = line.split("\t")
            fields[0] = _rewrite_contig_name(fields[0], style)
            line = "\t".join(fields)
        output_lines.append(line)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "\n".join(output_lines) + "\n", encoding="utf-8", newline="\n"
    )
    return destination


def _rewrite_contig_name(name: str, style: str) -> str:
    bare = re.sub(r"^chr", "", name, flags=re.IGNORECASE)
    if style == "ucsc":
        return "chrM" if bare in {"M", "MT"} else f"chr{bare}"
    return "MT" if bare == "M" else bare


def infer_sample_assignment(
    inspection: VcfInspection, *, sample_tag: str
) -> SampleAssignment:
    samples = list(inspection.sample_names)
    if not samples:
        return SampleAssignment(sample_tag, None, None, None)
    if len(samples) == 1:
        return SampleAssignment(sample_tag, samples[0], None, None)
    first, second = samples[:2]
    if _NORMAL_WORDS.search(first):
        tumor, normal = second, first
    elif _NORMAL_WORDS.search(second):
        tumor, normal = first, second
    else:
        tumor, normal = first, second
    return SampleAssignment(sample_tag, tumor, f"{sample_tag}_N", normal)


def looks_like_gvcf(path: str | Path) -> bool:
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if "<NON_REF>" in line or "GVCF" in line.upper():
                return True
    return False


def extract_small_variants(
    input_path: str | Path,
    output_path: str | Path,
    *,
    bcftools: str = "bcftools",
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split a gVCF and retain only SNV/MNV/indel alleles before liftover."""

    source = Path(input_path)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    split = destination.with_name(f".{destination.name}.split.vcf")
    split_command = (
        bcftools,
        "norm",
        "--multiallelics",
        "-any",
        "--output-type",
        "v",
        "--output",
        str(split),
        str(source),
    )
    filter_command = (
        bcftools,
        "view",
        "--types",
        "snps,indels,mnps",
        "--output-type",
        "v",
        "--output",
        str(destination),
        str(split),
    )
    try:
        subprocess.run(split_command, check=True, capture_output=True, text=True)
        subprocess.run(filter_command, check=True, capture_output=True, text=True)
    finally:
        _remove_if_present(split)
    return split_command, filter_command


def write_empty_maf(path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t", lineterminator="\n").writerow(MAF_HEADER)
    return output


def normalize_maf_contigs(path: str | Path, *, style: str) -> Path:
    """Normalize the MAF Chromosome column without changing annotation fields."""

    if style not in {"ucsc", "numeric"}:
        raise ValueError("MAF contig style must be ucsc or numeric")
    maf = Path(path)
    lines = maf.read_text(encoding="utf-8-sig").splitlines()
    header_index = next(
        (index for index, line in enumerate(lines) if line and not line.startswith("#")),
        None,
    )
    if header_index is None:
        raise ValueError("MAF has no header")
    header = lines[header_index].split("\t")
    try:
        chromosome_index = header.index("Chromosome")
    except ValueError as exc:
        raise ValueError("MAF is missing the Chromosome column") from exc
    for index in range(header_index + 1, len(lines)):
        if not lines[index] or lines[index].startswith("#"):
            continue
        fields = lines[index].split("\t")
        if len(fields) != len(header):
            raise ValueError(
                f"MAF column count mismatch at line {index + 1}: "
                f"expected {len(header)}, found {len(fields)}"
            )
        fields[chromosome_index] = _rewrite_contig_name(
            fields[chromosome_index], style
        )
        lines[index] = "\t".join(fields)
    maf.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return maf


def _chain_style(candidate: ResourceCandidate) -> str:
    if candidate.contig_style != "auto":
        return candidate.contig_style
    return "ucsc" if "hg38tohg19" in candidate.path.name.casefold() else "numeric"


def _select_liftover_reference(
    bundle: ReferenceBundle,
    source: Assembly,
    target: Assembly,
    chain: ResourceCandidate,
) -> ResourceCandidate:
    profile = bundle.liftover_for(source, target)
    candidates = bundle.references_for(target)
    requested_label = chain.target_reference_label or profile.target_reference_label
    if requested_label:
        for candidate in candidates:
            if candidate.label == requested_label:
                return candidate
        raise ValueError(
            f"Liftover target reference label {requested_label!r} "
            f"is not configured for {target.value}"
        )
    return candidates[0]


def _remove_if_present(path: Path) -> None:
    if path.is_file():
        path.unlink()


def _error_detail(exc: BaseException) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        output = exc.stderr or exc.stdout
        if output:
            text = str(output).strip()
            if len(text) > 4000:
                text = text[-4000:]
            return f"exit={exc.returncode}: {text}"
    return str(exc)


def _annotate_with_reference_fallback(
    input_vcf: Path,
    output_maf: Path,
    *,
    bundle: ReferenceBundle,
    target_assembly: Assembly,
    sample: SampleAssignment,
    bcftools: str,
    vcf2maf_path: str | Path | None,
    vep_path: str | Path | None,
    forks: int,
    work_directory: Path,
    attempts: list[dict[str, str]],
    sample_tag: str,
    compatibility_tmp_directory: Path | None,
) -> tuple[ResourceCandidate, AnnotationRun, Path]:
    failures: list[str] = []
    for index, candidate in enumerate(bundle.references_for(target_assembly), start=1):
        try:
            style = (
                candidate.contig_style
                if candidate.contig_style != "auto"
                else _contig_style_from_reference(candidate.path)
            )
            adapted = rewrite_contigs(
                input_vcf,
                work_directory / f"reference-{index}.{style}.vcf",
                style=style,
            )
            normalized = work_directory / f"reference-{index}.normalized.vcf"
            normalization = normalize_vcf(
                adapted,
                normalized,
                reference_fasta=candidate.path,
                bcftools=bcftools,
            )
            _remove_if_present(output_maf)
            compatibility_label = re.sub(r"[^A-Za-z0-9._-]", "_", candidate.label)
            if compatibility_tmp_directory is None:
                annotation_tmp = work_directory / f"vcf2maf-{index}"
                stdout_log = None
                stderr_log = None
            else:
                annotation_tmp = compatibility_tmp_directory
                lock_path = compatibility_tmp_directory / (
                    f".lock.{sample_tag}.vcf2maf"
                )
                lock_path.touch(exist_ok=True)
                stdout_log = compatibility_tmp_directory / (
                    f"{sample_tag}.vcf2maf.{compatibility_label}.stdout.log"
                )
                stderr_log = compatibility_tmp_directory / (
                    f"{sample_tag}.vcf2maf.{compatibility_label}.stderr.log"
                )
            with _sample_lock(annotation_tmp, sample_tag):
                annotation = annotate_vcf(
                    normalized,
                    output_maf,
                    reference_fasta=candidate.path,
                    assembly=target_assembly,
                    cache_version=bundle.cache_version,
                    vep_data=bundle.vep_data,
                    vcf2maf=vcf2maf_path,
                    vep_path=vep_path,
                    tumor_id=sample.tumor_id,
                    vcf_tumor_id=sample.vcf_tumor_id,
                    normal_id=sample.normal_id,
                    vcf_normal_id=sample.vcf_normal_id,
                    forks=forks,
                    temporary_directory=annotation_tmp,
                    stdout_log=stdout_log,
                    stderr_log=stderr_log,
                )
            normalize_maf_contigs(
                output_maf, style=bundle.output_contig_style
            )
            attempts.append(
                {
                    "stage": "reference_fallback",
                    "candidate": candidate.label,
                    "status": "SUCCESS",
                    "detail": f"{len(normalization.commands)} normalization commands",
                }
            )
            return candidate, annotation, normalized
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            detail = _error_detail(exc)
            failures.append(f"{candidate.label}: {detail}")
            attempts.append(
                {
                    "stage": "reference_fallback",
                    "candidate": candidate.label,
                    "status": "FAILED",
                    "detail": detail,
                }
            )
    raise ValueError("All FASTA candidates failed: " + " | ".join(failures))


def _process_one(
    input_path: Path,
    output_directory: Path,
    work_root: Path,
    manifest_directory: Path,
    *,
    bundle: ReferenceBundle,
    target_assembly: Assembly,
    sample_tag_length: int,
    source_assembly: Assembly | None,
    picard_jar: str | Path | None,
    java: str,
    bcftools: str,
    vcf2maf_path: str | Path | None,
    vep_path: str | Path | None,
    forks: int,
    overwrite: bool,
    compatibility_tmp_directory: Path | None,
) -> BatchItemResult:
    stem = safe_output_stem(input_path)
    sample_tag = stem[:sample_tag_length]
    output_maf = output_directory / f"{stem}.maf"
    manifest = manifest_directory / f"{stem}.maf.manifest.json"
    work_directory = work_root / f"{stem}.{uuid4().hex[:12]}"
    attempts: list[dict[str, str]] = []
    detected: Assembly | None = None
    is_gvcf = False
    has_normal = False
    chosen_reference: ResourceCandidate | None = None
    chosen_chain: ResourceCandidate | None = None
    final_vcf: Path | None = None
    annotation: AnnotationRun | None = None

    if output_maf.exists() and not overwrite:
        raise FileExistsError(
            f"Output already exists: {output_maf}; pass --overwrite to replace it"
        )
    work_directory.mkdir(parents=True, exist_ok=True)
    manifest_directory.mkdir(parents=True, exist_ok=True)

    try:
        staged = stage_vcf_input(input_path, work_directory / "00.staged.vcf")
        repaired = repair_vcf_structure(
            staged, work_directory / "01.repaired.vcf", fallback_sample=sample_tag
        )
        try:
            inspection = inspect_vcf(repaired, assembly_override=source_assembly)
        except AssemblyDetectionError:
            fallback = source_assembly or bundle.unknown_assembly
            if fallback is None:
                raise
            inspection = inspect_vcf(repaired, assembly_override=fallback)
            attempts.append(
                {
                    "stage": "assembly_detection",
                    "candidate": fallback.value,
                    "status": "FALLBACK",
                    "detail": "VCF had no unambiguous assembly metadata",
                }
            )
        detected = inspection.assembly
        if detected is None:
            raise ValueError("Source assembly could not be determined")
        is_gvcf = looks_like_gvcf(repaired)
        sample = infer_sample_assignment(inspection, sample_tag=sample_tag)
        has_normal = sample.has_normal

        if inspection.record_count == 0:
            write_empty_maf(output_maf)
            write_manifest(
                manifest,
                command=["cure-ngs", "batch-vcf-to-maf"],
                inputs={"vcf": input_path, "reference_config": bundle.config_path},
                outputs={"annotated_maf": output_maf},
                parameters={
                    "status": "VALID_EMPTY",
                    "source_assembly": detected.value,
                    "target_assembly": target_assembly.value,
                    "sample": asdict(sample),
                },
                tools={"vcf2maf": "not run for empty VCF"},
            )
            return BatchItemResult(
                str(input_path.resolve()),
                str(output_maf.resolve()),
                str(manifest.resolve()),
                "VALID_EMPTY",
                "VCF has no variants; created deterministic header-only MAF",
                sample_tag,
                detected.value,
                target_assembly.value,
                is_gvcf,
                has_normal,
                None,
                None,
                str(input_path.resolve()),
                tuple(attempts),
            )

        target_input = repaired
        if is_gvcf:
            gvcf_output = work_directory / "01.gvcf-small-variants.vcf"
            commands = extract_small_variants(
                repaired, gvcf_output, bcftools=bcftools
            )
            target_input = gvcf_output
            attempts.append(
                {
                    "stage": "gvcf_extraction",
                    "candidate": bcftools,
                    "status": "SUCCESS",
                    "detail": f"executed {len(commands)} commands",
                }
            )
        if (
            detected != target_assembly
            and inspect_vcf(target_input, require_assembly=False).record_count > 0
        ):
            if picard_jar is None:
                raise ValueError(
                    "PICARD_JAR or --picard-jar is required for cross-build input"
                )
            profile = bundle.liftover_for(detected, target_assembly)
            last_empty: Path | None = None
            failures: list[str] = []
            for index, chain in enumerate(profile.chains, start=1):
                try:
                    liftover_reference = _select_liftover_reference(
                        bundle, detected, target_assembly, chain
                    )
                    chain_input = rewrite_contigs(
                        target_input,
                        work_directory / f"02.chain-{index}.vcf",
                        style=_chain_style(chain),
                    )
                    lifted = work_directory / f"02.lifted-{index}.vcf"
                    rejected = work_directory / f"02.rejected-{index}.vcf"
                    run: LiftoverRun = liftover_vcf(
                        chain_input,
                        lifted,
                        rejected_path=rejected,
                        source_assembly=detected,
                        target_assembly=target_assembly,
                        chain_path=chain.path,
                        target_reference=liftover_reference.path,
                        picard_jar=picard_jar,
                        java=java,
                    )
                    attempts.append(
                        {
                            "stage": "chain_fallback",
                            "candidate": chain.label,
                            "status": "SUCCESS",
                            "detail": (
                                f"accepted={run.accepted_records}; "
                                f"rejected={run.rejected_records}"
                            ),
                        }
                    )
                    chosen_chain = chain
                    target_input = lifted
                    break
                except (OSError, ValueError, subprocess.CalledProcessError) as exc:
                    detail = _error_detail(exc)
                    failures.append(f"{chain.label}: {detail}")
                    attempts.append(
                        {
                            "stage": "chain_fallback",
                            "candidate": chain.label,
                            "status": "FAILED",
                            "detail": detail,
                        }
                    )
                    candidate_output = work_directory / f"02.lifted-{index}.vcf"
                    if candidate_output.is_file():
                        try:
                            if inspect_vcf(
                                candidate_output, require_assembly=False
                            ).record_count == 0:
                                last_empty = candidate_output
                        except (OSError, ValueError):
                            pass
            else:
                if bundle.allow_all_rejected_empty and last_empty is not None:
                    target_input = last_empty
                else:
                    raise ValueError(
                        "All liftover chain candidates failed: " + " | ".join(failures)
                    )

        if inspect_vcf(target_input, require_assembly=False).record_count == 0:
            write_empty_maf(output_maf)
            status = (
                "VALID_EMPTY_AFTER_GVCF_FILTER"
                if is_gvcf and chosen_chain is None
                else "VALID_EMPTY_AFTER_LIFTOVER"
            )
        else:
            chosen_reference, annotation, final_vcf = _annotate_with_reference_fallback(
                target_input,
                output_maf,
                bundle=bundle,
                target_assembly=target_assembly,
                sample=sample,
                bcftools=bcftools,
                vcf2maf_path=vcf2maf_path,
                vep_path=vep_path,
                forks=forks,
                work_directory=work_directory,
                attempts=attempts,
                sample_tag=sample_tag,
                compatibility_tmp_directory=compatibility_tmp_directory,
            )
            status = annotation.status

        manifest_inputs: dict[str, str | Path] = {
            "vcf": input_path,
            "reference_config": bundle.config_path,
        }
        write_manifest(
            manifest,
            command=["cure-ngs", "batch-vcf-to-maf"],
            inputs=manifest_inputs,
            outputs={"annotated_maf": output_maf},
            parameters={
                "status": status,
                "source_assembly": detected.value,
                "target_assembly": target_assembly.value,
                "sample": asdict(sample),
                "is_gvcf": is_gvcf,
                "chosen_reference": (
                    chosen_reference.to_dict() if chosen_reference else None
                ),
                "chosen_chain": chosen_chain.to_dict() if chosen_chain else None,
                "final_vcf": str(final_vcf) if final_vcf else str(target_input),
                "attempts": attempts,
                "annotation": annotation.to_dict() if annotation else None,
            },
            tools={
                "vep_cache_version": str(bundle.cache_version),
                **(
                    {"vcf2maf_sha256": annotation.vcf2maf_sha256}
                    if annotation
                    else {}
                ),
            },
        )
        return BatchItemResult(
            str(input_path.resolve()),
            str(output_maf.resolve()),
            str(manifest.resolve()),
            status,
            "completed",
            sample_tag,
            detected.value,
            target_assembly.value,
            is_gvcf,
            has_normal,
            chosen_reference.label if chosen_reference else None,
            chosen_chain.label if chosen_chain else None,
            str(final_vcf.resolve()) if final_vcf else str(target_input.resolve()),
            tuple(attempts),
        )
    except Exception as exc:
        _remove_if_present(output_maf)
        _remove_if_present(manifest)
        return BatchItemResult(
            str(input_path.resolve()),
            str(output_maf.resolve()),
            None,
            "FAILED",
            str(exc),
            sample_tag,
            detected.value if detected else None,
            target_assembly.value,
            is_gvcf,
            has_normal,
            chosen_reference.label if chosen_reference else None,
            chosen_chain.label if chosen_chain else None,
            str(final_vcf.resolve()) if final_vcf else None,
            tuple(attempts),
        )


def _write_log(path: Path, items: Iterable[BatchItemResult]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_LOG_FIELDS, delimiter="\t")
        writer.writeheader()
        for item in items:
            writer.writerow(
                {
                    "datetime_utc": datetime.now(timezone.utc).isoformat(),
                    "vcf_path": item.input_path,
                    "sample_tag": item.sample_tag,
                    "source_assembly": item.source_assembly or "",
                    "target_assembly": item.target_assembly,
                    "is_gvcf": int(item.is_gvcf),
                    "has_normal": int(item.has_normal),
                    "status": item.status,
                    "message": item.message,
                    "chosen_reference": item.chosen_reference or "",
                    "chosen_chain": item.chosen_chain or "",
                    "output_maf": item.output_maf,
                    "manifest": item.manifest or "",
                }
            )


def _v133_ref_info(item: BatchItemResult) -> str:
    if not item.source_assembly:
        return "NA"
    if item.source_assembly == item.target_assembly:
        value = item.source_assembly
    else:
        value = f"{item.source_assembly}\N{RIGHTWARDS ARROW}{item.target_assembly}"
        if item.chosen_chain:
            value += f":{item.chosen_chain}"
    if item.chosen_reference:
        value += f"+{item.chosen_reference}"
    return value


def _write_v133_log(path: Path, items: Iterable[BatchItemResult]) -> None:
    """Write the nine-column TSV displayed in the manuscript workflow figure."""

    write_header = not path.is_file() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_V133_LOG_FIELDS, delimiter="\t")
        if write_header:
            writer.writeheader()
        for item in items:
            valid_empty = item.status.startswith("VALID_EMPTY")
            success = item.status != "FAILED"
            if valid_empty:
                message = "VCF has no variants; created empty MAF header"
            elif success and item.chosen_reference:
                message = f"vcf2maf completed with ref={item.chosen_reference}"
            else:
                message = item.message
            writer.writerow(
                {
                    "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "vcf_path": item.input_path,
                    "sample_tag8": item.sample_tag,
                    "ref_info": _v133_ref_info(item),
                    "is_gvcf": int(item.is_gvcf),
                    "has_normal": int(item.has_normal),
                    "status": "SUCCESS" if success else "FAILED",
                    "message": message,
                    "final_vcf": item.final_vcf or item.input_path,
                }
            )


def batch_vcf_to_maf(
    input_directory: str | Path,
    output_directory: str | Path,
    *,
    bundle: ReferenceBundle,
    target_assembly: Assembly | None = None,
    source_assembly: Assembly | None = None,
    jobs: int = 4,
    sample_tag_length: int = 8,
    picard_jar: str | Path | None = None,
    java: str = "java",
    bcftools: str = "bcftools",
    vcf2maf_path: str | Path | None = None,
    vep_path: str | Path | None = None,
    forks: int = 1,
    work_directory: str | Path | None = None,
    log_directory: str | Path | None = None,
    manifest_directory: str | Path | None = None,
    v133_layout: bool = False,
    overwrite: bool = False,
) -> BatchRun:
    if jobs < 1:
        raise ValueError("jobs must be at least 1")
    if sample_tag_length < 1:
        raise ValueError("sample tag length must be at least 1")
    input_root = Path(input_directory)
    output_root = Path(output_directory)
    output_root.mkdir(parents=True, exist_ok=True)
    log_root = Path(log_directory or output_root)
    log_root.mkdir(parents=True, exist_ok=True)
    manifest_root = Path(manifest_directory or output_root)
    manifest_root.mkdir(parents=True, exist_ok=True)
    compatibility_tmp_directory: Path | None = None
    if v133_layout:
        compatibility_tmp_directory = Path(
            work_directory or output_root.parent / "VCF_ALL_TMP"
        )
        compatibility_tmp_directory.mkdir(parents=True, exist_ok=True)
        work_root = compatibility_tmp_directory / ".cure-ngs-work"
    else:
        work_root = Path(work_directory or output_root / ".cure-ngs-work")
    work_root.mkdir(parents=True, exist_ok=True)
    inputs = discover_vcf_inputs(input_root)
    if not inputs:
        raise ValueError(f"No supported VCF inputs were found under {input_root}")
    selected_target = target_assembly or bundle.target_assembly
    resolved_picard = picard_jar or os.environ.get("PICARD_JAR")

    stems: dict[str, list[Path]] = {}
    for path in inputs:
        stems.setdefault(safe_output_stem(path).casefold(), []).append(path)
    collisions = {key: paths for key, paths in stems.items() if len(paths) > 1}
    if collisions:
        details = "; ".join(
            f"{key}: {', '.join(str(path) for path in paths)}"
            for key, paths in collisions.items()
        )
        raise ValueError(f"Output filename collision after sanitization: {details}")

    kwargs = {
        "bundle": bundle,
        "target_assembly": selected_target,
        "sample_tag_length": sample_tag_length,
        "source_assembly": source_assembly,
        "picard_jar": resolved_picard,
        "java": java,
        "bcftools": bcftools,
        "vcf2maf_path": vcf2maf_path,
        "vep_path": vep_path,
        "forks": forks,
        "overwrite": overwrite,
        "compatibility_tmp_directory": compatibility_tmp_directory,
    }
    results: list[BatchItemResult] = []
    if jobs == 1:
        results = [
            _process_one(
                path, output_root, work_root, manifest_root, **kwargs
            )
            for path in inputs
        ]
    else:
        with ThreadPoolExecutor(max_workers=jobs) as executor:
            futures = {
                executor.submit(
                    _process_one,
                    path,
                    output_root,
                    work_root,
                    manifest_root,
                    **kwargs,
                ): path
                for path in inputs
            }
            results = [future.result() for future in as_completed(futures)]
        results.sort(key=lambda item: item.input_path.casefold())

    log_path = log_root / "vcf2maf_batch_log.tsv"
    if v133_layout:
        _write_v133_log(log_path, results)
    else:
        _write_log(log_path, results)
    succeeded = sum(item.status != "FAILED" for item in results)
    failed = len(results) - succeeded
    summary_path = log_root / "vcf2maf_batch_summary.json"
    payload = {
        "status": "SUCCESS" if failed == 0 else "COMPLETED_WITH_FAILURES",
        "input_directory": str(input_root.resolve()),
        "output_directory": str(output_root.resolve()),
        "total": len(results),
        "succeeded": succeeded,
        "failed": failed,
        "log_tsv": str(log_path.resolve()),
        "work_directory": str(work_root.resolve()),
        "manifest_directory": str(manifest_root.resolve()),
        "layout": "NCDC_batch_vcf2maf_V.1.3.3" if v133_layout else "portable",
        "items": [item.to_dict() for item in results],
    }
    summary_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return BatchRun(
        payload["status"],
        str(input_root.resolve()),
        str(output_root.resolve()),
        len(results),
        succeeded,
        failed,
        str(log_path.resolve()),
        str(summary_path.resolve()),
        tuple(results),
    )

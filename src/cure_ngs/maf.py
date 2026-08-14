from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from .fasta import FastaReference
from .models import Assembly


REQUIRED_MINIMAL_MAF_COLUMNS = (
    "Tumor_Sample_Barcode",
    "Chromosome",
    "Start_Position",
    "End_Position",
    "Reference_Allele",
    "Tumor_Seq_Allele2",
)


@dataclass(frozen=True)
class VcfAlleles:
    chromosome: str
    position: int
    reference: str
    alternate: str
    variant_type: str


@dataclass(frozen=True)
class MafToVcfResult:
    input_rows: int
    output_records: int
    sample_count: int
    variant_type_counts: dict[str, int]
    sample_files: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _validate_allele(value: str, *, field: str) -> str:
    allele = value.strip().upper()
    if not allele:
        raise ValueError(f"{field} is empty")
    if allele != "-" and not re.fullmatch(r"[ACGTN]+", allele):
        raise ValueError(f"{field} contains unsupported bases: {value!r}")
    return allele


def maf_alleles_to_vcf(
    *,
    chromosome: str,
    start: int,
    end: int,
    reference_allele: str,
    tumor_allele: str,
    reference: FastaReference,
) -> VcfAlleles:
    ref = _validate_allele(reference_allele, field="Reference_Allele")
    alt = _validate_allele(tumor_allele, field="Tumor_Seq_Allele2")
    contig = reference.resolve_contig(chromosome)

    if ref == "-" and alt == "-":
        raise ValueError("Reference and tumor alleles cannot both be '-' ")

    if ref == "-":
        if end != start - 1:
            raise ValueError(
                "Insertion coordinates must satisfy End_Position = Start_Position - 1"
            )
        anchor_position = start - 1
        anchor = reference.fetch(contig, anchor_position, anchor_position)
        return VcfAlleles(
            chromosome=contig,
            position=anchor_position,
            reference=anchor,
            alternate=f"{anchor}{alt}",
            variant_type="INS",
        )

    expected_end = start + len(ref) - 1
    if end != expected_end:
        raise ValueError(
            f"Coordinates do not match REF length: expected end {expected_end}, found {end}"
        )
    fasta_ref = reference.fetch(contig, start, end)
    if fasta_ref != ref:
        raise ValueError(
            f"Reference mismatch at {contig}:{start}-{end}: MAF={ref}, FASTA={fasta_ref}"
        )

    if alt == "-":
        anchor_position = start - 1
        anchor = reference.fetch(contig, anchor_position, anchor_position)
        return VcfAlleles(
            chromosome=contig,
            position=anchor_position,
            reference=f"{anchor}{ref}",
            alternate=anchor,
            variant_type="DEL",
        )

    if len(ref) == len(alt) == 1:
        variant_type = "SNV"
    elif len(ref) == len(alt):
        variant_type = "MNV"
    else:
        variant_type = "COMPLEX"
    return VcfAlleles(
        chromosome=contig,
        position=start,
        reference=ref,
        alternate=alt,
        variant_type=variant_type,
    )


def safe_sample_filename(sample_id: str) -> str:
    if not sample_id or any(character in sample_id for character in "\t\r\n"):
        raise ValueError(f"Invalid Tumor_Sample_Barcode: {sample_id!r}")
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", sample_id).strip("._")
    if not filename:
        raise ValueError(f"Sample ID cannot form a safe filename: {sample_id!r}")
    return filename


def minimal_maf_to_vcfs(
    maf_path: str | Path,
    output_directory: str | Path,
    *,
    reference_fasta: str | Path,
    assembly: Assembly,
) -> MafToVcfResult:
    maf_path = Path(maf_path)
    output_directory = Path(output_directory)
    reference = FastaReference(reference_fasta)
    rows_by_sample: dict[str, list[VcfAlleles]] = defaultdict(list)
    sample_filenames: dict[str, str] = {}
    filename_owners: dict[str, str] = {}
    variant_type_counts: Counter[str] = Counter()
    input_rows = 0

    with maf_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(
            (line for line in handle if line.strip() and not line.startswith("#")),
            delimiter="\t",
        )
        if reader.fieldnames is None:
            raise ValueError("Minimal MAF has no header")
        missing = [
            column for column in REQUIRED_MINIMAL_MAF_COLUMNS if column not in reader.fieldnames
        ]
        if missing:
            raise ValueError(f"Minimal MAF is missing columns: {', '.join(missing)}")

        for row_number, row in enumerate(reader, start=2):
            input_rows += 1
            sample_id = (row["Tumor_Sample_Barcode"] or "").strip()
            filename = safe_sample_filename(sample_id)
            previous_owner = filename_owners.setdefault(filename, sample_id)
            if previous_owner != sample_id:
                raise ValueError(
                    f"Sample filename collision: {previous_owner!r} and {sample_id!r} "
                    f"both map to {filename!r}"
                )
            sample_filenames[sample_id] = filename

            row_assembly = (row.get("Reference_Assembly") or "").strip()
            if row_assembly and row_assembly != assembly.value:
                raise ValueError(
                    f"Row {row_number} assembly {row_assembly!r} conflicts with "
                    f"requested {assembly.value}"
                )
            try:
                converted = maf_alleles_to_vcf(
                    chromosome=(row["Chromosome"] or "").strip(),
                    start=int(row["Start_Position"]),
                    end=int(row["End_Position"]),
                    reference_allele=row["Reference_Allele"] or "",
                    tumor_allele=row["Tumor_Seq_Allele2"] or "",
                    reference=reference,
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Minimal MAF row {row_number}: {exc}") from exc
            rows_by_sample[sample_id].append(converted)
            variant_type_counts[converted.variant_type] += 1

    if input_rows == 0:
        raise ValueError("Minimal MAF contains no variant rows")

    output_directory.mkdir(parents=True, exist_ok=True)
    sample_files: dict[str, str] = {}
    for sample_id in sorted(rows_by_sample):
        filename = f"{sample_filenames[sample_id]}.from_minimal_maf.vcf"
        output_path = output_directory / filename
        variants = rows_by_sample[sample_id]
        contigs = sorted({variant.chromosome for variant in variants})
        with output_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write("##fileformat=VCFv4.2\n")
            handle.write("##source=cure-ngs-harmonizer\n")
            handle.write(f"##reference={assembly.value}\n")
            for contig in contigs:
                handle.write(
                    f"##contig=<ID={contig},length={reference.entries[contig].length}>\n"
                )
            handle.write(
                "##FORMAT=<ID=GT,Number=1,Type=String,Description=\"Genotype\">\n"
            )
            handle.write(
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t"
                f"{sample_id}\n"
            )
            for variant in variants:
                handle.write(
                    f"{variant.chromosome}\t{variant.position}\t.\t"
                    f"{variant.reference}\t{variant.alternate}\t.\tPASS\t.\tGT\t0/1\n"
                )
        sample_files[sample_id] = str(output_path.resolve())

    return MafToVcfResult(
        input_rows=input_rows,
        output_records=sum(len(rows) for rows in rows_by_sample.values()),
        sample_count=len(rows_by_sample),
        variant_type_counts=dict(sorted(variant_type_counts.items())),
        sample_files=sample_files,
    )


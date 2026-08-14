from __future__ import annotations

import csv
import json
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from .fasta import FastaReference
from .tools import tool_version


@dataclass(frozen=True, order=True)
class VariantKey:
    sample_id: str
    chromosome: str
    start: int
    end: int
    reference: str
    alternate: str


@dataclass(frozen=True)
class MafCollection:
    paths: tuple[str, ...]
    rows: int
    unique_variants: int
    duplicate_rows: int
    evaluable_rows: int
    ineligible_rows: int
    evaluable_unique_variants: int
    eligibility_columns: tuple[str, ...]
    builds: tuple[str, ...]
    variants: frozenset[VariantKey]
    evaluable_variants: frozenset[VariantKey]


@dataclass(frozen=True)
class ConcordanceRun:
    summary_json: str
    by_sample_tsv: str
    discordant_tsv: str
    reference_rows: int
    query_rows: int
    concordant: int
    reference_only: int
    query_only: int
    evaluable_concordant: int | None
    evaluable_reference_only: int | None
    evaluable_query_only: int | None
    sample_count: int
    reference_canonical_vcf: str | None
    query_canonical_vcf: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _normalize_chromosome(value: str) -> str:
    chromosome = value.strip()
    if chromosome.casefold().startswith("chr"):
        chromosome = chromosome[3:]
    if chromosome.casefold() in {"m", "mt"}:
        return "MT"
    return chromosome


def maf_row_to_vcf_alleles(
    row: dict[str, str], *, reference: FastaReference
) -> tuple[str, int, str, str]:
    chromosome = reference.resolve_contig(row["Chromosome"])
    start = int(row["Start_Position"])
    end = int(row.get("End_Position") or start)
    ref = (row["Reference_Allele"] or "").strip().upper()
    alt = (row["Tumor_Seq_Allele2"] or "").strip().upper()
    if ref == "-":
        if not alt or alt == "-":
            raise ValueError("insertion has no alternate sequence")
        if end == start - 1:
            # Ensembl/HGVS insertion convention: start = end + 1.
            anchor_position = end
        elif end == start + 1:
            # Legacy vcf2maf convention: Start is the original VCF anchor.
            anchor_position = start
        else:
            raise ValueError(
                "insertion coordinates match neither Ensembl nor legacy vcf2maf convention"
            )
        anchor = reference.fetch(chromosome, anchor_position, anchor_position)
        return chromosome, anchor_position, anchor, f"{anchor}{alt}"
    if not ref or not alt:
        raise ValueError("reference or alternate allele is empty")
    expected_end = start + len(ref) - 1
    if end != expected_end:
        raise ValueError(
            f"coordinate span does not match REF length ({start}-{end}, {ref})"
        )
    observed = reference.fetch(chromosome, start, end)
    if observed != ref:
        raise ValueError(
            f"reference mismatch at {chromosome}:{start}-{end}: MAF={ref}, FASTA={observed}"
        )
    if alt == "-":
        if start <= 1:
            raise ValueError("cannot left-anchor a deletion starting at position 1")
        anchor_position = start - 1
        anchor = reference.fetch(chromosome, anchor_position, anchor_position)
        return chromosome, anchor_position, f"{anchor}{ref}", anchor
    return chromosome, start, ref, alt


def _split_maf_alternates(value: str) -> tuple[str, ...]:
    normalized = value.strip().upper().replace(",", "/")
    if "/" not in normalized:
        return (normalized,)
    alleles = tuple(dict.fromkeys(part.strip() for part in normalized.split("/")))
    if not alleles or any(not allele for allele in alleles):
        raise ValueError(f"malformed multi-allelic alternate field: {value!r}")
    return alleles


def load_canonical_maf_collection(
    paths: list[str | Path],
    *,
    reference_fasta: str | Path,
    output_prefix: str | Path,
    bcftools: str = "bcftools",
    require_any_columns: tuple[str, ...] = (),
) -> tuple[MafCollection, dict[str, object]]:
    if not paths:
        raise ValueError("At least one MAF path is required")
    reference = FastaReference(reference_fasta)
    output_prefix = Path(output_prefix)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    pre_normalization = output_prefix.with_suffix(".pre-normalization.vcf")
    normalized = output_prefix.with_suffix(".canonical.vcf")
    id_map_path = output_prefix.with_suffix(".id-map.tsv")
    records: list[tuple[str, str, int, str, str, str, bool, str, int]] = []
    builds: set[str] = set()
    resolved_paths: list[str] = []
    record_number = 0
    source_row_count = 0
    multiallelic_row_count = 0
    for value in paths:
        path = Path(value)
        if not path.is_file():
            raise FileNotFoundError(path)
        resolved_paths.append(str(path.resolve()))
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(
                (line for line in handle if line.strip() and not line.startswith("#")),
                delimiter="\t",
            )
            if reader.fieldnames is None:
                raise ValueError(f"MAF has no header: {path}")
            required = {
                "Tumor_Sample_Barcode",
                "Chromosome",
                "Start_Position",
                "Reference_Allele",
                "Tumor_Seq_Allele2",
            }
            missing = sorted(required - set(reader.fieldnames))
            if missing:
                raise ValueError(f"MAF {path} is missing columns: {', '.join(missing)}")
            missing_eligibility = sorted(
                set(require_any_columns) - set(reader.fieldnames)
            )
            if missing_eligibility:
                raise ValueError(
                    f"MAF {path} is missing eligibility columns: "
                    f"{', '.join(missing_eligibility)}"
                )
            for row_number, row in enumerate(reader, start=2):
                source_row_count += 1
                sample_id = (row["Tumor_Sample_Barcode"] or "").strip()
                if not sample_id:
                    raise ValueError(f"MAF {path} row {row_number} has no sample ID")
                build = (
                    row.get("NCBI_Build") or row.get("Reference_Assembly") or ""
                ).strip()
                if not build:
                    raise ValueError(f"MAF {path} row {row_number} has no genome build")
                builds.add(build)
                evaluable = not require_any_columns or any(
                    (row.get(column) or "").strip()
                    for column in require_any_columns
                )
                try:
                    alternates = _split_maf_alternates(
                        row.get("Tumor_Seq_Allele2") or ""
                    )
                    if len(alternates) > 1:
                        multiallelic_row_count += 1
                    for alternate in alternates:
                        allele_row = dict(row)
                        allele_row["Tumor_Seq_Allele2"] = alternate
                        chromosome, position, ref, alt = maf_row_to_vcf_alleles(
                            allele_row, reference=reference
                        )
                        record_id = f"V{record_number}"
                        records.append(
                            (
                                record_id,
                                chromosome,
                                position,
                                ref,
                                alt,
                                sample_id,
                                evaluable,
                                str(path.resolve()),
                                row_number,
                            )
                        )
                        record_number += 1
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f"MAF {path} row {row_number}: {exc}") from exc

    contigs = sorted({record[1] for record in records})
    with pre_normalization.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("##fileformat=VCFv4.2\n")
        handle.write("##source=cure-ngs-concordance\n")
        for contig in contigs:
            handle.write(
                f"##contig=<ID={contig},length={reference.entries[contig].length}>\n"
            )
        handle.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")
        for record_id, chromosome, position, ref, alt, *_ in records:
            handle.write(
                f"{chromosome}\t{position}\t{record_id}\t{ref}\t{alt}\t.\tPASS\t.\n"
            )
    with id_map_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(
            ["record_id", "sample_id", "evaluable", "source_maf", "source_row"]
        )
        for record_id, _, _, _, _, sample_id, evaluable, source, row_number in records:
            writer.writerow([record_id, sample_id, evaluable, source, row_number])

    command = [
        bcftools,
        "norm",
        "--fasta-ref",
        str(Path(reference_fasta)),
        "--check-ref",
        "e",
        "--multiallelics",
        "-any",
        "--output-type",
        "v",
        "--output",
        str(normalized),
        str(pre_normalization),
    ]
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    record_map = {
        record_id: (sample_id, evaluable)
        for record_id, _, _, _, _, sample_id, evaluable, _, _ in records
    }
    variants: list[VariantKey] = []
    evaluable_variants: list[VariantKey] = []
    seen_ids: set[str] = set()
    with normalized.open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) < 8:
                raise ValueError("Canonical VCF contains a malformed data row")
            chromosome, position_value, record_id, ref, alt = fields[:5]
            if record_id not in record_map:
                raise ValueError(f"Canonical VCF has an unknown record ID: {record_id}")
            sample_id, evaluable = record_map[record_id]
            position = int(position_value)
            variant = VariantKey(
                sample_id,
                _normalize_chromosome(chromosome),
                position,
                position + len(ref) - 1,
                ref.upper(),
                alt.upper(),
            )
            variants.append(variant)
            if evaluable:
                evaluable_variants.append(variant)
            seen_ids.add(record_id)
    if seen_ids != set(record_map):
        raise ValueError(
            f"bcftools normalization lost {len(set(record_map) - seen_ids)} records"
        )
    unique = frozenset(variants)
    evaluable_unique = frozenset(evaluable_variants)
    collection = MafCollection(
        paths=tuple(resolved_paths),
        rows=len(variants),
        unique_variants=len(unique),
        duplicate_rows=len(variants) - len(unique),
        evaluable_rows=len(evaluable_variants),
        ineligible_rows=len(variants) - len(evaluable_variants),
        evaluable_unique_variants=len(evaluable_unique),
        eligibility_columns=require_any_columns,
        builds=tuple(sorted(builds)),
        variants=unique,
        evaluable_variants=evaluable_unique,
    )
    return collection, {
        "command": command,
        "bcftools_version": tool_version(bcftools),
        "stderr": completed.stderr.strip(),
        "source_maf_rows": source_row_count,
        "multiallelic_source_rows_split": multiallelic_row_count,
        "allele_records_before_normalization": len(records),
        "pre_normalization_vcf": str(pre_normalization.resolve()),
        "canonical_vcf": str(normalized.resolve()),
        "id_map_tsv": str(id_map_path.resolve()),
    }


def _read_maf(
    path: Path, *, require_any_columns: tuple[str, ...] = ()
) -> tuple[list[VariantKey], list[VariantKey], set[str]]:
    variants: list[VariantKey] = []
    evaluable_variants: list[VariantKey] = []
    builds: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(
            (line for line in handle if line.strip() and not line.startswith("#")),
            delimiter="\t",
        )
        if reader.fieldnames is None:
            raise ValueError(f"MAF has no header: {path}")
        required = {
            "Tumor_Sample_Barcode",
            "Chromosome",
            "Start_Position",
            "Reference_Allele",
            "Tumor_Seq_Allele2",
        }
        missing = sorted(required - set(reader.fieldnames))
        if missing:
            raise ValueError(f"MAF {path} is missing columns: {', '.join(missing)}")
        missing_eligibility = sorted(set(require_any_columns) - set(reader.fieldnames))
        if missing_eligibility:
            raise ValueError(
                f"MAF {path} is missing eligibility columns: "
                f"{', '.join(missing_eligibility)}"
            )
        for row_number, row in enumerate(reader, start=2):
            try:
                sample_id = (row["Tumor_Sample_Barcode"] or "").strip()
                chromosome = _normalize_chromosome(row["Chromosome"] or "")
                start = int(row["Start_Position"])
                end = int(row.get("End_Position") or start)
                reference = (row["Reference_Allele"] or "").strip().upper()
                alternate = (row["Tumor_Seq_Allele2"] or "").strip().upper()
            except (TypeError, ValueError) as exc:
                raise ValueError(f"MAF {path} row {row_number}: {exc}") from exc
            if not all((sample_id, chromosome, reference, alternate)):
                raise ValueError(f"MAF {path} row {row_number} has an empty key field")
            build = (row.get("NCBI_Build") or row.get("Reference_Assembly") or "").strip()
            if not build:
                raise ValueError(f"MAF {path} row {row_number} has no genome build")
            builds.add(build)
            variant = VariantKey(
                sample_id,
                chromosome,
                start,
                end,
                reference,
                alternate,
            )
            variants.append(variant)
            if not require_any_columns or any(
                (row.get(column) or "").strip() for column in require_any_columns
            ):
                evaluable_variants.append(variant)
    return variants, evaluable_variants, builds


def load_maf_collection(
    paths: list[str | Path], *, require_any_columns: tuple[str, ...] = ()
) -> MafCollection:
    if not paths:
        raise ValueError("At least one MAF path is required")
    all_variants: list[VariantKey] = []
    all_evaluable_variants: list[VariantKey] = []
    builds: set[str] = set()
    resolved_paths: list[str] = []
    for value in paths:
        path = Path(value)
        if not path.is_file():
            raise FileNotFoundError(path)
        variants, evaluable_variants, file_builds = _read_maf(
            path, require_any_columns=require_any_columns
        )
        all_variants.extend(variants)
        all_evaluable_variants.extend(evaluable_variants)
        builds.update(file_builds)
        resolved_paths.append(str(path.resolve()))
    unique = frozenset(all_variants)
    evaluable_unique = frozenset(all_evaluable_variants)
    return MafCollection(
        paths=tuple(resolved_paths),
        rows=len(all_variants),
        unique_variants=len(unique),
        duplicate_rows=len(all_variants) - len(unique),
        evaluable_rows=len(all_evaluable_variants),
        ineligible_rows=len(all_variants) - len(all_evaluable_variants),
        evaluable_unique_variants=len(evaluable_unique),
        eligibility_columns=require_any_columns,
        builds=tuple(sorted(builds)),
        variants=unique,
        evaluable_variants=evaluable_unique,
    )


def _metric_row(
    analysis_set: str,
    sample_id: str,
    reference: set[VariantKey],
    query: set[VariantKey],
) -> dict[str, object]:
    concordant = len(reference & query)
    reference_only = len(reference - query)
    query_only = len(query - reference)
    union = len(reference | query)
    sensitivity = 100 * concordant / len(reference) if reference else None
    ppv = 100 * concordant / len(query) if query else None
    jaccard = 100 * concordant / union if union else None
    denominator = 2 * concordant + reference_only + query_only
    f1 = 100 * 2 * concordant / denominator if denominator else None
    return {
        "analysis_set": analysis_set,
        "sample_id": sample_id,
        "reference_unique": len(reference),
        "query_unique": len(query),
        "concordant": concordant,
        "reference_only": reference_only,
        "query_only": query_only,
        "reference_recovery_percent": round(sensitivity, 2) if sensitivity is not None else "",
        "query_ppv_percent": round(ppv, 2) if ppv is not None else "",
        "exact_set_agreement_percent": round(jaccard, 2) if jaccard is not None else "",
        "f1_percent": round(f1, 2) if f1 is not None else "",
    }


def compare_maf_routes(
    reference_paths: list[str | Path],
    query_paths: list[str | Path],
    output_directory: str | Path,
    *,
    reference_label: str = "direct-vcf",
    query_label: str = "report-hgvs",
    reference_require_any: tuple[str, ...] = (),
    reference_fasta: str | Path | None = None,
    bcftools: str = "bcftools",
) -> ConcordanceRun:
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    canonicalization: dict[str, object] | None = None
    if reference_fasta is not None:
        reference_collection, reference_canonicalization = (
            load_canonical_maf_collection(
                reference_paths,
                reference_fasta=reference_fasta,
                output_prefix=output_directory / "reference",
                bcftools=bcftools,
                require_any_columns=reference_require_any,
            )
        )
        query_collection, query_canonicalization = load_canonical_maf_collection(
            query_paths,
            reference_fasta=reference_fasta,
            output_prefix=output_directory / "query",
            bcftools=bcftools,
        )
        canonicalization = {
            "reference_fasta": str(Path(reference_fasta).resolve()),
            "reference": reference_canonicalization,
            "query": query_canonicalization,
        }
    else:
        reference_collection = load_maf_collection(
            reference_paths, require_any_columns=reference_require_any
        )
        query_collection = load_maf_collection(query_paths)
    if len(reference_collection.builds) != 1:
        raise ValueError(
            f"Reference route contains multiple builds: {reference_collection.builds}"
        )
    if len(query_collection.builds) != 1:
        raise ValueError(f"Query route contains multiple builds: {query_collection.builds}")
    if reference_collection.builds != query_collection.builds:
        raise ValueError(
            "Genome-build mismatch between routes: "
            f"{reference_collection.builds} vs {query_collection.builds}"
        )

    reference = set(reference_collection.variants)
    query = set(query_collection.variants)
    samples = sorted({variant.sample_id for variant in reference | query})
    rows = [
        _metric_row(
            "all-input-variants",
            sample,
            {variant for variant in reference if variant.sample_id == sample},
            {variant for variant in query if variant.sample_id == sample},
        )
        for sample in samples
    ]
    overall = _metric_row("all-input-variants", "ALL", reference, query)
    evaluable_overall: dict[str, object] | None = None
    evaluable_rows: list[dict[str, object]] = []
    if reference_require_any:
        evaluable_reference = set(reference_collection.evaluable_variants)
        evaluable_overall = _metric_row(
            "hgvs-evaluable-subset", "ALL", evaluable_reference, query
        )
        evaluable_rows = [
            _metric_row(
                "hgvs-evaluable-subset",
                sample,
                {
                    variant
                    for variant in evaluable_reference
                    if variant.sample_id == sample
                },
                {variant for variant in query if variant.sample_id == sample},
            )
            for sample in samples
        ]

    summary_path = output_directory / "concordance_summary.json"
    by_sample_path = output_directory / "concordance_by_sample.tsv"
    discordant_path = output_directory / "concordance_discordant.tsv"
    summary = {
        "schema_version": "1.0",
        "unit_of_analysis": "unique sample-aware genomic variant key",
        "variant_key": (
            [
                "Tumor_Sample_Barcode",
                "bcftools-normalized chromosome (chr prefix ignored)",
                "VCF POS",
                "VCF REF",
                "VCF ALT",
            ]
            if canonicalization
            else [
                "Tumor_Sample_Barcode",
                "Chromosome (chr prefix ignored)",
                "Start_Position",
                "End_Position",
                "Reference_Allele",
                "Tumor_Seq_Allele2",
            ]
        ),
        "genome_build": reference_collection.builds[0],
        "reference_label": reference_label,
        "query_label": query_label,
        "reference": {
            "files": list(reference_collection.paths),
            "rows": reference_collection.rows,
            "unique_variants": reference_collection.unique_variants,
            "duplicate_rows": reference_collection.duplicate_rows,
            "eligibility_columns_any_nonempty": list(reference_require_any),
            "evaluable_rows": reference_collection.evaluable_rows,
            "ineligible_rows": reference_collection.ineligible_rows,
            "evaluable_unique_variants": reference_collection.evaluable_unique_variants,
        },
        "query": {
            "files": list(query_collection.paths),
            "rows": query_collection.rows,
            "unique_variants": query_collection.unique_variants,
            "duplicate_rows": query_collection.duplicate_rows,
        },
        "sample_count": len(samples),
        "canonicalization": canonicalization,
        "overall": overall,
        "evaluable_subset": evaluable_overall,
        "definitions": {
            "reference_recovery_percent": "concordant / reference unique variants * 100",
            "query_ppv_percent": "concordant / query unique variants * 100",
            "exact_set_agreement_percent": "intersection / union * 100 (Jaccard)",
            "f1_percent": "2 * concordant / (2 * concordant + reference-only + query-only) * 100",
            "true_negatives": "not defined for a variant-list comparison",
        },
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    fieldnames = list(overall)
    with by_sample_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerow(overall)
        writer.writerows(rows)
        if evaluable_overall is not None:
            writer.writerow(evaluable_overall)
            writer.writerows(evaluable_rows)

    discordant_rows = []
    discordance_sets = [("all-input-variants", reference, query)]
    if reference_require_any:
        discordance_sets.append(
            (
                "hgvs-evaluable-subset",
                set(reference_collection.evaluable_variants),
                query,
            )
        )
    for analysis_set, analysis_reference, analysis_query in discordance_sets:
        for status, variants in (
            ("reference_only", analysis_reference - analysis_query),
            ("query_only", analysis_query - analysis_reference),
        ):
            for variant in sorted(variants):
                discordant_rows.append(
                    {
                        "analysis_set": analysis_set,
                        "status": status,
                        **asdict(variant),
                    }
                )
    with discordant_path.open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "analysis_set",
            "status",
            *asdict(VariantKey("", "", 0, 0, "", "")).keys(),
        ]
        writer = csv.DictWriter(
            handle, fieldnames=fields, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(discordant_rows)

    return ConcordanceRun(
        summary_json=str(summary_path.resolve()),
        by_sample_tsv=str(by_sample_path.resolve()),
        discordant_tsv=str(discordant_path.resolve()),
        reference_rows=reference_collection.rows,
        query_rows=query_collection.rows,
        concordant=int(overall["concordant"]),
        reference_only=int(overall["reference_only"]),
        query_only=int(overall["query_only"]),
        evaluable_concordant=(
            int(evaluable_overall["concordant"])
            if evaluable_overall is not None
            else None
        ),
        evaluable_reference_only=(
            int(evaluable_overall["reference_only"])
            if evaluable_overall is not None
            else None
        ),
        evaluable_query_only=(
            int(evaluable_overall["query_only"])
            if evaluable_overall is not None
            else None
        ),
        sample_count=len(samples),
        reference_canonical_vcf=(
            str(reference_canonicalization["canonical_vcf"])
            if canonicalization is not None
            else None
        ),
        query_canonical_vcf=(
            str(query_canonicalization["canonical_vcf"])
            if canonicalization is not None
            else None
        ),
    )

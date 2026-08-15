from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .annotation import annotate_vcf
from .liftover import liftover_vcf
from .models import Assembly
from .tools import normalize_vcf
from .vcf import inspect_vcf

DEFAULT_TARGET_ASSEMBLY = Assembly.GRCH37


@dataclass(frozen=True)
class VcfToMafRun:
    status: str
    source_assembly: str
    target_assembly: str
    input_records: int
    source_normalized_records: int
    liftover_accepted_records: int | None
    liftover_rejected_records: int | None
    target_normalized_records: int
    output_maf_rows: int
    work_directory: str
    stage_commands: dict[str, list[list[str]]]
    annotation: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def vcf_to_maf(
    input_path: str | Path,
    output_maf: str | Path,
    *,
    source_reference: str | Path,
    target_reference: str | Path | None,
    target_assembly: Assembly = DEFAULT_TARGET_ASSEMBLY,
    source_assembly: Assembly | None = None,
    chain_path: str | Path | None = None,
    picard_jar: str | Path | None = None,
    java: str = "java",
    bcftools: str = "bcftools",
    cache_version: int,
    vep_data: str | Path,
    vcf2maf_path: str | Path | None = None,
    vep_path: str | Path | None = None,
    tumor_id: str | None = None,
    vcf_tumor_id: str | None = None,
    normal_id: str | None = None,
    vcf_normal_id: str | None = None,
    forks: int = 1,
    work_directory: str | Path | None = None,
) -> VcfToMafRun:
    input_path = Path(input_path)
    output_maf = Path(output_maf)
    source_reference = Path(source_reference)
    target_reference = Path(target_reference or source_reference)
    initial = inspect_vcf(input_path, assembly_override=source_assembly)
    if initial.assembly is None:
        raise ValueError("Source assembly is required")
    detected_source = initial.assembly
    if detected_source != target_assembly and (chain_path is None or picard_jar is None):
        raise ValueError(
            "Liftover requires both --chain and --picard-jar when source and "
            "target assemblies differ"
        )

    work_path = Path(work_directory or f"{output_maf}.work")
    work_path.mkdir(parents=True, exist_ok=True)
    source_normalized = work_path / f"01.normalized.{detected_source.value}.vcf.gz"
    source_normalization = normalize_vcf(
        input_path,
        source_normalized,
        reference_fasta=source_reference,
        bcftools=bcftools,
    )
    source_normalized_inspection = inspect_vcf(
        source_normalized, assembly_override=detected_source
    )

    stage_commands: dict[str, list[list[str]]] = {
        "source_normalization": [list(command) for command in source_normalization.commands]
    }
    accepted_records: int | None = None
    rejected_records: int | None = None

    if detected_source != target_assembly:
        assert chain_path is not None and picard_jar is not None
        lifted = work_path / f"02.lifted.{target_assembly.value}.vcf"
        rejected = work_path / "02.liftover.rejected.vcf"
        liftover = liftover_vcf(
            source_normalized,
            lifted,
            rejected_path=rejected,
            source_assembly=detected_source,
            target_assembly=target_assembly,
            chain_path=chain_path,
            target_reference=target_reference,
            picard_jar=picard_jar,
            java=java,
        )
        accepted_records = liftover.accepted_records
        rejected_records = liftover.rejected_records
        stage_commands["liftover"] = [list(liftover.command)]
        target_input = lifted
    else:
        target_input = source_normalized

    target_normalized = work_path / f"03.normalized.{target_assembly.value}.vcf"
    target_normalization = normalize_vcf(
        target_input,
        target_normalized,
        reference_fasta=target_reference,
        bcftools=bcftools,
    )
    stage_commands["target_normalization"] = [
        list(command) for command in target_normalization.commands
    ]
    target_normalized_inspection = inspect_vcf(
        target_normalized, assembly_override=target_assembly
    )

    annotation = annotate_vcf(
        target_normalized,
        output_maf,
        reference_fasta=target_reference,
        assembly=target_assembly,
        cache_version=cache_version,
        vep_data=vep_data,
        vcf2maf=vcf2maf_path,
        vep_path=vep_path,
        tumor_id=tumor_id,
        vcf_tumor_id=vcf_tumor_id,
        normal_id=normal_id,
        vcf_normal_id=vcf_normal_id,
        forks=forks,
        temporary_directory=work_path / "04.vcf2maf",
    )
    stage_commands["annotation"] = [list(annotation.command)]

    return VcfToMafRun(
        status=annotation.status,
        source_assembly=detected_source.value,
        target_assembly=target_assembly.value,
        input_records=initial.record_count,
        source_normalized_records=source_normalized_inspection.record_count,
        liftover_accepted_records=accepted_records,
        liftover_rejected_records=rejected_records,
        target_normalized_records=target_normalized_inspection.record_count,
        output_maf_rows=annotation.output_rows,
        work_directory=str(work_path.resolve()),
        stage_commands=stage_commands,
        annotation=annotation.to_dict(),
    )

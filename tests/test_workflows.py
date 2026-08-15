from inspect import signature
from pathlib import Path

import pytest

from cure_ngs.models import Assembly
from cure_ngs.workflows import DEFAULT_TARGET_ASSEMBLY, vcf_to_maf


def test_python_workflow_defaults_to_grch37() -> None:
    assert DEFAULT_TARGET_ASSEMBLY is Assembly.GRCH37
    assert signature(vcf_to_maf).parameters["target_assembly"].default is Assembly.GRCH37


def test_cross_build_workflow_requires_liftover_assets(tmp_path: Path) -> None:
    vcf = tmp_path / "input.vcf"
    reference = tmp_path / "reference.fa"
    vcf.write_text(
        "##fileformat=VCFv4.2\n"
        "##reference=GRCh37\n"
        "##contig=<ID=1,length=249250621>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n",
        encoding="utf-8",
    )
    reference.write_text(">1\nA\n", encoding="utf-8")

    with pytest.raises(ValueError, match="requires both"):
        vcf_to_maf(
            vcf,
            tmp_path / "output.maf",
            source_reference=reference,
            target_reference=reference,
            source_assembly=Assembly.GRCH37,
            target_assembly=Assembly.GRCH38,
            cache_version=102,
            vep_data=tmp_path,
        )

from pathlib import Path
from unittest.mock import patch

import pytest

from cure_ngs.liftover import liftover_vcf
from cure_ngs.models import Assembly


VCF_HEADER = (
    "##fileformat=VCFv4.2\n"
    "##reference={assembly}\n"
    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
)


def test_liftover_requires_different_assemblies(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must differ"):
        liftover_vcf(
            tmp_path / "input.vcf",
            tmp_path / "output.vcf",
            rejected_path=tmp_path / "rejected.vcf",
            source_assembly=Assembly.GRCH38,
            target_assembly=Assembly.GRCH38,
            chain_path=tmp_path / "chain",
            target_reference=tmp_path / "reference.fa",
            picard_jar=tmp_path / "picard.jar",
        )


def test_all_rejected_is_not_treated_as_valid_empty(tmp_path: Path) -> None:
    input_path = tmp_path / "input.vcf"
    output_path = tmp_path / "output.vcf"
    rejected_path = tmp_path / "rejected.vcf"
    chain = tmp_path / "chain"
    reference = tmp_path / "reference.fa"
    picard = tmp_path / "picard.jar"
    input_path.write_text(
        VCF_HEADER.format(assembly="GRCh37") + "1\t1\t.\tA\tC\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    chain.write_text("chain\n", encoding="utf-8")
    reference.write_text(">1\nA\n", encoding="utf-8")
    picard.write_bytes(b"not-called-in-mock")

    def fake_run(*args: object, **kwargs: object) -> object:
        output_path.write_text(
            VCF_HEADER.format(assembly="GRCh38"), encoding="utf-8"
        )
        rejected_path.write_text(
            VCF_HEADER.format(assembly="GRCh37")
            + "1\t1\t.\tA\tC\t.\tPASS\t.\n",
            encoding="utf-8",
        )
        return object()

    with patch("cure_ngs.liftover.subprocess.run", side_effect=fake_run):
        with pytest.raises(ValueError, match="FAILED_LIFTOVER_ALL_REJECTED"):
            liftover_vcf(
                input_path,
                output_path,
                rejected_path=rejected_path,
                source_assembly=Assembly.GRCH37,
                target_assembly=Assembly.GRCH38,
                chain_path=chain,
                target_reference=reference,
                picard_jar=picard,
            )

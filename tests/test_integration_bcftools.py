import shutil
from pathlib import Path

import pytest

from cure_ngs.models import Assembly
from cure_ngs.tools import normalize_vcf
from cure_ngs.vcf import inspect_vcf


FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("bcftools") is None, reason="bcftools is unavailable")
def test_bcftools_splits_left_aligns_and_deduplicates(tmp_path: Path) -> None:
    reference = tmp_path / "reference.fa"
    reference.write_bytes((FIXTURES / "tiny.grch38.fa").read_bytes())
    Path(f"{reference}.fai").write_bytes(
        (FIXTURES / "tiny.grch38.fa.fai").read_bytes()
    )
    output = tmp_path / "normalized.vcf"

    run = normalize_vcf(
        FIXTURES / "normalize.grch38.vcf",
        output,
        reference_fasta=reference,
    )
    result = inspect_vcf(output, assembly_override=Assembly.GRCH38)
    records = [
        line.split("\t")
        for line in output.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]

    assert run.commands[0][:2] == ("bcftools", "reheader")
    assert run.commands[1][:2] == ("bcftools", "view")
    assert run.commands[2][:2] == ("bcftools", "norm")
    assert run.commands[3][:2] == ("bcftools", "view")
    assert run.commands[4][:2] == ("bcftools", "norm")
    assert run.tool_version.startswith("bcftools ")
    assert result.record_count == 4
    assert result.multiallelic_record_count == 0
    assert sum(fields[1] == "23" and fields[4] == "T" for fields in records) == 1
    assert any(fields[1] != "4" and len(fields[4]) > len(fields[3]) for fields in records)

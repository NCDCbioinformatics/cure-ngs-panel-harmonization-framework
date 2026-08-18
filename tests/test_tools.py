from unittest.mock import patch
from pathlib import Path

from cure_ngs.tools import (
    filter_plain_small_variant_records,
    parse_bcftools_norm_summary,
    tool_version,
)


def test_parse_bcftools_norm_summary() -> None:
    stderr = "Lines   total/split/realigned/skipped: 10/2/3/0\n"

    assert parse_bcftools_norm_summary(stderr) == {
        "total": 10,
        "split": 2,
        "realigned": 3,
        "skipped": 0,
    }


def test_tool_version_uses_first_nonempty_line() -> None:
    with patch("cure_ngs.tools.subprocess.run") as run:
        run.return_value.stdout = "\nThis is perl 5, version 34\n"
        run.return_value.stderr = ""

        assert tool_version("perl") == "This is perl 5, version 34"


def test_plain_small_variant_filter_removes_breakends_and_vendor_alt(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.vcf"
    output = tmp_path / "output.vcf"
    source.write_text(
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t1\t.\tA\tC\t.\tPASS\t.\n"
        "1\t2\t.\tA\t]2:5]A\t.\tPASS\t.\n"
        "1\t3\t.\tA\tA/T\t.\tPASS\t.\n"
        "1\t4\t.\tA\tAT\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    summary = filter_plain_small_variant_records(source, output)

    assert summary == {"kept_records": 2, "removed_unsupported_alleles": 2}
    assert [
        line.split("\t")[1]
        for line in output.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ] == ["1", "4"]

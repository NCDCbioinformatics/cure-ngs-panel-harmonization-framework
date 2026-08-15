from unittest.mock import patch

from cure_ngs.runtime import runtime_versions


def test_versions_report_unavailable_optional_tools() -> None:
    with patch("cure_ngs.runtime.shutil.which", return_value=None):
        result = runtime_versions(
            bcftools="missing-bcftools",
            samtools="missing-samtools",
            vep="missing-vep",
            perl="missing-perl",
            java="missing-java",
        )

    assert result["bcftools"]["status"] == "unavailable"
    assert result["samtools"]["status"] == "unavailable"
    assert result["vep"]["status"] == "unavailable"
    assert result["perl"]["status"] == "unavailable"
    assert result["java"]["status"] == "unavailable"

from unittest.mock import patch

from cure_ngs.tools import parse_bcftools_norm_summary, tool_version


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

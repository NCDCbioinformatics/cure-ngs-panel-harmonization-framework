from cure_ngs.tools import parse_bcftools_norm_summary


def test_parse_bcftools_norm_summary() -> None:
    stderr = "Lines   total/split/realigned/skipped: 10/2/3/0\n"

    assert parse_bcftools_norm_summary(stderr) == {
        "total": 10,
        "split": 2,
        "realigned": 3,
        "skipped": 0,
    }


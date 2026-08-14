import pytest

from cure_ngs.hgvs import normalize_hgvs


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("818g>a", "c.818G>A"),
        ("G818A", "c.818G>A"),
        ("NM_000546.6:C.818g>a", "NM_000546.6:c.818G>A"),
        ("c.76_78del", "c.76_78del"),
    ],
)
def test_coding_hgvs_sanitization(value: str, expected: str) -> None:
    result = normalize_hgvs(value, kind="c")

    assert result.normalized == expected
    assert result.syntax_status == "valid"


@pytest.mark.parametrize(
    "value",
    [
        "n.1685-87C>A",
        "n.1617-3658_1617-3656dup",
        "n.1968_1969insGCTTCTCCTGGCCCAGAGTCTCCAGCTGCCGCC",
    ],
)
def test_noncoding_transcript_hgvs_is_supported(value: str) -> None:
    result = normalize_hgvs(value, kind="n")

    assert result.normalized == value
    assert result.syntax_status == "valid"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("(R273H)", "p.R273H"),
        ("P.R273H", "p.R273H"),
        ("p.(Arg273His)", "p.Arg273His"),
        ("NP_000537.3:p.Arg97ProfsTer23", "NP_000537.3:p.Arg97ProfsTer23"),
    ],
)
def test_protein_hgvs_sanitization(value: str, expected: str) -> None:
    result = normalize_hgvs(value, kind="p")

    assert result.normalized == expected
    assert result.syntax_status == "valid"


def test_invalid_hgvs_is_retained_but_never_claimed_as_valid() -> None:
    result = normalize_hgvs("not-a-variant", kind="c")

    assert result.normalized == "c.not-a-variant"
    assert result.syntax_status == "unvalidated-syntax"


def test_missing_hgvs_stays_missing() -> None:
    result = normalize_hgvs("NA", kind="p")

    assert result.normalized is None
    assert result.syntax_status == "missing"

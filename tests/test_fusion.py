from pathlib import Path

from cure_ngs.fusion import normalize_fusion

from test_gene import _catalog


def test_fusion_preserves_five_to_three_prime_direction(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)

    forward = normalize_fusion("EML4-ALK", catalog)
    reverse = normalize_fusion("ALK::EML4", catalog)

    assert forward.status == "resolved"
    assert forward.normalized == "EML4--ALK"
    assert reverse.normalized == "ALK--EML4"


def test_fusion_handles_hyphenated_gene_and_unicode_dash(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)

    result = normalize_fusion("HLA-DRA\u2013BRAF", catalog)

    assert result.status == "resolved"
    assert result.gene_5prime is not None
    assert result.gene_5prime.matched_symbol == "HLA-DRA"
    assert result.normalized == "HLA-DRA--BRAF"


def test_fusion_does_not_guess_when_hyphen_split_is_ambiguous(tmp_path: Path) -> None:
    result = normalize_fusion("A-B-C", _catalog(tmp_path))

    assert result.status == "ambiguous-split"
    assert result.normalized is None
    assert set(result.candidates) == {"A|B-C", "A-B|C"}

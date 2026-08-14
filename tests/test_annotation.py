from pathlib import Path

import pytest

from cure_ngs.annotation import _resolve_samples, inspect_maf


def test_single_sample_is_used_without_filename_inference() -> None:
    resolved = _resolve_samples(
        ("full_vcf_sample_name",),
        tumor_id=None,
        vcf_tumor_id=None,
        normal_id=None,
        vcf_normal_id=None,
    )

    assert resolved == ("full_vcf_sample_name", "full_vcf_sample_name", None, None)


def test_multisample_vcf_requires_explicit_tumor() -> None:
    with pytest.raises(ValueError, match="multiple samples"):
        _resolve_samples(
            ("sample_a", "sample_b"),
            tumor_id=None,
            vcf_tumor_id=None,
            normal_id=None,
            vcf_normal_id=None,
        )


def test_output_and_vcf_sample_ids_are_separate() -> None:
    resolved = _resolve_samples(
        ("raw_tumor", "raw_normal"),
        tumor_id="database_tumor",
        vcf_tumor_id="raw_tumor",
        normal_id="database_normal",
        vcf_normal_id="raw_normal",
    )

    assert resolved == (
        "database_tumor",
        "raw_tumor",
        "database_normal",
        "raw_normal",
    )


def test_inspect_maf_counts_rows(tmp_path: Path) -> None:
    maf = tmp_path / "output.maf"
    maf.write_text(
        "#version 2.4\n"
        "NCBI_Build\tChromosome\tStart_Position\tReference_Allele\t"
        "Tumor_Seq_Allele2\tTumor_Sample_Barcode\n"
        "GRCh38\t1\t10\tC\tT\tsample\n",
        encoding="utf-8",
    )

    header, rows = inspect_maf(maf)

    assert header[0] == "NCBI_Build"
    assert rows == 1

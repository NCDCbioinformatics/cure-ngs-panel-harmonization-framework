from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_real_annotation_tutorial_persists_vep_download() -> None:
    tutorial = (ROOT / "docs" / "BEGINNER_TUTORIAL.md").read_text(
        encoding="utf-8"
    )
    reference_guide = (ROOT / "docs" / "REFERENCE_DATA.md").read_text(
        encoding="utf-8"
    )

    assert "INSTALL.pl -a cf -s homo_sapiens -y GRCh37 -c /data" in tutorial
    assert "INSTALL.pl -a cf -s homo_sapiens -y GRCh37 -c /data" in reference_guide


def test_real_annotation_tutorial_does_not_mix_toy_and_human_fasta() -> None:
    tutorial = (ROOT / "docs" / "BEGINNER_TUTORIAL.md").read_text(
        encoding="utf-8"
    )
    section = tutorial.split(
        "## 13. Optional: complete real VEP/vcf2maf annotation", maxsplit=1
    )[1]

    assert "annotate-vcf" not in section
    assert "synthetic_sample_001.from_minimal_maf.vcf" not in section
    assert "run_full_annotation_tutorial.sh" in section
    assert "25 non-empty MAF rows" in section

import csv
import json
import shutil
from pathlib import Path

import pytest

from cure_ngs.concordance import (
    _split_maf_alternates,
    compare_maf_routes,
    maf_row_to_vcf_alleles,
)
from cure_ngs.cli import main
from cure_ngs.fasta import FastaReference


HEADER = (
    "Tumor_Sample_Barcode\tChromosome\tStart_Position\tEnd_Position\t"
    "Reference_Allele\tTumor_Seq_Allele2\tReference_Assembly\n"
)


def make_reference(tmp_path: Path) -> Path:
    sequence = "TAAAAACCCCCGGGGGTTTTTACGTACGTACGT"
    reference = tmp_path / "reference.fa"
    reference.write_text(f">chr1\n{sequence}\n", encoding="ascii", newline="\n")
    Path(f"{reference}.fai").write_text(
        f"chr1\t{len(sequence)}\t6\t{len(sequence)}\t{len(sequence) + 1}\n",
        encoding="ascii",
        newline="\n",
    )
    return reference


def test_maf_coordinate_conventions_convert_to_equivalent_vcf_alleles(
    tmp_path: Path,
) -> None:
    reference = FastaReference(make_reference(tmp_path))
    common = {
        "Chromosome": "1",
        "Reference_Allele": "-",
        "Tumor_Seq_Allele2": "A",
    }

    ensembl = maf_row_to_vcf_alleles(
        {**common, "Start_Position": "6", "End_Position": "5"},
        reference=reference,
    )
    legacy_vcf2maf = maf_row_to_vcf_alleles(
        {**common, "Start_Position": "4", "End_Position": "5"},
        reference=reference,
    )
    deletion = maf_row_to_vcf_alleles(
        {
            "Chromosome": "1",
            "Start_Position": "12",
            "End_Position": "13",
            "Reference_Allele": "GG",
            "Tumor_Seq_Allele2": "-",
        },
        reference=reference,
    )

    assert ensembl == ("chr1", 5, "A", "AA")
    assert legacy_vcf2maf == ("chr1", 4, "A", "AA")
    assert deletion == ("chr1", 11, "CGG", "C")


def test_combined_maf_alternates_are_split_to_unique_alleles() -> None:
    assert _split_maf_alternates("A/T") == ("A", "T")
    assert _split_maf_alternates("A,T,A") == ("A", "T")
    with pytest.raises(ValueError, match="malformed multi-allelic"):
        _split_maf_alternates("A/")


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("bcftools") is None, reason="bcftools is unavailable")
def test_canonical_concordance_left_aligns_equivalent_insertions(
    tmp_path: Path,
) -> None:
    reference_fasta = make_reference(tmp_path)
    reference = tmp_path / "reference.maf"
    query = tmp_path / "query.maf"
    reference.write_text(
        HEADER + "sample\t1\t4\t5\t-\tA\tGRCh38\n", encoding="utf-8"
    )
    query.write_text(
        HEADER + "sample\tchr1\t6\t5\t-\tA\tGRCh38\n", encoding="utf-8"
    )

    result = compare_maf_routes(
        [reference],
        [query],
        tmp_path / "canonical-results",
        reference_fasta=reference_fasta,
    )
    summary = json.loads(Path(result.summary_json).read_text(encoding="utf-8"))

    assert result.concordant == 1
    assert summary["overall"]["exact_set_agreement_percent"] == 100.0
    assert summary["canonicalization"]["reference"]["bcftools_version"].startswith(
        "bcftools "
    )
    assert Path(result.reference_canonical_vcf).is_file()
    assert Path(result.query_canonical_vcf).is_file()


def test_concordance_reports_explicit_counts_and_metrics(tmp_path: Path) -> None:
    reference = tmp_path / "reference.maf"
    query = tmp_path / "query.maf"
    reference.write_text(
        HEADER
        + "sample-A\tchr1\t10\t10\tC\tT\tGRCh38\n"
        + "sample-A\tchr1\t10\t10\tC\tT\tGRCh38\n"
        + "sample-A\tchr1\t12\t13\tGG\t-\tGRCh38\n"
        + "sample-B\tchr1\t20\t20\tT\tA\tGRCh38\n",
        encoding="utf-8",
    )
    query.write_text(
        HEADER
        + "sample-A\t1\t10\t10\tC\tT\tGRCh38\n"
        + "sample-A\t1\t15\t15\tG\tA\tGRCh38\n"
        + "sample-B\t1\t20\t20\tT\tA\tGRCh38\n",
        encoding="utf-8",
    )

    result = compare_maf_routes([reference], [query], tmp_path / "results")
    summary = json.loads(Path(result.summary_json).read_text(encoding="utf-8"))

    assert summary["reference"]["rows"] == 4
    assert summary["reference"]["unique_variants"] == 3
    assert summary["reference"]["duplicate_rows"] == 1
    assert summary["overall"]["concordant"] == 2
    assert summary["overall"]["reference_only"] == 1
    assert summary["overall"]["query_only"] == 1
    assert summary["overall"]["exact_set_agreement_percent"] == 50.0
    with Path(result.by_sample_tsv).open("r", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert [row["sample_id"] for row in rows] == ["ALL", "sample-A", "sample-B"]


def test_concordance_separates_hgvs_evaluable_subset(tmp_path: Path) -> None:
    header = HEADER.rstrip("\n") + "\tHGVSc\n"
    reference = tmp_path / "reference.maf"
    query = tmp_path / "query.maf"
    reference.write_text(
        header
        + "sample\t1\t10\t10\tC\tT\tGRCh38\tc.1C>T\n"
        + "sample\t1\t20\t20\tT\tA\tGRCh38\t\n",
        encoding="utf-8",
    )
    query.write_text(
        HEADER
        + "sample\t1\t10\t10\tC\tT\tGRCh38\n"
        + "sample\t1\t30\t30\tA\tG\tGRCh38\n",
        encoding="utf-8",
    )

    result = compare_maf_routes(
        [reference],
        [query],
        tmp_path / "results",
        reference_require_any=("HGVSc",),
    )
    summary = json.loads(Path(result.summary_json).read_text(encoding="utf-8"))

    assert summary["overall"]["reference_recovery_percent"] == 50.0
    assert summary["evaluable_subset"]["reference_recovery_percent"] == 100.0
    assert summary["reference"]["ineligible_rows"] == 1
    with Path(result.discordant_tsv).open("r", encoding="utf-8") as handle:
        discordant_rows = list(csv.DictReader(handle, delimiter="\t"))
    assert {
        (row["analysis_set"], row["status"]) for row in discordant_rows
    } == {
        ("all-input-variants", "reference_only"),
        ("all-input-variants", "query_only"),
        ("hgvs-evaluable-subset", "query_only"),
    }


def test_concordance_rejects_build_mismatch(tmp_path: Path) -> None:
    reference = tmp_path / "reference.maf"
    query = tmp_path / "query.maf"
    reference.write_text(
        HEADER + "sample\t1\t10\t10\tC\tT\tGRCh38\n", encoding="utf-8"
    )
    query.write_text(
        HEADER + "sample\t1\t10\t10\tC\tT\tGRCh37\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Genome-build mismatch"):
        compare_maf_routes([reference], [query], tmp_path / "results")


def test_concordance_cli_writes_manifest(tmp_path: Path, capsys) -> None:
    reference = tmp_path / "reference.maf"
    query = tmp_path / "query.maf"
    reference.write_text(
        HEADER + "sample\t1\t10\t10\tC\tT\tGRCh38\n", encoding="utf-8"
    )
    query.write_text(
        HEADER + "sample\tchr1\t10\t10\tC\tT\tGRCh38\n", encoding="utf-8"
    )
    output = tmp_path / "results"

    exit_code = main(
        [
            "compare-maf-routes",
            str(output),
            "--reference-maf",
            str(reference),
            "--query-maf",
            str(query),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["concordant"] == 1
    assert Path(payload["manifest"]).is_file()

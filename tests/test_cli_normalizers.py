import csv
import json
from pathlib import Path

from cure_ngs.cli import build_parser, main
from cure_ngs.models import Assembly

from test_gene import _catalog


def test_normalize_gene_and_fusion_cli(tmp_path: Path, capsys) -> None:
    _catalog(tmp_path)

    assert main(
        [
            "normalize-gene",
            "P53",
            "--gtf",
            str(tmp_path / "genes.gtf"),
            "--hgnc",
            str(tmp_path / "hgnc.tsv"),
        ]
    ) == 0
    gene_result = json.loads(capsys.readouterr().out)
    assert gene_result["matched_symbol"] == "TP53"

    assert main(
        [
            "normalize-fusion",
            "EML4-ALK",
            "--gtf",
            str(tmp_path / "genes.gtf"),
            "--hgnc",
            str(tmp_path / "hgnc.tsv"),
        ]
    ) == 0
    fusion_result = json.loads(capsys.readouterr().out)
    assert fusion_result["normalized"] == "EML4--ALK"


def test_normalize_hgvs_cli(capsys) -> None:
    assert main(["normalize-hgvs", "G818A", "--kind", "c"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["normalized"] == "c.818G>A"
    assert result["syntax_status"] == "valid"


def test_table_cli_default_delimiter_is_tab() -> None:
    args = build_parser().parse_args(
        ["normalize-hgvs-table", "input.tsv", "output.tsv"]
    )

    assert args.delimiter == "\t"


def test_vcf_to_maf_cli_defaults_to_grch37() -> None:
    args = build_parser().parse_args(
        [
            "vcf-to-maf",
            "input.vcf",
            "output.maf",
            "--source-reference",
            "hg19.fa",
            "--cache-version",
            "116",
            "--vep-data",
            "vep-data",
        ]
    )

    assert args.target_assembly is Assembly.GRCH37


def test_normalize_hgvs_table_cli_uses_requested_csv_delimiter(
    tmp_path: Path, capsys
) -> None:
    source = tmp_path / "input.csv"
    output = tmp_path / "output.csv"
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["sample_id", "HGVSc", "HGVSp", "HGVSp_short"],
            delimiter=",",
        )
        writer.writeheader()
        writer.writerow(
            {
                "sample_id": "full-length-sample-123456789",
                "HGVSc": "818g>a",
                "HGVSp": "(R273H)",
                "HGVSp_short": "P.R273H",
            }
        )

    assert main(
        [
            "normalize-hgvs-table",
            str(source),
            str(output),
            "--delimiter",
            "comma",
        ]
    ) == 0
    result = json.loads(capsys.readouterr().out)

    assert result["rows"] == 1
    assert output.is_file()
    assert Path(result["manifest"]).is_file()
    with output.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=","))
    assert rows[0]["sample_id"] == "full-length-sample-123456789"
    assert rows[0]["HGVSc"] == "c.818G>A"

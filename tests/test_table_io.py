import csv
from pathlib import Path

from cure_ngs.table_io import normalize_hgvs_table, read_table, write_table


def _input_rows() -> list[dict[str, object]]:
    return [
        {
            "sample_id": "institution-A_sample-000000123",
            "HGVSc": "818g>a",
            "HGVSp": "(R273H)",
            "HGVSp_short": "P.R273H",
        },
        {
            "sample_id": "institution-B_sample-000000124",
            "HGVSc": "n.1685-87c>a",
            "HGVSp": "NA",
            "HGVSp_short": "NA",
        },
    ]


def test_csv_separator_regression_and_audit_columns(tmp_path: Path) -> None:
    input_path = tmp_path / "input.csv"
    output_path = tmp_path / "output.csv"
    header = ["sample_id", "HGVSc", "HGVSp", "HGVSp_short"]
    write_table(input_path, header, _input_rows(), delimiter=",")

    summary = normalize_hgvs_table(
        input_path, output_path, delimiter=","
    )

    assert output_path.is_file()
    assert summary == {
        "rows": 2,
        "changed_cells": 4,
        "unvalidated_syntax_cells": 0,
    }
    with output_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=","))
    assert rows[0]["sample_id"] == "institution-A_sample-000000123"
    assert rows[0]["HGVSc"] == "c.818G>A"
    assert rows[0]["HGVSc_before"] == "818g>a"
    assert rows[1]["HGVSc"] == "n.1685-87C>A"
    assert rows[1]["HGVSc_syntax_status"] == "valid"


def test_xlsx_round_trip_preserves_full_sample_ids(tmp_path: Path) -> None:
    input_path = tmp_path / "input.xlsx"
    output_path = tmp_path / "output.xlsx"
    header = ["sample_id", "HGVSc", "HGVSp", "HGVSp_short"]
    write_table(input_path, header, _input_rows())

    normalize_hgvs_table(input_path, output_path)
    output_header, rows = read_table(output_path)

    assert output_header[0] == "sample_id"
    assert rows[0]["sample_id"] == "institution-A_sample-000000123"
    assert rows[0]["HGVSp"] == "p.R273H"

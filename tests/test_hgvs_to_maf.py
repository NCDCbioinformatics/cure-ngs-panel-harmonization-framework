import csv
import json
from datetime import datetime
from pathlib import Path

from cure_ngs.hgvs_to_maf import (
    _build_expression,
    _mappings_from_rest_body,
    hgvs_table_to_minimal_maf,
    parse_vep_hgvs_output,
    prepare_hgvs_tasks,
)
from cure_ngs.models import Assembly

from test_maf import make_reference


def test_build_expression_prefers_valid_coding_and_can_fall_back_to_protein() -> None:
    assert _build_expression(
        gene="PIK3CA", hgvsc="1633g>a", hgvsp="p.E545K", hgvsp_short=None
    ) == ("PIK3CA:c.1633G>A", "")
    assert _build_expression(
        gene="PIK3CA",
        hgvsc="not-valid",
        hgvsp="p.Glu545Lys",
        hgvsp_short=None,
    ) == ("PIK3CA:p.Glu545Lys", "")
    assert _build_expression(
        gene="",
        hgvsc="NM_006218.4:c.1633G>A",
        hgvsp=None,
        hgvsp_short=None,
    ) == ("NM_006218.4:c.1633G>A", "")
    assert _build_expression(
        gene="TERT",
        hgvsc="n.1685-87C>A",
        hgvsp=None,
        hgvsp_short=None,
    ) == ("TERT:n.1685-87C>A", "")


def test_prepare_tasks_reports_missing_identifiers_and_hgvs() -> None:
    tasks, failures = prepare_hgvs_tasks(
        [
            {
                "sample ID": "",
                "Gene": "TP53",
                "HGVSc": "c.818G>A",
                "HGVSp": None,
                "HGVSp_short": None,
            },
            {
                "sample ID": "sample-2",
                "Gene": "TP53",
                "HGVSc": None,
                "HGVSp": None,
                "HGVSp_short": None,
            },
        ]
    )

    assert tasks == []
    assert [row["reason"] for row in failures] == [
        "MISSING_SAMPLE_ID",
        "NO_HGVS_STRING",
    ]


def test_prepare_tasks_rejects_excel_date_corrupted_gene_symbols() -> None:
    tasks, failures = prepare_hgvs_tasks(
        [
            {
                "sample ID": "sample-1",
                "Gene": datetime(2025, 9, 6),
                "HGVSc": "c.528+56A>G",
                "HGVSp": None,
                "HGVSp_short": None,
            },
            {
                "sample ID": "sample-2",
                "Gene": "2025-09-06 00:00:00",
                "HGVSc": "c.528+56A>G",
                "HGVSp": None,
                "HGVSp_short": None,
            },
        ]
    )

    assert tasks == []
    assert [row["reason"] for row in failures] == [
        "SUSPECTED_EXCEL_GENE_DATE",
        "SUSPECTED_EXCEL_GENE_DATE",
    ]


def test_parse_vep_output_validates_reference_and_deduplicates_consequences(
    tmp_path: Path,
) -> None:
    reference = make_reference(tmp_path)
    output = tmp_path / "vep.tsv"
    output.write_text(
        "## ENSEMBL VARIANT EFFECT PREDICTOR\n"
        "#Uploaded_variation\tLocation\tAllele\tREF_ALLELE\n"
        "SNV\t1:10\tT\tC\n"
        "SNV\t1:10\tT\tC\n"
        "INS\t1:12-11\tAA\t-\n"
        "DEL\t1:12-13\t-\tGG\n"
        "AMB\t1:10\tT\tC\n"
        "AMB\t1:10\tG\tC\n"
        "BAD\t1:10\tT\tA\n",
        encoding="utf-8",
    )

    mappings, errors = parse_vep_hgvs_output(
        output, reference_fasta=reference
    )

    assert len(mappings["SNV"]) == 1
    assert next(iter(mappings["INS"])).start == 12
    assert next(iter(mappings["INS"])).end == 11
    assert next(iter(mappings["DEL"])).reference == "GG"
    assert len(mappings["AMB"]) == 2
    assert "reference mismatch" in errors["BAD"][0]


def test_rest_negative_strand_insertion_is_reverse_complemented(
    tmp_path: Path,
) -> None:
    reference = make_reference(tmp_path)
    body = json.dumps(
        [
            {
                "assembly_name": "GRCh38",
                "seq_region_name": "1",
                "start": 6,
                "end": 5,
                "strand": -1,
                "allele_string": "-/T",
            }
        ]
    ).encode("utf-8")

    mappings, errors = _mappings_from_rest_body(
        body,
        assembly=Assembly.GRCH38,
        reference_fasta=reference,
    )

    assert errors == []
    assert len(mappings) == 1
    mapping = next(iter(mappings))
    assert (mapping.start, mapping.end, mapping.reference, mapping.alternate) == (
        6,
        5,
        "-",
        "A",
    )


def test_frozen_rest_route_writes_minimal_maf_and_replays_offline(
    tmp_path: Path, monkeypatch
) -> None:
    reference = make_reference(tmp_path)
    source = tmp_path / "input.tsv"
    source.write_text(
        "sample ID\tGene\tHGVSc\tHGVSp\tHGVSp_short\n"
        "full-sample-identifier-000001\tPIK3CA\tc.1633G>A\t\t\n"
        "full-sample-identifier-000002\tGENE\tc.2A>G\t\t\n",
        encoding="utf-8",
    )
    response_cache = tmp_path / "response-cache"

    def fake_http_get(url: str, *, timeout_seconds: float):
        assert timeout_seconds == 2.0
        if "PIK3CA" in url:
            payload = [
                {
                    "input": "PIK3CA:c.1633G>A",
                    "assembly_name": "GRCh38",
                    "seq_region_name": "1",
                    "start": 10,
                    "end": 10,
                    "allele_string": "C/T",
                }
            ]
        else:
            payload = [
                {
                    "assembly_name": "GRCh38",
                    "seq_region_name": "1",
                    "start": 10,
                    "end": 10,
                    "allele_string": "C/T",
                },
                {
                    "assembly_name": "GRCh38",
                    "seq_region_name": "1",
                    "start": 10,
                    "end": 10,
                    "allele_string": "C/G",
                },
            ]
        return 200, json.dumps(payload).encode("utf-8"), {"ETag": "synthetic"}

    monkeypatch.setattr("cure_ngs.hgvs_to_maf._http_get", fake_http_get)
    output = tmp_path / "minimal.maf"
    failures = tmp_path / "failed.tsv"

    result = hgvs_table_to_minimal_maf(
        source,
        output,
        failure_output=failures,
        reference_fasta=reference,
        assembly=Assembly.GRCH38,
        response_cache=response_cache,
        threads=2,
        retries=0,
        timeout_seconds=2.0,
    )

    assert result.status == "PARTIAL"
    assert result.output_rows == 1
    assert result.failed_rows == 1
    assert result.fetched_responses == 2
    assert result.cache_hits == 0
    with output.open("r", encoding="utf-8", newline="") as handle:
        output_rows = list(csv.DictReader(handle, delimiter="\t"))
    assert output_rows[0]["Tumor_Sample_Barcode"] == "full-sample-identifier-000001"
    assert output_rows[0]["Reference_Assembly"] == "GRCh38"
    with failures.open("r", encoding="utf-8", newline="") as handle:
        failure_rows = list(csv.DictReader(handle, delimiter="\t"))
    assert failure_rows[0]["reason"] == "AMBIGUOUS_MULTIPLE_GENOMIC_VARIANTS"

    def network_must_not_run(*args, **kwargs):
        raise AssertionError("network was used during offline replay")

    monkeypatch.setattr("cure_ngs.hgvs_to_maf._http_get", network_must_not_run)
    replay = hgvs_table_to_minimal_maf(
        source,
        tmp_path / "replay.maf",
        failure_output=tmp_path / "replay.failed.tsv",
        reference_fasta=reference,
        assembly=Assembly.GRCH38,
        response_cache=response_cache,
        offline_replay=True,
        threads=2,
    )
    assert replay.cache_hits == 2
    assert replay.fetched_responses == 0
    assert replay.output_rows == result.output_rows

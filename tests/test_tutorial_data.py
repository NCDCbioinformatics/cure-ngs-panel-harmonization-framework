from __future__ import annotations

from pathlib import Path

import pytest

from cure_ngs.cli import main
from cure_ngs.tutorial_data import (
    export_tutorial_data,
    export_v133_example_workspace,
    verify_tutorial_data,
)


SOURCE = Path(__file__).parents[1] / "examples" / "component-tests"


def test_six_component_bundle_is_complete_and_hash_valid() -> None:
    result = verify_tutorial_data(SOURCE)

    assert result["status"] == "VALID"
    assert result["file_count"] == 11


def test_export_copies_inputs_and_nonempty_reference_mafs(tmp_path: Path) -> None:
    output = tmp_path / "component-test-data"

    result = export_tutorial_data(output, source=SOURCE)

    assert result["status"] == "EXPORTED"
    assert result["components"] == 6
    assert (output / "inputs" / "MSKCC_VCCF_test.zip").is_file()
    assert (output / "LICENSE.MSKCC-vcf2maf.Apache-2.0").is_file()
    assert (output / "inputs" / "hgvs_to_minimal_maf_test.xlsx").is_file()
    assert (output / "expected" / "test_b37.maf").stat().st_size > 0
    maf_lines = [
        line
        for line in (output / "expected" / "test_b37.maf")
        .read_text(encoding="utf-8")
        .splitlines()
        if line and not line.startswith("#")
    ]
    assert len(maf_lines) - 1 == 25

    with pytest.raises(FileExistsError, match="not empty"):
        export_tutorial_data(output, source=SOURCE)


def test_export_tutorial_data_cli(tmp_path: Path) -> None:
    output = tmp_path / "exported"

    status = main(
        ["export-tutorial-data", str(output), "--source", str(SOURCE)]
    )

    assert status == 0
    assert (output / "manifest.json").is_file()


def test_export_v133_example_has_public_input_output_and_paper_tree(
    tmp_path: Path,
) -> None:
    output = tmp_path / "KOSMOS_VCF"

    result = export_v133_example_workspace(output, source=SOURCE)

    assert result["status"] == "REFERENCE_SNAPSHOT"
    assert {path.name for path in output.iterdir()} == {
        "VCF_ALL",
        "VCF_ALL_LOG",
        "VCF_ALL_MAF",
        "VCF_ALL_TMP",
    }
    vcf = output / "VCF_ALL" / "test_b37.vcf"
    maf = output / "VCF_ALL_MAF" / "test_b37.maf"
    assert sum(1 for line in vcf.read_text(encoding="utf-8").splitlines() if not line.startswith("#")) == 25
    maf_rows = [
        line
        for line in maf.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    assert len(maf_rows) - 1 == 25
    log_lines = (
        output / "VCF_ALL_LOG" / "vcf2maf_batch_log.tsv"
    ).read_text(encoding="utf-8").splitlines()
    assert log_lines[0].startswith("datetime\tvcf_path\tsample_tag8\tref_info")
    assert "REFERENCE_OUTPUT" in log_lines[1]
    assert (output / "VCF_ALL_LOG" / "reference-output.json").is_file()

    with pytest.raises(FileExistsError, match="already exist"):
        export_v133_example_workspace(output, source=SOURCE)


def test_export_v133_example_cli(tmp_path: Path) -> None:
    output = tmp_path / "KOSMOS_VCF"

    status = main(
        ["export-v1.3.3-example", str(output), "--source", str(SOURCE)]
    )

    assert status == 0
    assert (output / "VCF_ALL" / "test_b37.vcf").is_file()
    assert (output / "VCF_ALL_MAF" / "test_b37.maf").is_file()

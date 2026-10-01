import json
from pathlib import Path
import shutil
from unittest.mock import patch

import pytest

from cure_ngs.cli import main
from cure_ngs.self_test import run_self_test

CORE_VERSIONS = {
    "bcftools": {"status": "available", "version": "bcftools 1.13"},
    "samtools": {"status": "available", "version": "samtools 1.13"},
}


def test_self_test_invalid_profile(tmp_path):
    with pytest.raises(ValueError, match="core or full"):
        run_self_test(tmp_path, profile="unknown")


def test_self_test_failure_is_reported_not_passed(tmp_path):
    with patch("cure_ngs.self_test.runtime_versions", return_value=CORE_VERSIONS), patch(
        "cure_ngs.self_test.verify_tutorial_data", side_effect=ValueError("fixture checksum mismatch")
    ):
        report = run_self_test(tmp_path, profile="core")
    assert report["status"] == "FAILED"
    assert "checksum mismatch" in report["error"]
    assert json.loads((Path(report["output"]) / "self-test-report.json").read_text())["status"] == "FAILED"


def test_full_self_test_requires_actual_full_image_tools(tmp_path):
    versions = {**CORE_VERSIONS, "picard": {"status": "unavailable"}}
    with patch("cure_ngs.self_test.runtime_versions", return_value=versions):
        report = run_self_test(tmp_path)
    assert report["status"] == "FAILED"
    assert "picard" in report["error"]


@pytest.mark.parametrize("status,expected", [("PASS", 0), ("FAILED", 2)])
def test_self_test_cli_exit_status(tmp_path, status, expected, capsys):
    with patch("cure_ngs.self_test.run_self_test", return_value={"status": status}):
        assert main(["self-test", str(tmp_path), "--profile", "core"]) == expected
    assert json.loads(capsys.readouterr().out)["status"] == status


@pytest.mark.skipif(not shutil.which("bcftools") or not shutil.which("samtools"), reason="real tools not installed")
def test_core_self_test_executes_and_keeps_each_rerun(tmp_path):
    report = run_self_test(tmp_path, profile="core")
    assert report["status"] == "PASS", report
    assert "NOT_TESTED" in report["annotation"]
    output = Path(report["output"])
    assert (output / "NGS_VCF/VCF_ALL/test_b37.vcf").is_file()
    assert (output / "from-hgvs.maf").is_file()
    second = run_self_test(tmp_path, profile="core")
    assert second["status"] == "PASS", second
    assert second["output"] != report["output"]
    assert (output / "self-test-report.json").is_file()

from pathlib import Path

from cure_ngs.models import Assembly
from cure_ngs.preflight import check_environment


def available_versions() -> dict[str, object]:
    return {
        name: {"status": "available", "version": "test"}
        for name in (
            "bcftools",
            "samtools",
            "vep",
            "perl",
            "java",
            "picard",
            "vcf2maf",
        )
    }


def test_core_preflight_reports_ready_with_core_tools() -> None:
    report = check_environment(
        profile="core",
        assembly=Assembly.GRCH37,
        versions=available_versions(),
    )

    assert report["status"] == "READY"
    assert report["failed_checks"] == 0


def test_vcf_to_maf_preflight_reports_actionable_missing_resources() -> None:
    report = check_environment(
        profile="vcf-to-maf",
        assembly=Assembly.GRCH37,
        versions=available_versions(),
    )

    assert report["status"] == "NOT_READY"
    checks = {item["name"]: item for item in report["checks"]}
    assert checks["reference_fasta"]["status"] == "FAIL"
    assert checks["vep_data"]["status"] == "FAIL"


def test_gene_preflight_validates_fixture_headers(tmp_path: Path) -> None:
    gtf = tmp_path / "genes.gtf"
    gtf.write_text(
        '1\ttest\tgene\t1\t10\t.\t+\t.\tgene_id "ENSG1"; gene_name "TP53";\n',
        encoding="utf-8",
    )
    hgnc = tmp_path / "hgnc.tsv"
    hgnc.write_text(
        "symbol\talias_symbol\tprev_symbol\nTP53\tP53\tTRP53\n",
        encoding="utf-8",
    )

    report = check_environment(
        profile="gene",
        assembly=Assembly.GRCH37,
        gtf=gtf,
        hgnc=hgnc,
        versions=available_versions(),
    )

    assert report["status"] == "READY"

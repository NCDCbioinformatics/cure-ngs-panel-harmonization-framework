import gzip
import json
import shutil
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from cure_ngs.annotation import AnnotationRun
from cure_ngs.batch import (
    batch_vcf_to_maf,
    discover_vcf_inputs,
    infer_sample_assignment,
    normalize_maf_contigs,
    prepare_v133_workspace,
    repair_vcf_structure,
    rewrite_contigs,
    safe_output_stem,
    stage_vcf_input,
)
from cure_ngs.models import Assembly
from cure_ngs.reference_bundle import load_reference_bundle
from cure_ngs.tools import NormalizationRun
from cure_ngs.vcf import inspect_vcf


VCF = (
    "##fileformat=VCFv4.2\n"
    "##reference=GRCh37\n"
    "##contig=<ID=1,length=249250621>\n"
    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tTUMOR\n"
    "1\t10\t.\tA\tC\t.\tPASS\t.\tGT\t0/1\n"
)


def _bundle(tmp_path: Path, *, two_references: bool = False):
    first = tmp_path / "bad.fa"
    second = tmp_path / "good.fa"
    first.write_text(">1\nA\n", encoding="utf-8")
    second.write_text(">1\nA\n", encoding="utf-8")
    candidates = [
        {"label": "bad", "path": first.name, "contig_style": "numeric"}
    ]
    if two_references:
        candidates.append(
            {"label": "good", "path": second.name, "contig_style": "numeric"}
        )
    config = tmp_path / "bundle.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "target_assembly": "GRCh37",
                "unknown_assembly": "GRCh37",
                "assemblies": {"GRCh37": {"fasta_candidates": candidates}},
                "vep": {"data": "vep", "cache_version": 116},
            }
        ),
        encoding="utf-8",
    )
    return load_reference_bundle(config)


def test_discovery_and_names_support_legacy_inputs(tmp_path: Path) -> None:
    for name in ("plain.vcf", "compressed.vcf.gz", "report.vcf.vep"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    (tmp_path / "ignore.xlsx").write_text("x", encoding="utf-8")

    assert [path.name for path in discover_vcf_inputs(tmp_path)] == [
        "compressed.vcf.gz",
        "plain.vcf",
        "report.vcf.vep",
    ]
    assert safe_output_stem(tmp_path / "sample (PM).vcf.gz") == "sample_PM"


def test_stage_accepts_gzip_and_zip_without_extracting_paths(tmp_path: Path) -> None:
    gz_path = tmp_path / "input.vcf.gz"
    with gzip.open(gz_path, "wt", encoding="utf-8", newline="") as handle:
        handle.write(VCF.replace("\n", "\r\n"))
    staged_gz = stage_vcf_input(gz_path, tmp_path / "gzip.vcf")
    assert "\r" not in staged_gz.read_text(encoding="utf-8")

    zip_path = tmp_path / "input.vcf.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("nested/input.vcf", VCF)
    staged_zip = stage_vcf_input(zip_path, tmp_path / "zip.vcf")
    assert staged_zip.read_text(encoding="utf-8") == VCF


def test_repair_gins_layout_and_missing_sample_header(tmp_path: Path) -> None:
    gins = tmp_path / "gins.vcf"
    gins.write_text(
        "##fileformat=VCFv4.2\n"
        "##reference=GRCh37\n"
        "#CHROM\tPOS\tREF\tALT\tFILTER\tINFO\tFORMAT\tRAW\n"
        "chr1\t10\tA\tC\tPASS\t.\tGT\t0/1\n",
        encoding="utf-8",
    )
    fixed = repair_vcf_structure(gins, tmp_path / "fixed.vcf", fallback_sample="S1")
    assert inspect_vcf(fixed).sample_names == ("RAW",)
    assert fixed.read_text(encoding="utf-8").splitlines()[-1].startswith(
        "1\t10\t.\tA\tC\t."
    )

    missing = tmp_path / "missing.vcf"
    missing.write_text(
        "##fileformat=VCFv4.2\n"
        "##reference=GRCh37\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t10\t.\tA\tC\t.\tPASS\t.\tGT\t0/1\n",
        encoding="utf-8",
    )
    repaired = repair_vcf_structure(
        missing, tmp_path / "missing.fixed.vcf", fallback_sample="S1"
    )
    assert inspect_vcf(repaired).sample_names == ("S1",)


def test_repair_declares_vendor_tags_missing_from_header(tmp_path: Path) -> None:
    source = tmp_path / "vendor.vcf"
    source.write_text(
        "##fileformat=VCFv4.2\n"
        "##reference=GRCh37\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tTUMOR\n"
        "1\t10\t.\tA\tC\t.\tLowQ\tSOMATIC;QSI=25\tGT:DP2\t0/1:30\n",
        encoding="utf-8",
    )

    repaired = repair_vcf_structure(
        source, tmp_path / "fixed.vcf", fallback_sample="S1"
    )
    text = repaired.read_text(encoding="utf-8")

    assert "##INFO=<ID=SOMATIC,Number=0,Type=Flag" in text
    assert "##INFO=<ID=QSI,Number=.,Type=String" in text
    assert "##FORMAT=<ID=DP2,Number=.,Type=String" in text
    assert "##FILTER=<ID=LowQ" in text


def test_contig_rewrite_and_tumor_normal_inference(tmp_path: Path) -> None:
    source = tmp_path / "input.vcf"
    source.write_text(
        VCF.replace("\tTUMOR\n", "\tNORMAL_BLOOD\tTUMOR\n").replace(
            "\t0/1\n", "\t0/0\t0/1\n"
        ),
        encoding="utf-8",
    )
    rewritten = rewrite_contigs(source, tmp_path / "chr.vcf", style="ucsc")
    inspection = inspect_vcf(rewritten)
    assignment = infer_sample_assignment(inspection, sample_tag="SAMPLE01")

    assert rewritten.read_text(encoding="utf-8").splitlines()[-1].startswith("chr1\t")
    assert assignment.vcf_tumor_id == "TUMOR"
    assert assignment.vcf_normal_id == "NORMAL_BLOOD"


def test_maf_contigs_are_normalized_for_database_rows(tmp_path: Path) -> None:
    maf = tmp_path / "output.maf"
    maf.write_text(
        "#version 2.4\n"
        "NCBI_Build\tChromosome\tStart_Position\n"
        "GRCh37\tchr21\t10\n"
        "GRCh37\tchrM\t20\n",
        encoding="utf-8",
    )

    normalize_maf_contigs(maf, style="numeric")

    assert maf.read_text(encoding="utf-8").splitlines()[2:] == [
        "GRCh37\t21\t10",
        "GRCh37\tMT\t20",
    ]


def test_batch_empty_vcf_creates_auditable_empty_maf(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "negative.vcf").write_text(
        "##fileformat=VCFv4.2\n"
        "##reference=GRCh37\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n",
        encoding="utf-8",
    )
    result = batch_vcf_to_maf(
        input_dir, tmp_path / "output", bundle=_bundle(tmp_path), jobs=1
    )

    assert result.failed == 0
    assert result.items[0].status == "VALID_EMPTY"
    assert Path(result.items[0].output_maf).read_text(encoding="utf-8").startswith(
        "Hugo_Symbol\t"
    )
    assert Path(result.items[0].manifest).is_file()


def test_v133_workspace_layout_matches_manuscript_and_legacy_log(tmp_path: Path) -> None:
    workspace = prepare_v133_workspace(tmp_path / "NGS_VCF")
    (workspace.input_directory / "negative.vcf").write_text(
        "##fileformat=VCFv4.2\n"
        "##reference=GRCh37\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n",
        encoding="utf-8",
    )

    result = batch_vcf_to_maf(
        workspace.input_directory,
        workspace.maf_directory,
        bundle=_bundle(tmp_path),
        jobs=1,
        work_directory=workspace.temporary_directory,
        log_directory=workspace.log_directory,
        manifest_directory=workspace.manifest_directory,
        v133_layout=True,
    )

    assert {path.name for path in workspace.root.iterdir()} == {
        "VCF_ALL",
        "VCF_ALL_LOG",
        "VCF_ALL_MAF",
        "VCF_ALL_TMP",
    }
    assert [path.name for path in workspace.maf_directory.iterdir()] == [
        "negative.maf"
    ]
    assert Path(result.items[0].manifest).parent == workspace.manifest_directory
    assert Path(result.log_tsv).parent == workspace.log_directory
    assert Path(result.summary_json).parent == workspace.log_directory
    lines = Path(result.log_tsv).read_text(encoding="utf-8").splitlines()
    assert lines[0].split("\t") == [
        "datetime",
        "vcf_path",
        "sample_tag8",
        "ref_info",
        "is_gvcf",
        "has_normal",
        "status",
        "message",
        "final_vcf",
    ]
    assert lines[1].split("\t")[6:8] == [
        "SUCCESS",
        "VCF has no variants; created empty MAF header",
    ]

    batch_vcf_to_maf(
        workspace.input_directory,
        workspace.maf_directory,
        bundle=_bundle(tmp_path),
        jobs=1,
        work_directory=workspace.temporary_directory,
        log_directory=workspace.log_directory,
        manifest_directory=workspace.manifest_directory,
        v133_layout=True,
        overwrite=True,
    )
    assert len(Path(result.log_tsv).read_text(encoding="utf-8").splitlines()) == 3


def test_batch_retries_fasta_candidates(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "sample.vcf").write_text(VCF, encoding="utf-8")
    bundle = _bundle(tmp_path, two_references=True)

    def fake_normalize(
        input_path: str | Path,
        output_path: str | Path,
        *,
        reference_fasta: str | Path,
        bcftools: str,
    ) -> NormalizationRun:
        if Path(reference_fasta).name == "bad.fa":
            raise ValueError("REF mismatch")
        shutil.copyfile(input_path, output_path)
        return NormalizationRun((), "bcftools mock", ())

    def fake_annotate(
        input_path: str | Path, output_path: str | Path, **kwargs: object
    ) -> AnnotationRun:
        Path(output_path).write_text(
            "NCBI_Build\tChromosome\tStart_Position\tReference_Allele\t"
            "Tumor_Seq_Allele2\tTumor_Sample_Barcode\n"
            "GRCh37\t1\t10\tA\tC\tsample\n",
            encoding="utf-8",
        )
        return AnnotationRun(
            (), "SUCCESS", 1, 1, "GRCh37", "sample", "TUMOR", None, None, 116, "abc"
        )

    with patch("cure_ngs.batch.normalize_vcf", side_effect=fake_normalize), patch(
        "cure_ngs.batch.annotate_vcf", side_effect=fake_annotate
    ):
        result = batch_vcf_to_maf(
            input_dir, tmp_path / "output", bundle=bundle, jobs=1
        )

    assert result.failed == 0
    assert result.items[0].chosen_reference == "good"
    assert [attempt["status"] for attempt in result.items[0].attempts] == [
        "FAILED",
        "SUCCESS",
    ]


def test_v133_nonempty_run_places_compatibility_artifacts_in_tmp(
    tmp_path: Path,
) -> None:
    workspace = prepare_v133_workspace(tmp_path / "NGS_VCF")
    (workspace.input_directory / "sample.vcf").write_text(VCF, encoding="utf-8")

    def fake_normalize(
        input_path: str | Path,
        output_path: str | Path,
        **_: object,
    ) -> NormalizationRun:
        shutil.copyfile(input_path, output_path)
        return NormalizationRun((), "bcftools mock", ())

    def fake_annotate(
        input_path: str | Path,
        output_path: str | Path,
        **kwargs: object,
    ) -> AnnotationRun:
        Path(output_path).write_text(
            "NCBI_Build\tChromosome\tStart_Position\tReference_Allele\t"
            "Tumor_Seq_Allele2\tTumor_Sample_Barcode\n"
            "GRCh37\t1\t10\tA\tC\tsample\n",
            encoding="utf-8",
        )
        Path(kwargs["stdout_log"]).write_text("stdout\n", encoding="utf-8")
        Path(kwargs["stderr_log"]).write_text("stderr\n", encoding="utf-8")
        assert Path(kwargs["temporary_directory"]) == workspace.temporary_directory
        return AnnotationRun(
            (), "SUCCESS", 1, 1, "GRCh37", "sample", "TUMOR", None, None, 116, "abc"
        )

    with patch("cure_ngs.batch.normalize_vcf", side_effect=fake_normalize), patch(
        "cure_ngs.batch.annotate_vcf", side_effect=fake_annotate
    ):
        result = batch_vcf_to_maf(
            workspace.input_directory,
            workspace.maf_directory,
            bundle=_bundle(tmp_path),
            jobs=1,
            work_directory=workspace.temporary_directory,
            log_directory=workspace.log_directory,
            manifest_directory=workspace.manifest_directory,
            v133_layout=True,
        )

    assert result.failed == 0
    assert [path.name for path in workspace.maf_directory.iterdir()] == ["sample.maf"]
    assert (workspace.temporary_directory / ".lock.sample.vcf2maf").is_file()
    assert (
        workspace.temporary_directory / "sample.vcf2maf.bad.stdout.log"
    ).read_text(encoding="utf-8") == "stdout\n"
    assert (
        workspace.temporary_directory / "sample.vcf2maf.bad.stderr.log"
    ).read_text(encoding="utf-8") == "stderr\n"
    assert Path(result.items[0].manifest).parent == workspace.manifest_directory
    log_row = Path(result.log_tsv).read_text(encoding="utf-8").splitlines()[1]
    assert "GRCh37+bad" in log_row
    assert "vcf2maf completed with ref=bad" in log_row


def test_cli_parser_exposes_batch_bundle_options() -> None:
    from cure_ngs.cli import build_parser

    args = build_parser().parse_args(
        [
            "batch-vcf-to-maf",
            "/data/input",
            "/data/output",
            "--reference-config",
            "/references/reference-config.json",
        ]
    )

    assert args.jobs == 4
    assert args.sample_tag_length == 8
    assert args.target_assembly is None

    workspace_args = build_parser().parse_args(
        [
            "batch-vcf-to-maf",
            "--workspace-root",
            "/data/NGS_VCF",
            "--reference-config",
            "/references/reference-config.json",
        ]
    )
    assert workspace_args.input_directory is None
    assert workspace_args.output_directory is None
    assert workspace_args.workspace_root == "/data/NGS_VCF"

import json
import shutil
import subprocess
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

import pytest

from cure_ngs.annotation import AnnotationRun, annotate_vcf, validate_annotation_configuration
from cure_ngs.batch import batch_vcf_to_maf, prepare_v133_workspace, repair_vcf_structure
from cure_ngs.models import Assembly
from cure_ngs.sanitation import repair_legacy_info
from cure_ngs.tools import NormalizationRun
from cure_ngs.vcf import inspect_vcf

from test_batch import VCF, _bundle


def test_headerless_real_vcf_is_repaired_and_audited(tmp_path):
    source = tmp_path / "original.vcf"
    source.write_text(VCF.replace("##fileformat=VCFv4.2\n", ""))
    original = source.read_bytes()
    output = repair_vcf_structure(source, tmp_path / "repaired.vcf", fallback_sample="TUMOR")
    assert inspect_vcf(output).record_count == 1
    assert source.read_bytes() == original
    assert json.loads(output.with_suffix(".vcf.sanitation.json").read_text())["changes"][0]["action"] == "added_missing_fileformat"


def test_multianno_table_is_not_mislabelled_as_vcf(tmp_path):
    source = tmp_path / "multianno.vcf"
    source.write_text("Chr\tStart\tEnd\tRef\tAlt\tGene.refGene\n1\t10\t10\tA\tC\tGENE\n")
    with pytest.raises(ValueError, match="ANNOVAR multianno"):
        repair_vcf_structure(source, tmp_path / "fixed.vcf", fallback_sample="TUMOR")


@pytest.mark.parametrize("braces", [True, False])
def test_dictionary_info_is_losslessly_audited_not_used_as_alleles(tmp_path, braces):
    source = tmp_path / "original.vcf"
    raw = "{'location': 'exonic', 'origAlt': 'X;Y,Z=foo', 'depth': 4, 'tags': ['a b', 'c']}"
    if not braces:
        raw = raw[1:-1]
    source.write_text(VCF.replace("PASS\t.\tGT", f"PASS\t{raw}\tGT"))
    output = repair_vcf_structure(source, tmp_path / "fixed.vcf", fallback_sample="TUMOR")
    assert inspect_vcf(output).record_count == 1
    record = next(line for line in output.read_text().splitlines() if not line.startswith("#"))
    assert record.split("\t")[3:5] == ["A", "C"]
    assert "origAlt=X%3BY%2CZ%3Dfoo" in record
    audit = json.loads(output.with_suffix(".vcf.sanitation.json").read_text())
    assert audit["changes"][0]["original_info"] == raw


@pytest.mark.parametrize("text", [
    "{'bad,key': 1}", "{'x': 1, 'x': 2}", "{'x': {'nested': 1}}",
    "{'x': __import__('os').system('false')}", "'location'='exonic'",
])
def test_ambiguous_or_executable_info_rejected(text):
    with pytest.raises(ValueError):
        repair_legacy_info(text, line_number=7)


def test_json_info_supported():
    assert repair_legacy_info('{"flag": true, "missing": null}', line_number=1) == "flag=1;missing=."


def test_empty_info_and_trailing_delimiter_are_auditable_repairs():
    assert repair_legacy_info("", line_number=1) == "."
    assert repair_legacy_info("DP=3;", line_number=1) == "DP=3"


def test_parallel_same_basename_internal_vep_output_never_overlaps(tmp_path):
    workspace = prepare_v133_workspace(tmp_path / "NGS_VCF")
    # Same eight-character sample tag, distinct filenames and alleles.
    for name, allele in [("SAME0001.a.vcf", "C"), ("SAME0001.b.vcf", "G")]:
        (workspace.input_directory / name).write_text(VCF.replace("\tC\t", f"\t{allele}\t"))
    barrier = Barrier(2)
    seen = []

    def normalize(source, destination, **kwargs):
        shutil.copyfile(source, destination)
        return NormalizationRun((), "mock", ())

    def annotate(source, destination, **kwargs):
        temp = Path(kwargs["temporary_directory"])
        temp.mkdir(parents=True, exist_ok=True)
        seen.append(temp)
        record = next(line for line in Path(source).read_text().splitlines() if not line.startswith("#"))
        allele = record.split("\t")[4]
        shared_basename = temp / "reference-1.normalized.vep.vcf"
        shared_basename.write_text(allele)
        barrier.wait(timeout=10)
        assert shared_basename.read_text() == allele
        Path(destination).write_text(
            "NCBI_Build\tChromosome\tStart_Position\tReference_Allele\tTumor_Seq_Allele2\tTumor_Sample_Barcode\n"
            f"GRCh37\t1\t10\tA\t{allele}\tSAME0001\n"
        )
        return AnnotationRun((), "SUCCESS", 1, 1, "GRCh37", "SAME0001", "TUMOR", None, None, 116, "test")

    with patch("cure_ngs.batch.normalize_vcf", side_effect=normalize), patch("cure_ngs.batch.annotate_vcf", side_effect=annotate):
        result = batch_vcf_to_maf(workspace.input_directory, workspace.maf_directory,
            bundle=_bundle(tmp_path), jobs=2, work_directory=workspace.temporary_directory,
            v133_layout=True)
    assert result.failed == 0
    assert len(set(seen)) == 2
    assert "\tC\t" in (workspace.maf_directory / "SAME0001.a.maf").read_text()
    assert "\tG\t" in (workspace.maf_directory / "SAME0001.b.maf").read_text()


def annotation_resources(tmp_path):
    source = tmp_path / "sample.vcf"
    source.write_text(VCF)
    reference = tmp_path / "reference.fa"
    reference.write_text(">1\nAAAAAAAAAA\n")
    vcf2maf = tmp_path / "vcf2maf.pl"
    vcf2maf.write_text("# compatible upstream script\n")
    vep_path = tmp_path / "vep-bin"
    vep_path.mkdir()
    (vep_path / "vep").write_text("# test executable\n")
    cache = tmp_path / "cache"
    metadata = cache / "homo_sapiens/116_GRCh37/info.txt"
    metadata.parent.mkdir(parents=True)
    metadata.write_text("species\thomo_sapiens\nassembly\tGRCh37\n")
    return source, reference, vcf2maf, vep_path, cache


def test_wrong_cache_version_and_old_vcf2maf_rejected_before_annotation(tmp_path):
    _, _, converter, vep_path, cache = annotation_resources(tmp_path)
    with patch("cure_ngs.annotation._vep_major", return_value=116):
        with pytest.raises(ValueError, match="VEP/cache version mismatch"):
            validate_annotation_configuration(vep_path, converter, cache, Assembly.GRCH37, 106)
        converter.write_text("$cmd .= ' --af_esp';")
        with pytest.raises(ValueError, match="deprecated --af_esp"):
            validate_annotation_configuration(vep_path, converter, cache, Assembly.GRCH37, 116)


@pytest.mark.parametrize("wrong_metadata", ["species\tmus_musculus\nassembly\tGRCh37\n", "species\thomo_sapiens\nassembly\tGRCh38\n"])
def test_cache_identity_rejected(tmp_path, wrong_metadata):
    _, _, converter, vep_path, cache = annotation_resources(tmp_path)
    (cache / "homo_sapiens/116_GRCh37/info.txt").write_text(wrong_metadata)
    with patch("cure_ngs.annotation._vep_major", return_value=116), pytest.raises(ValueError, match="species/assembly mismatch"):
        validate_annotation_configuration(vep_path, converter, cache, Assembly.GRCH37, 116)


def test_direct_annotation_reruns_isolate_temp_and_publish_only_valid_maf(tmp_path):
    source, reference, converter, vep_path, cache = annotation_resources(tmp_path)
    output = tmp_path / "result.maf"
    output.write_text("previous validated result\n")
    tmp_dirs = []
    barcode = "TUMOR"

    def run(command, **kwargs):
        directory = Path(command[command.index("--tmp-dir") + 1])
        tmp_dirs.append(directory)
        assert not (directory / "sample.vep.vcf").exists()
        (directory / "sample.vep.vcf").write_text("new result")
        Path(command[command.index("--output-maf") + 1]).write_text(
            "NCBI_Build\tChromosome\tStart_Position\tReference_Allele\tTumor_Seq_Allele2\tTumor_Sample_Barcode\n"
            f"GRCh37\t1\t10\tA\tC\t{barcode}\n"
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    parameters = dict(reference_fasta=reference, assembly=Assembly.GRCH37,
        cache_version=116, vep_data=cache, vcf2maf=converter, vep_path=vep_path,
        temporary_directory=tmp_path / "shared")
    with patch("cure_ngs.annotation._vep_major", return_value=116), patch("cure_ngs.annotation.subprocess.run", side_effect=run):
        annotate_vcf(source, output, **parameters)
        annotate_vcf(source, output, **parameters)
        previous = output.read_bytes()
        barcode = "WRONG_SAMPLE"
        with pytest.raises(ValueError, match="tumor ID mismatch"):
            annotate_vcf(source, output, **parameters)
        assert output.read_bytes() == previous
    assert len(set(tmp_dirs)) == 3


def test_symbolic_only_is_explicitly_not_small_variant_annotation(tmp_path):
    workspace = prepare_v133_workspace(tmp_path / "NGS_VCF")
    (workspace.input_directory / "sv.vcf").write_text(VCF.replace("\tC\t", "\t<DEL>\t"))
    with patch("cure_ngs.batch.annotate_vcf") as annotation:
        result = batch_vcf_to_maf(workspace.input_directory, workspace.maf_directory,
            bundle=_bundle(tmp_path), jobs=1, work_directory=workspace.temporary_directory,
            log_directory=workspace.log_directory, v133_layout=True)
    assert result.failed == 0
    assert result.items[0].status == "NO_SUPPORTED_SMALL_VARIANTS"
    assert not annotation.called
    excluded = list(workspace.temporary_directory.rglob("01.excluded-symbolic-or-unsupported.vcf"))
    assert len(excluded) == 1
    assert inspect_vcf(excluded[0]).record_count == 1
    log = workspace.log_directory / "vcf2maf_batch_log.tsv"
    assert "NO_SUPPORTED_SMALL_VARIANTS" in log.read_text()


def test_failed_batch_rerun_keeps_previous_maf_and_manifest(tmp_path):
    workspace = prepare_v133_workspace(tmp_path / "NGS_VCF")
    (workspace.input_directory / "sample.vcf").write_text(VCF)
    output = workspace.maf_directory / "sample.maf"
    output.write_text("previous verified output")
    manifest = workspace.log_directory / "manifests" / "sample.maf.manifest.json"
    manifest.parent.mkdir(exist_ok=True)
    manifest.write_text('{"previous": true}')
    with patch("cure_ngs.batch._annotate_with_reference_fallback", side_effect=ValueError("annotation failed")):
        result = batch_vcf_to_maf(workspace.input_directory, workspace.maf_directory,
            bundle=_bundle(tmp_path), jobs=1, work_directory=workspace.temporary_directory,
            log_directory=workspace.log_directory, v133_layout=True, overwrite=True)
    assert result.failed == 1
    assert output.read_text() == "previous verified output"
    assert manifest.read_text() == '{"previous": true}'

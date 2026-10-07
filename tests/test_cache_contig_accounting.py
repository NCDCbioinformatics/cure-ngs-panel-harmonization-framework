import json
import hashlib
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from cure_ngs.annotation import annotate_vcf, annotation_outputs
from cure_ngs.contig_synonyms import REPORTS, assembly_contig_aliases, partition_cache_contigs, write_default_vep_config
from cure_ngs.models import Assembly
from cure_ngs.provenance import sha256_file, write_manifest
from cure_ngs.vcf import inspect_vcf
from test_annotation_regressions import annotation_resources


CONTIGS = ("chrUn_gl000212", "chrUn_gl000219", "chrUn_gl000217",
           "chr9_gl000198_random", "chr17_gl000204_random")


def _records(source: Path, contigs=CONTIGS):
    headers = "".join(line for line in source.read_text().splitlines(keepends=True) if line.startswith("#"))
    source.write_text(headers + "".join(
        f"{contig}\t10\t.\tA\tC\t.\tPASS\t.\tGT\t0/1\n" for contig in contigs))


def test_official_assembly_aliases_preserve_sequence_identity():
    aliases37 = assembly_contig_aliases(Assembly.GRCH37)
    assert aliases37["chrUn_gl000212"] == "GL000212.1"
    assert aliases37["chr9_gl000198_random"] == "GL000198.1"
    assert aliases37["NT_113914.1"] == "GL000198.1"
    assert "chr1" not in aliases37
    aliases38 = assembly_contig_aliases(Assembly.GRCH38)
    assert aliases38["chrUn_KI270442v1"] == "KI270442.1"
    assert "chr1" not in aliases38


def test_corrupted_assembly_report_is_rejected(monkeypatch):
    filename, _ = REPORTS[Assembly.GRCH37]
    monkeypatch.setitem(REPORTS, Assembly.GRCH37, (filename, "0" * 64))
    with pytest.raises(ValueError, match="checksum mismatch"):
        assembly_contig_aliases(Assembly.GRCH37)


def test_per_invocation_synonyms_configuration(tmp_path):
    directories = (tmp_path / "a", tmp_path / "b")
    for directory in directories:
        directory.mkdir()
        config = write_default_vep_config(directory, Assembly.GRCH37)
        assert config.read_text() == f"synonyms {directory / 'assembly-contig-synonyms.tsv'}\n"
        assert "GL000212.1\tchrUn_gl000212\n" in (directory / "assembly-contig-synonyms.tsv").read_text()
    assert (directories[0] / "default-vep.config").read_text() != (directories[1] / "default-vep.config").read_text()


def test_added_aliases_keep_existing_cache_synonyms(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    original = "MT\tchrM\nMT\tNC_012920.1\n1\tchr1\n"
    (cache / "chr_synonyms.txt").write_text(original)
    work = tmp_path / "work"
    work.mkdir()
    write_default_vep_config(work, Assembly.GRCH37, cache)
    combined = (work / "assembly-contig-synonyms.tsv").read_text()
    assert combined.startswith(original)
    assert "GL000212.1\tchrUn_gl000212\n" in combined
    assert (cache / "chr_synonyms.txt").read_text() == original


@pytest.mark.parametrize("mito_length", [16571, 16569])
def test_legacy_or_non_rcrs_mitochondrion_is_preserved_not_renamed(tmp_path, mito_length):
    source, reference, _, _, cache = annotation_resources(tmp_path)
    _records(source, ("1", "chrM"))
    reference.write_text(">chrM\n" + "A" * mito_length + "\n")
    Path(f"{reference}.fai").write_text(f"chrM\t{mito_length}\t6\t{mito_length}\t{mito_length + 1}\n")
    original = source.read_bytes()
    work = tmp_path / "work"
    work.mkdir()
    partition = partition_cache_contigs(source, work, cache / "homo_sapiens/116_GRCh37", Assembly.GRCH37, reference)
    assert partition.eligible_records == partition.excluded_records == 1
    assert "chrM\t10\t.\tA\tC\t" in partition.excluded_vcf.read_text()
    evidence = json.loads(partition.audit.read_text())
    assert evidence["excluded_contigs"][0]["reason"] == "MITOCHONDRIAL_REFERENCE_INCOMPATIBLE_WITH_GRCH_RCRS"
    assert evidence["mitochondrial_reference"]["chrM"]["length"] == mito_length
    assert source.read_bytes() == original


def test_exact_mito_contig_identity_with_both_chrM_and_chrMT(tmp_path, monkeypatch):
    # Synthetic sequences test the identity guard; not a human-reference claim.
    import cure_ngs.contig_synonyms as module
    source, reference, _, _, cache = annotation_resources(tmp_path)
    _records(source, ("chrM", "chrMT"))
    sequence = "C" * 16569
    monkeypatch.setattr(module, "RCRS_SEQUENCE_SHA256", hashlib.sha256(sequence.encode()).hexdigest())
    first = ">chrM\n" + "A" * 16571 + "\n"
    reference.write_text(first + ">chrMT\n" + sequence + "\n")
    Path(f"{reference}.fai").write_text(f"chrM\t16571\t6\t16571\t16572\nchrMT\t16569\t{len(first) + 7}\t16569\t16570\n")
    work = tmp_path / "work"
    work.mkdir()
    partition = partition_cache_contigs(source, work, cache / "homo_sapiens/116_GRCh37", Assembly.GRCH37, reference)
    assert partition.eligible_records == partition.excluded_records == 1
    assert "chrMT\t10" in partition.annotation_vcf.read_text()
    assert "chrM\t10" in partition.excluded_vcf.read_text()


def test_partition_preserves_no_cache_contigs_without_rewriting_alleles(tmp_path):
    source, _, _, _, cache = annotation_resources(tmp_path)
    _records(source)
    original = source.read_bytes()
    cache_directory = cache / "homo_sapiens/116_GRCh37"
    for canonical in ("GL000212.1", "GL000219.1", "GL000204.1"):
        (cache_directory / canonical).mkdir()
    work = tmp_path / "partition"
    work.mkdir()
    partition = partition_cache_contigs(source, work, cache_directory, Assembly.GRCH37)
    assert partition.eligible_records == 3
    assert partition.excluded_records == 2
    assert inspect_vcf(partition.excluded_vcf).record_count == 2
    assert inspect_vcf(partition.annotation_vcf).record_count == 3
    expected = [line for line in source.read_text().splitlines() if not line.startswith("#")]
    retained = [line for path in (partition.annotation_vcf, partition.excluded_vcf)
                for line in path.read_text().splitlines() if not line.startswith("#")]
    assert sorted(retained) == sorted(expected)
    audit = json.loads(partition.audit.read_text())
    assert audit["coordinates_ref_alt_changed"] is False
    assert audit["input_records"] == 5
    assert {item["canonical_contig"] for item in audit["excluded_contigs"]} == {"GL000217.1", "GL000198.1"}
    assert source.read_bytes() == original


def test_primary_and_unknown_contigs_are_not_silently_excluded(tmp_path):
    source, _, _, _, cache = annotation_resources(tmp_path)
    _records(source, ("1", "chr1", "unknown_vendor_sequence", "GL000217.1"))
    work = tmp_path / "partition"
    work.mkdir()
    partition = partition_cache_contigs(source, work, cache / "homo_sapiens/116_GRCh37", Assembly.GRCH37)
    assert partition.eligible_records == 3
    assert partition.excluded_records == 1
    assert "unknown_vendor_sequence" in partition.annotation_vcf.read_text()


def _mock_annotation(command, **kwargs):
    source = Path(command[command.index("--input-vcf") + 1])
    output = Path(command[command.index("--output-maf") + 1])
    records = [line.split("\t") for line in source.read_text().splitlines() if not line.startswith("#")]
    output.write_text("NCBI_Build\tChromosome\tStart_Position\tReference_Allele\tTumor_Seq_Allele2\tTumor_Sample_Barcode\n"
        + "".join(f"GRCh37\t{row[0]}\t{row[1]}\t{row[3]}\t{row[4]}\tTUMOR\n" for row in records))
    return subprocess.CompletedProcess(command, 0, stdout="", stderr="test warnings\n")


def _parameters(reference, converter, vep_path, cache):
    return dict(reference_fasta=reference, assembly=Assembly.GRCH37,
                cache_version=116, vep_data=cache, vcf2maf=converter, vep_path=vep_path)


def test_annotation_accounting_and_sidecar_manifest_hashes(tmp_path):
    source, reference, converter, vep_path, cache = annotation_resources(tmp_path)
    _records(source)
    for canonical in ("GL000212.1", "GL000219.1", "GL000204.1"):
        (cache / "homo_sapiens/116_GRCh37" / canonical).mkdir()
    output = tmp_path / "annotated.maf"
    with patch("cure_ngs.annotation._vep_major", return_value=116), patch("cure_ngs.annotation.subprocess.run", side_effect=_mock_annotation):
        result = annotate_vcf(source, output, **_parameters(reference, converter, vep_path, cache))
    assert result.status == "SUCCESS"
    assert result.input_records == 5
    assert result.annotation_input_records == result.output_rows == 3
    assert result.excluded_contig_records == 2
    config = Path(result.command[result.command.index("--vep-config") + 1])
    assert "synonyms " in config.read_text()
    assert (config.parent / "vcf2maf.stderr.log").read_text() == "test warnings\n"
    manifest = write_manifest(tmp_path / "manifest.json", command=list(result.command), inputs={"vcf": source},
        outputs=annotation_outputs(output, result.to_dict()), parameters=result.to_dict(), tools={})
    payload = json.loads(manifest.read_text())
    for key in ("excluded_contigs_vcf", "contig_exclusion_audit"):
        assert payload["outputs"][key]["sha256"] == sha256_file(payload["outputs"][key]["path"])


def test_custom_vep_configuration_is_passed_unchanged(tmp_path):
    source, reference, converter, vep_path, cache = annotation_resources(tmp_path)
    _records(source, ("chrUn_gl000217",))
    custom = tmp_path / "custom.config"
    custom.write_text("gff custom-annotation.gff.gz\n")
    before = custom.read_bytes()
    with patch("cure_ngs.annotation._vep_major", return_value=116), patch("cure_ngs.annotation.subprocess.run", side_effect=_mock_annotation):
        result = annotate_vcf(source, tmp_path / "result.maf", vep_config=custom,
            **_parameters(reference, converter, vep_path, cache))
    assert result.command[result.command.index("--vep-config") + 1] == str(custom)
    assert result.annotation_input_records == result.output_rows == 1
    assert result.excluded_contig_records == 0
    assert result.excluded_contigs_vcf is None
    assert custom.read_bytes() == before


def test_unexpected_partial_maf_does_not_replace_previous_valid_output(tmp_path):
    source, reference, converter, vep_path, cache = annotation_resources(tmp_path)
    _records(source, ("1", "unknown_vendor_sequence"))
    output = tmp_path / "result.maf"
    output.write_text("previous validated MAF\n")
    original_hash = sha256_file(source)
    def drop_one(command, **kwargs):
        completed = _mock_annotation(command, **kwargs)
        staged = Path(command[command.index("--output-maf") + 1])
        staged.write_text("\n".join(staged.read_text().splitlines()[:-1]) + "\n")
        return completed
    with patch("cure_ngs.annotation._vep_major", return_value=116), patch("cure_ngs.annotation.subprocess.run", side_effect=drop_one):
        with pytest.raises(ValueError, match="expected 2 MAF rows, observed 1"):
            annotate_vcf(source, output, **_parameters(reference, converter, vep_path, cache))
    assert output.read_text() == "previous validated MAF\n"
    assert sha256_file(source) == original_hash


def test_all_no_cache_records_are_preserved_and_not_reported_as_annotation_success(tmp_path):
    source, reference, converter, vep_path, cache = annotation_resources(tmp_path)
    _records(source, ("chrUn_gl000217", "GL000198.1"))
    with patch("cure_ngs.annotation._vep_major", return_value=116), patch("cure_ngs.annotation.subprocess.run") as run:
        result = annotate_vcf(source, tmp_path / "result.maf", **_parameters(reference, converter, vep_path, cache))
    assert not run.called
    assert result.status == "NO_CACHE_SUPPORTED_VARIANTS"
    assert result.command == ()
    assert result.input_records == result.excluded_contig_records == 2
    assert result.output_rows == result.annotation_input_records == 0
    assert inspect_vcf(result.excluded_contigs_vcf).record_count == 2

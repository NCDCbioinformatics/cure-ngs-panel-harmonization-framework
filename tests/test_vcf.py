from pathlib import Path

import pytest

from cure_ngs.models import (
    Assembly,
    AssemblyDetectionError,
    AssemblyEvidenceConflictError,
    AssemblyUndeterminedError,
    InspectionStatus,
    VcfFormatError,
)
from cure_ngs.vcf import derive_sample_id, detect_assembly, inspect_vcf, sanitize_vcf


FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"


def test_inspect_multiallelic_grch38_vcf() -> None:
    result = inspect_vcf(FIXTURES / "multiallelic.grch38.vcf")

    assert result.status is InspectionStatus.VALID
    assert result.assembly is Assembly.GRCH38
    assert result.sample_names == ("fixture_tumor",)
    assert result.record_count == 1
    assert result.alternate_allele_count == 2
    assert result.multiallelic_record_count == 1
    assert result.symbolic_allele_count == 0


def test_empty_vcf_has_distinct_status() -> None:
    result = inspect_vcf(FIXTURES / "empty.grch37.vcf")

    assert result.status is InspectionStatus.VALID_EMPTY
    assert result.assembly is Assembly.GRCH37
    assert result.record_count == 0


def test_unknown_assembly_fails_closed() -> None:
    header = ["##fileformat=VCFv4.2"]

    with pytest.raises(AssemblyUndeterminedError, match="could not be determined"):
        detect_assembly(header)


def test_conflicting_assembly_evidence_fails() -> None:
    header = [
        "##reference=GRCh37",
        "##contig=<ID=chr1,length=248956422>",
    ]

    with pytest.raises(AssemblyEvidenceConflictError, match="Conflicting"):
        detect_assembly(header)


def test_command_path_is_not_used_as_assembly_evidence() -> None:
    header = [
        "##reference=GRCh37",
        "##bcftools_normCommand=norm -o /tmp/b38/random.vcf input.vcf",
        "##contig=<ID=1,length=249250621>",
    ]

    assembly, evidence = detect_assembly(header)

    assert assembly is Assembly.GRCH37
    assert all("bcftools_normCommand" not in item for item in evidence)


def test_sample_id_is_not_truncated() -> None:
    assert derive_sample_id("institution_sample_000123.vcf.gz") == (
        "institution_sample_000123"
    )


def test_blank_data_line_is_rejected(tmp_path: Path) -> None:
    malformed = tmp_path / "blank-line.vcf"
    malformed.write_text(
        "##fileformat=VCFv4.2\n"
        "##reference=GRCh38\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "\n",
        encoding="utf-8",
    )

    with pytest.raises(VcfFormatError, match="Blank data line"):
        inspect_vcf(malformed)


def test_sanitize_vcf_removes_bom_and_crlf(tmp_path: Path) -> None:
    source = tmp_path / "windows.vcf"
    destination = tmp_path / "sanitized.vcf"
    source.write_bytes(
        b"\xef\xbb\xbf##fileformat=VCFv4.2\r\n"
        b"##reference=GRCh38\r\n"
        b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\r\n"
        b"1\t1\t.\tA\tC\t.\tPASS\t.\r\n"
    )

    sanitize_vcf(source, destination)

    output = destination.read_bytes()
    assert not output.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in output
    assert inspect_vcf(destination).record_count == 1

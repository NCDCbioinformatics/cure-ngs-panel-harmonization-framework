from pathlib import Path

import pytest

from cure_ngs.fasta import FastaReference
from cure_ngs.maf import maf_alleles_to_vcf, minimal_maf_to_vcfs
from cure_ngs.models import Assembly
from cure_ngs.vcf import inspect_vcf


SEQUENCE = "TAAAAACCCCCGGGGGTTTTTACGTACGTACGT"


def make_reference(tmp_path: Path) -> Path:
    reference = tmp_path / "reference.fa"
    reference.write_text(f">chr1\n{SEQUENCE}\n", encoding="ascii", newline="\n")
    Path(f"{reference}.fai").write_text(
        f"chr1\t{len(SEQUENCE)}\t6\t{len(SEQUENCE)}\t{len(SEQUENCE) + 1}\n",
        encoding="ascii",
        newline="\n",
    )
    return reference


def test_maf_indels_are_anchored_with_reference_base(tmp_path: Path) -> None:
    reference = FastaReference(make_reference(tmp_path))

    insertion = maf_alleles_to_vcf(
        chromosome="1",
        start=12,
        end=11,
        reference_allele="-",
        tumor_allele="AA",
        reference=reference,
    )
    deletion = maf_alleles_to_vcf(
        chromosome="1",
        start=12,
        end=13,
        reference_allele="GG",
        tumor_allele="-",
        reference=reference,
    )

    assert (insertion.position, insertion.reference, insertion.alternate) == (11, "C", "CAA")
    assert (deletion.position, deletion.reference, deletion.alternate) == (11, "CGG", "C")


def test_reference_mismatch_fails(tmp_path: Path) -> None:
    reference = FastaReference(make_reference(tmp_path))

    with pytest.raises(ValueError, match="Reference mismatch"):
        maf_alleles_to_vcf(
            chromosome="chr1",
            start=10,
            end=10,
            reference_allele="A",
            tumor_allele="T",
            reference=reference,
        )


def test_minimal_maf_to_vcfs_preserves_full_sample_id(tmp_path: Path) -> None:
    reference = make_reference(tmp_path)
    maf = tmp_path / "input.maf"
    sample = "institution_sample_000123"
    maf.write_text(
        "Tumor_Sample_Barcode\tChromosome\tStart_Position\tEnd_Position\t"
        "Reference_Allele\tTumor_Seq_Allele2\tReference_Assembly\n"
        f"{sample}\t1\t10\t10\tC\tT\tGRCh38\n"
        f"{sample}\t1\t12\t11\t-\tAA\tGRCh38\n"
        f"{sample}\t1\t12\t13\tGG\t-\tGRCh38\n",
        encoding="utf-8",
        newline="\n",
    )

    result = minimal_maf_to_vcfs(
        maf,
        tmp_path / "vcfs",
        reference_fasta=reference,
        assembly=Assembly.GRCH38,
    )
    output = Path(result.sample_files[sample])
    inspection = inspect_vcf(output)

    assert output.name == f"{sample}.from_minimal_maf.vcf"
    assert inspection.sample_names == (sample,)
    assert inspection.record_count == 3
    assert result.variant_type_counts == {"DEL": 1, "INS": 1, "SNV": 1}


def test_sanitized_sample_filename_collisions_fail(tmp_path: Path) -> None:
    reference = make_reference(tmp_path)
    maf = tmp_path / "collision.maf"
    maf.write_text(
        "Tumor_Sample_Barcode\tChromosome\tStart_Position\tEnd_Position\t"
        "Reference_Allele\tTumor_Seq_Allele2\n"
        "sample/a\t1\t10\t10\tC\tT\n"
        "sample?a\t1\t10\t10\tC\tG\n",
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(ValueError, match="filename collision"):
        minimal_maf_to_vcfs(
            maf,
            tmp_path / "vcfs",
            reference_fasta=reference,
            assembly=Assembly.GRCH38,
        )

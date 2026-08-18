import gzip
import json
from pathlib import Path

import pytest

from cure_ngs.models import Assembly
from cure_ngs.reference_bundle import (
    inspect_reference_bundle,
    load_reference_bundle,
    write_reference_config_template,
)


def _write_config(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_user_can_create_config_for_selected_reference_root(tmp_path: Path) -> None:
    output = tmp_path / "config" / "reference-config.json"

    created = write_reference_config_template(
        output, reference_root="/institution/references", cache_version=116
    )
    payload = json.loads(created.read_text(encoding="utf-8"))

    assert payload["reference_root"] == "/institution/references"
    assert len(payload["assemblies"]["GRCh37"]["fasta_candidates"]) == 3
    assert len(payload["liftover"]["GRCh38_to_GRCh37"]["chains"]) == 2
    assert payload["vep"] == {"data": "vep", "cache_version": 116}
    with pytest.raises(FileExistsError, match="--force"):
        write_reference_config_template(
            output, reference_root="/different/root", cache_version=116
        )


def test_bundle_paths_are_portable_and_root_relative(tmp_path: Path) -> None:
    configured_root = tmp_path / "institution-resources"
    config = _write_config(
        tmp_path / "bundle.json",
        {
            "schema_version": "1.0",
            "reference_root": "ignored-by-cli-override",
            "target_assembly": "GRCh37",
            "assemblies": {
                "GRCh37": {
                    "fasta_candidates": [
                        {"label": "hg19", "path": "grch37/hg19.fa"}
                    ]
                }
            },
            "vep": {"data": "vep", "cache_version": 116},
        },
    )

    bundle = load_reference_bundle(config, reference_root=configured_root)

    assert bundle.root == configured_root.resolve()
    assert bundle.target_assembly is Assembly.GRCH37
    assert bundle.references_for(Assembly.GRCH37)[0].path == (
        configured_root / "grch37" / "hg19.fa"
    ).resolve()
    assert bundle.vep_data == (configured_root / "vep").resolve()


def test_bundle_supports_chain_specific_target_references(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path / "bundle.json",
        {
            "schema_version": "1.0",
            "target_assembly": "GRCh37",
            "assemblies": {
                "GRCh37": {
                    "fasta_candidates": [
                        {"label": "ucsc", "path": "hg19.fa"},
                        {"label": "gatk", "path": "b37.fa"},
                    ]
                }
            },
            "liftover": {
                "GRCh38_to_GRCh37": {
                    "chains": [
                        {
                            "label": "ucsc-chain",
                            "path": "hg38ToHg19.over.chain.gz",
                            "target_reference_label": "ucsc",
                        },
                        {
                            "label": "numeric-chain",
                            "path": "GRCh38_to_GRCh37.chain.gz",
                            "target_reference_label": "gatk",
                        },
                    ]
                }
            },
            "vep": {"data": "vep", "cache_version": 116},
        },
    )

    bundle = load_reference_bundle(config)
    profile = bundle.liftover_for(Assembly.GRCH38, Assembly.GRCH37)

    assert [item.target_reference_label for item in profile.chains] == [
        "ucsc",
        "gatk",
    ]


def test_bundle_rejects_unknown_target_reference_label(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path / "bundle.json",
        {
            "schema_version": "1.0",
            "assemblies": {
                "GRCh37": {
                    "fasta_candidates": [{"label": "hg19", "path": "hg19.fa"}]
                }
            },
            "liftover": {
                "GRCh38_to_GRCh37": {
                    "chains": [
                        {
                            "path": "chain.gz",
                            "target_reference_label": "missing",
                        }
                    ]
                }
            },
            "vep": {"data": "vep", "cache_version": 116},
        },
    )

    with pytest.raises(ValueError, match="unknown GRCh37 FASTA labels"):
        load_reference_bundle(config)


def test_doctor_bundle_reports_missing_assets(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path / "bundle.json",
        {
            "schema_version": "1.0",
            "assemblies": {
                "GRCh37": {
                    "fasta_candidates": [{"label": "hg19", "path": "hg19.fa"}]
                }
            },
            "vep": {"data": "vep", "cache_version": 116},
        },
    )

    report = inspect_reference_bundle(load_reference_bundle(config))

    assert report["status"] == "NOT_READY"
    assert report["failed_checks"] >= 3


def test_doctor_bundle_verifies_assembly_chain_and_cache_identity(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "hg19.fa"
    reference.write_text(">chr1\nA\n", encoding="utf-8")
    Path(f"{reference}.fai").write_text(
        "chr1\t249250621\t6\t1\t2\n", encoding="utf-8"
    )
    reference.with_suffix(".dict").write_text(
        "@HD\tVN:1.6\n@SQ\tSN:chr1\tLN:249250621\n",
        encoding="utf-8",
    )
    chain = tmp_path / "hg38ToHg19.over.chain.gz"
    with gzip.open(chain, "wt", encoding="utf-8") as handle:
        handle.write(
            "chain 1 chr1 248956422 + 0 100 chr1 249250621 + 0 100 1\n"
        )
    cache = tmp_path / "vep" / "homo_sapiens" / "116_GRCh37"
    (cache / "1").mkdir(parents=True)
    (cache / "info.txt").write_text(
        "species\thomo_sapiens\nassembly\tGRCh37\n", encoding="utf-8"
    )
    (cache / "1" / "1-1000000.gz").write_bytes(b"cache")
    config = _write_config(
        tmp_path / "bundle.json",
        {
            "schema_version": "1.0",
            "target_assembly": "GRCh37",
            "assemblies": {
                "GRCh37": {
                    "fasta_candidates": [
                        {
                            "label": "hg19",
                            "path": "hg19.fa",
                            "contig_style": "ucsc",
                        }
                    ]
                }
            },
            "liftover": {
                "GRCh38_to_GRCh37": {
                    "chains": [
                        {
                            "label": "ucsc",
                            "path": "hg38ToHg19.over.chain.gz",
                            "contig_style": "ucsc",
                            "target_reference_label": "hg19",
                        }
                    ]
                }
            },
            "vep": {"data": "vep", "cache_version": 116},
        },
    )

    bundle = load_reference_bundle(config)
    report = inspect_reference_bundle(
        bundle,
        runtime_vep={
            "status": "available",
            "version": "ensembl-vep          : 116.1",
        },
    )
    checks = {item["name"]: item for item in report["checks"]}

    assert report["status"] == "READY"
    assert checks["assembly:GRCh37:hg19"]["status"] == "PASS"
    assert (
        checks["chain_direction:GRCh38_to_GRCh37:ucsc"]["status"]
        == "PASS"
    )
    assert checks["chain_target_style:GRCh38_to_GRCh37:ucsc"]["status"] == "PASS"
    assert checks["vep_cache_identity"]["status"] == "PASS"
    assert checks["vep_cache_payload"]["status"] == "PASS"
    assert checks["vep_runtime_cache_compatibility"]["status"] == "PASS"

    mismatch = inspect_reference_bundle(
        bundle,
        runtime_vep={
            "status": "available",
            "version": "ensembl-vep          : 115.2",
        },
    )
    mismatch_check = next(
        item
        for item in mismatch["checks"]
        if item["name"] == "vep_runtime_cache_compatibility"
    )
    assert mismatch["status"] == "NOT_READY"
    assert mismatch_check["status"] == "FAIL"


def test_doctor_bundle_rejects_wrong_fasta_assembly(tmp_path: Path) -> None:
    reference = tmp_path / "wrong.fa"
    reference.write_text(">1\nA\n", encoding="utf-8")
    Path(f"{reference}.fai").write_text(
        "1\t248956422\t3\t1\t2\n", encoding="utf-8"
    )
    cache = tmp_path / "vep" / "homo_sapiens" / "116_GRCh37"
    (cache / "1").mkdir(parents=True)
    (cache / "info.txt").write_text(
        "species\thomo_sapiens\nassembly\tGRCh37\n", encoding="utf-8"
    )
    (cache / "1" / "chunk.gz").write_bytes(b"cache")
    config = _write_config(
        tmp_path / "bundle.json",
        {
            "schema_version": "1.0",
            "assemblies": {
                "GRCh37": {
                    "fasta_candidates": [
                        {
                            "label": "wrong-build",
                            "path": "wrong.fa",
                            "contig_style": "numeric",
                        }
                    ]
                }
            },
            "vep": {"data": "vep", "cache_version": 116},
        },
    )

    report = inspect_reference_bundle(load_reference_bundle(config))
    assembly_check = next(
        item
        for item in report["checks"]
        if item["name"] == "assembly:GRCh37:wrong-build"
    )

    assert report["status"] == "NOT_READY"
    assert assembly_check["status"] == "FAIL"
    assert "observed_length=248956422" in assembly_check["detail"]

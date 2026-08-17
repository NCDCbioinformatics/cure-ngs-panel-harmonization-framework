import json
from pathlib import Path

import pytest

from cure_ngs.models import Assembly
from cure_ngs.reference_bundle import inspect_reference_bundle, load_reference_bundle


def _write_config(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


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

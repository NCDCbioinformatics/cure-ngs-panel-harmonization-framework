import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "resources" / "components.lock.json"

EXPECTED_RELEASES = {
    "panel_VCF_vcf2maf_pipeline": "NCDC_batch_vcf2maf_V.1.3.3_github",
    "HGVS_to_minimal_MAF_pipeline": "minimal_maf_vep_hg38tohg19_V.1.0.3",
    "minimal_MAF_to_annotated_MAF_pipeline": "minimal_maf_to_vep_maf_V.1.0.2",
    "gene_name_harmonization": "gene_normalizer_human",
    "gene_fusion_normalizer": "gene_fusion_normalizer",
    "hgvs_normerlizer": "hgvsnorm-cli-0.2.2.tar",
}


def test_component_lock_pins_all_six_latest_release_tags() -> None:
    payload = json.loads(LOCK.read_text(encoding="utf-8"))
    observed = {
        component["repository"]: component["release"]["tag"]
        for component in payload["components"]
    }

    assert payload["schema_version"] == "1.0"
    assert payload["organization"] == "NCDCbioinformatics"
    assert observed == EXPECTED_RELEASES


def test_component_lock_pins_commits_and_release_asset_digests() -> None:
    payload = json.loads(LOCK.read_text(encoding="utf-8"))

    for component in payload["components"]:
        assert re.fullmatch(r"[0-9a-f]{40}", component["release"]["commit_sha"])
        assert component["assets"]
        for asset in component["assets"]:
            assert asset["size"] > 0
            assert re.fullmatch(r"[0-9a-f]{64}", asset["sha256"])

import hashlib
import json
from pathlib import Path

import pytest

from cure_ngs.resources import verify_profile_resources


def make_lock(tmp_path: Path, expected_hash: str) -> Path:
    lock = tmp_path / "resources.lock.json"
    lock.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "profiles": {
                    "test": {
                        "resources": {
                            "reference": {
                                "filename": "reference.fa",
                                "sha256": expected_hash,
                            }
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return lock


def test_resource_checksum_match(tmp_path: Path) -> None:
    resource = tmp_path / "reference.fa"
    resource.write_bytes(b">chr1\nACGT\n")
    expected = hashlib.sha256(resource.read_bytes()).hexdigest()

    results = verify_profile_resources(
        make_lock(tmp_path, expected),
        profile="test",
        supplied_paths={"reference": resource},
    )

    assert len(results) == 1
    assert results[0].valid


def test_resource_checksum_mismatch_fails(tmp_path: Path) -> None:
    resource = tmp_path / "reference.fa"
    resource.write_bytes(b">chr1\nACGT\n")

    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_profile_resources(
            make_lock(tmp_path, "0" * 64),
            profile="test",
            supplied_paths={"reference": resource},
        )

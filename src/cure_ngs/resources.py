from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .provenance import sha256_file


@dataclass(frozen=True)
class ResourceVerification:
    name: str
    path: str
    expected_sha256: str
    observed_sha256: str

    @property
    def valid(self) -> bool:
        return self.expected_sha256 == self.observed_sha256


def load_resource_lock(path: str | Path) -> dict[str, object]:
    lock_path = Path(path)
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0":
        raise ValueError("Unsupported or missing resource lock schema_version")
    if not isinstance(payload.get("profiles"), dict):
        raise ValueError("Resource lock has no profiles object")
    return payload


def verify_profile_resources(
    lock_path: str | Path,
    *,
    profile: str,
    supplied_paths: dict[str, str | Path],
) -> list[ResourceVerification]:
    payload = load_resource_lock(lock_path)
    profiles = payload["profiles"]
    if profile not in profiles:
        raise ValueError(f"Unknown resource profile: {profile}")
    profile_data = profiles[profile]
    resources = profile_data.get("resources")
    if not isinstance(resources, dict) or not resources:
        raise ValueError(f"Profile {profile!r} has no resources")

    missing = sorted(set(resources) - set(supplied_paths))
    unexpected = sorted(set(supplied_paths) - set(resources))
    if missing:
        raise ValueError(f"Missing resource paths: {', '.join(missing)}")
    if unexpected:
        raise ValueError(f"Unexpected resource paths: {', '.join(unexpected)}")

    results: list[ResourceVerification] = []
    for name in sorted(resources):
        path = Path(supplied_paths[name])
        if not path.is_file():
            raise FileNotFoundError(path)
        expected = resources[name].get("sha256")
        if not isinstance(expected, str) or len(expected) != 64:
            raise ValueError(f"Invalid SHA-256 in lock for {name}")
        result = ResourceVerification(
            name=name,
            path=str(path.resolve()),
            expected_sha256=expected,
            observed_sha256=sha256_file(path),
        )
        if not result.valid:
            raise ValueError(
                f"Resource checksum mismatch for {name}: "
                f"expected {result.expected_sha256}, observed {result.observed_sha256}"
            )
        results.append(result)
    return results


#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen


EXPECTED_REPOSITORIES = {
    "panel_VCF_vcf2maf_pipeline",
    "HGVS_to_minimal_MAF_pipeline",
    "minimal_MAF_to_annotated_MAF_pipeline",
    "gene_name_harmonization",
    "gene_fusion_normalizer",
    "hgvs_normerlizer",
}


def load_lock(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0":
        raise ValueError("component lock schema_version must be 1.0")
    if payload.get("organization") != "NCDCbioinformatics":
        raise ValueError("component lock organization must be NCDCbioinformatics")

    components = payload.get("components")
    if not isinstance(components, list):
        raise ValueError("component lock must contain a components list")
    repositories = {component.get("repository") for component in components}
    if repositories != EXPECTED_REPOSITORIES:
        raise ValueError(
            "component lock repositories differ from the six supported repositories"
        )

    sha_pattern = re.compile(r"[0-9a-f]{40}")
    digest_pattern = re.compile(r"[0-9a-f]{64}")
    for component in components:
        release = component.get("release")
        assets = component.get("assets")
        if not isinstance(release, dict) or not release.get("tag"):
            raise ValueError(f"missing release identity for {component['repository']}")
        if not sha_pattern.fullmatch(str(release.get("commit_sha", ""))):
            raise ValueError(f"invalid release commit for {component['repository']}")
        if not isinstance(assets, list) or not assets:
            raise ValueError(f"no release assets recorded for {component['repository']}")
        for asset in assets:
            if not digest_pattern.fullmatch(str(asset.get("sha256", ""))):
                raise ValueError(
                    f"invalid asset SHA-256 for {component['repository']}: "
                    f"{asset.get('name')}"
                )
            if not isinstance(asset.get("size"), int) or asset["size"] <= 0:
                raise ValueError(
                    f"invalid asset size for {component['repository']}: "
                    f"{asset.get('name')}"
                )
    return payload


def github_json(url: str, token: str | None) -> dict[str, object]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "cure-ngs-component-release-verifier",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def stream_sha256(url: str, token: str | None) -> tuple[int, str]:
    headers = {"User-Agent": "cure-ngs-component-release-verifier"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    digest = hashlib.sha256()
    size = 0
    with urlopen(request, timeout=120) as response:
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def verify_latest(
    payload: dict[str, object], *, token: str | None, verify_downloads: bool
) -> list[str]:
    organization = str(payload["organization"])
    failures: list[str] = []
    for component in payload["components"]:
        repository = component["repository"]
        release = component["release"]
        api_base = f"https://api.github.com/repos/{organization}/{repository}"
        latest = github_json(f"{api_base}/releases/latest", token)
        tag = str(latest["tag_name"])
        commit = github_json(f"{api_base}/commits/{quote(tag, safe='')}", token)

        checks = {
            "release id": (latest["id"], release["id"]),
            "tag": (tag, release["tag"]),
            "release name": (latest["name"], release["name"]),
            "published timestamp": (latest["published_at"], release["published_at"]),
            "release commit": (commit["sha"], release["commit_sha"]),
        }
        for label, (observed, expected) in checks.items():
            if observed != expected:
                failures.append(
                    f"{repository}: {label} drifted; observed={observed!r}, "
                    f"locked={expected!r}"
                )

        latest_assets = {asset["name"]: asset for asset in latest["assets"]}
        locked_assets = {asset["name"]: asset for asset in component["assets"]}
        if latest_assets.keys() != locked_assets.keys():
            failures.append(f"{repository}: release asset names drifted")
        for name, locked in locked_assets.items():
            observed = latest_assets.get(name)
            if observed is None:
                continue
            observed_digest = str(observed.get("digest") or "").removeprefix(
                "sha256:"
            )
            if observed["size"] != locked["size"]:
                failures.append(f"{repository}: size drifted for {name}")
            if observed_digest != locked["sha256"]:
                failures.append(f"{repository}: API digest drifted for {name}")
            if verify_downloads:
                size, digest = stream_sha256(locked["url"], token)
                if size != locked["size"] or digest != locked["sha256"]:
                    failures.append(f"{repository}: downloaded asset mismatch for {name}")

        print(f"OK {repository}: {release['tag']} @ {release['commit_sha']}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the six-component CURE-NGS GitHub Release lock."
    )
    parser.add_argument(
        "--lock",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "resources"
        / "components.lock.json",
    )
    parser.add_argument(
        "--check-latest",
        action="store_true",
        help="Compare the lock with each repository's current latest GitHub Release.",
    )
    parser.add_argument(
        "--verify-downloads",
        action="store_true",
        help="Stream every release asset and independently recompute its SHA-256.",
    )
    args = parser.parse_args()

    try:
        payload = load_lock(args.lock)
        if args.verify_downloads and not args.check_latest:
            parser.error("--verify-downloads requires --check-latest")
        failures = (
            verify_latest(
                payload,
                token=os.environ.get("GITHUB_TOKEN"),
                verify_downloads=args.verify_downloads,
            )
            if args.check_latest
            else []
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    print(f"Verified {len(payload['components'])} component release locks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

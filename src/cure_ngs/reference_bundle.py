from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Assembly
from .provenance import sha256_file


@dataclass(frozen=True)
class ResourceCandidate:
    label: str
    path: Path
    contig_style: str = "auto"
    target_reference_label: str | None = None
    sha256: str | None = None

    def to_dict(self) -> dict[str, str]:
        return {
            "label": self.label,
            "path": str(self.path),
            "contig_style": self.contig_style,
            **(
                {"target_reference_label": self.target_reference_label}
                if self.target_reference_label
                else {}
            ),
            **({"sha256": self.sha256} if self.sha256 else {}),
        }


@dataclass(frozen=True)
class LiftoverProfile:
    source_assembly: Assembly
    target_assembly: Assembly
    chains: tuple[ResourceCandidate, ...]
    target_reference_label: str | None = None


@dataclass(frozen=True)
class ReferenceBundle:
    config_path: Path
    root: Path
    target_assembly: Assembly
    fasta_candidates: dict[Assembly, tuple[ResourceCandidate, ...]]
    liftover_profiles: dict[tuple[Assembly, Assembly], LiftoverProfile]
    vep_data: Path
    cache_version: int
    unknown_assembly: Assembly | None
    allow_all_rejected_empty: bool
    output_contig_style: str

    def references_for(self, assembly: Assembly) -> tuple[ResourceCandidate, ...]:
        candidates = self.fasta_candidates.get(assembly, ())
        if not candidates:
            raise ValueError(
                f"No FASTA candidates are configured for {assembly.value}"
            )
        return candidates

    def liftover_for(
        self, source: Assembly, target: Assembly
    ) -> LiftoverProfile:
        try:
            return self.liftover_profiles[(source, target)]
        except KeyError as exc:
            raise ValueError(
                f"No liftover profile is configured for "
                f"{source.value}_to_{target.value}"
            ) from exc

    def to_dict(self) -> dict[str, object]:
        return {
            "config_path": str(self.config_path),
            "root": str(self.root),
            "target_assembly": self.target_assembly.value,
            "unknown_assembly": (
                self.unknown_assembly.value if self.unknown_assembly else None
            ),
            "allow_all_rejected_empty": self.allow_all_rejected_empty,
            "output_contig_style": self.output_contig_style,
            "vep": {
                "data": str(self.vep_data),
                "cache_version": self.cache_version,
            },
            "assemblies": {
                assembly.value: {
                    "fasta_candidates": [item.to_dict() for item in candidates]
                }
                for assembly, candidates in self.fasta_candidates.items()
            },
            "liftover": {
                f"{source.value}_to_{target.value}": {
                    "chains": [item.to_dict() for item in profile.chains],
                    "target_reference_label": profile.target_reference_label,
                }
                for (source, target), profile in self.liftover_profiles.items()
            },
        }


def _assembly(value: object, *, field: str) -> Assembly:
    try:
        return Assembly(str(value))
    except ValueError as exc:
        raise ValueError(f"{field} must be GRCh37 or GRCh38") from exc


def _resolve_path(value: object, *, root: Path, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty path string")
    expanded = Path(os.path.expandvars(os.path.expanduser(value)))
    return (expanded if expanded.is_absolute() else root / expanded).resolve()


def _candidate(
    value: object, *, root: Path, field: str, default_label: str
) -> ResourceCandidate:
    if isinstance(value, str):
        path_value = value
        label = default_label
        contig_style = "auto"
        target_reference_label = None
        checksum = None
    elif isinstance(value, dict):
        path_value = value.get("path")
        label = str(value.get("label") or default_label)
        contig_style = str(value.get("contig_style") or "auto").lower()
        target_reference_label = (
            str(value["target_reference_label"])
            if value.get("target_reference_label")
            else None
        )
        checksum = str(value["sha256"]).lower() if value.get("sha256") else None
    else:
        raise ValueError(f"{field} must be a path string or object")
    if contig_style not in {"auto", "ucsc", "numeric"}:
        raise ValueError(f"{field}.contig_style must be auto, ucsc, or numeric")
    if checksum is not None and not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError(f"{field}.sha256 must be a 64-character hexadecimal digest")
    return ResourceCandidate(
        label=label,
        path=_resolve_path(path_value, root=root, field=f"{field}.path"),
        contig_style=contig_style,
        target_reference_label=target_reference_label,
        sha256=checksum,
    )


def _require_object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"reference config field {key!r} must be an object")
    return value


def load_reference_bundle(
    config_path: str | Path, *, reference_root: str | Path | None = None
) -> ReferenceBundle:
    """Load a portable reference manifest whose data paths are root-relative."""

    config = Path(config_path).resolve()
    if not config.is_file():
        raise FileNotFoundError(config)
    try:
        payload = json.loads(config.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid reference config JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("reference config must contain a JSON object")
    if payload.get("schema_version") != "1.0":
        raise ValueError("reference config schema_version must be '1.0'")

    root_value = (
        reference_root
        or os.environ.get("CURE_NGS_REFERENCE_ROOT")
        or payload.get("reference_root")
        or config.parent
    )
    root_path = Path(os.path.expandvars(os.path.expanduser(str(root_value))))
    if not root_path.is_absolute():
        root_path = config.parent / root_path
    root = root_path.resolve()

    target = _assembly(
        payload.get("target_assembly", Assembly.GRCH37.value),
        field="target_assembly",
    )
    unknown_value = payload.get("unknown_assembly")
    unknown = (
        _assembly(unknown_value, field="unknown_assembly")
        if unknown_value is not None
        else None
    )
    output_contig_style = str(
        payload.get("output_contig_style", "numeric")
    ).lower()
    if output_contig_style not in {"numeric", "ucsc"}:
        raise ValueError("output_contig_style must be numeric or ucsc")

    assemblies_payload = _require_object(payload, "assemblies")
    fasta_candidates: dict[Assembly, tuple[ResourceCandidate, ...]] = {}
    for key, value in assemblies_payload.items():
        assembly = _assembly(key, field=f"assemblies.{key}")
        if not isinstance(value, dict):
            raise ValueError(f"assemblies.{key} must be an object")
        raw_candidates = value.get("fasta_candidates")
        if not isinstance(raw_candidates, list) or not raw_candidates:
            raise ValueError(
                f"assemblies.{key}.fasta_candidates must be a non-empty array"
            )
        candidates = tuple(
            _candidate(
                item,
                root=root,
                field=f"assemblies.{key}.fasta_candidates[{index}]",
                default_label=f"{assembly.value}-{index + 1}",
            )
            for index, item in enumerate(raw_candidates)
        )
        labels = [item.label for item in candidates]
        if len(labels) != len(set(labels)):
            raise ValueError(f"Duplicate FASTA label in assemblies.{key}")
        fasta_candidates[assembly] = candidates

    liftover_profiles: dict[tuple[Assembly, Assembly], LiftoverProfile] = {}
    liftover_payload = payload.get("liftover", {})
    if not isinstance(liftover_payload, dict):
        raise ValueError("liftover must be an object")
    for key, value in liftover_payload.items():
        if not isinstance(value, dict) or "_to_" not in key:
            raise ValueError(f"Invalid liftover profile: {key}")
        source_value, target_value = key.split("_to_", maxsplit=1)
        source = _assembly(source_value, field=f"liftover.{key}.source")
        profile_target = _assembly(target_value, field=f"liftover.{key}.target")
        raw_chains = value.get("chains")
        if not isinstance(raw_chains, list) or not raw_chains:
            raise ValueError(f"liftover.{key}.chains must be a non-empty array")
        chains = tuple(
            _candidate(
                item,
                root=root,
                field=f"liftover.{key}.chains[{index}]",
                default_label=f"{key}-{index + 1}",
            )
            for index, item in enumerate(raw_chains)
        )
        liftover_profiles[(source, profile_target)] = LiftoverProfile(
            source_assembly=source,
            target_assembly=profile_target,
            chains=chains,
            target_reference_label=(
                str(value["target_reference_label"])
                if value.get("target_reference_label")
                else None
            ),
        )

    for profile in liftover_profiles.values():
        if profile.target_assembly not in fasta_candidates:
            raise ValueError(
                f"Liftover target {profile.target_assembly.value} has no FASTA candidates"
            )
        target_labels = {
            item.label for item in fasta_candidates.get(profile.target_assembly, ())
        }
        requested = [
            label
            for label in (
                profile.target_reference_label,
                *(chain.target_reference_label for chain in profile.chains),
            )
            if label
        ]
        missing = sorted(set(requested) - target_labels)
        if missing:
            raise ValueError(
                f"Liftover profile references unknown {profile.target_assembly.value} "
                f"FASTA labels: {', '.join(missing)}"
            )

    vep = _require_object(payload, "vep")
    cache_version = vep.get("cache_version")
    if not isinstance(cache_version, int) or cache_version < 1:
        raise ValueError("vep.cache_version must be a positive integer")
    vep_data = _resolve_path(vep.get("data"), root=root, field="vep.data")

    policies = payload.get("policies", {})
    if not isinstance(policies, dict):
        raise ValueError("policies must be an object")
    allow_all_rejected_empty = policies.get("allow_all_rejected_empty", False)
    if not isinstance(allow_all_rejected_empty, bool):
        raise ValueError("policies.allow_all_rejected_empty must be boolean")

    return ReferenceBundle(
        config_path=config,
        root=root,
        target_assembly=target,
        fasta_candidates=fasta_candidates,
        liftover_profiles=liftover_profiles,
        vep_data=vep_data,
        cache_version=cache_version,
        unknown_assembly=unknown,
        allow_all_rejected_empty=allow_all_rejected_empty,
        output_contig_style=output_contig_style,
    )


def inspect_reference_bundle(bundle: ReferenceBundle) -> dict[str, object]:
    checks: list[dict[str, str]] = []

    def check_file(name: str, path: Path, expected_sha256: str | None = None) -> None:
        present = path.is_file() and path.stat().st_size > 0
        checks.append(
            {
                "name": name,
                "status": "PASS" if present else "FAIL",
                "detail": str(path),
            }
        )
        if present and expected_sha256:
            observed = sha256_file(path)
            checks.append(
                {
                    "name": f"sha256:{name}",
                    "status": "PASS" if observed == expected_sha256 else "FAIL",
                    "detail": f"expected={expected_sha256}; observed={observed}",
                }
            )

    checks.append(
        {
            "name": "reference_root",
            "status": "PASS" if bundle.root.is_dir() else "FAIL",
            "detail": str(bundle.root),
        }
    )
    for assembly, candidates in bundle.fasta_candidates.items():
        for candidate in candidates:
            prefix = f"{assembly.value}:{candidate.label}"
            check_file(f"fasta:{prefix}", candidate.path, candidate.sha256)
            check_file(f"fai:{prefix}", Path(f"{candidate.path}.fai"))
    for profile in bundle.liftover_profiles.values():
        for chain in profile.chains:
            check_file(
                f"chain:{profile.source_assembly.value}_to_"
                f"{profile.target_assembly.value}:{chain.label}",
                chain.path,
                chain.sha256,
            )
            label = chain.target_reference_label or profile.target_reference_label
            target_candidates = bundle.references_for(profile.target_assembly)
            target_reference = next(
                (item for item in target_candidates if item.label == label),
                target_candidates[0],
            )
            check_file(
                f"dict:{profile.target_assembly.value}:{target_reference.label}",
                target_reference.path.with_suffix(".dict"),
            )
    checks.append(
        {
            "name": "vep_data",
            "status": "PASS" if bundle.vep_data.is_dir() else "FAIL",
            "detail": str(bundle.vep_data),
        }
    )
    cache = (
        bundle.vep_data
        / "homo_sapiens"
        / f"{bundle.cache_version}_{bundle.target_assembly.value}"
    )
    checks.append(
        {
            "name": "vep_cache",
            "status": "PASS" if cache.is_dir() else "FAIL",
            "detail": str(cache),
        }
    )
    failed = sum(item["status"] == "FAIL" for item in checks)
    return {
        "status": "READY" if failed == 0 else "NOT_READY",
        "failed_checks": failed,
        "bundle": bundle.to_dict(),
        "checks": checks,
    }

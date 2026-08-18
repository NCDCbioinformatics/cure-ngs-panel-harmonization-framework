from __future__ import annotations

import gzip
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Assembly
from .provenance import sha256_file


_PRIMARY_CONTIG_LENGTH = {
    Assembly.GRCH37: 249_250_621,
    Assembly.GRCH38: 248_956_422,
}


def reference_config_template(
    *, reference_root: str, cache_version: int = 116
) -> dict[str, object]:
    """Return the standard multi-reference GRCh37-target bundle template."""

    if not reference_root.strip():
        raise ValueError("reference_root must be a non-empty path")
    if cache_version < 1:
        raise ValueError("cache_version must be a positive integer")
    return {
        "schema_version": "1.0",
        "reference_root": reference_root,
        "target_assembly": "GRCh37",
        "unknown_assembly": "GRCh37",
        "output_contig_style": "numeric",
        "assemblies": {
            "GRCh37": {
                "fasta_candidates": [
                    {
                        "label": "hg19_genome",
                        "path": "grch37/hg19.fa",
                        "contig_style": "ucsc",
                    },
                    {
                        "label": "GATK_assembly19",
                        "path": "grch37/Homo_sapiens_assembly19.fasta",
                        "contig_style": "numeric",
                    },
                    {
                        "label": "Ensembl_GRCh37_toplevel",
                        "path": "grch37/Homo_sapiens.GRCh37.dna.toplevel.fa",
                        "contig_style": "numeric",
                    },
                ]
            }
        },
        "liftover": {
            "GRCh38_to_GRCh37": {
                "chains": [
                    {
                        "label": "UCSC_hg38ToHg19",
                        "path": "liftover/hg38ToHg19.over.chain.gz",
                        "contig_style": "ucsc",
                        "target_reference_label": "hg19_genome",
                    },
                    {
                        "label": "Ensembl_GRCh38_to_GRCh37",
                        "path": "liftover/GRCh38_to_GRCh37.chain.gz",
                        "contig_style": "numeric",
                        "target_reference_label": "GATK_assembly19",
                    },
                ]
            }
        },
        "vep": {"data": "vep", "cache_version": cache_version},
        "policies": {"allow_all_rejected_empty": False},
    }


def write_reference_config_template(
    output_path: str | Path,
    *,
    reference_root: str,
    cache_version: int = 116,
    force: bool = False,
) -> Path:
    """Create a user-selected reference config without overwriting by default."""

    output = Path(output_path).expanduser().resolve()
    if output.exists() and not force:
        raise FileExistsError(
            f"Reference config already exists: {output}; pass --force to replace it"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = reference_config_template(
        reference_root=reference_root, cache_version=cache_version
    )
    output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output


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
                f"Liftover target {profile.target_assembly.value} has no "
                "FASTA candidates"
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


def _contig_style(name: str) -> str:
    return "ucsc" if name.casefold().startswith("chr") else "numeric"


def _is_primary_chromosome_one(name: str) -> bool:
    return re.sub(r"^chr", "", name, flags=re.IGNORECASE) == "1"


def _primary_fai_entry(path: Path) -> tuple[str, int]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) >= 2 and _is_primary_chromosome_one(fields[0]):
                return fields[0], int(fields[1])
    raise ValueError("chromosome 1 is absent from the FASTA index")


def _primary_dict_entry(path: Path) -> tuple[str, int]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.startswith("@SQ\t"):
                continue
            values = {
                field.split(":", maxsplit=1)[0]: field.split(":", maxsplit=1)[1]
                for field in line.rstrip("\n").split("\t")[1:]
                if ":" in field
            }
            name = values.get("SN", "")
            if _is_primary_chromosome_one(name):
                return name, int(values["LN"])
    raise ValueError("chromosome 1 is absent from the sequence dictionary")


def _primary_chain_entry(path: Path) -> tuple[str, int, str, int]:
    opener = gzip.open if path.suffix.casefold() == ".gz" else Path.open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.startswith("chain "):
                continue
            fields = line.rstrip("\n").split()
            if len(fields) != 13:
                continue
            source_name, source_length = fields[2], int(fields[3])
            target_name, target_length = fields[7], int(fields[8])
            if _is_primary_chromosome_one(
                source_name
            ) and _is_primary_chromosome_one(target_name):
                return source_name, source_length, target_name, target_length
    raise ValueError("no chromosome-1 chain header was found")


def _vep_cache_metadata(path: Path) -> dict[str, str]:
    metadata: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            key, separator, value = line.rstrip("\n").partition("\t")
            if separator:
                metadata[key] = value
    return metadata


def inspect_reference_bundle(
    bundle: ReferenceBundle,
    *,
    runtime_vep: dict[str, str] | None = None,
) -> dict[str, object]:
    checks: list[dict[str, str]] = []
    fasta_styles: dict[tuple[Assembly, str], str] = {}

    def add_check(name: str, passed: bool, detail: str) -> None:
        checks.append(
            {
                "name": name,
                "status": "PASS" if passed else "FAIL",
                "detail": detail,
            }
        )

    def check_file(name: str, path: Path, expected_sha256: str | None = None) -> None:
        present = path.is_file() and path.stat().st_size > 0
        add_check(name, present, str(path))
        if present and expected_sha256:
            observed = sha256_file(path)
            add_check(
                f"sha256:{name}",
                observed == expected_sha256,
                f"expected={expected_sha256}; observed={observed}",
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
            fai = Path(f"{candidate.path}.fai")
            check_file(f"fai:{prefix}", fai)
            if fai.is_file() and fai.stat().st_size > 0:
                try:
                    name, length = _primary_fai_entry(fai)
                    expected_length = _PRIMARY_CONTIG_LENGTH[assembly]
                    add_check(
                        f"assembly:{prefix}",
                        length == expected_length,
                        f"chromosome={name}; observed_length={length}; "
                        f"expected_{assembly.value}_length={expected_length}",
                    )
                    observed_style = _contig_style(name)
                    fasta_styles[(assembly, candidate.label)] = observed_style
                    add_check(
                        f"contig_style:{prefix}",
                        candidate.contig_style in {"auto", observed_style},
                        f"configured={candidate.contig_style}; "
                        f"observed={observed_style}; chromosome={name}",
                    )
                except (OSError, ValueError) as exc:
                    add_check(f"assembly:{prefix}", False, str(exc))
    for profile in bundle.liftover_profiles.values():
        for chain in profile.chains:
            profile_name = (
                f"{profile.source_assembly.value}_to_"
                f"{profile.target_assembly.value}:{chain.label}"
            )
            check_file(f"chain:{profile_name}", chain.path, chain.sha256)
            label = chain.target_reference_label or profile.target_reference_label
            target_candidates = bundle.references_for(profile.target_assembly)
            target_reference = next(
                (item for item in target_candidates if item.label == label),
                target_candidates[0],
            )
            check_file(
                f"dict:{profile.target_assembly.value}:{target_reference.label}",
                dictionary := target_reference.path.with_suffix(".dict"),
            )
            if dictionary.is_file() and dictionary.stat().st_size > 0:
                try:
                    dict_name, dict_length = _primary_dict_entry(dictionary)
                    expected_length = _PRIMARY_CONTIG_LENGTH[profile.target_assembly]
                    add_check(
                        f"dict_assembly:{profile.target_assembly.value}:"
                        f"{target_reference.label}",
                        dict_length == expected_length,
                        f"chromosome={dict_name}; observed_length={dict_length}; "
                        f"expected_{profile.target_assembly.value}_length="
                        f"{expected_length}",
                    )
                except (OSError, ValueError, KeyError) as exc:
                    add_check(
                        f"dict_assembly:{profile.target_assembly.value}:"
                        f"{target_reference.label}",
                        False,
                        str(exc),
                    )
            if chain.path.is_file() and chain.path.stat().st_size > 0:
                try:
                    source_name, source_length, target_name, target_length = (
                        _primary_chain_entry(chain.path)
                    )
                    expected_source = _PRIMARY_CONTIG_LENGTH[
                        profile.source_assembly
                    ]
                    expected_target = _PRIMARY_CONTIG_LENGTH[
                        profile.target_assembly
                    ]
                    add_check(
                        f"chain_direction:{profile_name}",
                        source_length == expected_source
                        and target_length == expected_target,
                        f"source={source_name}:{source_length} "
                        f"(expected {profile.source_assembly.value}:"
                        f"{expected_source}); target={target_name}:"
                        f"{target_length} (expected "
                        f"{profile.target_assembly.value}:{expected_target})",
                    )
                    source_style = _contig_style(source_name)
                    add_check(
                        f"chain_source_style:{profile_name}",
                        chain.contig_style in {"auto", source_style},
                        f"configured={chain.contig_style}; "
                        f"observed={source_style}; chromosome={source_name}",
                    )
                    target_style = _contig_style(target_name)
                    reference_style = fasta_styles.get(
                        (profile.target_assembly, target_reference.label),
                        target_reference.contig_style,
                    )
                    add_check(
                        f"chain_target_style:{profile_name}",
                        reference_style == "auto" or target_style == reference_style,
                        f"chain_target={target_style}; "
                        f"target_reference={target_reference.label}:"
                        f"{reference_style}",
                    )
                except (OSError, ValueError) as exc:
                    add_check(f"chain_direction:{profile_name}", False, str(exc))
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
    info = cache / "info.txt"
    check_file("vep_cache_info", info)
    if info.is_file() and info.stat().st_size > 0:
        try:
            metadata = _vep_cache_metadata(info)
            observed_assembly = metadata.get("assembly", "")
            observed_species = metadata.get("species", "")
            add_check(
                "vep_cache_identity",
                observed_assembly == bundle.target_assembly.value
                and observed_species == "homo_sapiens",
                f"species={observed_species or 'missing'}; "
                f"assembly={observed_assembly or 'missing'}; "
                f"directory_version={bundle.cache_version}",
            )
        except OSError as exc:
            add_check("vep_cache_identity", False, str(exc))
    primary_cache = next(
        (path for path in (cache / "1", cache / "chr1") if path.is_dir()),
        None,
    )
    cache_has_payload = primary_cache is not None and any(
        item.is_file() and item.stat().st_size > 0
        for item in primary_cache.rglob("*")
    )
    add_check(
        "vep_cache_payload",
        cache_has_payload,
        str(primary_cache or cache / "{1,chr1}"),
    )
    if runtime_vep is not None:
        runtime_status = runtime_vep.get("status")
        runtime_version = runtime_vep.get("version", "")
        version_match = re.search(
            r"ensembl-vep\s*:\s*(\d+)", runtime_version, re.IGNORECASE
        )
        observed_version = int(version_match.group(1)) if version_match else None
        add_check(
            "vep_runtime_cache_compatibility",
            runtime_status == "available"
            and observed_version == bundle.cache_version,
            f"runtime_status={runtime_status or 'missing'}; "
            f"runtime_version={runtime_version or 'unknown'}; "
            f"configured_cache_version={bundle.cache_version}",
        )
    failed = sum(item["status"] == "FAIL" for item in checks)
    return {
        "status": "READY" if failed == 0 else "NOT_READY",
        "failed_checks": failed,
        "bundle": bundle.to_dict(),
        "checks": checks,
    }

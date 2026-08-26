from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from .batch import prepare_v133_workspace


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def default_tutorial_data_root() -> Path:
    configured = os.environ.get("CURE_NGS_TUTORIAL_DATA")
    if configured:
        return Path(configured)

    image_root = Path("/opt/cure-ngs/examples/component-tests")
    if image_root.is_dir():
        return image_root

    source_root = Path(__file__).resolve().parents[2] / "examples" / "component-tests"
    if source_root.is_dir():
        return source_root

    raise FileNotFoundError(
        "Bundled component test data were not found. Use the official Docker "
        "image or set CURE_NGS_TUTORIAL_DATA to examples/component-tests."
    )


def load_tutorial_manifest(source: str | Path | None = None) -> tuple[Path, dict[str, object]]:
    root = Path(source) if source is not None else default_tutorial_data_root()
    manifest_path = root / "manifest.json"
    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest.get("schema_version") != "1.0":
        raise ValueError("Unsupported tutorial-data manifest schema")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("Tutorial-data manifest has no files")
    return root, manifest


def _safe_relative_path(value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("Tutorial-data file path must be a non-empty string")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe tutorial-data file path: {value!r}")
    return path


def verify_tutorial_data(source: str | Path | None = None) -> dict[str, object]:
    root, manifest = load_tutorial_manifest(source)
    verified: list[dict[str, object]] = []
    for entry in manifest["files"]:
        if not isinstance(entry, dict):
            raise ValueError("Tutorial-data file entry must be an object")
        relative = _safe_relative_path(entry.get("path"))
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(f"Bundled tutorial file is missing: {relative}")
        expected_size = entry.get("bytes")
        if not isinstance(expected_size, int) or path.stat().st_size != expected_size:
            raise ValueError(f"Size mismatch for bundled tutorial file: {relative}")
        expected_hash = entry.get("sha256")
        if not isinstance(expected_hash, str) or _sha256(path) != expected_hash:
            raise ValueError(f"SHA-256 mismatch for bundled tutorial file: {relative}")
        verified.append(
            {"path": relative.as_posix(), "bytes": expected_size, "sha256": expected_hash}
        )
    return {
        "status": "VALID",
        "bundle_version": manifest.get("bundle_version"),
        "source": str(root.resolve()),
        "file_count": len(verified),
        "files": verified,
    }


def export_tutorial_data(
    output: str | Path,
    *,
    source: str | Path | None = None,
    force: bool = False,
) -> dict[str, object]:
    root, manifest = load_tutorial_manifest(source)
    verification = verify_tutorial_data(root)
    destination = Path(output)
    if destination.exists() and any(destination.iterdir()) and not force:
        raise FileExistsError(
            f"Output directory is not empty: {destination}; pass --force to overwrite bundled files"
        )
    destination.mkdir(parents=True, exist_ok=True)

    for name in ("README.md", "manifest.json"):
        shutil.copy2(root / name, destination / name)
    for entry in manifest["files"]:
        relative = _safe_relative_path(entry["path"])
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, target)
        if _sha256(target) != entry["sha256"]:
            raise OSError(f"Exported tutorial file failed SHA-256 verification: {relative}")

    return {
        "status": "EXPORTED",
        "bundle_version": manifest.get("bundle_version"),
        "output": str(destination.resolve()),
        "file_count": verification["file_count"],
        "components": len(manifest.get("components", [])),
    }


def export_v133_example_workspace(
    output: str | Path,
    *,
    source: str | Path | None = None,
    force: bool = False,
) -> dict[str, object]:
    """Export the public 25-record VCF/MAF pair in the paper's folder layout.

    This is an inspectable reference snapshot, not a substitute for executing
    ``batch-vcf-to-maf --workspace-root`` with a configured VEP bundle.
    """

    source_root, _ = load_tutorial_manifest(source)
    verify_tutorial_data(source_root)
    workspace = prepare_v133_workspace(output)
    input_target = workspace.input_directory / "test_b37.vcf"
    maf_target = workspace.maf_directory / "test_b37.maf"
    log_target = workspace.log_directory / "vcf2maf_batch_log.tsv"
    snapshot_manifest = workspace.log_directory / "reference-output.json"
    targets = (input_target, maf_target, log_target, snapshot_manifest)
    existing = [path for path in targets if path.exists()]
    if existing and not force:
        raise FileExistsError(
            "Example workspace files already exist: "
            + ", ".join(str(path) for path in existing)
            + "; pass --force to overwrite only these bundled example files"
        )

    shutil.copy2(source_root / "inputs" / "test_b37.vcf", input_target)
    shutil.copy2(source_root / "expected" / "test_b37.maf", maf_target)
    log_target.write_text(
        "datetime\tvcf_path\tsample_tag8\tref_info\tis_gvcf\thas_normal\t"
        "status\tmessage\tfinal_vcf\n"
        "BUNDLED_REFERENCE\tVCF_ALL/test_b37.vcf\ttest_b37\tGRCh37\t0\t1\t"
        "REFERENCE_OUTPUT\tvalidated 25-row public reference MAF; run the full "
        "image to reproduce annotation\tVCF_ALL/test_b37.vcf\n",
        encoding="utf-8",
        newline="\n",
    )
    payload = {
        "schema_version": "1.0",
        "status": "REFERENCE_SNAPSHOT",
        "note": (
            "The MAF was copied from the validated public component fixture. "
            "It was not re-annotated by this export command."
        ),
        "input": {
            "path": "VCF_ALL/test_b37.vcf",
            "records": 25,
            "sha256": _sha256(input_target),
        },
        "reference_output": {
            "path": "VCF_ALL_MAF/test_b37.maf",
            "rows": 25,
            "sha256": _sha256(maf_target),
        },
        "full_run_command": (
            "cure-ngs batch-vcf-to-maf --workspace-root /data/KOSMOS_VCF "
            "--reference-config /references/reference-config.json"
        ),
    }
    snapshot_manifest.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {
        **payload,
        "workspace": workspace.to_dict(),
        "input_file": str(input_target.resolve()),
        "reference_maf": str(maf_target.resolve()),
        "log_tsv": str(log_target.resolve()),
    }

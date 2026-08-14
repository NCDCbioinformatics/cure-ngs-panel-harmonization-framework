from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(
    path: str | Path,
    *,
    command: list[str],
    inputs: dict[str, str | Path],
    outputs: dict[str, str | Path],
    parameters: dict[str, Any],
    tools: dict[str, str],
) -> Path:
    manifest_path = Path(path)
    payload = {
        "schema_version": "1.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "cure_ngs_version": __version__,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "command": command,
        "parameters": parameters,
        "tools": tools,
        "inputs": {
            name: {
                "path": str(Path(value).resolve()),
                "sha256": sha256_file(value),
            }
            for name, value in inputs.items()
        },
        "outputs": {
            name: {
                "path": str(Path(value).resolve()),
                "sha256": sha256_file(value),
            }
            for name, value in outputs.items()
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest_path


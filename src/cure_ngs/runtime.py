from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .liftover import java_version, picard_version
from .provenance import sha256_file
from .tools import tool_version


def _optional_executable_version(name: str, executable: str) -> dict[str, str]:
    if shutil.which(executable) is None:
        return {"status": "unavailable", "executable": executable}
    try:
        return {
            "status": "available",
            "executable": executable,
            "version": tool_version(executable),
        }
    except (OSError, subprocess.CalledProcessError, IndexError) as exc:
        return {"status": "error", "executable": executable, "error": str(exc)}


def _vep_version(executable: str) -> dict[str, str]:
    if shutil.which(executable) is None:
        return {"status": "unavailable", "executable": executable}
    try:
        result = subprocess.run(
            [executable, "--help"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        lines = (result.stdout or result.stderr).splitlines()
        version_line = next(
            (line.strip() for line in lines if "ensembl-vep" in line), "unknown"
        )
        return {
            "status": "available",
            "executable": executable,
            "version": version_line,
        }
    except (OSError, subprocess.CalledProcessError) as exc:
        return {"status": "error", "executable": executable, "error": str(exc)}


def runtime_versions(
    *,
    bcftools: str = "bcftools",
    samtools: str = "samtools",
    vep: str = "vep",
    perl: str = "perl",
    java: str = "java",
    picard_jar: str | None = None,
    vcf2maf: str | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "cure_ngs": {"status": "available", "version": __version__},
        "python": {"status": "available", "version": sys.version.split()[0]},
        "bcftools": _optional_executable_version("bcftools", bcftools),
        "samtools": _optional_executable_version("samtools", samtools),
        "vep": _vep_version(vep),
        "perl": _optional_executable_version("perl", perl),
    }

    if shutil.which(java) is None:
        result["java"] = {"status": "unavailable", "executable": java}
    else:
        try:
            result["java"] = {
                "status": "available",
                "executable": java,
                "version": java_version(java),
            }
        except (OSError, subprocess.CalledProcessError, IndexError) as exc:
            result["java"] = {"status": "error", "error": str(exc)}

    picard_path = picard_jar or os.environ.get("PICARD_JAR")
    if picard_path and Path(picard_path).is_file():
        result["picard"] = {
            "status": "available",
            "path": picard_path,
            "version": picard_version(picard_path),
            "sha256": sha256_file(picard_path),
        }
    else:
        result["picard"] = {"status": "unavailable", "path": picard_path}

    vcf2maf_path = vcf2maf or os.environ.get("VCF2MAF_PATH")
    if vcf2maf_path and Path(vcf2maf_path).is_file():
        result["vcf2maf"] = {
            "status": "available",
            "path": vcf2maf_path,
            "revision": os.environ.get("VCF2MAF_REVISION", "unknown"),
            "sha256": sha256_file(vcf2maf_path),
        }
    else:
        result["vcf2maf"] = {"status": "unavailable", "path": vcf2maf_path}
    return result

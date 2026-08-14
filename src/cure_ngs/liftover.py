from __future__ import annotations

import re
import subprocess
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

from .models import Assembly
from .provenance import sha256_file
from .vcf import inspect_vcf


@dataclass(frozen=True)
class LiftoverRun:
    command: tuple[str, ...]
    input_records: int
    accepted_records: int
    rejected_records: int
    source_assembly: str
    target_assembly: str
    java_version: str
    picard_version: str
    picard_sha256: str
    chain_sha256: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def picard_version(path: str | Path) -> str:
    with zipfile.ZipFile(path) as archive:
        manifest = archive.read("META-INF/MANIFEST.MF").decode("utf-8", errors="replace")
    for key in ("Implementation-Version", "Bundle-Version"):
        match = re.search(rf"^{key}:\s*(.+)$", manifest, flags=re.MULTILINE)
        if match:
            return match.group(1).strip()
    return "unknown"


def java_version(executable: str = "java") -> str:
    result = subprocess.run(
        [executable, "--version"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return (result.stdout or result.stderr).splitlines()[0].strip()


def liftover_vcf(
    input_path: str | Path,
    output_path: str | Path,
    *,
    rejected_path: str | Path,
    source_assembly: Assembly,
    target_assembly: Assembly,
    chain_path: str | Path,
    target_reference: str | Path,
    picard_jar: str | Path,
    java: str = "java",
) -> LiftoverRun:
    if source_assembly == target_assembly:
        raise ValueError("Source and target assemblies must differ for liftover")

    input_path = Path(input_path)
    output_path = Path(output_path)
    rejected_path = Path(rejected_path)
    chain_path = Path(chain_path)
    target_reference = Path(target_reference)
    picard_jar = Path(picard_jar)
    for path in (input_path, chain_path, target_reference, picard_jar):
        if not path.is_file():
            raise FileNotFoundError(path)

    before = inspect_vcf(input_path, assembly_override=source_assembly)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rejected_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        java,
        "-jar",
        str(picard_jar),
        "LiftoverVcf",
        f"I={input_path}",
        f"O={output_path}",
        f"CHAIN={chain_path}",
        f"REJECT={rejected_path}",
        f"R={target_reference}",
        "WARN_ON_MISSING_CONTIG=true",
        "RECOVER_SWAPPED_REF_ALT=false",
        "WRITE_ORIGINAL_POSITION=true",
        "WRITE_ORIGINAL_ALLELES=true",
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)

    accepted = inspect_vcf(output_path, require_assembly=False)
    rejected = inspect_vcf(rejected_path, require_assembly=False)
    if accepted.record_count + rejected.record_count != before.record_count:
        raise ValueError(
            "Liftover accounting mismatch: "
            f"input={before.record_count}, accepted={accepted.record_count}, "
            f"rejected={rejected.record_count}"
        )
    if before.record_count > 0 and accepted.record_count == 0:
        raise ValueError(
            "FAILED_LIFTOVER_ALL_REJECTED: every input variant was rejected"
        )

    return LiftoverRun(
        command=tuple(command),
        input_records=before.record_count,
        accepted_records=accepted.record_count,
        rejected_records=rejected.record_count,
        source_assembly=source_assembly.value,
        target_assembly=target_assembly.value,
        java_version=java_version(java),
        picard_version=picard_version(picard_jar),
        picard_sha256=sha256_file(picard_jar),
        chain_sha256=sha256_file(chain_path),
    )

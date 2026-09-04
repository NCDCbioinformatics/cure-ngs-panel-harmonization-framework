from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class Assembly(str, Enum):
    GRCH37 = "GRCh37"
    GRCH38 = "GRCh38"


class InspectionStatus(str, Enum):
    VALID = "VALID"
    VALID_EMPTY = "VALID_EMPTY"


@dataclass(frozen=True)
class VcfInspection:
    path: str
    status: InspectionStatus
    assembly: Assembly | None
    assembly_evidence: tuple[str, ...]
    sample_names: tuple[str, ...]
    record_count: int
    alternate_allele_count: int
    multiallelic_record_count: int
    symbolic_allele_count: int

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        result["assembly"] = self.assembly.value if self.assembly else None
        result["assembly_evidence"] = list(self.assembly_evidence)
        result["sample_names"] = list(self.sample_names)
        return result


class VcfFormatError(ValueError):
    """Raised when a file is not a structurally valid VCF."""


class AssemblyDetectionError(ValueError):
    """Raised when assembly evidence is absent or contradictory."""


class AssemblyUndeterminedError(AssemblyDetectionError):
    """Raised when no usable assembly evidence is present."""


class AssemblyEvidenceConflictError(AssemblyDetectionError):
    """Raised when VCF metadata supports more than one genome assembly."""


from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FastaIndexEntry:
    name: str
    length: int
    offset: int
    line_bases: int
    line_width: int


class FastaReference:
    """Random-access FASTA reader backed by a samtools-compatible .fai index."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        index_path = Path(f"{self.path}.fai")
        if not index_path.is_file():
            raise FileNotFoundError(
                f"FASTA index is missing: {index_path}; run samtools faidx first"
            )
        self.entries = self._read_index(index_path)

    @staticmethod
    def _read_index(path: Path) -> dict[str, FastaIndexEntry]:
        entries: dict[str, FastaIndexEntry] = {}
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            fields = line.split("\t")
            if len(fields) < 5:
                raise ValueError(f"Invalid FASTA index line {line_number}: {line!r}")
            entry = FastaIndexEntry(
                name=fields[0],
                length=int(fields[1]),
                offset=int(fields[2]),
                line_bases=int(fields[3]),
                line_width=int(fields[4]),
            )
            if entry.name in entries:
                raise ValueError(f"Duplicate FASTA contig in index: {entry.name}")
            entries[entry.name] = entry
        if not entries:
            raise ValueError(f"FASTA index is empty: {path}")
        return entries

    def resolve_contig(self, chromosome: str) -> str:
        chromosome = chromosome.strip()
        candidates = [chromosome]
        if chromosome.lower().startswith("chr"):
            candidates.append(chromosome[3:])
        else:
            candidates.append(f"chr{chromosome}")
        if chromosome in {"M", "MT", "chrM", "chrMT"}:
            candidates.extend(["M", "MT", "chrM", "chrMT"])
        matches = [candidate for candidate in dict.fromkeys(candidates) if candidate in self.entries]
        if len(matches) != 1:
            if not matches:
                raise KeyError(f"Chromosome {chromosome!r} is absent from the FASTA index")
            raise KeyError(
                f"Chromosome {chromosome!r} is ambiguous in the FASTA index: {matches}"
            )
        return matches[0]

    def fetch(self, chromosome: str, start: int, end: int) -> str:
        contig = self.resolve_contig(chromosome)
        entry = self.entries[contig]
        if start < 1 or end < start or end > entry.length:
            raise ValueError(
                f"Invalid FASTA interval {contig}:{start}-{end}; contig length={entry.length}"
            )

        start_zero = start - 1
        end_zero = end - 1
        byte_start = (
            entry.offset
            + (start_zero // entry.line_bases) * entry.line_width
            + (start_zero % entry.line_bases)
        )
        byte_end = (
            entry.offset
            + (end_zero // entry.line_bases) * entry.line_width
            + (end_zero % entry.line_bases)
        )
        bytes_to_read = byte_end - byte_start + 1
        with self.path.open("rb") as handle:
            handle.seek(byte_start)
            raw = handle.read(bytes_to_read)
        sequence = raw.replace(b"\n", b"").replace(b"\r", b"").decode("ascii")
        expected_length = end - start + 1
        if len(sequence) != expected_length:
            raise ValueError(
                f"Could not read complete FASTA interval {contig}:{start}-{end}"
            )
        return sequence.upper()


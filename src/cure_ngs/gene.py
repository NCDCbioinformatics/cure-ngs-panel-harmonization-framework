from __future__ import annotations

import csv
import difflib
import gzip
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TextIO


@dataclass(frozen=True)
class GeneResolution:
    token: str
    matched_symbol: str | None
    ensembl_gene_ids: tuple[str, ...]
    match_type: str
    score: float | None = None
    candidates: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _open_text(path: Path) -> TextIO:
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", errors="strict")
    return path.open("r", encoding="utf-8-sig", errors="strict")


def parse_gtf_gene_map(path: str | Path) -> tuple[dict[str, set[str]], dict[str, str]]:
    names_to_ids: dict[str, set[str]] = defaultdict(set)
    ids_to_names: dict[str, str] = {}
    with _open_text(Path(path)) as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line or line.startswith("#"):
                continue
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) != 9:
                raise ValueError(f"Invalid GTF column count at line {line_number}")
            if fields[2] != "gene":
                continue
            gene_id = re.search(r'(?:^|;)\s*gene_id\s+"([^"]+)"', fields[8])
            gene_name = re.search(r'(?:^|;)\s*gene_name\s+"([^"]+)"', fields[8])
            if not gene_id or not gene_name:
                continue
            identifier = gene_id.group(1)
            symbol = gene_name.group(1)
            names_to_ids[symbol.casefold()].add(identifier)
            ids_to_names[identifier] = symbol
    if not ids_to_names:
        raise ValueError("GTF contains no gene features with gene_id and gene_name")
    return dict(names_to_ids), ids_to_names


def parse_hgnc_aliases(path: str | Path) -> tuple[dict[str, set[str]], set[str]]:
    aliases: dict[str, set[str]] = defaultdict(set)
    canonical_symbols: set[str] = set()
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames or "symbol" not in reader.fieldnames:
            raise ValueError("HGNC table must contain a 'symbol' column")
        for row in reader:
            canonical = (row.get("symbol") or "").strip()
            if not canonical:
                continue
            canonical_symbols.add(canonical)
            aliases[canonical.casefold()].add(canonical)
            for column in ("alias_symbol", "prev_symbol"):
                value = row.get(column) or ""
                for alias in re.split(r"[|,;]", value):
                    alias = alias.strip()
                    if alias:
                        aliases[alias.casefold()].add(canonical)
    return dict(aliases), canonical_symbols


class GeneCatalog:
    def __init__(
        self,
        names_to_ids: dict[str, set[str]],
        ids_to_names: dict[str, str],
        aliases: dict[str, set[str]],
    ) -> None:
        self.names_to_ids = names_to_ids
        self.ids_to_names = ids_to_names
        self.aliases = aliases
        self._universe = tuple(sorted(set(names_to_ids) | set(aliases)))

    @classmethod
    def from_files(cls, *, gtf: str | Path, hgnc: str | Path) -> "GeneCatalog":
        names_to_ids, ids_to_names = parse_gtf_gene_map(gtf)
        aliases, _ = parse_hgnc_aliases(hgnc)
        return cls(names_to_ids, ids_to_names, aliases)

    def _canonical_result(
        self, token: str, canonical: str, match_type: str, score: float | None = None
    ) -> GeneResolution:
        ids = tuple(sorted(self.names_to_ids.get(canonical.casefold(), set())))
        return GeneResolution(token, canonical, ids, match_type, score)

    def resolve(
        self,
        token: str,
        *,
        fuzzy: bool = False,
        cutoff: float = 0.92,
        ambiguity_delta: float = 0.02,
    ) -> GeneResolution:
        raw = str(token).strip()
        key = raw.casefold()
        if not key:
            return GeneResolution(raw, None, (), "unmatched")
        if key == "intergenic":
            return GeneResolution(raw, "INTERGENIC", (), "special-intergenic")

        # An approved symbol takes precedence over a colliding legacy alias.
        # This prevents a current HGNC symbol from becoming spuriously
        # ambiguous merely because another gene once used it as an alias.
        if key in self.names_to_ids:
            ids = tuple(sorted(self.names_to_ids[key]))
            canonical = self.ids_to_names[ids[0]]
            return GeneResolution(raw, canonical, ids, "name-exact", 1.0)

        alias_candidates = tuple(sorted(self.aliases.get(key, set())))
        if len(alias_candidates) > 1:
            return GeneResolution(
                raw, None, (), "ambiguous-alias", candidates=alias_candidates
            )
        if len(alias_candidates) == 1:
            canonical = alias_candidates[0]
            match_type = (
                "name-exact" if canonical.casefold() == key else "synonym-exact"
            )
            return self._canonical_result(raw, canonical, match_type, 1.0)
        if not fuzzy or not self._universe:
            return GeneResolution(raw, None, (), "unmatched")

        scored = sorted(
            (
                difflib.SequenceMatcher(None, key, candidate).ratio(),
                candidate,
            )
            for candidate in self._universe
        )
        best_score, best_key = scored[-1]
        if best_score < cutoff:
            return GeneResolution(raw, None, (), "unmatched")
        close_keys = {
            candidate
            for score, candidate in scored
            if score >= cutoff and best_score - score <= ambiguity_delta
        }
        canonical_candidates: set[str] = set()
        for candidate in close_keys:
            if candidate in self.names_to_ids:
                ids = sorted(self.names_to_ids[candidate])
                if ids:
                    canonical_candidates.add(self.ids_to_names[ids[0]])
            else:
                canonical_candidates.update(self.aliases.get(candidate, set()))
        if len(canonical_candidates) != 1:
            return GeneResolution(
                raw,
                None,
                (),
                "ambiguous-fuzzy",
                best_score,
                tuple(sorted(canonical_candidates)),
            )
        canonical = next(iter(canonical_candidates))
        source_type = (
            "fuzzy-name" if best_key in self.names_to_ids else "fuzzy-synonym"
        )
        return self._canonical_result(raw, canonical, source_type, best_score)

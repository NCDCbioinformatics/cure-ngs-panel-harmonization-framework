from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .gene import GeneCatalog, GeneResolution


@dataclass(frozen=True)
class FusionResolution:
    input: str
    gene_5prime: GeneResolution | None
    gene_3prime: GeneResolution | None
    normalized: str | None
    status: str
    candidates: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _resolution_score(result: GeneResolution) -> int:
    if result.match_type in {"name-exact", "synonym-exact"}:
        return 3
    if result.match_type == "special-intergenic":
        return 2
    if result.match_type.startswith("fuzzy"):
        return 1
    return 0


def normalize_fusion(
    value: str, catalog: GeneCatalog, *, fuzzy: bool = False
) -> FusionResolution:
    raw = str(value).strip()
    if not raw:
        return FusionResolution(raw, None, None, None, "unmatched")
    cleaned = re.sub(r"\s+", "", raw)
    # Escapes avoid source corruption under Windows code pages.
    cleaned = cleaned.translate(
        str.maketrans({"\u2010": "-", "\u2011": "-", "\u2013": "-", "\u2014": "-", "\u2212": "-"})
    )

    explicit = re.split(r"::|/", cleaned)
    if len(explicit) == 2 and all(explicit):
        left, right = explicit
        left_result = catalog.resolve(left, fuzzy=fuzzy)
        right_result = catalog.resolve(right, fuzzy=fuzzy)
        if min(_resolution_score(left_result), _resolution_score(right_result)) == 0:
            return FusionResolution(raw, left_result, right_result, None, "unmatched")
        return FusionResolution(
            raw,
            left_result,
            right_result,
            f"{left_result.matched_symbol}--{right_result.matched_symbol}",
            "resolved",
        )
    if len(explicit) > 2:
        return FusionResolution(raw, None, None, None, "ambiguous-delimiter")

    candidates: list[tuple[int, str, GeneResolution, GeneResolution]] = []
    for index, character in enumerate(cleaned):
        if character != "-":
            continue
        left, right = cleaned[:index], cleaned[index + 1 :]
        if not left or not right:
            continue
        left_result = catalog.resolve(left, fuzzy=fuzzy)
        right_result = catalog.resolve(right, fuzzy=fuzzy)
        score = _resolution_score(left_result) + _resolution_score(right_result)
        candidates.append((score, f"{left}|{right}", left_result, right_result))
    if not candidates:
        return FusionResolution(raw, None, None, None, "unmatched")
    best_score = max(item[0] for item in candidates)
    best = [item for item in candidates if item[0] == best_score and best_score >= 4]
    if len(best) != 1:
        return FusionResolution(
            raw,
            None,
            None,
            None,
            "ambiguous-split" if len(best) > 1 else "unmatched",
            tuple(item[1] for item in best),
        )
    _, _, left_result, right_result = best[0]
    return FusionResolution(
        raw,
        left_result,
        right_result,
        f"{left_result.matched_symbol}--{right_result.matched_symbol}",
        "resolved",
    )

from __future__ import annotations

import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class HgvsNormalization:
    input: str | None
    normalized: str | None
    kind: str
    changed: bool
    reasons: tuple[str, ...]
    syntax_status: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


_NUCLEOTIDE_BODY = re.compile(
    r"^(?:[-*]?\d+(?:[+-]\d+)?(?:_[-*]?\d+(?:[+-]\d+)?)?)"
    r"(?:[ACGTN]>[ACGTN]|del(?:[ACGTN]+)?|dup(?:[ACGTN]+)?|ins[ACGTN]+|"
    r"delins[ACGTN]+|=|\?)$",
    re.IGNORECASE,
)
_NUCLEOTIDE_POSITION = (
    r"[-*]?\d+(?:[+-]\d+)?(?:_[-*]?\d+(?:[+-]\d+)?)?"
)
_PROTEIN_BODY = re.compile(
    r"^(?:[A-Z][a-z]{2}|[A-Z*])\d+"
    r"(?:(?:[A-Z][a-z]{2}|[A-Z*=])(?:fs(?:Ter|\*)?\d*)?|del|dup|"
    r"ins(?:[A-Z][a-z]{2}|[A-Z])+|delins(?:[A-Z][a-z]{2}|[A-Z])+|\?)$"
)


def _clean(value: object) -> tuple[str | None, list[str]]:
    if value is None:
        return None, []
    original = str(value).strip()
    if not original or original.casefold() in {"none", "nan", "na"}:
        return None, []
    reasons: list[str] = []
    cleaned = re.sub(r"\s+", "", original)
    if cleaned != original:
        reasons.append("removed_whitespace")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = cleaned[1:-1]
        reasons.append("removed_outer_parentheses")
    return cleaned, reasons


def normalize_hgvs(value: object, *, kind: str) -> HgvsNormalization:
    if kind not in {"c", "n", "p"}:
        raise ValueError("HGVS kind must be 'c', 'n', or 'p'")
    original = None if value is None else str(value)
    cleaned, reasons = _clean(value)
    if cleaned is None:
        return HgvsNormalization(original, None, kind, False, (), "missing")

    transcript = ""
    body = cleaned
    if ":" in cleaned:
        transcript, body = cleaned.rsplit(":", 1)
        transcript += ":"

    if kind in {"c", "n"}:
        prefix = f"{kind}."
        if body.lower().startswith(prefix):
            if not body.startswith(prefix):
                reasons.append("normalized_prefix_case")
            body = body[2:]
        elif body.lower().startswith(kind):
            body = body[1:].lstrip(".")
            reasons.append(f"normalized_prefix_{kind}")
        else:
            reasons.append(f"added_prefix_{kind}")

        match = re.fullmatch(r"([ACGTacgtn])(\d+)([ACGTacgtn])", body)
        if match:
            ref, position, alt = match.groups()
            body = f"{int(position)}{ref.upper()}>{alt.upper()}"
            reasons.append("reordered_ref_position_alt")
        else:
            snv = re.fullmatch(
                rf"({_NUCLEOTIDE_POSITION})([ACGTacgtn])>([ACGTacgtn])",
                body,
            )
            if snv:
                position, ref, alt = snv.groups()
                normalized_position = (
                    str(int(position)) if position.isdecimal() else position
                )
                normalized_body = (
                    f"{normalized_position}{ref.upper()}>{alt.upper()}"
                )
                if normalized_body != body:
                    reasons.append("normalized_position_or_bases")
                body = normalized_body
            else:
                operation = re.fullmatch(
                    rf"({_NUCLEOTIDE_POSITION})(delins|ins|del|dup)([ACGTN]*)",
                    body,
                    re.IGNORECASE,
                )
                if operation:
                    position, operator, sequence = operation.groups()
                    normalized_body = (
                        f"{position}{operator.lower()}{sequence.upper()}"
                    )
                    if normalized_body != body:
                        reasons.append("normalized_operation_or_bases")
                    body = normalized_body
        normalized = f"{transcript}{kind}.{body}"
        status = (
            "valid" if _NUCLEOTIDE_BODY.fullmatch(body) else "unvalidated-syntax"
        )
    else:
        if body.lower().startswith("p."):
            if not body.startswith("p."):
                reasons.append("normalized_prefix_case")
            body = body[2:]
        elif body.startswith("P."):
            body = body[2:]
            reasons.append("normalized_prefix_case")
        else:
            reasons.append("added_prefix_p")
        if body.startswith("(") and body.endswith(")"):
            body = body[1:-1]
            reasons.append("removed_prediction_parentheses")
        normalized = f"{transcript}p.{body}"
        status = "valid" if _PROTEIN_BODY.fullmatch(body) else "unvalidated-syntax"

    changed = normalized != cleaned or bool(reasons)
    return HgvsNormalization(
        original, normalized, kind, changed, tuple(dict.fromkeys(reasons)), status
    )

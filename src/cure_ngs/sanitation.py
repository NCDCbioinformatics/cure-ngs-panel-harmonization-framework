"""Conservative, auditable conversion of legacy dictionary INFO metadata."""
from __future__ import annotations

import ast
import json
import math
import re
from urllib.parse import quote

_TAG = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*\Z")


def validate_tag(key: str) -> None:
    if not _TAG.fullmatch(key):
        raise ValueError(f"Invalid VCF metadata ID {key!r}; expected a VCF tag, not free text")


def _value(value: object) -> str:
    if value is None:
        return "."
    if isinstance(value, (list, tuple)):
        if any(isinstance(item, (list, tuple, dict, set)) for item in value):
            raise ValueError("Nested INFO containers require an explicit input schema")
        return ",".join(_value(item) for item in value) or "."
    if isinstance(value, bool):
        return "1" if value else "0"
    if not isinstance(value, (str, int, float)):
        raise ValueError("Unsupported dictionary INFO value")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite dictionary INFO value")
    # Escape delimiters and whitespace; do not reinterpret origAlt as genomic ALT.
    return quote(str(value), safe="-._~:/+|") or "."


def repair_legacy_info(info: str, *, line_number: int) -> str:
    text = info.strip()
    if not text:
        return "."
    if not text.startswith("{"):
        if text != ".":
            items = [item for item in text.split(";") if item]
            for item in items:
                validate_tag(item.partition("=")[0])
            return ";".join(items) or "."
        return info
    try:
        tree = ast.parse(text, mode="eval")
        if not isinstance(tree.body, ast.Dict):
            raise ValueError("INFO is not a dictionary literal")
        keys = [ast.literal_eval(key) for key in tree.body.keys]
        if any(not isinstance(key, str) for key in keys) or len(set(keys)) != len(keys):
            raise ValueError("Non-string or duplicate dictionary INFO keys")
        try:
            values = ast.literal_eval(tree)
        except ValueError:
            # JSON true/false/null are also accepted, but duplicate keys were
            # already checked on the AST above.
            values = json.loads(text)
        result = []
        for key, value in values.items():
            validate_tag(key)
            result.append(f"{key}={_value(value)}")
        return ";".join(result) or "."
    except (SyntaxError, ValueError, TypeError) as exc:
        raise ValueError(f"Unsafe or malformed dictionary INFO at line {line_number}: {exc}") from exc

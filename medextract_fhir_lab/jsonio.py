"""Strict JSON input and exact JSON numbers for FHIR decimal values."""

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path


def _object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate JSON object key")
        out[key] = value
    return out


def _invalid_number(_):
    raise ValueError("non-finite JSON number")


def loads(text):
    try:
        return json.loads(
            text,
            parse_float=Decimal,
            parse_constant=_invalid_number,
            object_pairs_hook=_object,
        )
    except InvalidOperation as exc:
        raise ValueError("unsupported JSON decimal") from exc


def read_bytes(path: Path, *, root: Path | None = None) -> bytes:
    """Read a regular input file without including its filename in an error."""
    try:
        resolved = path.resolve(strict=True)
        if root is not None and not resolved.is_relative_to(root):
            raise ValueError("input outside suite directory")
        if not resolved.is_file():
            raise ValueError("input must be a regular file")
        return resolved.read_bytes()
    except (OSError, RuntimeError):
        raise ValueError("input file missing, unreadable or unresolvable") from None


def read_json(path: Path, *, root: Path | None = None):
    return loads(read_bytes(path, root=root))


def dumps(obj):
    """The standard encoder handles strings; decimal quantities stay numeric on the wire."""
    if isinstance(obj, Decimal):
        if not obj.is_finite():
            raise ValueError("non-finite decimal")
        return format(obj, "f")
    if isinstance(obj, dict):
        return (
            "{" + ",".join(json.dumps(k) + ":" + dumps(v) for k, v in obj.items()) + "}"
        )
    if isinstance(obj, list):
        return "[" + ",".join(dumps(v) for v in obj) + "]"
    return json.dumps(obj, ensure_ascii=False, allow_nan=False)

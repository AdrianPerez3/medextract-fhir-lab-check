"""Explicit mappings for a narrow synthetic quantitative lab-report contract."""

from decimal import Decimal
from hashlib import sha256
import re
from uuid import NAMESPACE_URL, uuid5

from .checker import validate_reference
from .jsonio import loads
from .result_value import export_result

LOINC = "http://loinc.org"
DECIMAL = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?")
EUROPEAN = re.compile(r"[+-]?(?:[0-9]+|[0-9]{1,3}(?:\.[0-9]{3})+)(?:,[0-9]+)?")


def export_bundle(reference):
    """Export a base R4 collection, preserving documented facts and stable row identifiers."""
    validate_reference(reference)
    system = reference["identifier_system"]
    report_id = reference["report_id"]

    def entry(kind, key, **fields):
        uid = str(uuid5(NAMESPACE_URL, f"{system}|{report_id}|{kind}|{key}"))
        return {
            "fullUrl": "urn:uuid:" + uid,
            "resource": {"resourceType": kind, "id": uid, **fields},
        }

    report = entry(
        "DiagnosticReport",
        "report",
        identifier=[{"system": system + "/reports", "value": report_id}],
        status="unknown",
        code={"text": "Laboratory report"},
        result=[],
    )
    entries = [report]
    for row in reference["rows"]:
        observation = entry(
            "Observation",
            row["id"],
            identifier=[{"system": system, "value": row["id"]}],
            status=row["status"] or "unknown",
            code={"coding": [{"system": LOINC, "code": row["loinc"]}]},
            **export_result(row),
        )
        entries.append(observation)
        report["resource"]["result"].append({"reference": observation["fullUrl"]})
        if row["specimen"] is not None:
            specimen = entry(
                "Specimen", row["id"], type={"coding": [dict(row["specimen"])]}
            )
            entries.append(specimen)
            observation["resource"]["specimen"] = {"reference": specimen["fullUrl"]}
    return {"resourceType": "Bundle", "type": "collection", "entry": entries}


def _rows(doc, report_id):
    if (
        not isinstance(doc, dict)
        or not isinstance(doc.get("results"), list)
        or not doc["results"]
    ):
        raise ValueError("expected a nonempty starter results array")
    if "report_id" in doc and doc["report_id"] != report_id:
        raise ValueError("starter labels and coordinate report IDs differ")
    required = {"value", "loinc", "unit"}
    allowed = required | {"test_name", "panel", "flag", "reference_range"}
    for row in doc["results"]:
        if not isinstance(row, dict) or not required <= row.keys() <= allowed:
            raise ValueError("missing or unsupported starter row fields")
        if not isinstance(row["loinc"], str) or not isinstance(row["unit"], str):
            raise ValueError("invalid starter LOINC or unit")
        if any(row.get(key) not in (None, "") for key in ("flag", "reference_range")):
            raise ValueError(
                "populated flags and reference intervals require another source contract"
            )
    return doc["results"]


def _agrees(printed, normalized):
    # The generator can use a comma decimal and dots for thousands. The separately
    # supplied normalized label disambiguates a value such as '1.234'.
    if (
        not isinstance(printed, str)
        or not isinstance(normalized, str)
        or not DECIMAL.fullmatch(normalized)
    ):
        return False
    expected = Decimal(normalized)
    if DECIMAL.fullmatch(printed) and Decimal(printed) == expected:
        return True
    return bool(
        EUROPEAN.fullmatch(printed)
        and Decimal(printed.replace(".", "").replace(",", ".")) == expected
    )


def import_starter(visible_bytes, normalized, coordinates, identifier_system):
    """Bind the public starter's normalized labels to its printed rows and sidecar."""
    if (
        not isinstance(coordinates, dict)
        or type(coordinates.get("schema_version")) is not int
        or coordinates["schema_version"] != 1
    ):
        raise ValueError("expected starter coordinate schema version 1")
    if sha256(visible_bytes).hexdigest() != coordinates.get("ground_truth_sha256"):
        raise ValueError("printed labels do not match the coordinate sidecar digest")
    report_id = coordinates.get("report_id")
    visible = _rows(loads(visible_bytes), report_id)
    canonical = _rows(normalized, report_id)
    if len(visible) != len(canonical):
        raise ValueError("normalized and printed row counts differ")
    # In v0.2.0, the coordinate index is in *printed* order. Normalized labels
    # join by unique LOINC within the report and can be in a different order.
    by_loinc = {row["loinc"]: row for row in canonical}
    if len(by_loinc) != len(canonical):
        raise ValueError("repeated normalized LOINC is ambiguous in starter v0.2.0")
    reference = {
        "schema_version": 1,
        "report_id": report_id,
        "identifier_system": identifier_system,
        "rows": [],
    }
    pages = coordinates.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ValueError("expected coordinate pages")
    for n, page in enumerate(pages, 1):
        if (
            not isinstance(page, dict)
            or type(page.get("page")) is not int
            or page["page"] != n
            or not isinstance(page.get("rows"), list)
        ):
            raise ValueError("invalid coordinate page")
        for cell in page["rows"]:
            i = len(reference["rows"])
            if (
                not isinstance(cell, dict)
                or type(cell.get("result_index")) is not int
                or cell["result_index"] != i
                or i >= len(visible)
            ):
                raise ValueError(
                    "coordinate rows must cover each source index in order"
                )
            printed = visible[i]
            norm = by_loinc.pop(printed["loinc"], None)
            if (
                norm is None
                or cell.get("loinc") != printed["loinc"]
                or printed.get("unit") != norm.get("unit")
                or not _agrees(printed.get("value"), norm.get("value"))
            ):
                raise ValueError(
                    f"starter labels disagree or use an unsupported result at row {i + 1}"
                )
            reference["rows"].append(
                {
                    "id": f"{report_id}.{i + 1}",
                    "loinc": norm["loinc"],
                    "value": norm["value"],
                    "comparator": None,
                    "unit": norm["unit"],
                    "status": None,
                    "specimen": None,
                }
            )
    if len(reference["rows"]) != len(visible):
        raise ValueError("coordinate coverage is incomplete")
    validate_reference(reference)
    return reference

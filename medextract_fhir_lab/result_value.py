"""Source-attested quantities and coded missing results in the R4 fixture contract."""

from decimal import Decimal
import re

UCUM = "http://unitsofmeasure.org"
REASON_SYSTEM = "http://terminology.hl7.org/CodeSystem/data-absent-reason"
# R4 (4.0.1) DataAbsentReason subset. The remaining standard code, as-text,
# points to a resource narrative that the row contract cannot attest. Local-only
# codes also need a reviewed mapping.
REASONS = frozenset(
    {
        "unknown",
        "asked-unknown",
        "temp-unknown",
        "not-asked",
        "asked-declined",
        "masked",
        "not-applicable",
        "unsupported",
        "error",
        "not-a-number",
        "negative-infinity",
        "positive-infinity",
        "not-performed",
        "not-permitted",
    }
)
NUMBER = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?")
COMPARATORS = {
    None: None,
    "<": "<",
    ">": ">",
    "<=": "<=",
    ">=": ">=",
    "≤": "<=",
    "≥": ">=",
}
COMMON = {"id", "loinc", "status", "specimen"}


def check_primitive_metadata(element, field, path):
    """An R4 primitive can carry an element id alongside its literal value."""
    key = "_" + field
    if key not in element:
        return
    metadata = element[key]
    if not (
        field in element
        and isinstance(metadata, dict)
        and metadata.keys() == {"id"}
        and isinstance(metadata["id"], str)
        and metadata["id"].strip()
    ):
        raise ValueError(f"unsupported primitive metadata on {path}.{field}")


def validate_source_result(row, version):
    kind = "quantity" if version == 1 else row.get("kind")
    fields = COMMON if version == 1 else COMMON | {"kind"}
    if kind == "absent":
        if row.keys() != fields | {"absent_reason"}:
            raise ValueError(
                "absent row must contain only an attested absence reason and common fields"
            )
        if (
            not isinstance(row["absent_reason"], str)
            or row["absent_reason"] not in REASONS
        ):
            raise ValueError("unsupported R4 source absence reason")
        return
    if kind != "quantity":
        raise ValueError("version 2 row requires an explicit quantity or absent kind")
    fields = fields | {"value", "unit", "comparator"}
    if version == 2 and "display_unit" in row:
        fields.add("display_unit")
        display = row["display_unit"]
        if not isinstance(display, str) or not display or display.strip() != display:
            raise ValueError("source display_unit must be a nonempty literal")
    if version == 2 and "preserve_decimal_places" in row:
        fields.add("preserve_decimal_places")
        if type(row["preserve_decimal_places"]) is not bool:
            raise ValueError("preserve_decimal_places must be boolean")
    if row.keys() != fields:
        raise ValueError("invalid fields for source quantity")
    if not isinstance(row["value"], str) or not NUMBER.fullmatch(row["value"]):
        raise ValueError("source value must be a plain finite decimal string")
    unit = row["unit"]
    if not isinstance(unit, str) or not unit or unit.strip() != unit:
        raise ValueError("source UCUM code must be a nonempty string")
    comp = row["comparator"]
    if comp is not None and (not isinstance(comp, str) or comp not in COMPARATORS):
        raise ValueError("unsupported source comparator")


def export_result(row):
    if row.get("kind") == "absent":
        return {
            "dataAbsentReason": {
                "coding": [{"system": REASON_SYSTEM, "code": row["absent_reason"]}]
            }
        }
    quantity = {
        "value": Decimal(row["value"]),
        "system": UCUM,
        "unit": row.get("display_unit", row["unit"]),
        "code": row["unit"],
    }
    if row["comparator"] is not None:
        quantity["comparator"] = COMPARATORS[row["comparator"]]
    return {"valueQuantity": quantity}


def read_result(observation, version):
    if any(
        k.startswith("_value") or (k.startswith("value") and k != "valueQuantity")
        for k in observation
    ):
        raise ValueError("unsupported Observation value type or primitive extension")
    if "dataAbsentReason" in observation:
        if version == 1 or "valueQuantity" in observation:
            raise ValueError(
                "a supported absent result needs a v2 reference and no value"
            )
        reason = observation["dataAbsentReason"]
        if not isinstance(reason, dict) or not isinstance(reason.get("coding"), list):
            raise ValueError("expected coded Observation.dataAbsentReason")
        codes = set()
        for coding in reason["coding"]:
            if not isinstance(coding, dict):
                raise ValueError("unsupported absence reason coding")
            check_primitive_metadata(coding, "system", "dataAbsentReason.coding")
            if coding.get("system") == REASON_SYSTEM:
                check_primitive_metadata(coding, "code", "dataAbsentReason.coding")
                code = coding.get("code")
                if not isinstance(code, str) or code not in REASONS:
                    raise ValueError("unsupported standard absence reason code")
                codes.add(code)
        if len(codes) != 1:
            raise ValueError("absent result needs one unambiguous standard reason")
        return None, codes.pop()
    quantity = observation.get("valueQuantity")
    if not isinstance(quantity, dict):
        raise ValueError(
            "expected measured quantity or an explicitly coded absence reason"
        )
    for field in ("value", "system", "code", "comparator"):
        check_primitive_metadata(quantity, field, "valueQuantity")
    if "comparator" in quantity and quantity["comparator"] not in (
        "<",
        "<=",
        ">",
        ">=",
    ):
        raise ValueError("invalid FHIR Quantity comparator")
    value = quantity.get("value")
    if isinstance(value, bool) or not isinstance(value, (Decimal, float, int)):
        raise ValueError("valueQuantity.value must be a finite JSON number")
    number = Decimal(str(value)) if isinstance(value, float) else Decimal(value)
    if not number.is_finite():
        raise ValueError("valueQuantity.value must be finite")
    return quantity, number


def compare_result(row, quantity, result, add):
    if row.get("kind") == "absent":
        if quantity is not None:
            add("invented-value", "valueQuantity")
        elif result != row["absent_reason"]:
            add("absent-reason-changed", "dataAbsentReason")
        return
    if quantity is None:
        add("lost-value", "valueQuantity")
        return
    expected = Decimal(row["value"])
    precision = row.get("preserve_decimal_places", False)
    if precision and isinstance(quantity["value"], float):
        raise ValueError("decimal-place comparison requires JSON parsed with Decimal")
    if result != expected:
        add("value-changed", "valueQuantity.value")
    elif precision and max(0, -result.as_tuple().exponent) != max(
        0, -expected.as_tuple().exponent
    ):
        add("decimal-places-changed", "valueQuantity.value")
    if quantity.get("comparator") != COMPARATORS[row["comparator"]]:
        add("comparator-changed", "valueQuantity.comparator")
    if "display_unit" in row:
        check_primitive_metadata(quantity, "unit", "valueQuantity")
        if quantity.get("unit") != row["display_unit"]:
            add("unit-display-changed", "valueQuantity.unit")
    if quantity.get("system") != UCUM or quantity.get("code") != row["unit"]:
        add("unit-changed", "valueQuantity.code")

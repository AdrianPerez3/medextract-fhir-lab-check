import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from medextract_fhir_lab.adapter import export_bundle
from medextract_fhir_lab.checker import check, validate_reference
from medextract_fhir_lab.jsonio import dumps, loads

EX = Path(__file__).resolve().parents[1] / "examples"


class ResultStates(unittest.TestCase):
    def setUp(self):
        self.ref = loads((EX / "absent-reference.json").read_bytes())
        self.bundle = loads((EX / "absent-correct.bundle.json").read_bytes())
        self.a, self.b = [e["resource"] for e in self.bundle["entry"][1:]]

    def findings(self):
        return [(f["code"], f.get("row_id")) for f in check(self.ref, self.bundle)]

    def test_authored_document_and_export(self):
        self.assertEqual(self.findings(), [])
        candidate = export_bundle(self.ref)
        self.assertEqual(check(self.ref, loads(dumps(candidate))), [])
        self.assertNotIn("valueQuantity", candidate["entry"][1]["resource"])
        self.assertIn("0.00", dumps(candidate))

    def test_unperformed_transcribed_as_zero(self):
        self.bundle = loads((EX / "absent-as-zero.bundle.json").read_bytes())
        self.assertEqual(self.findings(), [("invented-value", "r01")])

    def test_measured_zero_transcribed_as_absent_and_distinct_reason(self):
        self.b.pop("valueQuantity")
        self.b["dataAbsentReason"] = deepcopy(self.a["dataAbsentReason"])
        self.a["dataAbsentReason"]["coding"][0]["code"] = "unknown"
        self.assertEqual(
            self.findings(), [("absent-reason-changed", "r01"), ("lost-value", "r02")]
        )

    def test_invalid_or_untranslatable_reason(self):
        reason = self.a["dataAbsentReason"]["coding"][0]
        for obj in [
            {},
            {"text": "no result"},
            {"coding": [dict(reason, system="urn:example:other")]},
            {"coding": [reason, dict(reason, code="unknown")]},
            {"coding": [dict(reason, code="INVALID")]},
            {"coding": [dict(reason, _code={"extension": []})]},
        ]:
            with self.subTest(obj=obj), self.assertRaises(ValueError):
                self.a["dataAbsentReason"] = obj
                self.findings()

    def test_simultaneous_or_unsupported_values(self):
        for k, value in [
            ("valueQuantity", self.b["valueQuantity"]),
            ("valueString", "Negative"),
            ("_valueString", {"extension": []}),
        ]:
            with self.subTest(k=k), self.assertRaises(ValueError):
                self.a[k] = value
                self.findings()
            del self.a[k]
        del self.a["dataAbsentReason"]
        with self.assertRaises(ValueError):
            self.findings()

    def test_reference_rejects_mixed_fields_or_unexplicit_kinds(self):
        for k, v in [
            ("value", "0"),
            ("unit", "%"),
            ("comparator", None),
            ("kind", "observation"),
            ("absent_reason", False),
            ("absent_reason", "unknown-code"),
        ]:
            ref = deepcopy(self.ref)
            ref["rows"][0][k] = v
            with self.subTest(k=k), self.assertRaises(ValueError):
                validate_reference(ref)
        self.ref["rows"][1]["preserve_decimal_places"] = 1
        with self.assertRaises(ValueError):
            validate_reference(self.ref)

    def test_wire_decimal_places_opt_in_and_no_double_penalty(self):
        self.b["valueQuantity"]["value"] = 0
        self.assertEqual(self.findings(), [("decimal-places-changed", "r02")])
        self.b["valueQuantity"]["value"] = Decimal("1.2")
        self.assertEqual(self.findings(), [("value-changed", "r02")])
        self.b["valueQuantity"]["value"] = 0
        self.ref["rows"][1].pop("preserve_decimal_places")
        self.assertEqual(self.findings(), [])

    def test_precision_requires_lossless_python_input(self):
        self.b["valueQuantity"]["value"] = 0.0
        with self.assertRaises(ValueError):
            self.findings()

    def test_as_text_requires_a_separately_attested_resource_narrative(self):
        self.ref["rows"][0]["absent_reason"] = "as-text"
        with self.assertRaises(ValueError):
            export_bundle(self.ref)
        self.ref["rows"][0]["absent_reason"] = "unknown"
        self.a["dataAbsentReason"]["coding"][0]["code"] = "as-text"
        with self.assertRaises(ValueError):
            self.findings()

    def test_correct_ucum_with_wrong_human_unit_display(self):
        row = self.ref["rows"][1]
        row["display_unit"] = "por ciento"
        candidate = export_bundle(self.ref)
        measurement = candidate["entry"][2]["resource"]["valueQuantity"]
        self.assertEqual(
            (measurement["code"], measurement["unit"]), ("%", "por ciento")
        )
        self.bundle = candidate
        self.assertEqual(self.findings(), [])
        measurement["unit"] = "mg/dL"
        self.assertEqual(self.findings(), [("unit-display-changed", "r02")])
        del measurement["unit"]
        self.assertEqual(self.findings(), [("unit-display-changed", "r02")])
        row.pop("display_unit")
        self.assertEqual(self.findings(), [])

    def test_bad_source_display_and_extension_on_reviewed_wire_unit(self):
        for literal in [None, False, "", " "]:
            self.ref["rows"][1]["display_unit"] = literal
            with self.subTest(literal=literal), self.assertRaises(ValueError):
                validate_reference(self.ref)
        self.ref["rows"][1]["display_unit"] = "%"
        self.b["valueQuantity"]["_unit"] = {"extension": [{}]}
        with self.assertRaises(ValueError):
            self.findings()

    def test_v1_contract_still_requires_a_quantity(self):
        self.ref = loads((EX / "reference.json").read_bytes())
        with self.assertRaises(ValueError):
            self.findings()

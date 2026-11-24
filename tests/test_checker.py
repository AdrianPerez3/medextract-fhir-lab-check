"""Executable examples for the one-report fidelity contract."""

from copy import deepcopy
from decimal import Decimal
import unittest

from medextract_fhir_lab.checker import check

NS = "https://example.org/medextract/row"
LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"
SCT = "http://snomed.info/sct"


def row(key, code, value, comparator=None):
    return dict(
        id=key,
        loinc=code,
        value=value,
        comparator=comparator,
        unit="mg/L",
        status=None,
        specimen=None,
    )


def fixtures():
    rows = [row("r1", "1000-9", "0.10", "≤"), row("r2", "1001-7", "6")]
    ref = dict(
        schema_version=1, report_id="LAB-DEMO-001", identifier_system=NS, rows=rows
    )
    report = {
        "resourceType": "DiagnosticReport",
        "id": "report",
        "status": "unknown",
        "identifier": [{"system": NS + "/reports", "value": ref["report_id"]}],
        "result": [{"reference": "Observation/o1"}, {"reference": "Observation/o2"}],
    }
    entries = [{"resource": report}]
    for number, r in enumerate(rows, 1):
        q = {"value": Decimal(r["value"]), "system": UCUM, "code": r["unit"]}
        if r["comparator"]:
            q["comparator"] = "<="
        obs = {
            "resourceType": "Observation",
            "id": f"o{number}",
            "identifier": [{"system": NS, "value": r["id"]}],
            "status": "unknown",
            "code": {"coding": [{"system": LOINC, "code": r["loinc"]}]},
            "valueQuantity": q,
        }
        entries.append(
            {
                "fullUrl": f"urn:uuid:00000000-0000-4000-8000-00000000000{number}",
                "resource": obs,
            }
        )
    bundle = {"resourceType": "Bundle", "type": "collection", "entry": entries}
    return ref, bundle


class Fidelity(unittest.TestCase):
    def setUp(self):
        self.ref, self.bundle = fixtures()
        self.report, self.a, self.b = [e["resource"] for e in self.bundle["entry"]]

    def check(self):
        return check(self.ref, self.bundle)

    def codes(self):
        return [i["code"] for i in self.check()]

    def test_same_value_trailing_zeros_and_order(self):
        self.bundle["entry"].reverse()
        self.report["result"].reverse()
        self.assertEqual(self.check(), [])

    def test_multiple_identifier_systems_and_alternate_coding(self):
        self.a["identifier"].append({"system": "urn:other", "value": "other"})
        self.a["code"]["coding"].append({"system": SCT, "code": "other"})
        self.a["valueQuantity"]["unit"] = "milligrams per litre"
        self.assertEqual(self.check(), [])

    def test_full_url_and_relative_refs_in_report(self):
        self.report["result"][0]["reference"] = self.bundle["entry"][1]["fullUrl"]
        self.assertEqual(self.check(), [])

    def test_swapped_quantities_fail_each_row(self):
        self.a["valueQuantity"], self.b["valueQuantity"] = (
            self.b["valueQuantity"],
            self.a["valueQuantity"],
        )
        self.assertEqual(
            sorted(i["row_id"] for i in self.check() if i["code"] == "value-changed"),
            ["r1", "r2"],
        )
        self.assertEqual(self.codes().count("comparator-changed"), 2)

    def test_lost_comparator(self):
        del self.a["valueQuantity"]["comparator"]
        self.assertEqual(
            self.check(),
            [
                {
                    "code": "comparator-changed",
                    "row_id": "r1",
                    "field": "valueQuantity.comparator",
                }
            ],
        )

    def test_wrong_units_or_wrong_system(self):
        for key, value in [
            ("code", "Mg/L"),
            ("code", "g/L"),
            ("system", "urn:untrusted"),
        ]:
            with self.subTest(key=key, value=value):
                old = self.a["valueQuantity"][key]
                self.a["valueQuantity"][key] = value
                self.assertIn("unit-changed", self.codes())
                self.a["valueQuantity"][key] = old

    def test_decimal_difference_beyond_binary_float_precision(self):
        self.ref["rows"][0]["value"] = "1.000000000000000001"
        self.a["valueQuantity"]["value"] = Decimal("1.000000000000000002")
        self.assertIn("value-changed", self.codes())

    def test_nonfinite_and_wrong_value_type(self):
        for v in [True, float("nan"), Decimal("Infinity"), "1"]:
            with self.subTest(v=v):
                self.a["valueQuantity"]["value"] = v
                with self.assertRaises(ValueError):
                    self.check()

    def test_ambiguous_loinc_and_wrong_code(self):
        self.a["code"]["coding"].append({"system": LOINC, "code": "different"})
        self.assertIn("ambiguous-code", self.codes())
        self.a["code"]["coding"].pop(0)
        self.assertIn("loinc-changed", self.codes())

    def test_duplicate_and_extra_rows_and_missing_reference(self):
        self.b["identifier"][0]["value"] = "r1"
        self.assertIn("duplicate-row", self.codes())
        self.assertIn("missing-row", self.codes())
        self.b["identifier"][0]["value"] = "private-candidate-data"
        findings = self.check()
        self.assertIn("extra-row", [i["code"] for i in findings])
        self.assertNotIn("private-candidate-data", repr(findings))

    def test_duplicate_report_result_also_when_href_is_aliased(self):
        self.report["result"].append({"reference": self.bundle["entry"][1]["fullUrl"]})
        self.assertIn("duplicate-reference", self.codes())

    def test_dangling_and_unlinked_resource(self):
        self.report["result"][0]["reference"] = "Observation/missing"
        self.assertIn("unresolved-reference", self.codes())
        self.assertIn("unlinked-observation", self.codes())
        self.assertIn("missing-row", self.codes())

    def test_wrong_report_link_type(self):
        self.report["result"][0]["reference"] = "DiagnosticReport/report"
        self.assertIn("unresolved-reference", self.codes())

    def test_unknown_status_must_not_become_final(self):
        self.a["status"] = "final"
        self.assertIn("status-changed", self.codes())
        self.ref["rows"][0]["status"] = "amended"
        self.assertIn("status-changed", self.codes())

    def test_report_id_and_row_identifier(self):
        self.report["identifier"][0]["value"] = "different"
        self.assertIn("report-id-changed", self.codes())
        self.a["identifier"].append({"system": NS, "value": "r2"})
        self.assertIn("ambiguous-identifier", self.codes())

    def add_specimen(self):
        specimen = {
            "resourceType": "Specimen",
            "id": "s1",
            "type": {"coding": [{"system": SCT, "code": "123"}]},
        }
        self.bundle["entry"].append({"resource": specimen})
        self.a["specimen"] = {"reference": "Specimen/s1"}
        return specimen

    def test_specimen_omitted_known_unknown_and_mismatched(self):
        specimen = self.add_specimen()
        self.assertIn("specimen-changed", self.codes())
        self.ref["rows"][0]["specimen"] = {"system": SCT, "code": "123"}
        self.assertEqual(self.check(), [])
        specimen["type"]["coding"][0]["code"] = "456"
        self.assertIn("specimen-changed", self.codes())
        del self.a["specimen"]
        self.assertIn("specimen-changed", self.codes())

    def test_report_only_added_specimen(self):
        self.add_specimen()
        del self.a["specimen"]
        self.report["specimen"] = [{"reference": "Specimen/s1"}]
        self.assertIn("unlinked-specimen", self.codes())

    def test_cross_subject(self):
        self.report["subject"] = {"reference": "Patient/one"}
        self.a["subject"] = {"reference": "Patient/two"}
        self.assertIn("subject-conflict", self.codes())

    def test_panels_datatypes_and_unsupported_reports(self):
        for addition in [
            {"component": [{}]},
            {"hasMember": [{}]},
            {"dataAbsentReason": {}},
            {"valueString": "text"},
            {"modifierExtension": [{}]},
            {"contained": [{}]},
        ]:
            with self.subTest(addition=addition):
                self.a.update(addition)
                with self.assertRaises(ValueError):
                    self.check()
                for key in addition:
                    del self.a[key]
        self.bundle["entry"].append({"resource": deepcopy(self.report)})
        with self.assertRaises(ValueError):
            self.check()

    def test_bad_reference_specification(self):
        for key, val in [
            ("rows", []),
            ("schema_version", True),
            ("schema_version", 2),
            ("rows", [{}]),
        ]:
            source = {**self.ref, key: val}
            with self.subTest(key=key), self.assertRaises(ValueError):
                check(source, self.bundle)
        self.ref["rows"].append(deepcopy(self.ref["rows"][1]))
        with self.assertRaises(ValueError):
            self.check()

    def test_two_resources_cannot_own_same_full_url(self):
        self.bundle["entry"][2]["fullUrl"] = self.bundle["entry"][1]["fullUrl"]
        with self.assertRaises(ValueError):
            self.check()

    def test_no_writes_to_inputs(self):
        ref, bundle = deepcopy(self.ref), deepcopy(self.bundle)
        self.check()
        self.assertEqual((ref, bundle), (self.ref, self.bundle))

    def test_http_relative_references_resolve_at_the_source_rest_base(self):
        base = "https://a.example.invalid/fhir/"
        for entry in self.bundle["entry"]:
            resource = entry["resource"]
            entry["fullUrl"] = base + resource["resourceType"] + "/" + resource["id"]
        self.assertEqual(self.check(), [])
        self.bundle["entry"][1]["fullUrl"] = (
            "https://b.example.invalid/fhir/Observation/o1"
        )
        self.assertIn("unresolved-reference", self.codes())

    def test_urn_and_local_reference_convention_cannot_capture_another_host(self):
        self.bundle["entry"][1]["fullUrl"] = (
            "https://b.example.invalid/fhir/Observation/o1"
        )
        self.assertIn("unresolved-reference", self.codes())

    def test_positive_document_bundle_and_invalid_first_entry(self):
        self.bundle["type"] = "document"
        with self.assertRaises(ValueError):
            self.check()
        self.bundle["entry"].insert(
            0, {"resource": {"resourceType": "Composition", "id": "doc"}}
        )
        self.assertEqual(self.check(), [])

    def test_invalid_quantity_comparator_and_extensions_do_not_pass(self):
        self.b["valueQuantity"]["comparator"] = None
        with self.assertRaises(ValueError):
            self.check()
        del self.b["valueQuantity"]["comparator"]
        self.b["valueQuantity"]["_comparator"] = {"extension": [{"url": "urn:example"}]}
        with self.assertRaises(ValueError):
            self.check()

    def test_unrelated_metadata_may_not_contain_unattested_reference_fields(self):
        self.ref["rows"][0]["interpretation"] = "abnormal"
        with self.assertRaises(ValueError):
            self.check()

    def test_importance_of_row_id_when_loinc_is_repeated(self):
        for row, obs in zip(self.ref["rows"], [self.a, self.b]):
            row.update(loinc="1988-5", comparator=None)
            obs["code"]["coding"][0]["code"] = "1988-5"
            obs["valueQuantity"].pop("comparator", None)
        self.assertEqual(self.check(), [])
        self.a["identifier"], self.b["identifier"] = (
            self.b["identifier"],
            self.a["identifier"],
        )
        self.assertEqual(
            self.check(),
            [
                {
                    "code": "value-changed",
                    "field": "valueQuantity.value",
                    "row_id": "r1",
                },
                {
                    "code": "value-changed",
                    "field": "valueQuantity.value",
                    "row_id": "r2",
                },
            ],
        )
        self.bundle["entry"].reverse()
        self.report["result"].reverse()
        self.assertEqual([f["row_id"] for f in self.check()], ["r1", "r2"])

    def test_report_anchor_for_reused_rows(self):
        self.report["identifier"][0]["value"] = "different-report"
        self.assertEqual(self.codes(), ["report-id-changed"])

    def test_modifier_or_implicit_rules_rejected_at_every_level(self):
        specimen = self.add_specimen()
        self.ref["rows"][0]["specimen"] = {"system": SCT, "code": "123"}
        for obj in [
            self.report,
            self.a,
            self.a["valueQuantity"],
            specimen,
            self.a["code"]["coding"][0],
            self.a["identifier"][0],
        ]:
            for key, val in [
                ("modifierExtension", [{"url": "urn:example:negation"}]),
                ("implicitRules", "urn:example:local-rules"),
            ]:
                with self.subTest(resource=obj.get("resourceType"), key=key):
                    obj[key] = val
                    with self.assertRaises(ValueError):
                        self.check()
                    del obj[key]
        self.assertEqual(self.check(), [])

    def test_report_status_is_independent_of_attested_observation_status(self):
        for row, obs in zip(self.ref["rows"], [self.a, self.b]):
            row["status"] = obs["status"] = "final"
        self.assertEqual(self.check(), [])
        self.report["status"] = "final"
        self.assertEqual(self.check(), [])

    def test_valid_wrong_status_and_malformed_assertions(self):
        self.a["status"] = "amended"
        self.assertEqual(self.codes(), ["status-changed"])
        for target, name, val in [
            (self.a, "status", ["final"]),
            (self.a, "status", "made-up"),
            (self.a, "status", None),
            (self.a, "_status", {"extension": []}),
            (self.a, "focus", [{"reference": "Patient/someone-else"}]),
        ]:
            with self.subTest(name=name):
                original = target.get(name)
                target[name] = val
                with self.assertRaises(ValueError):
                    self.check()
                if original is None:
                    del target[name]
                else:
                    target[name] = original

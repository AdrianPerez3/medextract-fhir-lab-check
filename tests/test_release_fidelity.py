"""Regressions for independent row, document and starter identities."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import unittest

from medextract_fhir_lab.adapter import import_starter
from medextract_fhir_lab.checker import check
from medextract_fhir_lab.jsonio import dumps, loads
from medextract_fhir_lab.narrative import check_narrative


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def example(name):
    return loads((EXAMPLES / name).read_bytes())


class ReleaseFidelityTests(unittest.TestCase):
    def test_element_ids_on_measured_fields_do_not_change_the_result(self):
        ref = example("reference.json")
        ref["schema_version"] = 2
        for row in ref["rows"]:
            row.update(kind="quantity", display_unit=row["unit"])
        bundle = example("correct.bundle.json")
        obs = bundle["entry"][1]["resource"]
        quantity = obs["valueQuantity"]
        specimen = bundle["entry"][3]["resource"]
        specimen["status"] = "available"
        for obj, field in [(obs, "status"), (specimen, "status")] + [
            (quantity, k) for k in ("value", "comparator", "unit", "code", "system")
        ]:
            obj["_" + field] = {"id": "annotation-" + field}
            with self.subTest(field=field, resource=obj.get("resourceType")):
                self.assertEqual(check(ref, bundle), [])
            del obj["_" + field]

    def test_element_ids_on_absence_codings_do_not_change_the_reason(self):
        ref = example("absent-reference.json")
        bundle = example("absent-correct.bundle.json")
        coding = bundle["entry"][1]["resource"]["dataAbsentReason"]["coding"][0]
        for field in ("system", "code"):
            coding["_" + field] = {"id": "absent-" + field}
            with self.subTest(field=field):
                self.assertEqual(check(ref, bundle), [])
            del coding["_" + field]

    def test_rest_full_url_cannot_name_another_resource(self):
        ref = example("reference.json")
        bundle = example("correct.bundle.json")
        report, first = bundle["entry"][:2]
        for url in (
            "https://example.org/fhir/Observation/wrong",
            "https://example.org/fhir/Patient/result1",
            "HTTPS://example.org/fhir/Observation/wrong",
        ):
            report["resource"]["result"][0]["reference"] = first["fullUrl"] = url
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "fullUrl"):
                check(ref, bundle)
        # A non-FHIR endpoint need not end in the resource's logical id.
        url = "https://example.org/archive/Records/opaque"
        report["resource"]["result"][0]["reference"] = first["fullUrl"] = url
        self.assertEqual(check(ref, bundle), [])
        url = "https:///Observation/result1"
        report["resource"]["result"][0]["reference"] = first["fullUrl"] = url
        with self.assertRaisesRegex(ValueError, "host"):
            check(ref, bundle)

    def test_opaque_subject_url_can_have_a_capitalized_path(self):
        ref = example("reference.json")
        bundle = example("correct.bundle.json")
        bundle["entry"][1]["resource"]["subject"] = {
            "reference": "https://example.org/archive/Records/person",
            "type": "Patient",
        }
        self.assertEqual(check(ref, bundle), [])

    def test_literal_result_and_attested_row_identifier_must_agree(self):
        ref = example("reference.json")
        bundle = example("correct.bundle.json")
        report = bundle["entry"][0]["resource"]
        first_link = report["result"][0]
        first_link["identifier"] = {"system": ref["identifier_system"], "value": "r02"}
        self.assertEqual(
            check(ref, bundle),
            [
                {
                    "code": "reference-identifier-conflict",
                    "field": "DiagnosticReport.result.identifier",
                    "row_id": "r01",
                }
            ],
        )
        first_link["identifier"]["value"] = "r01"
        self.assertEqual(check(ref, bundle), [])
        first_link["identifier"] = {"system": "urn:vendor:ids", "value": "other"}
        self.assertEqual(check(ref, bundle), [])

    def test_extension_only_implicit_rules_require_separate_interpretation(self):
        ref = example("reference.json")
        bundle = example("correct.bundle.json")
        missing_rules = {
            "extension": [
                {
                    "url": "http://hl7.org/fhir/StructureDefinition/data-absent-reason",
                    "valueCode": "masked",
                }
            ]
        }
        for owner in (bundle, bundle["entry"][1]["resource"]):
            owner["_implicitRules"] = missing_rules
            with (
                self.subTest(owner=owner["resourceType"]),
                self.assertRaisesRegex(ValueError, "implicitRules"),
            ):
                check(ref, bundle)
            del owner["_implicitRules"]

    def test_reviewed_section_focus_cannot_silently_change_subject(self):
        bundle = example("eu-teaching.document.json")
        review = example("eu-narrative-review.json")
        composition = bundle["entry"][0]["resource"]
        section = composition["section"][0]
        other = {
            "fullUrl": "urn:uuid:ea1b0c94-5da9-4206-a818-0f8df4d6e3a8",
            "resource": {"resourceType": "Patient", "id": "other-person"},
        }
        bundle["entry"].append(other)
        section["focus"] = {"reference": other["fullUrl"]}
        with self.assertRaisesRegex(ValueError, "focus"):
            check_narrative(bundle, review)
        section["focus"] = deepcopy(composition["subject"])
        self.assertEqual(check_narrative(bundle, review), [])
        # A different section can describe another person.
        composition["section"].append(
            {
                "code": {"coding": [{"system": "urn:example", "code": "family"}]},
                "focus": {"reference": other["fullUrl"]},
                "text": section["text"],
            }
        )
        self.assertEqual(check_narrative(bundle, review), [])

    def test_starter_checks_any_explicit_report_identifier_on_joined_labels(self):
        row = {"value": "1", "unit": "mg/L", "loinc": "1988-5"}
        side = {
            "schema_version": 1,
            "report_id": "source",
            "pages": [{"page": 1, "rows": [{"result_index": 0, "loinc": "1988-5"}]}],
        }
        for visible_id, normalized_id in (("other", "source"), ("source", "other")):
            norm = {"report_id": normalized_id, "results": [row]}
            visible = dumps({"report_id": visible_id, "results": [row]}).encode()
            side["ground_truth_sha256"] = sha256(visible).hexdigest()
            with (
                self.subTest(visible_id=visible_id),
                self.assertRaisesRegex(ValueError, "report"),
            ):
                import_starter(visible, norm, side, "urn:fixture:rows")
        norm = {"report_id": "source", "results": [row]}
        visible = dumps(norm).encode()
        side["ground_truth_sha256"] = sha256(visible).hexdigest()
        self.assertEqual(
            import_starter(visible, norm, side, "urn:fixture:rows")["report_id"],
            "source",
        )

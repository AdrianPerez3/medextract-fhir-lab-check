"""Single-subject consistency checks on synthetic R4 report and document graphs."""

import copy
import unittest
from pathlib import Path

from medextract_fhir_lab.checker import check
from medextract_fhir_lab.jsonio import loads


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
BASE = "https://example.org/fhir/"
DANGLING = "urn:uuid:00000000-0000-4000-8000-000000000001"


class SubjectGraphTests(unittest.TestCase):
    def setUp(self):
        self.ref = loads((EXAMPLES / "reference.json").read_bytes())
        self.bundle = loads((EXAMPLES / "correct.bundle.json").read_bytes())
        self.report, self.first, self.second, self.serum = [
            entry["resource"] for entry in self.bundle["entry"]
        ]

    def findings(self):
        return check(self.ref, self.bundle)

    def test_nullified_specimen_cannot_support_even_a_matching_type(self):
        self.serum["status"] = "entered-in-error"
        self.assertEqual(
            self.findings(),
            [
                {
                    "code": "invalidated-specimen",
                    "field": "specimen.status",
                    "row_id": "r02",
                }
            ],
        )

    def test_specimen_lifecycle_is_not_assumed_from_numeric_results(self):
        for status in ["available", "unavailable", "unsatisfactory"]:
            with self.subTest(status=status):
                self.serum["status"] = status
                self.assertEqual(self.findings(), [])
        for status in ["final", None, []]:
            with (
                self.subTest(status=status),
                self.assertRaisesRegex(ValueError, "Specimen.status"),
            ):
                self.serum["status"] = status
                self.findings()
        del self.serum["status"]
        self.serum["_status"] = {"extension": [{"url": "https://example.org/unknown"}]}
        with self.assertRaisesRegex(ValueError, "Specimen.status"):
            self.findings()

    def test_report_subject_cannot_be_resolved_to_a_specimen(self):
        self.report["subject"] = {"reference": "Specimen/serum"}
        self.assertEqual(
            self.findings(),
            [{"code": "subject-type-mismatch", "field": "DiagnosticReport.subject"}],
        )

    def test_declared_target_type_must_match_the_resource(self):
        self.bundle["entry"].append(
            {"fullUrl": DANGLING, "resource": {"resourceType": "Device", "id": "d"}}
        )
        self.first["subject"] = {"reference": DANGLING, "type": "Patient"}
        issues = self.findings()
        self.assertEqual(
            issues,
            [{"code": "subject-type-mismatch", "field": "subject", "row_id": "r01"}],
        )
        self.assertNotIn(DANGLING, str(issues))

    def test_rest_reference_type_must_match_declared_type_even_outside_bundle(self):
        self.second["subject"] = {"reference": "Patient/external", "type": "Group"}
        self.assertEqual(
            self.findings(),
            [{"code": "subject-type-mismatch", "field": "subject", "row_id": "r02"}],
        )

    def test_missing_urn_target_is_detected_even_when_all_addresses_agree(self):
        for r in [self.report, self.first, self.second, self.serum]:
            r["subject"] = {"reference": DANGLING}
        issues = self.findings()
        self.assertEqual(len(issues), 4)
        self.assertEqual({i["code"] for i in issues}, {"unresolved-reference"})
        self.assertNotIn(DANGLING, str(issues))

    def test_external_typed_rest_subjects_in_collection_can_agree_offline(self):
        self.report["subject"] = {"reference": BASE + "Patient/absent"}
        self.first["subject"] = {"reference": "Patient/absent", "type": "Patient"}
        self.assertEqual(self.findings(), [])

    def test_external_opaque_http_url_needs_type_evidence(self):
        self.first["subject"] = {"reference": "https://example.org/subjects/key"}
        with self.assertRaisesRegex(ValueError, "type"):
            self.findings()
        self.first["subject"]["type"] = "Patient"
        self.assertEqual(self.findings(), [])

    def test_composition_subject_cannot_identify_another_bundled_patient(self):
        self.bundle = loads((EXAMPLES / "eu-teaching.document.json").read_bytes())
        self.bundle["entry"].append(
            {
                "fullUrl": DANGLING,
                "resource": {
                    "resourceType": "Patient",
                    "id": "second-synthetic-patient",
                },
            }
        )
        self.bundle["entry"][0]["resource"]["subject"] = {"reference": DANGLING}
        self.assertEqual(
            self.findings(),
            [{"code": "subject-conflict", "field": "Composition.subject"}],
        )

    def test_document_requires_a_directly_referenced_composition_subject_locally(self):
        self.bundle = loads((EXAMPLES / "eu-teaching.document.json").read_bytes())
        for entry in self.bundle["entry"]:
            resource = entry["resource"]
            if "subject" in resource:
                resource["subject"] = {"reference": BASE + "Patient/external"}
        self.assertEqual(
            self.findings(),
            [{"code": "unresolved-reference", "field": "Composition.subject"}],
        )

    def test_specimen_subject_on_one_row_conflicts_with_another_rows_subject(self):
        self.first["subject"] = {"reference": "Patient/one"}
        self.serum["subject"] = {"reference": "Patient/two"}
        self.assertEqual(
            self.findings(), [{"code": "subject-conflict", "field": "subject"}]
        )

    def test_local_specimen_conflict_has_one_attributable_finding(self):
        self.second["subject"] = {"reference": "Patient/one"}
        self.serum["subject"] = {"reference": "Patient/two"}
        self.assertEqual(
            self.findings(),
            [
                {
                    "code": "subject-conflict",
                    "field": "specimen.subject",
                    "row_id": "r02",
                }
            ],
        )

    def test_different_specimen_subjects_cannot_hide_behind_missing_observation_subjects(
        self,
    ):
        first_specimen = copy.deepcopy(self.serum)
        first_specimen["id"] = "first"
        first_specimen["subject"] = {"reference": "Patient/one"}
        self.bundle["entry"].append(
            {"resource": first_specimen, "fullUrl": BASE + "Specimen/first"}
        )
        self.first["specimen"] = {"reference": "Specimen/first"}
        self.ref["rows"][0]["specimen"] = self.ref["rows"][1]["specimen"].copy()
        self.serum["subject"] = {"reference": "Patient/two"}
        self.assertEqual(
            self.findings(), [{"code": "subject-conflict", "field": "subject"}]
        )
        first_specimen["subject"] = {"reference": "Patient/two"}
        self.assertEqual(self.findings(), [])

    def test_absent_subjects_and_valid_target_types_have_no_fabricated_identity(self):
        self.assertEqual(self.findings(), [])
        for kind in ("Patient", "Group", "Device", "Location"):
            with self.subTest(kind=kind):
                self.report["subject"] = {"reference": kind + "/source"}
                self.assertEqual(self.findings(), [])
        del self.report["subject"]
        self.serum["subject"] = {"reference": "Substance/mixed-sample"}
        self.assertEqual(self.findings(), [])
        self.first["subject"] = {"reference": "Substance/mixed-sample"}
        self.assertEqual(
            self.findings(),
            [{"code": "subject-type-mismatch", "field": "subject", "row_id": "r01"}],
        )

    def test_local_subject_aliases_and_external_server_boundaries(self):
        self.bundle["entry"].append(
            {
                "fullUrl": BASE + "Patient/one",
                "resource": {"resourceType": "Patient", "id": "one"},
            }
        )
        self.report["subject"] = {"reference": BASE + "Patient/one"}
        self.first["subject"] = {"reference": "Patient/one"}
        self.assertEqual(self.findings(), [])
        self.first["subject"] = {
            "reference": "https://another.example/fhir/Patient/one"
        }
        self.assertEqual(
            self.findings(),
            [{"code": "subject-conflict", "field": "subject", "row_id": "r01"}],
        )

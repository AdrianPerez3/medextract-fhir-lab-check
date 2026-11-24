"""Independent manifest tests use the same fixtures as the end-to-end checker."""

from copy import deepcopy
from pathlib import Path
import unittest

from medextract_fhir_lab.binding import bind
from medextract_fhir_lab.checker import check
from medextract_fhir_lab.jsonio import loads


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def read_fixture(name):
    return loads((EXAMPLES / name).read_bytes())


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.ref = read_fixture("reference.json")
        self.manifest = read_fixture("bindings.json")
        self.bundle = read_fixture("correct.bundle.json")
        self.report, self.first, self.second, *_ = [
            entry["resource"] for entry in self.bundle["entry"]
        ]
        for resource in (self.report, self.first, self.second):
            resource.pop("identifier")

    def bind(self):
        return bind(self.ref, self.bundle, self.manifest)

    def test_no_vendor_ids_needed_and_other_identifiers_are_preserved(self):
        ordinary = {"system": "urn:example:vendor", "value": "native-id"}
        self.first["identifier"] = [ordinary]
        baseline = deepcopy((self.ref, self.bundle, self.manifest))
        bound = self.bind()
        self.assertEqual(check(self.ref, bound), [])
        self.assertEqual(
            bound["entry"][1]["resource"]["identifier"],
            [ordinary, {"system": self.ref["identifier_system"], "value": "r01"}],
        )
        bound["entry"][1]["resource"]["identifier"][0]["value"] = "edited"
        self.assertEqual((self.ref, self.bundle, self.manifest), baseline)
        self.assertIn(
            "missing-identifier", {f["code"] for f in check(self.ref, self.bundle)}
        )

    def test_reordering_all_inputs_does_not_change_the_outcome(self):
        self.bundle["entry"].reverse()
        self.report["result"].reverse()
        self.ref["rows"].reverse()
        self.manifest["rows"].reverse()
        self.assertEqual(check(self.ref, self.bind()), [])

    def test_different_report_id_and_wrong_target(self):
        for field, value in [
            ("report_id", "LAB-OTHER"),
            ("report_full_url", self.manifest["rows"][0]["observation_full_url"]),
            ("report_full_url", "https://external.example/DiagnosticReport/no-report"),
            ("report_full_url", "DiagnosticReport/report1"),
        ]:
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    bind(self.ref, self.bundle, {**self.manifest, field: value})

    def test_swapped_result_values_still_fail_under_a_correct_binding(self):
        a, b = self.first["valueQuantity"], self.second["valueQuantity"]
        a["value"], b["value"] = b["value"], a["value"]
        self.assertEqual(
            check(self.ref, self.bind()),
            [
                {
                    "code": "value-changed",
                    "field": "valueQuantity.value",
                    "row_id": "r01",
                },
                {
                    "code": "value-changed",
                    "field": "valueQuantity.value",
                    "row_id": "r02",
                },
            ],
        )

    def test_wrong_independent_mapping_is_never_corrected_using_candidate_values(self):
        a, b = self.manifest["rows"]
        a["observation_full_url"], b["observation_full_url"] = (
            b["observation_full_url"],
            a["observation_full_url"],
        )
        differences = check(self.ref, self.bind())
        self.assertEqual(
            [d["row_id"] for d in differences if d["code"] == "loinc-changed"],
            ["r01", "r02"],
        )

    def test_target_must_exist_and_be_an_observation(self):
        for address in [
            self.manifest["report_full_url"],
            self.bundle["entry"][3]["fullUrl"],
            "https://example.org/fhir/Observation/absent",
            "Observation/result1",
        ]:
            self.manifest["rows"][0]["observation_full_url"] = address
            with self.subTest(address=address), self.assertRaises(ValueError):
                self.bind()

    def test_duplicate_row_or_observation_and_partial_or_unknown_bindings_fail(self):
        first, second = self.manifest["rows"]
        for rows in [
            [first, {**second, "row_id": "r01"}],
            [first, {**second, "observation_full_url": first["observation_full_url"]}],
            [first],
            [],
            [first, {**second, "row_id": "r99"}],
        ]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                bind(self.ref, self.bundle, {**self.manifest, "rows": rows})

    def test_missing_candidate_row_remains_unbindable_even_if_manifest_is_shortened(
        self,
    ):
        self.bundle["entry"].pop(2)
        self.report["result"].pop()
        with self.assertRaises(ValueError):
            self.bind()
        self.manifest["rows"].pop()
        with self.assertRaises(ValueError):
            self.bind()

    def test_duplicate_fullurl_ambiguous_even_if_target_is_unused(self):
        self.bundle["entry"].append(deepcopy(self.bundle["entry"][3]))
        with self.assertRaises(ValueError):
            self.bind()

    def test_matching_existing_project_ids_are_idempotent(self):
        self.bundle = read_fixture("correct.bundle.json")
        self.assertEqual(self.bind(), self.bundle)

    def test_conflicting_existing_project_identifiers_are_errors(self):
        for resource, system in [
            (self.first, self.ref["identifier_system"]),
            (self.report, self.ref["identifier_system"] + "/reports"),
        ]:
            resource["identifier"] = [{"system": system, "value": "private-conflict"}]
            with self.assertRaises(ValueError) as exc:
                self.bind()
            self.assertNotIn("private-conflict", str(exc.exception))
            resource.pop("identifier")
        self.first["identifier"] = [
            {"system": self.ref["identifier_system"], "value": "r01"}
        ] * 2
        with self.assertRaises(ValueError):
            self.bind()

    def test_extra_observations_and_broken_diagnostic_report_link_still_reach_checker(
        self,
    ):
        extra = deepcopy(self.bundle["entry"][1])
        extra["fullUrl"] += "-extra"
        extra["resource"]["id"] += "-extra"
        self.bundle["entry"].append(extra)
        self.report["result"][0]["reference"] = "Observation/missing"
        findings = check(self.ref, self.bind())
        self.assertIn(
            {
                "code": "missing-row",
                "row_id": "r01",
                "field": "DiagnosticReport.result",
            },
            findings,
        )
        self.assertEqual(sum(f["code"] == "unlinked-observation" for f in findings), 2)
        self.assertIn("unresolved-reference", [f["code"] for f in findings])

    def test_conflicting_claim_on_a_different_unbound_candidate_resource_fails(self):
        extra = deepcopy(self.bundle["entry"][1])
        extra["fullUrl"] += "-extra"
        extra["resource"]["id"] += "-extra"
        extra["resource"]["identifier"] = [
            {"system": self.ref["identifier_system"], "value": "r01"}
        ]
        self.bundle["entry"].append(extra)
        with self.assertRaises(ValueError):
            self.bind()

    def test_missing_malformed_or_unrecognized_manifest_fields(self):
        for manifest in [
            None,
            {},
            {**self.manifest, "schema_version": True},
            {**self.manifest, "extra": "unused"},
            {**self.manifest, "rows": {}},
            {**self.manifest, "rows": [[]]},
            {**self.manifest, "rows": [{"row_id": "r01"}]},
            {
                **self.manifest,
                "rows": [{"row_id": [], "observation_full_url": "urn:example:demo"}],
            },
        ]:
            with self.subTest(manifest=manifest), self.assertRaises(ValueError):
                bind(self.ref, self.bundle, manifest)

    def test_exact_urn_targets_with_sender_owned_relative_resource_ids(self):
        addresses = [
            f"urn:uuid:00000000-0000-4000-8000-00000000000{i}" for i in range(1, 5)
        ]
        for entry, address in zip(self.bundle["entry"], addresses):
            entry["fullUrl"] = address
        self.manifest["report_full_url"] = addresses[0]
        self.manifest["rows"][0]["observation_full_url"] = addresses[1]
        self.manifest["rows"][1]["observation_full_url"] = addresses[2]
        for ref, address in zip(self.report["result"], addresses[1:3]):
            ref["reference"] = address
        self.second["specimen"]["reference"] = addresses[3]
        self.assertEqual(check(self.ref, self.bind()), [])

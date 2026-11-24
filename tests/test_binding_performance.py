"""The indexed binding path must preserve both findings and the original candidate."""

from copy import deepcopy
from pathlib import Path
import unittest

from medextract_fhir_lab.binding import _bound_graph, bind
from medextract_fhir_lab.checker import _check_graph, check, validate_reference
from medextract_fhir_lab.jsonio import loads


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class IndexedBindingTests(unittest.TestCase):
    def setUp(self):
        self.reference = loads((EXAMPLES / "reference.json").read_bytes())
        self.manifest = loads((EXAMPLES / "bindings.json").read_bytes())
        self.bundle = loads((EXAMPLES / "lost-limit.bundle.json").read_bytes())
        validate_reference(self.reference)
        for entry in self.bundle["entry"]:
            if "identifier" in entry["resource"]:
                entry["resource"]["identifier"] = [
                    {"system": "urn:sender", "value": "native"}
                ]

    def test_indexed_comparison_preserves_findings_and_all_inputs(self):
        inputs = self.reference, self.bundle, self.manifest
        before = deepcopy(inputs)
        graph = _bound_graph(*inputs)
        materialized = bind(*inputs)
        findings = _check_graph(self.reference, graph)
        self.assertEqual(findings, check(self.reference, materialized))
        self.assertEqual(
            findings,
            [
                {
                    "code": "comparator-changed",
                    "field": "valueQuantity.comparator",
                    "row_id": "r01",
                }
            ],
        )
        # Mutating an untouched, deeply nested Specimen in the public copy must
        # also leave both the candidate and the comparison graph intact.
        specimen = next(
            e["resource"]
            for e in materialized["entry"]
            if e["resource"]["resourceType"] == "Specimen"
        )
        specimen["type"]["coding"].clear()
        self.assertEqual(_check_graph(self.reference, graph), findings)
        self.assertEqual(inputs, before)

    def test_late_conflict_leaves_earlier_resources_unmodified(self):
        self.bundle["entry"][2]["resource"]["identifier"] = [
            {"system": self.reference["identifier_system"], "value": "conflict"},
        ]
        original = deepcopy(self.bundle)
        with self.assertRaisesRegex(ValueError, "conflicts"):
            _bound_graph(self.reference, self.bundle, self.manifest)
        self.assertEqual(self.bundle, original)


if __name__ == "__main__":
    unittest.main()

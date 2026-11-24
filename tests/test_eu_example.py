"""Regression checks for the two rows in the hand-authored EU teaching document."""

from pathlib import Path
import unittest

from medextract_fhir_lab.checker import check
from medextract_fhir_lab.jsonio import loads


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class EuropeanDocumentTest(unittest.TestCase):
    def test_source_rows_keep_their_meaning_inside_the_document(self):
        reference = loads((EXAMPLES / "reference.json").read_bytes())
        document = loads((EXAMPLES / "eu-teaching.document.json").read_bytes())
        self.assertEqual(document["type"], "document")
        self.assertEqual(
            document["entry"][0]["resource"]["resourceType"], "Composition"
        )
        self.assertEqual(check(reference, document), [])

        row = next(
            entry["resource"]
            for entry in document["entry"]
            if entry["resource"]["resourceType"] == "Observation"
            and entry["resource"]["identifier"][0]["value"] == "r01"
        )
        self.assertNotIn("specimen", row)
        self.assertEqual(row["status"], "unknown")
        self.assertEqual(row["valueQuantity"].pop("comparator"), "<=")
        self.assertEqual(
            check(reference, document),
            [
                {
                    "row_id": "r01",
                    "field": "valueQuantity.comparator",
                    "code": "comparator-changed",
                }
            ],
        )

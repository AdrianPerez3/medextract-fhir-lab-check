import hashlib
import unittest
from pathlib import Path

from medextract_fhir_lab.adapter import import_starter
from medextract_fhir_lab.checker import check
from medextract_fhir_lab.jsonio import loads

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
STARTER = EXAMPLES / "starter"


class StarterExampleTests(unittest.TestCase):
    def test_original_starter_hashes(self):
        for line in (STARTER / "SHA256SUMS").read_text().splitlines():
            expected, filename = line.split("  ")
            with self.subTest(file=filename):
                self.assertEqual(
                    hashlib.sha256((STARTER / filename).read_bytes()).hexdigest(),
                    expected,
                )

    def test_wrong_association_in_adjoining_rows_of_printed_report(self):
        ref = import_starter(
            (STARTER / "visible.json").read_bytes(),
            loads((STARTER / "normalized.json").read_bytes()),
            loads((STARTER / "coordinates.json").read_bytes()),
            "https://example.org/medextract/starter/rows",
        )
        # These are independent transcriptions of the adjacent numeric cells on the public PDF.
        self.assertEqual(
            [(r["id"], r["loinc"], r["value"]) for r in ref["rows"][9:11]],
            [("RPT_000726.10", "2160-0", "0.726"), ("RPT_000726.11", "2345-7", "83.6")],
        )
        candidate = loads((EXAMPLES / "starter-swapped.bundle.json").read_bytes())
        self.assertEqual(
            check(ref, candidate),
            [
                {
                    "code": "value-changed",
                    "field": "valueQuantity.value",
                    "row_id": "RPT_000726.10",
                },
                {
                    "code": "value-changed",
                    "field": "valueQuantity.value",
                    "row_id": "RPT_000726.11",
                },
            ],
        )

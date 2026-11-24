import json
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from medextract_fhir_lab.adapter import export_bundle, import_starter
from medextract_fhir_lab.jsonio import dumps, loads

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "examples"


def cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "medextract_fhir_lab", *map(str, args)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


class InterfaceTests(unittest.TestCase):
    def test_independently_written_fixtures(self):
        for name, code in [("correct", 0), ("lost-limit", 1)]:
            with self.subTest(name=name):
                result = cli(
                    "check",
                    "--reference",
                    EX / "reference.json",
                    "--bundle",
                    EX / f"{name}.bundle.json",
                )
                self.assertEqual(result.returncode, code, result.stderr)
                result = json.loads(result.stdout)
                self.assertEqual(len(result["findings"]), code)
                if code:
                    self.assertEqual(
                        result["findings"][0]["code"], "comparator-changed"
                    )

    def test_export_is_checkable_and_lossless(self):
        reference = loads((EX / "reference.json").read_bytes())
        reference["rows"][0]["value"] = "0.100000000000000000000123400"
        bundle = export_bundle(reference)
        self.assertEqual(dumps(bundle), dumps(export_bundle(reference)))
        with tempfile.TemporaryDirectory() as d:
            ref, candidate = Path(d) / "ref.json", Path(d) / "bundle.json"
            ref.write_text(dumps(reference))
            raw = cli("export", "--reference", ref)
            self.assertEqual(raw.returncode, 0, raw.stderr)
            self.assertIn(
                '"value":0.100000000000000000000123400', raw.stdout.replace(" ", "")
            )
            candidate.write_text(raw.stdout)
            check = cli("check", "--reference", ref, "--bundle", candidate)
            self.assertEqual(check.returncode, 0, check.stderr)
        observations = [
            e["resource"]
            for e in bundle["entry"]
            if e["resource"]["resourceType"] == "Observation"
        ]
        self.assertEqual(observations[0]["valueQuantity"]["comparator"], "<=")
        self.assertEqual(observations[0]["status"], "unknown")
        self.assertNotIn("specimen", observations[0])
        self.assertEqual(observations[1]["status"], "final")
        self.assertIn("specimen", observations[1])

    def test_invalid_json_and_duplicate_keys_are_input_errors(self):
        for raw in [
            b'{"rows":[],"rows":[]}',
            b'{"v":NaN}',
            b'{"v":Infinity}',
            b'{"v":',
        ]:
            with self.assertRaises(ValueError):
                loads(raw)
        run = cli(
            "check",
            "--reference",
            EX / "reference.json",
            "--bundle",
            EX / "does-not-exist.json",
        )
        self.assertEqual(run.returncode, 2)
        self.assertFalse(run.stdout.strip())

    def test_starter_import_binds_visible_label_and_normalized_value(self):
        visible = b'{"results":[{"value":"1.234","unit":"mg/dL","loinc":"2345-7"}]}'
        normalized = {
            "results": [{"value": "1234", "unit": "mg/dL", "loinc": "2345-7"}]
        }
        side = {
            "schema_version": 1,
            "report_id": "FICT-01",
            "ground_truth_sha256": sha256(visible).hexdigest(),
            "pages": [{"page": 1, "rows": [{"result_index": 0, "loinc": "2345-7"}]}],
        }
        r = import_starter(visible, normalized, side, "https://example.org/rows")
        self.assertEqual(r["rows"][0]["id"], "FICT-01.1")
        self.assertEqual(r["rows"][0]["value"], "1234")
        self.assertIsNone(r["rows"][0]["specimen"])
        with self.assertRaises(ValueError):
            import_starter(visible + b" ", normalized, side, "https://example.org/rows")
        normalized["results"][0]["value"] = "12.34"
        with self.assertRaises(ValueError):
            import_starter(visible, normalized, side, "https://example.org/rows")
        normalized["results"][0]["value"] = "1234"
        side["pages"][0]["rows"][0]["result_index"] = 1
        with self.assertRaises(ValueError):
            import_starter(visible, normalized, side, "https://example.org/rows")

    def test_starter_rejects_missing_units_and_new_clinical_fields(self):
        row = {"value": "1", "unit": "mg/L", "loinc": "1988-5"}
        for changes in [
            {"unit": None},
            {"comparator": "<"},
            {"specimen": "SER"},
            {"flag": "H"},
            {"reference_range": "10–12"},
        ]:
            modified = {**row, **changes}
            if modified["unit"] is None:
                del modified["unit"]
            normalized = {"results": [modified]}
            visible = json.dumps(normalized).encode()
            side = {
                "schema_version": 1,
                "report_id": "T",
                "ground_truth_sha256": sha256(visible).hexdigest(),
                "pages": [
                    {"page": 1, "rows": [{"result_index": 0, "loinc": "1988-5"}]}
                ],
            }
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                import_starter(visible, normalized, side, "https://example.org/rows")

    def test_starter_joins_normalized_labels_by_unique_loinc_in_visible_order(self):
        a = {"value": "1", "unit": "mg/L", "loinc": "1988-5"}
        b = {"value": "2", "unit": "mg/dL", "loinc": "2345-7"}
        visible = json.dumps({"results": [a, b]}).encode()
        side = {
            "schema_version": 1,
            "report_id": "T",
            "ground_truth_sha256": sha256(visible).hexdigest(),
            "pages": [
                {
                    "page": 1,
                    "rows": [
                        {"result_index": i, "loinc": row["loinc"]}
                        for i, row in enumerate([a, b])
                    ],
                }
            ],
        }
        ns = "https://example.org/rows"
        ref = import_starter(visible, {"results": [b, a]}, side, ns)
        self.assertEqual(
            [(row["id"], row["loinc"]) for row in ref["rows"]],
            [("T.1", "1988-5"), ("T.2", "2345-7")],
        )
        with self.assertRaises(ValueError):
            import_starter(visible, {"results": [a, a]}, side, ns)
        visible = json.dumps({"results": [a, a]}).encode()
        side["ground_truth_sha256"] = sha256(visible).hexdigest()
        side["pages"][0]["rows"][1]["loinc"] = a["loinc"]
        with self.assertRaises(ValueError):
            import_starter(visible, {"results": [a, b]}, side, ns)

    def test_check_with_external_bindings_leaves_vendor_file_intact(self):
        doc = json.loads((EX / "lost-limit.bundle.json").read_bytes())
        for entry in doc["entry"]:
            entry["resource"].pop("identifier", None)
        with tempfile.TemporaryDirectory() as folder:
            vendor = Path(folder) / "vendor.json"
            original = json.dumps(doc).encode()
            vendor.write_bytes(original)
            run = cli(
                "check",
                "--reference",
                EX / "reference.json",
                "--bundle",
                vendor,
                "--bindings",
                EX / "bindings.json",
            )
            self.assertEqual(run.returncode, 1, run.stderr)
            self.assertEqual(
                json.loads(run.stdout)["findings"],
                [
                    {
                        "row_id": "r01",
                        "code": "comparator-changed",
                        "field": "valueQuantity.comparator",
                    }
                ],
            )
            self.assertEqual(vendor.read_bytes(), original)

    def test_exact_json_decimal_and_string_escaping(self):
        value = {"label": 'a"b', "n": Decimal("1.20")}
        self.assertEqual(loads(dumps(value)), value)
        self.assertIn("1.20", dumps(value))

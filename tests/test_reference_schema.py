"""Keep the published source-fixture schema in step with the offline Python checker."""

import copy
from pathlib import Path
import re
import unittest

from medextract_fhir_lab.checker import _STATUSES, validate_reference
from medextract_fhir_lab.jsonio import loads
from medextract_fhir_lab.result_value import COMPARATORS, REASONS

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/reference-v2.schema.json"
FIXTURE = ROOT / "examples/absent-reference.json"


class ReferenceSchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = loads(SCHEMA.read_bytes())
        self.defs = self.schema["$defs"]
        self.reference = loads(FIXTURE.read_bytes())

    def test_closed_required_field_sets_match_the_worked_case(self):
        schema = self.schema
        self.assertEqual(
            schema["$schema"], "https://json-schema.org/draft/2020-12/schema"
        )
        self.assertEqual(
            schema["properties"]["schema_version"], {"type": "integer", "const": 2}
        )
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(self.reference))
        self.assertEqual(schema["properties"]["rows"]["minItems"], 1)
        self.assertFalse(self.defs["row"]["unevaluatedProperties"])
        for row in self.reference["rows"]:
            fields = set(self.defs["commonRow"]["required"]) | set(
                self.defs[row["kind"]]["required"]
            )
            optional = set(self.defs[row["kind"]]["properties"]) - set(
                self.defs[row["kind"]]["required"]
            )
            self.assertEqual(
                optional,
                {"display_unit", "preserve_decimal_places"}
                if row["kind"] == "quantity"
                else set(),
            )
            self.assertEqual(set(row), fields | optional)
            for removed in fields:
                doc = copy.deepcopy(self.reference)
                target = next(r for r in doc["rows"] if r["kind"] == row["kind"])
                del target[removed]
                with (
                    self.subTest(kind=row["kind"], removed=removed),
                    self.assertRaises(ValueError),
                ):
                    validate_reference(doc)

    def test_enums_follow_runtime_and_reject_as_text(self):
        self.assertEqual(set(self.defs["status"]["enum"]), _STATUSES | {None})
        self.assertEqual(
            set(self.defs["quantity"]["properties"]["comparator"]["enum"]),
            set(COMPARATORS),
        )
        reasons = self.defs["absent"]["properties"]["absent_reason"]["enum"]
        self.assertEqual(set(reasons), REASONS)
        self.assertEqual(len(reasons), 14)
        self.assertNotIn("as-text", reasons)

    def test_all_schema_references_are_bundled(self):
        def visit(obj):
            if isinstance(obj, dict):
                if "$ref" in obj:
                    self.assertTrue(obj["$ref"].startswith("#/$defs/"))
                    self.assertIn(obj["$ref"].split("/")[-1], self.defs)
                for v in obj.values():
                    visit(v)
            elif isinstance(obj, list):
                for v in obj:
                    visit(v)

        visit(self.schema)

    def test_source_decimal_pattern_preserves_wire_precision(self):
        shape = self.defs["decimalLiteral"]
        for value in ["0", "-1", "+0.000", "1.2500", "1e2", "٠", "3\n", "2.", ".5", ""]:
            row = self.reference["rows"][1]
            row["value"] = value
            allowed = re.search(shape["pattern"], value) and not re.search(
                shape["not"]["pattern"], value
            )
            if allowed:
                validate_reference(self.reference)
            else:
                with self.subTest(value=value), self.assertRaises(ValueError):
                    validate_reference(self.reference)

    def test_rejects_duplicate_ids_and_fractional_version_tokens_after_decoding(self):
        for doc in [
            loads(
                FIXTURE.read_text().replace(
                    '"schema_version": 2', '"schema_version": 2.0'
                )
            ),
            dict(
                self.reference,
                rows=[
                    self.reference["rows"][0],
                    dict(self.reference["rows"][1], id=self.reference["rows"][0]["id"]),
                ],
            ),
        ]:
            with self.assertRaises(ValueError):
                validate_reference(doc)

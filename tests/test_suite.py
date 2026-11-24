import json
import tempfile
import unittest
from pathlib import Path

from medextract_fhir_lab.suite import run_suite


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class SuiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "case-pack"
        self.root.mkdir()
        self.manifest = self.root / "suite.json"
        for name in (
            "reference.json",
            "correct.bundle.json",
            "lost-limit.bundle.json",
            "bindings.json",
        ):
            (self.root / name).write_bytes((EXAMPLES / name).read_bytes())

    @staticmethod
    def case(case_id, bundle="correct.bundle.json", **extra):
        return {"id": case_id, "reference": "reference.json", "bundle": bundle, **extra}

    def run_cases(self, *cases):
        self.manifest.write_text(
            json.dumps({"schema_version": 1, "cases": list(cases)})
        )
        return run_suite(self.manifest)

    def test_public_example_runs_every_case_and_reports_exact_discrepancies(self):
        report, status = run_suite(EXAMPLES / "pilot.suite.json")
        self.assertEqual(status, 1)
        self.assertEqual(report["result"], "fail")
        self.assertEqual(
            [(c["id"], c["result"]) for c in report["cases"]],
            [
                ("eu-document", "pass"),
                ("lost-comparator", "fail"),
                ("absent-and-measured-zero", "pass"),
                ("invented-zero", "fail"),
                ("changed-human-readable-result", "fail"),
            ],
        )
        self.assertEqual(
            report["summary"],
            {
                "total_reports": 5,
                "report_counts": {"pass": 2, "fail": 3, "unevaluable": 0},
                "known_expected_rows": 10,
                "evaluated_expected_rows": 10,
                "reports_with_unknown_expected_rows": 0,
                "affected_expected_rows": 2,
                "finding_counts": {
                    "comparator-changed": 1,
                    "invented-value": 1,
                    "narrative-changed": 1,
                },
            },
        )
        self.assertEqual(
            report["cases"][1]["finding_counts"], {"comparator-changed": 1}
        )

    def test_optional_narrative_input_is_counted_and_private(self):
        report, code = self.run_cases(
            self.case(
                "broken-review",
                "correct.bundle.json",
                narrative_review="unavailable-private-name.json",
            )
        )
        self.assertEqual(code, 2)
        self.assertEqual(report["cases"][0]["error_stage"], "narrative_review")
        self.assertNotIn("unavailable-private-name", json.dumps(report))

    def test_valid_run_with_bindings_is_reproducible(self):
        path = self.root / "producer.json"
        vendor = json.loads((self.root / "correct.bundle.json").read_bytes())
        for entry in vendor["entry"]:
            entry["resource"].pop("identifier", None)
        original_bytes = json.dumps(vendor).encode()
        path.write_bytes(original_bytes)
        case = self.case("own-export", path.name, bindings="bindings.json")
        report, status = self.run_cases(case)
        self.assertEqual(status, 0)
        self.assertEqual(report["result"], "pass")
        self.assertEqual(
            report["cases"],
            [
                {
                    "id": "own-export",
                    "result": "pass",
                    "expected_rows": 2,
                    "affected_expected_rows": 0,
                    "finding_counts": {},
                }
            ],
        )
        self.assertEqual(run_suite(self.manifest), (report, status))
        self.assertEqual(path.read_bytes(), original_bytes)

    def test_mixed_run_keeps_denominators_and_does_not_emit_document_details(self):
        (self.root / "private-bundle.json").write_text(
            '{"private-data": 1, "private-data": 2}'
        )
        (self.root / "invalid-reference.json").write_text('{"rows":[]}')
        bundle = json.loads((self.root / "correct.bundle.json").read_bytes())
        obs = next(
            e["resource"]
            for e in bundle["entry"]
            if e["resource"]["resourceType"] == "Observation"
        )
        obs["valueString"] = "PRIVATE-CLINICAL-VALUE"
        del obs["valueQuantity"]
        (self.root / "qualitative.json").write_text(json.dumps(bundle))
        run, status = self.run_cases(
            self.case("a", "private-bundle.json"),
            self.case("b", "lost-limit.bundle.json"),
            self.case("c", reference="invalid-reference.json"),
            self.case("d", "qualitative.json"),
            self.case("e", bindings="private-missing-bindings.json"),
            self.case("f"),
        )
        self.assertEqual(status, 2)
        self.assertEqual(run["result"], "unevaluable")
        self.assertEqual([c["id"] for c in run["cases"]], list("abcdef"))
        self.assertEqual(
            [c.get("error_stage") for c in run["cases"]],
            ["bundle", None, "reference", "comparison", "bindings", None],
        )
        self.assertEqual(
            [c["expected_rows"] for c in run["cases"]], [2, 2, None, 2, 2, 2]
        )
        self.assertIsNone(run["cases"][0]["finding_counts"])
        self.assertIsNone(run["cases"][0]["affected_expected_rows"])
        self.assertEqual(
            run["summary"],
            {
                "total_reports": 6,
                "report_counts": {"pass": 1, "fail": 1, "unevaluable": 4},
                "known_expected_rows": 10,
                "evaluated_expected_rows": 4,
                "reports_with_unknown_expected_rows": 1,
                "affected_expected_rows": 1,
                "finding_counts": {"comparator-changed": 1},
            },
        )
        output = json.dumps(run)
        for secret in (
            "LAB-DEMO",
            "r01",
            self.temp.name,
            ".json",
            "PRIVATE",
            "private-data",
            "2345-7",
        ):
            self.assertNotIn(secret, output)

    def test_distinct_rows_and_issue_counts_have_different_denominators(self):
        bundle = json.loads((self.root / "lost-limit.bundle.json").read_bytes())
        first = next(
            e["resource"]
            for e in bundle["entry"]
            if e["resource"]["resourceType"] == "Observation"
        )
        first["valueQuantity"]["code"] = "g/L"
        (self.root / "double.json").write_text(json.dumps(bundle))
        report, status = self.run_cases(self.case("two-fields-one-row", "double.json"))
        self.assertEqual(status, 1)
        self.assertEqual(report["summary"]["affected_expected_rows"], 1)
        self.assertEqual(report["summary"]["evaluated_expected_rows"], 2)
        self.assertEqual(
            report["summary"]["finding_counts"],
            {"comparator-changed": 1, "unit-changed": 1},
        )

    def test_report_level_findings_are_retained_without_attributing_them_to_source_rows(
        self,
    ):
        bundle = json.loads((self.root / "correct.bundle.json").read_bytes())
        report = next(
            e["resource"]
            for e in bundle["entry"]
            if e["resource"]["resourceType"] == "DiagnosticReport"
        )
        report["identifier"][0]["value"] = "PRIVATE-WRONG-REPORT-ID"
        (self.root / "other.json").write_text(json.dumps(bundle))
        report, status = self.run_cases(self.case("report-only", "other.json"))
        self.assertEqual(status, 1)
        self.assertEqual(report["summary"]["affected_expected_rows"], 0)
        self.assertEqual(report["summary"]["finding_counts"], {"report-id-changed": 1})
        self.assertNotIn("PRIVATE-WRONG", json.dumps(report))

    def test_invalid_manifest_shape_ids_and_paths_are_rejected_without_echoing_inputs(
        self,
    ):
        case = self.case("sample")
        for manifest in [
            {"schema_version": True, "cases": [case]},
            {"schema_version": 1, "cases": []},
            {"schema_version": 1, "cases": [case, case]},
            {"schema_version": 1, "cases": [self.case("")]},
            {"schema_version": 2, "cases": [case]},
            {"schema_version": 1, "cases": [{"id": "sample"}]},
            {"schema_version": 1, "cases": [{**case, "PRIVATE-KEY": "PRIVATE-DATA"}]},
            {"schema_version": 1, "cases": [self.case("case-1", "../PRIVATE-patient")]},
            {
                "schema_version": 1,
                "cases": [self.case("case-1", str(self.root / "PRIVATE"))],
            },
            {
                "schema_version": 1,
                "cases": [self.case("case-1", r"C:\PRIVATE\file.json")],
            },
        ]:
            with self.subTest(manifest=manifest):
                self.manifest.write_text(json.dumps(manifest))
                with self.assertRaises(ValueError) as ctx:
                    run_suite(self.manifest)
                self.assertNotIn("PRIVATE", str(ctx.exception))

    def test_missing_invalid_or_duplicate_key_manifest_error_is_sanitized(self):
        missing = self.root / "PRIVATE-name"
        with self.assertRaisesRegex(ValueError, "manifest") as ctx:
            run_suite(missing)
        self.assertNotIn("PRIVATE", str(ctx.exception))
        for raw in [
            b'{"schema_version":1,"cases":[],"cases":[]}',
            b"{",
            b"\xff\xfe\xff",
        ]:
            self.manifest.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, "manifest"):
                run_suite(self.manifest)

    def test_symlinks_stay_inside_the_manifest_directory(self):
        outside = Path(self.temp.name) / "PRIVATE"
        outside.write_bytes((self.root / "reference.json").read_bytes())
        (self.root / "out").symlink_to(outside)
        (self.root / "in").symlink_to(self.root / "reference.json")
        run, status = self.run_cases(
            self.case("internal", reference="in"),
            self.case("external", reference="out"),
        )
        self.assertEqual(status, 2)
        self.assertEqual([c["result"] for c in run["cases"]], ["pass", "unevaluable"])
        self.assertEqual(run["cases"][1]["error_stage"], "reference")
        self.assertNotIn("PRIVATE", json.dumps(run))

    def test_directory_in_place_of_file_is_an_unevaluable_case(self):
        directory = self.root / "directory"
        directory.mkdir()
        run, status = self.run_cases(self.case("directory-input", directory.name))
        self.assertEqual(status, 2)
        self.assertEqual(run["cases"][0]["error_stage"], "bundle")
        self.assertEqual(run["summary"]["known_expected_rows"], 2)

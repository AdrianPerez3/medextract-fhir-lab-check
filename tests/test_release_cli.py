"""Release contracts exercised through the public command."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from medextract_fhir_lab import __version__

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "examples"


def run(*args):
    return subprocess.run(
        [sys.executable, "-m", "medextract_fhir_lab", *map(str, args)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


class ReleaseCLI(unittest.TestCase):
    def test_invalid_resource_urls_do_not_echo_candidate_identifiers(self):
        marker = "synthetic-identifier"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.json"
            for field in ("fullUrl", "subject"):
                for authority in (f"[{marker}]", f"{marker}\uff0fexample.org"):
                    with self.subTest(field=field, authority=authority):
                        bundle = json.loads((EX / "correct.bundle.json").read_bytes())
                        entry = bundle["entry"][0]
                        if field == "fullUrl":
                            entry["fullUrl"] = (
                                f"https://{authority}/DiagnosticReport/report1"
                            )
                        else:
                            entry["resource"]["subject"] = {
                                "reference": f"https://{authority}/Patient/example"
                            }
                        path.write_text(json.dumps(bundle), encoding="utf-8")
                        result = run(
                            "check",
                            "--reference",
                            EX / "reference.json",
                            "--bundle",
                            path,
                        )
                        self.assertEqual(result.returncode, 2)
                        self.assertEqual(result.stdout, "")
                        self.assertIn("comparison", result.stderr)
                        self.assertNotIn(marker, result.stderr)

    def test_independent_narrative_survives_an_unusable_row_reference(self):
        with tempfile.TemporaryDirectory() as d:
            files = Path(d)
            bundle, review = (
                "eu-changed-narrative.document.json",
                "eu-narrative-review.json",
            )
            for name in (bundle, review):
                shutil.copyfile(EX / name, files / name)
            (files / "private-directory").mkdir()
            (files / "private-invalid").write_text('{"rows":[]}', encoding="utf-8")
            cases = []
            for label in ("missing", "invalid", "directory"):
                reference = "private-" + label
                args = (
                    "check",
                    "--reference",
                    files / reference,
                    "--bundle",
                    files / bundle,
                )
                partial = run(*args, "--narrative-review", files / review)
                with self.subTest(label=label):
                    self.assertEqual(partial.returncode, 2)
                    self.assertNotIn("private-", partial.stdout + partial.stderr)
                    self.assertTrue(
                        partial.stdout, "completed section review needs a JSON result"
                    )
                    result = json.loads(partial.stdout)
                    self.assertEqual(result["result"], "unevaluable")
                    self.assertEqual(result["error_stage"], "reference")
                    self.assertIsNone(result["expected_rows"])
                    self.assertEqual(
                        result["findings"],
                        [
                            {
                                "code": "narrative-changed",
                                "field": "Composition.section.text.div",
                            }
                        ],
                    )
                cases.append(
                    {
                        "id": label,
                        "reference": reference,
                        "bundle": bundle,
                        "narrative_review": review,
                    }
                )
            single = run(
                "check",
                "--reference",
                files / "private-missing",
                "--bundle",
                files / bundle,
            )
            self.assertEqual(single.returncode, 2)
            self.assertEqual(single.stdout, "")
            self.assertIn("reference", single.stderr)
            self.assertNotIn("private-", single.stderr)
            manifest = files / "suite.json"
            manifest.write_text(
                json.dumps({"schema_version": 1, "cases": cases}), encoding="utf-8"
            )
            suite = run("suite", "--manifest", manifest)
            self.assertEqual(suite.returncode, 2)
            self.assertNotIn("private-", suite.stdout + suite.stderr)
            report = json.loads(suite.stdout)
            for case in report["cases"]:
                self.assertIsNone(case["expected_rows"])
                self.assertIsNone(case["affected_expected_rows"])
                self.assertEqual(case["finding_counts"], {"narrative-changed": 1})
            self.assertEqual(report["summary"]["reports_with_unknown_expected_rows"], 3)
            self.assertEqual(report["summary"]["evaluated_expected_rows"], 0)
            self.assertEqual(
                report["summary"]["finding_counts"], {"narrative-changed": 3}
            )

    def test_independent_narrative_failure_survives_unsupported_structured_result(self):
        with tempfile.TemporaryDirectory() as d:
            files = Path(d)
            for name in ("reference.json", "eu-narrative-review.json"):
                shutil.copyfile(EX / name, files / name)
            candidate = json.loads(
                (EX / "eu-changed-narrative.document.json").read_bytes()
            )
            row = next(
                e["resource"]
                for e in candidate["entry"]
                if e["resource"]["resourceType"] == "Observation"
            )
            row.pop("valueQuantity")
            row["valueString"] = "Synthetic qualitative result"
            (files / "candidate.json").write_text(
                json.dumps(candidate), encoding="utf-8"
            )
            paths = {
                "reference": "reference.json",
                "bundle": "candidate.json",
                "narrative_review": "eu-narrative-review.json",
            }
            manifest = {
                "schema_version": 1,
                "cases": [{"id": "synthetic-both", **paths}],
            }
            (files / "suite.json").write_text(json.dumps(manifest), encoding="utf-8")
            single = run(
                "check",
                "--reference",
                files / paths["reference"],
                "--bundle",
                files / paths["bundle"],
                "--narrative-review",
                files / paths["narrative_review"],
            )
            suite = run("suite", "--manifest", files / "suite.json")
            for proc in (single, suite):
                self.assertEqual(proc.returncode, 2)
                self.assertNotIn(
                    "Synthetic qualitative result", proc.stdout + proc.stderr
                )
            self.assertEqual(json.loads(single.stdout)["error_stage"], "comparison")
            self.assertEqual(
                [f["code"] for f in json.loads(single.stdout)["findings"]],
                ["narrative-changed"],
            )
            case = json.loads(suite.stdout)["cases"][0]
            self.assertEqual(case["finding_counts"], {"narrative-changed": 1})
            self.assertIsNone(case["affected_expected_rows"])
            self.assertEqual(
                json.loads(suite.stdout)["summary"]["evaluated_expected_rows"], 0
            )

    def test_file_errors_identify_input_without_echoing_private_path(self):
        p = run(
            "check",
            "--reference",
            EX / "reference.json",
            "--bundle",
            EX / "PRIVATE-IDENTITY.json",
        )
        self.assertEqual(p.returncode, 2)
        self.assertEqual(p.stdout, "")
        self.assertNotIn("PRIVATE-IDENTITY", p.stderr)
        self.assertIn("bundle", p.stderr.lower())

    def test_demo_verifies_the_deliberate_failures(self):
        p = run("demo")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("5", p.stdout)
        self.assertIn("3", p.stdout)
        self.assertIn("expected", p.stdout.lower())

    def test_summary_only_keeps_all_counts_and_omits_case_records(self):
        manifest = EX / "pilot.suite.json"
        full = run("suite", "--manifest", manifest)
        compact = run("suite", "--manifest", manifest, "--summary-only")
        self.assertEqual((full.returncode, compact.returncode), (1, 1))
        details = json.loads(full.stdout)
        details.pop("cases")
        self.assertEqual(json.loads(compact.stdout), details)
        self.assertNotIn("invented-zero", compact.stdout)

    def test_version_available_without_build_tooling(self):
        p = run("--version")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), f"medextract-fhir-lab {__version__}")

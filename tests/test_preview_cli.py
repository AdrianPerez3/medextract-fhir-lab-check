"""Public command behavior for the v0.2 result and narrative checks."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "examples"


def run(*args):
    return subprocess.run(
        [sys.executable, "-m", "medextract_fhir_lab", *map(str, args)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


class PreviewCLI(unittest.TestCase):
    def test_changed_narrative_is_opt_in(self):
        args = (
            "check",
            "--reference",
            EX / "reference.json",
            "--bundle",
            EX / "eu-changed-narrative.document.json",
        )
        self.assertEqual(run(*args).returncode, 0)
        result = run(*args, "--narrative-review", EX / "eu-narrative-review.json")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(
            [f["code"] for f in json.loads(result.stdout)["findings"]],
            ["narrative-changed"],
        )

    def test_unrepresentable_decimal_is_a_cli_input_error(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.json"
            path.write_text('{"example": 1e999999999999999999999999}')
            result = run(
                "check", "--reference", EX / "reference.json", "--bundle", path
            )
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Traceback", result.stderr)

    def test_suite_keeps_known_findings_when_optional_narrative_cannot_be_scored(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for filename in ("reference.json", "lost-limit.bundle.json"):
                (root / filename).write_bytes((EX / filename).read_bytes())
            manifest = root / "suite.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "cases": [
                            {
                                "id": "partial",
                                "reference": "reference.json",
                                "bundle": "lost-limit.bundle.json",
                                "narrative_review": "no-review.json",
                            }
                        ],
                    }
                )
            )
            result = run("suite", "--manifest", manifest)
            self.assertEqual(result.returncode, 2)
            report = json.loads(result.stdout)
            self.assertEqual(
                report["cases"][0]["finding_counts"], {"comparator-changed": 1}
            )
            self.assertEqual(report["summary"]["evaluated_expected_rows"], 0)
            self.assertEqual(
                report["summary"]["finding_counts"], {"comparator-changed": 1}
            )

    def test_single_check_also_preserves_a_known_error(self):
        result = run(
            "check",
            "--reference",
            EX / "reference.json",
            "--bundle",
            EX / "lost-limit.bundle.json",
            "--narrative-review",
            EX / "eu-narrative-review.json",
        )
        self.assertEqual(result.returncode, 2)
        out = json.loads(result.stdout)
        self.assertEqual(out["result"], "unevaluable")
        self.assertEqual(out["error_stage"], "narrative_review")
        self.assertEqual([f["code"] for f in out["findings"]], ["comparator-changed"])

"""Run declared source-to-FHIR cases offline and retain every report in the totals."""

from collections import Counter
from pathlib import Path, PureWindowsPath
import re

from .evaluation import evaluate
from .jsonio import read_json


_CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def _validate_manifest(doc):
    if not isinstance(doc, dict) or doc.keys() != {"schema_version", "cases"}:
        raise ValueError("suite manifest requires schema_version and cases")
    if type(doc["schema_version"]) is not int or doc["schema_version"] != 1:
        raise ValueError("unsupported suite manifest version")
    cases = doc["cases"]
    if not isinstance(cases, list) or not cases:
        raise ValueError("suite manifest needs a nonempty cases array")
    ids = set()
    for case in cases:
        required = {"id", "reference", "bundle"}
        if not isinstance(case, dict) or not required <= case.keys() <= required | {
            "bindings",
            "narrative_review",
        }:
            raise ValueError(
                "suite manifest case requires id, reference and bundle with optional bindings and narrative_review"
            )
        key = case["id"]
        if not isinstance(key, str) or not _CASE_ID.fullmatch(key) or key in ids:
            raise ValueError("suite manifest case identifiers must be valid and unique")
        ids.add(key)
        for field in case.keys() - {"id"}:
            name = case[field]
            if (
                not isinstance(name, str)
                or not name
                or not Path(name).parts
                or Path(name).is_absolute()
                or PureWindowsPath(name).drive
                or "\\" in name
                or "\x00" in name
                or ".." in Path(name).parts
            ):
                raise ValueError(
                    "suite manifest paths must be relative to its directory"
                )
    return cases


def _run_case(root, case):
    outcome = evaluate(
        root / case["reference"],
        root / case["bundle"],
        bindings_path=root / case["bindings"] if "bindings" in case else None,
        narrative_path=root / case["narrative_review"]
        if "narrative_review" in case
        else None,
        root=root,
    )
    affected = {f["row_id"] for f in outcome.findings if "row_id" in f}
    counts = Counter(f["code"] for f in outcome.findings)
    return {
        "id": case["id"],
        "result": outcome.result,
        "expected_rows": outcome.expected_rows,
        "affected_expected_rows": len(affected) if outcome.row_checked else None,
        "finding_counts": dict(sorted(counts.items())) if outcome.evaluated else None,
        **outcome.error_fields(),
    }


def run_suite(manifest_path: Path, *, summary_only: bool = False) -> tuple[dict, int]:
    """Evaluate cases in manifest order. Use synthetic, non-identifying manifest case IDs.

    Paths are relative to the manifest's on-disk location. The summary counts a
    report once per case, including multiple candidates for the same source.
    Known expected rows include validated references whose candidate cannot be
    compared. Evaluated rows count fully evaluated cases. Summary-only mode
    keeps identical totals and discards each case record after aggregation.
    """
    try:
        path = Path(manifest_path).resolve(strict=True)
        doc = read_json(path)
    except (OSError, ValueError, RuntimeError):
        raise ValueError("suite manifest could not be read as JSON") from None
    cases = _validate_manifest(doc)
    results = []
    counts = {"pass": 0, "fail": 0, "unevaluable": 0}
    findings = Counter()
    known_rows = evaluated_rows = affected_rows = unknown_references = 0
    for spec in cases:
        case = _run_case(path.parent, spec)
        if not summary_only:
            results.append(case)
        counts[case["result"]] += 1
        if case["expected_rows"] is None:
            unknown_references += 1
        else:
            known_rows += case["expected_rows"]
        if case["result"] != "unevaluable":
            evaluated_rows += case["expected_rows"]
        if case["finding_counts"] is not None:
            affected_rows += case["affected_expected_rows"] or 0
            findings.update(case["finding_counts"])

    if counts["unevaluable"]:
        outcome, exit_code = "unevaluable", 2
    elif counts["fail"]:
        outcome, exit_code = "fail", 1
    else:
        outcome, exit_code = "pass", 0
    report = {
        "schema_version": 1,
        "result": outcome,
        "summary": {
            "total_reports": len(cases),
            "report_counts": counts,
            "known_expected_rows": known_rows,
            "evaluated_expected_rows": evaluated_rows,
            "reports_with_unknown_expected_rows": unknown_references,
            "affected_expected_rows": affected_rows,
            "finding_counts": dict(sorted(findings.items())),
        },
    }
    if not summary_only:
        report["cases"] = results
    return report, exit_code

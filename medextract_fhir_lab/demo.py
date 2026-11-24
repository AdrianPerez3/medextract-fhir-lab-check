"""Replay the bundled synthetic pilot and compare with its recorded result."""

from pathlib import Path

from .jsonio import read_json
from .suite import run_suite


def _data_root():
    source = Path(__file__).resolve().parents[1]
    if (source / "examples/pilot.suite.json").is_file() and (
        source / "pyproject.toml"
    ).is_file():
        return source
    from importlib.metadata import PackageNotFoundError, distribution

    try:
        installed = distribution("medextract-fhir-lab-check")
    except PackageNotFoundError:
        raise ValueError(
            "demo data unavailable; reinstall the wheel or use the release source"
        ) from None
    suffix = ("share", "medextract-fhir-lab-check", "examples", "pilot.suite.json")
    for entry in installed.files or ():
        if entry.parts[-4:] == suffix:
            return Path(installed.locate_file(entry)).parents[1]
    raise ValueError(
        "demo data unavailable; reinstall the wheel or use the release source"
    )


def run_demo():
    root = _data_root()
    report, status = run_suite(root / "examples/pilot.suite.json")
    expected = read_json(root / "evidence/pilot-results.json")
    if report != expected:
        return (
            "Demo outcomes differ from the recorded pilot. Run the suite to inspect the cases.",
            2 if status == 2 else 1,
        )
    summary = report["summary"]
    return (
        f"Verified {summary['total_reports']} synthetic cases matched their expected outcomes "
        f"({summary['report_counts']['pass']} passes, {summary['report_counts']['fail']} deliberate failures).",
        0,
    )

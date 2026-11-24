"""Run an offline semantic check, export a base R4 collection, or import starter labels."""

import argparse
import json
from pathlib import Path
import sys

from .adapter import export_bundle, import_starter
from . import __version__
from .demo import run_demo
from .evaluation import evaluate
from .jsonio import dumps, read_bytes, read_json
from .suite import run_suite


def main(argv=None):
    parser = argparse.ArgumentParser(prog="medextract-fhir-lab", description=__doc__)
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    commands = parser.add_subparsers(required=True, dest="command")
    commands.add_parser(
        "demo",
        help="Verify the installed synthetic pilot against its expected outcomes",
    )
    compare = commands.add_parser(
        "check", help="Compare independent expected rows with a FHIR R4 bundle"
    )
    compare.add_argument("--reference", type=Path, required=True)
    compare.add_argument("--bundle", type=Path, required=True)
    compare.add_argument(
        "--bindings",
        type=Path,
        help="Independent mapping to the vendor Bundle fullUrls",
    )
    compare.add_argument(
        "--narrative-review",
        type=Path,
        help="Independently reviewed document section fingerprint",
    )
    suite = commands.add_parser(
        "suite", help="Evaluate every case in a local CI manifest"
    )
    suite.add_argument("--manifest", type=Path, required=True)
    suite.add_argument(
        "--summary-only",
        action="store_true",
        help="Keep totals and exit code without retaining individual case records",
    )
    export = commands.add_parser(
        "export", help="Export reviewed quantitative rows as a base R4 collection"
    )
    export.add_argument("--reference", type=Path, required=True)
    starter = commands.add_parser(
        "import-starter", help="Import MedExtract quantitative synthetic labels"
    )
    for arg in ("visible", "normalized", "coordinates"):
        starter.add_argument("--" + arg, type=Path, required=True)
    starter.add_argument(
        "--identifier-system",
        required=True,
        help="Stable correlation namespace for these rows",
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            message, status = run_demo()
            print(message)
            return status
        if args.command == "suite":
            report, status = run_suite(args.manifest, summary_only=args.summary_only)
            print(json.dumps(report, indent=2))
            return status
        if args.command == "check":
            outcome = evaluate(
                args.reference,
                args.bundle,
                bindings_path=args.bindings,
                narrative_path=args.narrative_review,
            )
            if outcome.errors and not outcome.evaluated:
                stage, description = next(iter(outcome.errors.items()))
                print(f"Input error at {stage}: {description}", file=sys.stderr)
                return 2
            print(
                json.dumps(
                    {
                        "schema_version": 1,
                        "result": outcome.result,
                        "expected_rows": outcome.expected_rows,
                        "findings": outcome.findings,
                        **outcome.error_fields(),
                    },
                    indent=2,
                )
            )
            return {"pass": 0, "fail": 1, "unevaluable": 2}[outcome.result]
        if args.command == "import-starter":
            doc = import_starter(
                read_bytes(args.visible),
                read_json(args.normalized),
                read_json(args.coordinates),
                args.identifier_system,
            )
        else:
            doc = export_bundle(read_json(args.reference))
        print(dumps(doc))
        return 0
    except (ValueError, OSError, RecursionError) as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

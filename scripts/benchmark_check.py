"""Measure warm, file-backed CLI runs on synthetic reports. See --help."""

import argparse
from contextlib import redirect_stdout
from copy import deepcopy
import gc
import hashlib
import io
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc


ROOT = Path(__file__).resolve().parents[1]


def write_cases(folder, count):
    """Scale the two checked-in quantitative rows, keeping their shared specimen."""
    examples = ROOT / "examples"
    reference = json.loads((examples / "reference.json").read_bytes())
    bundle = json.loads((examples / "correct.bundle.json").read_bytes())
    report, *observations, specimen = bundle["entry"]
    templates = reference["rows"]
    reference["rows"] = []
    report["resource"]["result"] = []
    bundle["entry"] = [report, specimen]
    manifest = {
        "schema_version": 1,
        "report_id": reference["report_id"],
        "report_full_url": report["fullUrl"],
        "rows": [],
    }
    for i in range(count):
        source = dict(templates[i % 2], id=f"r{i:06}")
        reference["rows"].append(source)
        entry = deepcopy(observations[i % 2])
        observation = entry["resource"]
        observation["id"] = f"obs{i}"
        entry["fullUrl"] = f"https://example.org/fhir/Observation/obs{i}"
        observation["identifier"][0]["value"] = source["id"]
        bundle["entry"].append(entry)
        report["resource"]["result"].append({"reference": f"Observation/obs{i}"})
        manifest["rows"].append(
            {"row_id": source["id"], "observation_full_url": entry["fullUrl"]}
        )

    # A predictable finding checks that a faster run really compared the rows.
    del bundle["entry"][2]["resource"]["valueQuantity"]["comparator"]
    case = {
        "id": "synthetic",
        "reference": "ref.json",
        "bundle": "sender.json",
        "bindings": "links.json",
    }
    files = {
        "ref.json": reference,
        "identified.json": bundle,
        "links.json": manifest,
        "suite.json": {"schema_version": 1, "cases": [case]},
    }
    for name, data in files.items():
        (folder / name).write_text(json.dumps(data), encoding="utf-8")
    for entry in bundle["entry"]:
        if "identifier" in entry["resource"]:
            entry["resource"]["identifier"] = [
                {"system": "urn:example:sender", "value": entry["resource"]["id"]}
            ]
    (folder / "sender.json").write_text(json.dumps(bundle), encoding="utf-8")


def measure(cli, argv, rows, repeats):
    def run():
        with redirect_stdout(io.StringIO()) as output:
            status = cli(argv)
        return status, output.getvalue()

    expected = run()
    status, stdout = expected
    doc = json.loads(stdout)
    if argv[0] == "suite":
        correct = doc["summary"]["evaluated_expected_rows"] == rows and doc["summary"][
            "finding_counts"
        ] == {"comparator-changed": 1}
    else:
        correct = doc["expected_rows"] == rows and doc["findings"] == [
            {
                "code": "comparator-changed",
                "field": "valueQuantity.comparator",
                "row_id": "r000000",
            }
        ]
    if status != 1 or not correct:
        raise ValueError(f"wrong benchmark result for {argv[0]}")
    wall_ms, cpu_ms = [], []
    for _ in range(repeats):
        gc.collect()
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        result = run()
        cpu_ms.append((time.process_time_ns() - cpu) / 1e6)
        wall_ms.append((time.perf_counter_ns() - wall) / 1e6)
        if result != expected:
            raise ValueError("unstable command output")
    gc.collect()
    tracemalloc.start()
    try:
        result = run()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    if result != expected:
        raise ValueError("unstable traced output")
    return {
        "median_wall_ms": round(statistics.median(wall_ms), 3),
        "wall_range_ms": [round(min(wall_ms), 3), round(max(wall_ms), 3)],
        "median_cpu_ms": round(statistics.median(cpu_ms), 3),
        "peak_python_bytes": peak,
        "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
    }


def fresh_process_ms(checkout, folder, argv, expected_digest, repeats):
    command = [
        sys.executable,
        "-Es",
        "-X",
        f"pycache_prefix={folder / 'bytecode'}",
        "-m",
        "medextract_fhir_lab",
        *argv,
    ]
    samples = []
    # Prime a private bytecode cache equally for each checkout before timing.
    for iteration in range(repeats + 1):
        start = time.perf_counter_ns()
        run = subprocess.run(command, cwd=checkout, capture_output=True, text=True)
        elapsed = (time.perf_counter_ns() - start) / 1e6
        if (
            run.returncode != 1
            or hashlib.sha256(run.stdout.encode()).hexdigest() != expected_digest
        ):
            raise ValueError("fresh process returned different findings")
        if iteration:
            samples.append(elapsed)
    return round(statistics.median(samples), 3)


def run_checkout(checkout, sizes, repeats):
    if not (checkout / "medextract_fhir_lab" / "__main__.py").is_file():
        raise ValueError("checkout must contain the CLI package source")
    sys.path.insert(0, str(checkout.resolve()))
    from medextract_fhir_lab.__main__ import main

    digest = hashlib.sha256()
    for path in sorted((checkout / "medextract_fhir_lab").glob("*.py")):
        digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    cases = {}
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        for rows in sizes:
            write_cases(folder, rows)
            check = ["check", "--reference", str(folder / "ref.json"), "--bundle"]
            commands = {
                "identified_check": [*check, str(folder / "identified.json")],
                "manifest_check": [
                    *check,
                    str(folder / "sender.json"),
                    "--bindings",
                    str(folder / "links.json"),
                ],
                "manifest_suite": ["suite", "--manifest", str(folder / "suite.json")],
            }
            cases[str(rows)] = {
                name: measure(main, argv, rows, repeats)
                for name, argv in commands.items()
            }
            bound = cases[str(rows)]["manifest_check"]
            bound["median_fresh_process_wall_ms"] = fresh_process_ms(
                checkout,
                folder,
                commands["manifest_check"],
                bound["stdout_sha256"],
                repeats,
            )
    return {"package_source_sha256": digest.hexdigest(), "cases": cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--checkout",
        type=Path,
        default=ROOT,
        help="package source directory to measure",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        help="also measure this unpacked version and verify identical outputs",
    )
    parser.add_argument("--rows", type=int, nargs="+", default=[16, 1000])
    parser.add_argument("--repeats", type=int, default=9)
    args = parser.parse_args()
    if args.repeats < 1 or any(n < 2 for n in args.rows):
        parser.error("use positive repeats and report sizes of at least two rows")
    if not args.baseline:
        print(
            json.dumps(run_checkout(args.checkout, args.rows, args.repeats), indent=2)
        )
        return

    report = {
        "python": platform.python_version(),
        "platform": platform.system(),
        "os_release": platform.release(),
        "machine": platform.machine(),
        "benchmark_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "repeats": args.repeats,
        "method": "Warm in-process CLI including local file reads, JSON and stdout, with one warm-up per case. Separate single-run tracemalloc peak excludes startup and native allocations. Manifest checks also measure fresh interpreter wall time after priming a private bytecode cache on each checkout. Filesystem caches are warm in both measurements.",
        "inputs": "Synthetic v1 collection with alternating quantity rows, shared specimen, and one removed comparator. Sender identifiers plus independent fullUrl manifest for bound cases.",
    }
    for name, checkout in (("baseline", args.baseline), ("candidate", args.checkout)):
        command = [
            sys.executable,
            "-IB",
            __file__,
            "--checkout",
            str(checkout),
            "--repeats",
            str(args.repeats),
            "--rows",
            *map(str, args.rows),
        ]
        report[name] = json.loads(subprocess.check_output(command))
    for size, cases in report["baseline"]["cases"].items():
        for label, before in cases.items():
            after = report["candidate"]["cases"][size][label]
            if before["stdout_sha256"] != after["stdout_sha256"]:
                raise ValueError(f"outputs differ for {size} rows / {label}")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

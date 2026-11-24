"""Compare full and aggregate-only suite output for 3,000 synthetic CI cases."""

import gc
import json
from pathlib import Path
import platform
import shutil
import sys
import tempfile
from time import perf_counter
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from medextract_fhir_lab.suite import run_suite  # noqa: E402


def measure(manifest, compact):
    report, status = run_suite(manifest, summary_only=compact)
    size = len(json.dumps(report, indent=2).encode("utf-8"))
    return {"status": status, "summary": report["summary"], "json_bytes": size}


def main():
    count = 3000
    bundles = ["correct.bundle.json", "lost-limit.bundle.json", "missing.bundle.json"]
    modes = {"full": False, "summary_only": True}
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        for name in ["reference.json", *bundles[:2]]:
            shutil.copyfile(ROOT / "examples" / name, work / name)
        cases = [
            {
                "id": f"case-{i:04}",
                "reference": "reference.json",
                "bundle": bundles[i % 3],
            }
            for i in range(count)
        ]
        manifest = work / "suite.json"
        manifest.write_text(
            json.dumps({"schema_version": 1, "cases": cases}), encoding="utf-8"
        )
        del cases

        results = {}
        for name, compact in modes.items():
            results[name] = measure(manifest, compact)
            gc.collect()
            tracemalloc.start()
            measure(manifest, compact)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            results[name].update(traced_peak_bytes=peak, timings_ms=[])
        for i in range(6):
            for name in list(modes) if i % 2 == 0 else list(reversed(modes)):
                start = perf_counter()
                measure(manifest, modes[name])
                results[name]["timings_ms"].append(
                    round((perf_counter() - start) * 1000, 3)
                )

    full, compact = results.values()
    if (
        full["status"] != 2
        or compact["status"] != 2
        or full["summary"] != compact["summary"]
    ):
        sys.exit("Full and summary-only results must match the mixed-case control")
    if full["summary"]["report_counts"] != {
        "pass": 1000,
        "fail": 1000,
        "unevaluable": 1000,
    }:
        sys.exit("Unexpected case outcomes")
    print(
        json.dumps(
            {
                "python": platform.python_version(),
                "platform": platform.system(),
                "machine": platform.machine(),
                "manifest_cases": count,
                "workload": "Repeat a correct report, a lost comparator and a missing bundle equally.",
                "scope": "run_suite and indented UTF-8 JSON serialization, no trailing newline. Separate tracemalloc run per mode, warm filesystem, six alternating timed pairs. Python allocations exclude native memory and filesystem cache.",
                "replay": "python3 scripts/benchmark_suite.py",
                "modes": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

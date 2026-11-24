"""Replay the published v0.2.0 starter labels using only the three report Parquets."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

import pyarrow.parquet as parquet

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from medextract_fhir_lab.adapter import export_bundle, import_starter  # noqa: E402
from medextract_fhir_lab.checker import check  # noqa: E402
from medextract_fhir_lab.jsonio import dumps, loads  # noqa: E402


REVISION = "81da521d08425bd57922a1cf8bb17aa49d11b537"
PARQUETS = {
    "train": "7339cbc49ce6aeafcaad5bd7df58700065668c3dba3f8899a018e1f29fbc346d",
    "validation": "4e1844f1a090d732c460aeef28e379baabcb78334bac251a9956b88a42c3d2a8",
    "test": "e3df275f589e02400549ed1b0a32825859b3586ab220e9dfadf39ef10cf3d6c9",
}
FIELDS = ("ground_truth", "normalized_ground_truth", "coordinates")
SYSTEM = "https://example.org/medextract/starter/rows"


def file_digest(path):
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def seed_error(observation, n):
    quantity = observation["valueQuantity"]
    kind = n % 5
    if kind == 0:
        quantity["comparator"] = "<"
        return "comparator-changed"
    if kind == 1:
        quantity["code"] = "g" if quantity["code"] != "g" else "mg"
        return "unit-changed"
    if kind == 2:
        coding = observation["code"]["coding"][0]
        coding["code"] = "2345-7" if coding["code"] != "2345-7" else "1988-5"
        return "loinc-changed"
    if kind == 3:
        observation["status"] = "final"
        return "status-changed"
    quantity["value"] = 0 if quantity["value"] else 1
    return "value-changed"


def replay(root):
    ids, terms, detections, splits = set(), set(), Counter(), {}
    columns = ["report_id", "page_count"] + [
        f"{f}_{s}" for f in FIELDS for s in ("sha256", "json")
    ]
    for split, expected in PARQUETS.items():
        path = root / "data" / "reports" / f"{split}.parquet"
        if file_digest(path) != expected:
            raise ValueError(f"unexpected file digest for {split}")
        reports = rows = pages = reordered = 0
        for batch in parquet.ParquetFile(path).iter_batches(
            batch_size=16, columns=columns
        ):
            for entry in batch.to_pylist():
                for key in FIELDS:
                    if (
                        sha256(entry[key + "_json"].encode()).hexdigest()
                        != entry[key + "_sha256"]
                    ):
                        raise ValueError(f"sidecar digest mismatch for {key}")
                side = loads(entry["coordinates_json"])
                visible = entry["ground_truth_json"].encode()
                normalized = loads(entry["normalized_ground_truth_json"])
                ref = import_starter(visible, normalized, side, SYSTEM)
                reordered += [row["loinc"] for row in ref["rows"]] != [
                    row["loinc"] for row in normalized["results"]
                ]
                if (
                    ref["report_id"] != entry["report_id"]
                    or ref["report_id"] in ids
                    or len(side["pages"]) != entry["page_count"]
                ):
                    raise ValueError("unexpected report identity or pages")
                rows += len(ref["rows"])
                pages += entry["page_count"]
                reports += 1
                terms.update(row["loinc"] for row in ref["rows"])
                bundle = loads(dumps(export_bundle(ref)))
                if check(ref, bundle):
                    raise ValueError("unexpected unmodified round-trip findings")
                observations = [
                    e["resource"]
                    for e in bundle["entry"]
                    if e["resource"]["resourceType"] == "Observation"
                ]
                row_index = len(ids) % len(observations)
                row_id = ref["rows"][row_index]["id"]
                code = seed_error(observations[row_index], len(ids))
                findings = check(ref, bundle)
                if [(f["code"], f.get("row_id")) for f in findings] != [(code, row_id)]:
                    raise ValueError(
                        f"failed to identify the seeded {code} at {row_id}: {findings}"
                    )
                detections[code] += 1
                ids.add(ref["report_id"])
        splits[split] = {
            "reports": reports,
            "rows": rows,
            "pages": pages,
            "different_row_order": reordered,
        }
    return {
        "dataset": "AdrianPerez3/medextract-synthetic-lab-reports-starter",
        "revision": REVISION,
        "report_parquet_sha256": PARQUETS,
        "splits": splits,
        "distinct_loinc_strings": len(terms),
        "totals": {
            key: sum(v[key] for v in splits.values())
            for key in ("reports", "rows", "pages", "different_row_order")
        },
        "unmodified_reports_with_findings": 0,
        "one_seeded_error_per_report_detected_at_expected_row": dict(detections),
        "scope": "Synthetic normalized/printed labels and index coverage. No OCR, image inspection, independent clinical mapping review, or EU document generation.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("starter_directory", type=Path)
    try:
        print(json.dumps(replay(parser.parse_args().starter_directory), indent=2))
    except (ValueError, OSError) as exc:
        sys.exit(str(exc))

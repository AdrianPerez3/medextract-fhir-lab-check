"""Locate an expected row in the MedExtract starter's native, unrotated page.

From the project root, with DATASET pointing to the downloaded starter:

    python scripts/locate_row.py --coordinates "$DATASET/examples/coordinates/RPT_000726.json" \
        --visible "$DATASET/examples/ground_truth/RPT_000726.json" --row-id RPT_000726.1 --pixels

All rectangles are [left, top, right, bottom]. Pixel rectangles use exclusive
right and bottom edges. Cropping, resizing or deskewing requires a separate
transform. Image paths in sidecars are never opened.
"""

import argparse
import re
import sys
from decimal import Decimal
from fractions import Fraction
from hashlib import sha256
from math import ceil, floor
from pathlib import Path

# Support a source checkout without requiring package installation.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from medextract_fhir_lab.jsonio import dumps, loads, read_bytes, read_json  # noqa: E402

FIELDS = ("test_name", "value", "unit")
COLUMNS = (*FIELDS, "reference_range", "flag", "method")
GRID_TOLERANCE = Decimal(
    "1e-8"
)  # Independently placed PDF rows can share a rounded edge.


def object_at(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"expected an object for {label}")
    return value


def array_at(value, label):
    if not isinstance(value, list):
        raise ValueError(f"expected an array for {label}")
    return value


def point(value):
    return type(value) is int or (isinstance(value, Decimal) and value.is_finite())


def rectangle(box, bounds, label):
    if not isinstance(box, list) or len(box) != 4 or not all(point(x) for x in box):
        raise ValueError(f"invalid {label} rectangle")
    left, top, right, bottom = box
    if not (
        bounds[0] <= left < right <= bounds[2]
        and bounds[1] <= top < bottom <= bounds[3]
    ):
        raise ValueError(f"{label} rectangle is empty or outside its enclosing bounds")
    return box


def native_pixels(box, pdf_size, image_size):
    # Fractions preserve exact floor/ceil results even at a pixel boundary.
    scaled = [
        Fraction(edge) * image_size[i % 2] / Fraction(pdf_size[i % 2])
        for i, edge in enumerate(box)
    ]
    return [floor(scaled[0]), floor(scaled[1]), ceil(scaled[2]), ceil(scaled[3])]


def row_boxes(row, bounds, index):
    outer = rectangle(row.get("bbox"), bounds, f"row {index + 1}")
    cells = object_at(row.get("cells"), "cells")
    if set(cells) != set(COLUMNS[: len(cells)]) or len(cells) < len(FIELDS):
        raise ValueError("missing or unsupported starter cell columns")
    result = {"row": outer}
    previous_right = outer[0]
    for field in COLUMNS[: len(cells)]:
        box = rectangle(cells[field], outer, field)
        if (
            box[0] < previous_right
            or box[0] - previous_right > GRID_TOLERANCE
            or box[1] - outer[1] > GRID_TOLERANCE
            or outer[3] - box[3] > GRID_TOLERANCE
        ):
            raise ValueError("cell rectangles must partition each row in column order")
        previous_right = box[2]
        if field in FIELDS:
            result[field] = box
    if outer[2] - previous_right > GRID_TOLERANCE:
        raise ValueError("cell rectangles must cover the width of the row")
    return result


def locate_row(coordinates, visible_bytes, row_id, *, pixels=False):
    side = object_at(coordinates, "coordinates")
    if (
        type(side.get("schema_version")) is not int
        or side["schema_version"] != 1
        or side.get("coordinate_space") != "pdf_points_top_left"
    ):
        raise ValueError(
            "expected starter schema 1 and pdf_points_top_left coordinates"
        )
    if sha256(visible_bytes).hexdigest() != side.get("ground_truth_sha256"):
        raise ValueError("visible labels do not match the coordinate sidecar SHA-256")
    prefix, dot, ordinal = row_id.rpartition(".")
    if (
        not dot
        or not prefix.strip()
        or prefix != side.get("report_id")
        or not re.fullmatch(r"[1-9][0-9]*", ordinal)
    ):
        raise ValueError("expected this report's row ID and canonical 1-based index")
    visible = object_at(loads(visible_bytes), "visible labels")
    if "report_id" in visible and visible["report_id"] != prefix:
        raise ValueError("visible and coordinate report IDs differ")
    results = array_at(visible.get("results"), "visible results")
    if not results:
        raise ValueError("expected at least one visible result")
    selected = None
    index = 0
    for number, page in enumerate(array_at(side.get("pages"), "pages"), 1):
        page = object_at(page, "coordinate page")
        if type(page.get("page")) is not int or page["page"] != number:
            raise ValueError(
                "coordinate page numbers must start at 1 and be consecutive"
            )
        size = [page.get("width"), page.get("height")]
        if not all(point(n) and n > 0 for n in size):
            raise ValueError("expected positive PDF page dimensions")
        image_size = None
        if "image" in page:
            image = object_at(page["image"], "image")
            image_size = [image.get("width"), image.get("height")]
            if not all(type(n) is int and n > 0 for n in image_size):
                raise ValueError("expected positive integer native image dimensions")
        previous_bottom = 0
        for row in array_at(page.get("rows"), "coordinate rows"):
            row = object_at(row, "coordinate row")
            if (
                type(row.get("result_index")) is not int
                or row["result_index"] != index
                or index >= len(results)
            ):
                raise ValueError(
                    "coordinate result indexes must cover visible rows in order"
                )
            printed = object_at(results[index], "printed result")
            if (
                not isinstance(printed.get("loinc"), str)
                or not printed["loinc"].strip()
                or row.get("loinc") != printed["loinc"]
            ):
                raise ValueError(f"LOINC mismatch at row {index + 1}")
            if not all(isinstance(printed.get(f), str) for f in FIELDS) or not all(
                printed[f].strip() for f in ("test_name", "value")
            ):
                raise ValueError(f"missing printed labels at row {index + 1}")
            boxes = row_boxes(row, [0, 0, *size], index)
            if previous_bottom - boxes["row"][1] > GRID_TOLERANCE:
                raise ValueError("coordinate rows overlap or are out of reading order")
            previous_bottom = boxes["row"][3]
            index += 1
            if str(index) == ordinal:
                selected = {
                    "row_id": row_id,
                    "page": number,
                    "loinc": printed["loinc"],
                    "printed": {f: printed[f] for f in FIELDS},
                    "pdf_points_top_left": {"size": size, "boxes": boxes},
                }
                if pixels:
                    if image_size is None:
                        raise ValueError(
                            "the selected page has no native image dimensions"
                        )
                    selected["native_pixels_top_left"] = {
                        "size": image_size,
                        "boxes": {
                            f: native_pixels(b, size, image_size)
                            for f, b in boxes.items()
                        },
                    }
    if index != len(results):
        raise ValueError("coordinate coverage of visible rows is incomplete")
    if selected is None:
        raise ValueError("row ID exceeds the visible result count")
    return selected


def main():
    parser = argparse.ArgumentParser(
        description="Locate a printed starter result on its native page."
    )
    parser.add_argument(
        "--coordinates",
        required=True,
        type=Path,
        help="starter coordinate sidecar JSON",
    )
    parser.add_argument(
        "--visible",
        required=True,
        type=Path,
        help="original printed-label JSON (exact bytes)",
    )
    parser.add_argument(
        "--row-id", required=True, help="<report_id>.<1-based flattened index>"
    )
    parser.add_argument(
        "--pixels",
        action="store_true",
        help="include native full-page image crop rectangles",
    )
    args = parser.parse_args()
    try:
        result = locate_row(
            read_json(args.coordinates),
            read_bytes(args.visible),
            args.row_id,
            pixels=args.pixels,
        )
        print(dumps(result))
    except (OSError, ValueError) as exc:
        parser.exit(2, f"locate_row: {exc}\n")


if __name__ == "__main__":
    main()

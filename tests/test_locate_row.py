import json
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from medextract_fhir_lab.jsonio import dumps, loads
from scripts.locate_row import locate_row

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "locate_row.py"


def fixture():
    visible = dumps(
        {
            "results": [
                {
                    "loinc": "789-8",
                    "test_name": "Hematíes",
                    "value": "4,19",
                    "unit": "10*6/uL",
                },
                {
                    "loinc": "789-8",
                    "test_name": "Hematíes",
                    "value": "<0,5",
                    "unit": "",
                },
            ]
        }
    ).encode()
    pages = []
    for i in range(2):
        pages.append(
            {
                "page": i + 1,
                "width": 9,
                "height": 10,
                "image": {"width": 14, "height": 25, "path": "/never/read/this.path"},
                "rows": [
                    {
                        "result_index": i,
                        "loinc": "789-8",
                        "bbox": [0, 1, 9, 10],
                        "cells": {
                            "test_name": [0, 1, 3, 10],
                            "value": [3, 1, 6, 10],
                            "unit": [6, 1, 9, 10],
                        },
                    }
                ],
            }
        )
    return visible, {
        "schema_version": 1,
        "coordinate_space": "pdf_points_top_left",
        "report_id": "REPORT",
        "ground_truth_sha256": sha256(visible).hexdigest(),
        "pages": pages,
    }


class LocateRowTests(unittest.TestCase):
    def test_whole_page_native_pixel_bounds_and_printed_text(self):
        visible, side = fixture()
        out = locate_row(side, visible, "REPORT.2", pixels=True)
        self.assertEqual(
            (out["row_id"], out["page"], out["loinc"]), ("REPORT.2", 2, "789-8")
        )
        self.assertEqual(
            out["printed"], {"test_name": "Hematíes", "value": "<0,5", "unit": ""}
        )
        self.assertEqual(
            out["native_pixels_top_left"]["boxes"],
            {
                "row": [0, 2, 14, 25],
                "test_name": [0, 2, 5, 25],
                "value": [4, 2, 10, 25],
                "unit": [9, 2, 14, 25],
            },
        )
        self.assertEqual(out["pdf_points_top_left"]["boxes"]["value"], [3, 1, 6, 10])

    def test_exact_pdf_edge_distinguishes_subpixel_difference(self):
        visible, side = fixture()
        p = side["pages"][0]
        p["width"] = 14
        tiny = Decimal("3.00000000000000000000000000001")
        p["rows"][0]["cells"]["value"][0] = tiny
        p["rows"][0]["cells"]["test_name"][2] = tiny
        out = locate_row(side, visible, "REPORT.1", pixels=True)
        self.assertEqual(out["pdf_points_top_left"]["boxes"]["test_name"][2], tiny)
        self.assertEqual(out["native_pixels_top_left"]["boxes"]["test_name"][2], 4)

    def test_image_metadata_is_optional_without_pixels(self):
        visible, side = fixture()
        side["pages"][0].pop("image")
        self.assertNotIn(
            "native_pixels_top_left", locate_row(side, visible, "REPORT.1")
        )
        with self.assertRaisesRegex(ValueError, "no native image"):
            locate_row(side, visible, "REPORT.1", pixels=True)

    def test_identity_byte_digest_and_coverage(self):
        visible, side = fixture()
        for row_id in ("OTHER.1", "REPORT.0", "REPORT.01", "REPORT.3", "REPORT.-1"):
            with self.subTest(row_id=row_id), self.assertRaises(ValueError):
                locate_row(side, visible, row_id)
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            locate_row(side, visible + b" ", "REPORT.1")
        side["pages"].pop()
        with self.assertRaisesRegex(ValueError, "coverage"):
            locate_row(side, visible, "REPORT.1")

    def test_geometry_and_identity_checked_even_after_selected_row(self):
        def duplicate_index(page, row):
            row["result_index"] = 0

        def bad_code(page, row):
            row["loinc"] = "718-7"

        def above_page(page, row):
            row["bbox"][1] = -1

        def overlapping_columns(page, row):
            row["cells"]["value"][0] = 2

        def missing_unit(page, row):
            del row["cells"]["unit"]

        def empty_rectangle(page, row):
            row["cells"]["value"][2] = 3

        def boolean_dimension(page, row):
            page["image"]["width"] = True

        def unexpected_space(page, row):
            page["width"] = 0

        def missing_label():
            v, s = fixture()
            labels = loads(v)
            labels["results"][1].pop("value")
            v = dumps(labels).encode()
            s["ground_truth_sha256"] = sha256(v).hexdigest()
            return locate_row(s, v, "REPORT.1")

        for mutate in (
            duplicate_index,
            bad_code,
            above_page,
            overlapping_columns,
            missing_unit,
            empty_rectangle,
            boolean_dimension,
            unexpected_space,
        ):
            visible, side = fixture()
            page = side["pages"][1]
            mutate(page, page["rows"][0])
            with self.subTest(case=mutate.__name__), self.assertRaises(ValueError):
                locate_row(side, visible, "REPORT.1")
        with self.assertRaisesRegex(ValueError, "missing printed"):
            missing_label()

    def test_rejects_overlapping_rows_and_reordered_pages(self):
        visible, side = fixture()
        side["pages"][0]["rows"].extend(side["pages"].pop()["rows"])
        with self.assertRaisesRegex(ValueError, "overlap"):
            locate_row(side, visible, "REPORT.1")
        _, side = fixture()
        side["pages"].reverse()
        with self.assertRaisesRegex(ValueError, "page numbers"):
            locate_row(side, visible, "REPORT.1")

    def test_cli_from_outside_project_and_error_status(self):
        visible, side = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "visible.json").write_bytes(visible)
            coord = root / "coords.json"
            coord.write_text(dumps(side))
            cmd = [
                sys.executable,
                "-B",
                str(SCRIPT),
                "--coordinates",
                coord.name,
                "--visible",
                "visible.json",
                "--row-id",
                "REPORT.1",
            ]
            good = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
            self.assertEqual(good.returncode, 0, good.stderr)
            self.assertEqual(json.loads(good.stdout)["printed"]["value"], "4,19")
            coord.write_text('{"pages":[],"pages":[]}')
            bad = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
            self.assertEqual(bad.returncode, 2)
            self.assertEqual(bad.stdout, "")
            self.assertIn("duplicate JSON", bad.stderr)
            self.assertNotIn("Traceback", bad.stderr)

    def test_missing_inputs_do_not_disclose_filenames(self):
        marker = "private-fixture-name.json"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "coords.json").write_text("{}", encoding="utf-8")
            for coords, visible in ((marker, "visible.json"), ("coords.json", marker)):
                with self.subTest(coords=coords, visible=visible):
                    result = subprocess.run(
                        [
                            sys.executable,
                            "-B",
                            str(SCRIPT),
                            "--coordinates",
                            coords,
                            "--visible",
                            visible,
                            "--row-id",
                            "REPORT.1",
                        ],
                        cwd=root,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, "")
                    self.assertNotIn(marker, result.stderr)
                    self.assertIn("missing", result.stderr.lower())

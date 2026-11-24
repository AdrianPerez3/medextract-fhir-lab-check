"""A matching version string cannot establish that the release wheel contains tested code."""

import gzip
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from zipfile import ZipFile

from build_backend.release import normalize_sdist
from scripts.verify_distribution import verify_source_headers, verify_wheel_payload


class DistributionContentsTests(unittest.TestCase):
    def test_source_archive_drops_builder_identity_and_preserves_payload_and_modes(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = []
            for owner, timestamp in (("first-builder", 1000), ("second-builder", 2000)):
                raw, result = root / f"{owner}.tar.gz", root / f"clean-{owner}.tar.gz"
                with (
                    raw.open("wb") as dest,
                    gzip.GzipFile(filename="", mode="wb", fileobj=dest, mtime=0) as gz,
                    tarfile.open(fileobj=gz, mode="w") as archive,
                ):
                    folder = tarfile.TarInfo("fixture")
                    folder.type = tarfile.DIRTYPE
                    folder.mode = 0o755
                    archive.addfile(folder)
                    entry = tarfile.TarInfo("fixture/script")
                    entry.uid, entry.gid = timestamp, timestamp + 1
                    entry.uname, entry.gname = owner, "local-group"
                    entry.pax_headers = {"atime": str(timestamp)}
                    entry.mtime, entry.mode, entry.size = timestamp, 0o751, 4
                    archive.addfile(entry, io.BytesIO(b"case"))
                with self.assertRaisesRegex(
                    SystemExit, "Noncanonical source archive metadata"
                ):
                    verify_source_headers(raw)
                normalize_sdist(raw, result)
                verify_source_headers(result)
                with tarfile.open(result) as archive:
                    self.assertEqual(archive.getmember("fixture/script").mode, 0o751)
                    self.assertEqual(
                        archive.extractfile("fixture/script").read(), b"case"
                    )
                    self.assertTrue(archive.getmember("fixture").isdir())
                results.append(result.read_bytes())
            self.assertEqual(results[0], results[1])
            named = root / "named.tar.gz"
            with (
                named.open("wb") as dest,
                gzip.GzipFile(
                    filename="local-name", mode="wb", fileobj=dest, mtime=0
                ) as gz,
            ):
                gz.write(gzip.decompress(results[0]))
            with self.assertRaisesRegex(SystemExit, "gzip header"):
                verify_source_headers(named)

    def test_same_version_wheel_must_match_tested_modules_and_assets(self):
        sources = {
            "lab/check.py": "lab/check.py",
            "lab.data/data/share/schemas/v2.json": "schemas/v2.json",
        }
        current = {member: b"current" for member in sources}
        with tempfile.TemporaryDirectory() as directory:
            checkout, extracted = (
                Path(directory) / "checkout",
                Path(directory) / "sdist",
            )
            for root in (checkout, extracted):
                for name in sources.values():
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"current")
            for case, files in (
                ("matching", current),
                ("stale module", {**current, "lab/check.py": b"old code"}),
                (
                    "stale schema",
                    {**current, "lab.data/data/share/schemas/v2.json": b"old schema"},
                ),
                (
                    "missing module",
                    {
                        key: data
                        for key, data in current.items()
                        if key != "lab/check.py"
                    },
                ),
                ("extra file", {**current, "unreviewed.txt": b"extra"}),
            ):
                with self.subTest(case=case), ZipFile(io.BytesIO(), "w") as wheel:
                    for member, data in files.items():
                        wheel.writestr(member, data)
                    if case == "matching":
                        verify_wheel_payload(wheel, sources, set(), extracted, checkout)
                    else:
                        with self.assertRaises(SystemExit):
                            verify_wheel_payload(
                                wheel, sources, set(), extracted, checkout
                            )

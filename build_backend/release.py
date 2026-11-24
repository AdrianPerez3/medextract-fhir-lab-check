"""Setuptools PEP 517 backend with anonymous, deterministic source-archive headers."""

import gzip
from pathlib import Path
import tarfile
import tempfile


def normalize_sdist(raw, output):
    with (
        tarfile.open(raw, "r:gz") as source,
        output.open("wb") as dest,
        gzip.GzipFile(
            filename="", fileobj=dest, mode="wb", compresslevel=9, mtime=0
        ) as gz,
        tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as archive,
    ):
        for item in sorted(source.getmembers(), key=lambda member: member.name):
            if not (item.isdir() or item.isreg()):
                raise ValueError(
                    "source distribution must contain only files and directories"
                )
            # A fresh TarInfo starts with uid/gid 0, empty owner names and no PAX metadata.
            clean = tarfile.TarInfo(item.name)
            clean.type, clean.mode, clean.size = item.type, item.mode, item.size
            clean.mtime = (
                946684800  # 2000-01-01 UTC is also representable in wheel ZIPs.
            )
            archive.addfile(clean, source.extractfile(item) if item.isreg() else None)


def build_sdist(sdist_directory, config_settings=None):
    from setuptools import build_meta

    destination = Path(sdist_directory).resolve()
    with tempfile.TemporaryDirectory(dir=destination) as temporary:
        stage = Path(temporary)
        name = build_meta.build_sdist(str(stage), config_settings)
        clean = stage / "normalized.tar.gz"
        normalize_sdist(stage / name, clean)
        clean.replace(destination / name)
    return name


def __getattr__(name):
    # Delegate the remaining PEP 517 and PEP 660 hooks to the installed setuptools.
    if name in {
        "build_wheel",
        "build_editable",
        "get_requires_for_build_sdist",
        "get_requires_for_build_wheel",
        "get_requires_for_build_editable",
        "prepare_metadata_for_build_wheel",
        "prepare_metadata_for_build_editable",
    }:
        from setuptools import build_meta

        return getattr(build_meta, name)
    raise AttributeError(name)

"""Verify a matching sdist and wheel in a directory after running python -m build."""

import argparse
from email.parser import BytesParser
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import venv
from zipfile import ZipFile


PROJECT = "medextract-fhir-lab-check"
ROOT = Path(__file__).resolve().parents[1]
LICENSE_FILES = {
    "LICENSE",
    "NOTICE.md",
    "examples/starter/CC-BY-4.0.txt",
    "examples/starter/LOINC_short_license.txt",
    "examples/starter/license.txt",
    "examples/starter/TERMINOLOGY.md",
    "examples/starter/terminology.csv",
}


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def read_json(path):
    return json.loads(path.read_bytes())


def verify_source_headers(sdist):
    with sdist.open("rb") as raw:
        header = raw.read(10)
    require(
        len(header) == 10
        and header[:8] == b"\x1f\x8b\x08\x00\x00\x00\x00\x00"
        and header[9] == 255,
        "Source gzip header must have anonymous origin, zero timestamp and no optional fields",
    )
    with tarfile.open(sdist, "r:gz") as source:
        require(not source.pax_headers, "Unexpected global source archive metadata")
        for member in source:
            require(
                (member.uid, member.gid, member.uname, member.gname, member.mtime)
                == (0, 0, "", "", 946684800)
                and not (set(member.pax_headers) - {"path"}),
                f"Noncanonical source archive metadata: {member.name}",
            )


def unpack_source(source, extracted):
    archive_root = extracted.name
    generated = {"PKG-INFO", "setup.cfg"}
    egg_info = PROJECT.replace("-", "_") + ".egg-info/"
    for member in source:
        if member.isdir():
            continue
        path = (extracted.parent / member.name).resolve()
        require(
            member.isfile() and path.is_relative_to(extracted),
            "Unexpected source member",
        )
        name = path.relative_to(extracted).as_posix()
        data = source.extractfile(member).read()
        original = ROOT / name
        if not name.startswith(egg_info) and (
            name not in generated or original.is_file()
        ):
            require(
                original.is_file() and data == original.read_bytes(),
                f"Source archive differs from checkout: {name}",
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    tests = {p.name for p in (ROOT / "tests").glob("test_*.py")}
    require(
        tests and tests == {p.name for p in (extracted / "tests").glob("test_*.py")},
        f"Source test modules differ from checkout: {archive_root}",
    )


def wheel_sources(archive_root, licenses):
    # tomli is installed by the build frontend on Python 3.10.
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib

    with (ROOT / "pyproject.toml").open("rb") as config_file:
        config = tomllib.load(config_file)
    require(
        licenses == set(config["project"]["license-files"]),
        "License metadata differs from pyproject.toml",
    )
    modules = [
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "medextract_fhir_lab").rglob("*.py")
    ]
    expected = {name: name for name in modules}
    for dest, files in config["tool"]["setuptools"]["data-files"].items():
        for name in files:
            member = f"{archive_root}.data/data/{dest}/{Path(name).name}"
            expected[member] = name
    for name in licenses:
        expected[f"{archive_root}.dist-info/licenses/{name}"] = name
    return expected


def verify_wheel_payload(binary, sources, generated, extracted, checkout):
    members = binary.namelist()
    expected = set(sources) | generated
    require(
        len(members) == len(set(members)) and set(members) == expected,
        f"Wheel members differ from the expected files: {sorted(set(members) ^ expected)}",
    )
    for member, name in sources.items():
        data = binary.read(member)
        require(
            data == (extracted / name).read_bytes() == (checkout / name).read_bytes(),
            f"Wheel, source archive and checkout differ: {name}",
        )


def verify_archives(wheel, sdist, work):
    verify_source_headers(sdist)
    with ZipFile(wheel) as binary, tarfile.open(sdist, "r:gz") as source:
        (metadata_path,) = (
            name for name in binary.namelist() if name.endswith(".dist-info/METADATA")
        )
        metadata = BytesParser().parsebytes(binary.read(metadata_path))
        version = metadata["Version"]
        archive_root = f"{PROJECT.replace('-', '_')}-{version}"
        require(sdist.name == f"{archive_root}.tar.gz", "Source archive name mismatch")
        require(
            wheel.name == f"{archive_root}-py3-none-any.whl",
            "Expected a universal Python 3 wheel",
        )
        extracted = work / archive_root
        unpack_source(source, extracted)
        source_metadata = BytesParser().parsebytes(
            (extracted / "PKG-INFO").read_bytes()
        )
        licenses = set(metadata.get_all("License-File", []))
        require(
            licenses == set(source_metadata.get_all("License-File", []))
            and licenses >= LICENSE_FILES,
            "Missing or inconsistent license and attribution metadata",
        )
        for headers in (metadata, source_metadata):
            require(headers["Name"] == PROJECT, "Unexpected distribution name")
            require(headers["Version"] == version, "Distribution versions disagree")
            require(
                headers["Requires-Python"] == ">=3.10", "Unexpected Python requirement"
            )
            require(
                not headers.get_all("Requires-Dist"), "Unexpected runtime dependency"
            )
        info = f"{archive_root}.dist-info/"
        generated = {
            info + name
            for name in (
                "METADATA",
                "WHEEL",
                "entry_points.txt",
                "top_level.txt",
                "RECORD",
            )
        }
        verify_wheel_payload(
            binary, wheel_sources(archive_root, licenses), generated, extracted, ROOT
        )
        for headers in (metadata, source_metadata):
            description = headers.get_payload(decode=True).decode("utf-8").splitlines()
            require(
                description
                == (extracted / "README.md").read_text(encoding="utf-8").splitlines(),
                "Metadata description differs from README.md",
            )
    subprocess.run(
        [sys.executable, "-E", "-m", "unittest", "discover", "-s", "tests"],
        cwd=extracted,
        check=True,
    )
    return version


def run(command, cwd, expected=0):
    # Never import the checkout via a caller's PYTHONPATH. The child runs in an empty directory.
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True)
    require(
        result.returncode == expected,
        f"{command} exited {result.returncode}, expected {expected}\n"
        + (result.stderr + result.stdout).decode("utf-8", errors="replace"),
    )
    return result.stdout


def verify_install(wheel, version, work):
    from jsonschema import Draft202012Validator

    prefix = work / "clean environment"
    venv.EnvBuilder(with_pip=True, symlinks=os.name != "nt").create(prefix)
    scripts = prefix / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    cli = scripts / (
        "medextract-fhir-lab.exe" if os.name == "nt" else "medextract-fhir-lab"
    )
    cwd = work / "outside checkout"
    cwd.mkdir()
    run(
        [
            python,
            "-I",
            "-m",
            "pip",
            "--disable-pip-version-check",
            "--isolated",
            "install",
            "--no-index",
            "--no-deps",
            wheel,
        ],
        cwd,
    )
    require(
        run([cli, "--version"], cwd).decode().strip().split()[-1] == version,
        "CLI version mismatch",
    )
    run([cli, "demo"], cwd)

    data = prefix / "share" / PROJECT
    examples = data / "examples"
    schema = read_json(data / "schemas" / "reference-v2.schema.json")
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    reference = read_json(examples / "absent-reference.json")
    validator.validate(reference)
    absent = next(row for row in reference["rows"] if row["kind"] == "absent")
    absent["value"] = "0"
    require(
        not validator.is_valid(reference),
        "Installed schema accepted mixed result fields",
    )

    check = [cli, "check", "--reference", examples / "reference.json", "--bundle"]
    good = json.loads(run([*check, examples / "correct.bundle.json"], cwd))
    bad = json.loads(run([*check, examples / "lost-limit.bundle.json"], cwd, 1))
    require(good["result"] == "pass" and not good["findings"], "Passing control failed")
    require(
        bad["findings"]
        == [
            {
                "code": "comparator-changed",
                "field": "valueQuantity.comparator",
                "row_id": "r01",
            }
        ],
        "Lost-limit control failed",
    )
    report = json.loads(
        run([cli, "suite", "--manifest", examples / "pilot.suite.json"], cwd, 1)
    )
    expected = read_json(data / "evidence" / "pilot-results.json")
    require(
        report == expected == read_json(ROOT / "evidence/pilot-results.json"),
        "Pilot differs from recorded evidence",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist_directory", type=Path)
    args = parser.parse_args()
    dist = args.dist_directory.resolve()
    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(dist.glob("*.tar.gz"))
    require(
        len(wheels) == len(sdists) == 1,
        "Expected exactly one wheel and one .tar.gz source distribution",
    )
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary).resolve()
        version = verify_archives(wheels[0], sdists[0], work)
        verify_install(wheels[0], version, work)
    print(
        f"Verified {PROJECT} {version} on Python {sys.version.split()[0]} ({sys.platform})"
    )


if __name__ == "__main__":
    main()

# Contributing a case

Choose one loss of information you can show in a fictional laboratory report. Supply a short source, the independent expected rows, a correct candidate and a one-change candidate that demonstrates the error. Give each expected row a stable identifier. Document who or what established the source-to-result association. Base the expected answer on the source, before examining the candidate's clinical fields.

Explain which details a reviewer can see on the page, which come from a documented mapping and which are unknown. Include the version and license of third-party terms or fixtures. For a template with an image, record page number, page dimensions, coordinate space, and enough geometry to find the exact row and cell. Use invented identifiers, facilities, dates and people in public examples.

Run `python3 -m unittest discover -s tests -v`. Use the CLI on the good and deliberately changed files and include the resulting finding code. A new unsupported representation needs a separate contract and tests, for example grouped panels or coded qualitative values. Keep the eligibility denominator and unsupported count visible in any published score.

For a proposed profile-conformance claim, provide the guide and package version, validator release and hash, terminology mode and complete severity counts. A terminology assertion needs its provenance and reviewer. An affected lab or vendor can reproduce a synthetic defect privately and share the minimal fictional demonstration.

To contribute a v2 case, identify whether the source attests a measured quantity or a missing result with a specific reason. Keep legitimate zero values, inequality bounds and omitted rows as independent controls. If a unit display, decimal precision or document section has an exact wording requirement, state who or what established that independent expectation. [Runnable pilot](examples/pilot.suite.json)

## Test a release candidate

Run the unit suite with `python -m unittest discover -s tests`. The source archive and the installed wheel each have their own checks. From a clean checkout or extracted source archive, use an isolated development environment:

```sh
python -m pip install "build>=1.2,<2" "jsonschema>=4.18,<5"
python -m build --outdir dist
python scripts/verify_distribution.py dist
```

Use an empty output directory for each version. The default build produces a source distribution with neutral file ownership and builds the wheel from it. The verifier checks archive metadata and compares packaged files with the checkout before testing the installed CLI, schema and demo in a clean offline environment. Retain the artifact hashes with the release and run hosted CI before promotion. [Full release criteria](PRODUCTION_PLAN.md)

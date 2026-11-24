# What the HL7 validator sees when an extraction drops a result limit

Measured on 24 November 2026 with the HL7 Java validator 7.0.6, OpenJDK 25.0.2, FHIR R4 4.0.1 and the HL7 Europe Laboratory Report 2.1.0 trial-use package. All processing ran locally. The inputs were this project's synthetic collections and the published HL7 Europe example. [Validator release](https://github.com/hapifhir/org.hl7.fhir.core/releases/tag/7.0.6) · [EU laboratory guide](https://hl7.eu/fhir/laboratory/2.1.0/)

The synthetic source reports **≤0,10 mg/L**. One FHIR collection represents the limit with `valueQuantity.comparator: "<="`. The other keeps the same number and unit and drops that one field. Every remaining JSON element agrees. R4 makes the comparator optional and gives it meaning when present. Both versions therefore make sense to a receiver, but only the first carries the source result. [FHIR R4 Quantity](https://hl7.org/fhir/R4/datatypes.html#Quantity) · [Project fixtures](../examples/)

## Measured results

Each row represents its own validator process. The synthetic-fixture configuration enables reserved example URLs and disables the terminology server.

| Input | Target | Fatal | Errors | Warnings | Information | Exit |
|---|---|---:|---:|---:|---:|---:|
| Project collection, limit intact | Base R4 | 0 | 0 | 12 | 0 | 0 |
| Project collection, limit dropped | Base R4 | 0 | 0 | 12 | 0 | 0 |
| Same intact collection with required `Bundle.type` removed | Base R4 | 0 | 7 | 12 | 0 | 1 |
| HL7 Simple Chemistry document, original | EU Lab 2.1.0 | 0 | 0 | 7 | 6 | 0 |
| Same HL7 example with a comparator added to one quantity | EU Lab 2.1.0 | 0 | 0 | 7 | 6 | 0 |
| Project collection, limit intact | EU Lab 2.1.0 | 0 | 12 | 12 | 3 | 1 |
| Project collection, limit intact, stock URL policy | Base R4 | 0 | 3 | 12 | 2 | 1 |

The official EU example originally has no comparator on the first numeric Observation. The added `<=` is an experimental mutation. Removing that addition reproduces the original parsed JSON. Within each comparator pair even the severity, issue code, diagnostic message and FHIR element paths matched. These experiments demonstrate a specific gap in validation against a source document. They provide no estimate of error frequency in clinical data. [Upstream example](https://hl7.eu/fhir/laboratory/2.1.0/Bundle-SimpleChemistryResultReport.html) · [Machine-readable results, digests and package inventory](../evidence/validator-results.json)

The project collections triggered four missing-narrative recommendations, six recommendations concerning Observation subject, performer or effective time, and two warnings for UCUM verification. Stock URL policy also flagged the three example-domain identifier systems. The EU profile correctly rejected the project's collection type and reported missing document identifier, timestamp, Composition and linked report requirements. That is why a passing base fixture beside a failing fidelity test is an honest first demonstration. [EU laboratory Bundle profile](https://hl7.eu/fhir/laboratory/2.1.0/StructureDefinition-Bundle-eu-lab.html)

The upstream EU example produced two language-system warnings, two UCUM verification warnings, two document reachability warnings and one ambiguous reference-profile warning. Six slice-matching messages were informational. With `-tx n/a`, the validator can check locally available constraints and terminologies. Coverage of LOINC, SNOMED CT, UCUM and value-set membership depends on the installed content and services. A versioned local terminology service with the required rights, independent lab review and site-specific acceptance tests are separate steps for a deployment. [HL7 validation scope](https://hl7.org/fhir/R4/validation.html) · [EU package dependencies](https://hl7.eu/fhir/laboratory/2.1.0/dependencies.html)

## Reproduce the checks

Use Bash, Java and Python 3, starting in the project root. Package hydration requires network access on a fresh cache. The commands disable the remote terminology server and use a temporary FHIR package cache. Raw validator outcomes can carry their input pathname and excerpts of a resource. Run these examples with the supplied synthetic inputs.

```bash
work_dir=$(mktemp -d "${TMPDIR:-/tmp}/medextract-validator.XXXXXX")
export JAVA_TOOL_OPTIONS="-Duser.home=$work_dir/java-home"
curl -fLsS https://github.com/hapifhir/org.hl7.fhir.core/releases/download/7.0.6/validator_cli.jar -o "$work_dir/validator_cli.jar"
curl -fLsS https://hl7.eu/fhir/laboratory/2.1.0/package.tgz -o "$work_dir/eu-lab.tgz"
curl -fLsS https://hl7.eu/fhir/laboratory/2.1.0/Bundle-SimpleChemistryResultReport.json -o "$work_dir/eu-example.json"
python3 - "$work_dir/eu-example.json" <<'PY'
import hashlib, pathlib, sys
expected = "62a19b0864ab3d8c450b885b1d11a95ed3474700f3bfb18413f23f2289e36267"
if hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest() != expected:
    sys.exit("Unexpected EU example SHA-256")
PY

scripts/validate-fhir.sh "$work_dir/validator_cli.jar" examples/correct.bundle.json "$work_dir/correct-outcome.json"
scripts/validate-fhir.sh "$work_dir/validator_cli.jar" examples/lost-limit.bundle.json "$work_dir/lost-limit-outcome.json"
scripts/validate-fhir.sh "$work_dir/validator_cli.jar" "$work_dir/eu-example.json" "$work_dir/eu-outcome.json" "$work_dir/eu-lab.tgz"
```

The wrapper checks the validator and optional EU package SHA-256, runs a single input, then inspects `OperationOutcome.issue[].severity`. It uses a new output path for each run. The CLI flags are `-version 4.0.1 -tx n/a -allow-example-urls true`. Supplying the EU archive adds `-ig PATH -profile http://hl7.eu/fhir/laboratory/StructureDefinition/Bundle-eu-lab`. The direct package pins and observed transitive package versions are recorded in the evidence. A future fully offline distribution should additionally checksum and archive all permissible dependencies. [Wrapper](../scripts/validate-fhir.sh) · [Measured environment](../evidence/validator-results.json)

To create the two experimental controls in scratch space:

```bash
python3 - "$work_dir" <<'PY'
import json, pathlib, sys
work_dir = pathlib.Path(sys.argv[1])
eu = json.loads((work_dir / "eu-example.json").read_bytes())
first = next(e["resource"] for e in eu["entry"]
             if e["resource"]["resourceType"] == "Observation" and "valueQuantity" in e["resource"])
assert "comparator" not in first["valueQuantity"]
first["valueQuantity"]["comparator"] = "<="
(work_dir / "eu-seeded-comparator.json").write_text(json.dumps(eu, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
local = pathlib.Path("examples/correct.bundle.json").read_bytes()
line = b'  "type": "collection",\n'
assert local.count(line) == 1
(work_dir / "missing-type.json").write_bytes(local.replace(line, b""))
PY

scripts/validate-fhir.sh "$work_dir/validator_cli.jar" "$work_dir/eu-seeded-comparator.json" "$work_dir/seeded-outcome.json" "$work_dir/eu-lab.tgz"
scripts/validate-fhir.sh "$work_dir/validator_cli.jar" "$work_dir/missing-type.json" "$work_dir/missing-type-outcome.json"
```

Expect the last command to exit 1. The single-file control caught the missing required field and six resulting constraint violations. In a separate unwrapped CLI invocation that validated all three project inputs together, Java exited **0** while the third entry of its output Bundle contained seven errors. CI must inspect each returned outcome or use one input per wrapper invocation. The wrapper preserves the outcome and reports failure for any fatal or error severity. [Batch run evidence](../evidence/validator-results.json)

## A project document that exercises the EU profile

A separately measured, hand-authored seven-resource EU teaching document now carries the same two source rows. The identical file passed the independent row check and returned zero profile errors under both base R4 and EU Lab 2.1.0 with remote terminology disabled. Removing only the first result's comparator produced the same profile diagnostics and a `comparator-changed` finding for r01. The invented document context, three EU warnings and two informational messages are documented in the worked example. [Worked EU document](../examples/eu-context.md) · [Validation evidence](../evidence/eu-teaching-results.json)

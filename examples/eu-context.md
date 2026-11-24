# Synthetic EU laboratory document

[Open the FHIR document](eu-teaching.document.json) to see the two source rows inside a complete seven-resource example. The Composition comes first. Its results section points to the DiagnosticReport and both Observations. The DiagnosticReport links back to the Composition through the R5 Composition extension for R4 and lists both Observations as results. All resource references resolve inside the Bundle. The document is hand-authored. The project's `export` command produces a base R4 collection. [EU laboratory document profile](https://hl7.eu/fhir/laboratory/2.1.0/StructureDefinition-Bundle-eu-lab.html) · [EU DiagnosticReport profile](https://hl7.eu/fhir/laboratory/2.1.0/StructureDefinition-DiagnosticReport-eu-lab.html)

## Which fields come from the source?

| Field | Origin |
|---|---|
| Report and row identifiers | `LAB-DEMO-001`, `r01`, `r02` and their code assignments come from the synthetic source and independent reference. |
| Row r01 | Proteína C reactiva, LOINC 1988-5, ≤0,10 mg/L. The source gives neither a result status nor a specimen. The Observation carries `status: unknown`, structured quantity `0.10`, comparator `<=` and no specimen reference. |
| Row r02 | Glucosa, LOINC 2345-7, 92 mg/dL, final, serum. Only r02 references the serum Specimen. Its type is the source reference's HL7 v2-0487 code `SER`. |
| Synthetic subject and organization | “Fictional Teaching Subject”, date of birth 2000-01-01, and “Synthetic Teaching Laboratory” were invented. The organization is the document author and the performer of each example Observation. |
| Synthetic timestamps | Both Observations carry 2025-01-15 09:00 UTC. Document assembly and composition use 09:30 UTC on that date. These timestamps were chosen solely for the example. |
| Document metadata | The document identifier `DOC-DEMO-001`, entry UUIDs, narrative sections and Composition status `final` describe this assembled teaching document. The source report's workflow status is unspecified and the DiagnosticReport records `unknown`. The document has no encounter. |

The extra context makes this instance usable for profile testing. An integration using an actual report would need its own supported patient, author, performer and timing context. The example includes no clinical interpretation, inferred specimen for r01 or terminology translation for the serum sample. [Readable source](source.txt) · [Independent row reference](reference.json) · [EU Observation profile](https://hl7.eu/fhir/laboratory/2.1.0/StructureDefinition-Observation-resultslab-eu-lab.html)

## Reproduce the comparator test

From the project root, use the following commands. The altered document is created in a temporary directory and differs by exactly the structured comparator line. Its unchanged narrative still shows the limit, as it would if a system dropped the comparator while building a structured result.

```bash
python3 -m medextract_fhir_lab check --reference examples/reference.json --bundle examples/eu-teaching.document.json
demo_dir=$(mktemp -d "${TMPDIR:-/tmp}/medextract-eu-demo.XXXXXX")
python3 - "$demo_dir/lost-limit.json" <<'PY'
import pathlib, sys
document = pathlib.Path("examples/eu-teaching.document.json").read_bytes()
line = b'          "comparator": "<=",\n'
assert document.count(line) == 1
pathlib.Path(sys.argv[1]).write_bytes(document.replace(line, b""))
PY
python3 -m medextract_fhir_lab check --reference examples/reference.json --bundle "$demo_dir/lost-limit.json"
```

The original returns exit 0 and the altered copy returns exit 1 with `comparator-changed` on r01. To reproduce the profile checks, first follow the validator setup. Then run the commands below. Both use the same document bytes. The example selects the EU profile explicitly on the validator command line so a base-R4-only validator can also inspect it without attempting to resolve a declared EU profile. [Validator setup](../research/validation.md)

```bash
scripts/validate-fhir.sh "$work_dir/validator_cli.jar" examples/eu-teaching.document.json "$demo_dir/base-outcome.json"
scripts/validate-fhir.sh "$work_dir/validator_cli.jar" examples/eu-teaching.document.json "$demo_dir/eu-outcome.json" "$work_dir/eu-lab.tgz"
scripts/validate-fhir.sh "$work_dir/validator_cli.jar" "$demo_dir/lost-limit.json" "$demo_dir/lost-eu-outcome.json" "$work_dir/eu-lab.tgz"
```

For both versions the base validator reported zero errors and two warnings. With remote terminology disabled it could not verify `mg/L` or `mg/dL`. EU Lab 2.1.0 reported zero errors, those same two warnings, and a third warning because the backported Composition link matched both R4 and R5 target profiles. The EU run also emitted two informational messages. The results section did not match a named slice, and the source's v2 `SER` code was outside the preferred EU specimen value set. The warnings, complete diagnostic messages and SHA-256 hashes are recorded alongside the row-checker findings. [Measured results](../evidence/eu-teaching-results.json) · [EU specimen profile](https://hl7.eu/fhir/laboratory/2.1.0/StructureDefinition-Specimen-eu-lab.html)

The document uses the structure published by HL7 Europe in the 2.1.0 laboratory guide under CC0. Its identities, dates, narratives and laboratory results were authored for this project. [HL7 Europe profile and attribution](https://hl7.eu/fhir/laboratory/2.1.0/StructureDefinition-Bundle-eu-lab.html)

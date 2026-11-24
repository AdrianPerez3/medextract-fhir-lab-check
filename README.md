# MedExtract FHIR Lab Check

MedExtract FHIR Lab Check is an offline Python tool for testing whether an HL7 FHIR R4 laboratory report preserves what the source report says. Give it a FHIR `Bundle` and an independently prepared list of expected lab results. It returns JSON findings that identify the changed field and, for a row-level discrepancy, the source row. Integration engineers can use it to test a converter or catch a regression in a data pipeline.

For example, a synthetic Spanish report records C-reactive protein as **≤0,10 mg/L**. An export that keeps the number and unit but drops the inequality now reports an exact measurement. The two quantities can both satisfy the same FHIR profile. Comparing the export with the source reveals the lost upper bound. [Source report](examples/source.txt) · [FHIR validator comparison](research/validation.md)

## Quickstart from a checkout

Run these commands from the repository root with Python 3.10 or later. The commands read bundled synthetic fixtures, run locally using the Python standard library, and write results to the terminal. No installation, account, terminology server or network connection is needed after checkout. On systems where Python 3 is named `python3`, substitute that command for `python`.

```sh
python -m medextract_fhir_lab --version
python -m medextract_fhir_lab demo
```

The demo prints one verification line.

```text
Verified 5 synthetic cases matched their expected outcomes (2 passes, 3 deliberate failures).
```

To see what went wrong in one report, compare the original export and the copy with the missing inequality. Run each command individually. The first exits **0**. The second exits **1** and names row `r01`.

```sh
python -m medextract_fhir_lab check --reference examples/reference.json --bundle examples/correct.bundle.json
python -m medextract_fhir_lab check --reference examples/reference.json --bundle examples/lost-limit.bundle.json
```

The second command returns this finding in its `findings` array.

```json
{"code": "comparator-changed", "field": "valueQuantity.comparator", "row_id": "r01"}
```

To install the console command, run `python -m pip install .` from the checkout in a virtual environment, then run `medextract-fhir-lab demo` from any directory. Installation from source can fetch build tools. The installed checker has no third-party runtime dependencies.

## Test your own FHIR converter

1. **Prepare the expected rows.** Transcribe a synthetic report before inspecting the candidate export. Give each row its own stable ID. Two measurements can share the same LOINC code. The v2 reference distinguishes a numeric quantity, an explicit absence such as “test not performed”, and a measured zero. [Worked reference](examples/absent-reference.json) · [Reference schema and field definitions](schemas/README.md)
2. **Link rows to observations.** Export one `DiagnosticReport` and its direct result `Observation` resources in an R4 collection or document Bundle. If your converter emits the reference’s report and row identifiers, pass the reference and Bundle directly to `check`. For a vendor’s own identifiers, supply `--bindings` with a trace from source rows to entry `fullUrl` values captured during conversion or independent review. Matching by code, number or array position after export can conceal a swap. [Binding manifest example](examples/bindings.json)
3. **Run the comparison and the profile validator.** `check` tests agreement with the supplied source. Use the official HL7 validator for the receiver’s selected implementation guide and terminology configuration. Keep the checker version, source fixture and both sets of results with the test. [Validation procedure](research/validation.md)

## Use the exit codes in CI

```sh
python -m medextract_fhir_lab suite --manifest examples/pilot.suite.json --summary-only
```

| Exit | Meaning for `check` and `suite` | What to inspect |
| --- | --- | --- |
| `0` | Every requested comparison completed and agreed with its reference. | Keep the source and candidate versions with the result. |
| `1` | At least one comparison found a discrepancy, and all requested comparisons completed. | Use the detailed `check` output to find the field and source row. |
| `2` | At least one input or representation could not be evaluated. | Inspect the error stage and retain any findings from comparisons that did complete. |

The pilot suite exits **1**. Across five cases and ten expected row occurrences, it finds a lost comparator, an invented zero and a changed human-readable section. The `demo` self-test exits **0** because those are its recorded outcomes. Omit `--summary-only` for per-case results. The summary counts missing and unsupported cases and distinguishes known expected rows from rows in fully evaluated cases. Single-report checks that cannot complete any comparison return a diagnostic on standard error. Case IDs from the manifest and source row IDs can appear in output. Choose synthetic, non-identifying labels for shared CI logs. [Pilot manifest](examples/pilot.suite.json) · [Full expected JSON](evidence/pilot-results.json)

## Supported laboratory data

| Area | What the checker evaluates |
| --- | --- |
| Results | Numeric value, comparator, expected LOINC test code and case-sensitive UCUM unit code. The v2 reference can also require exact decimal places or a reviewed unit display. |
| Missing results | In v2, compares a coded `dataAbsentReason` separately from a measured zero. Distinguishes an omitted expected row when the candidate carries benchmark IDs. A missing target in an explicit binding manifest makes that input unevaluable. |
| Relationships | Checks row identity, the direct links from the report to its results, Observation status, expected specimen and conflicting subjects within the bundle. [Subject and specimen examples](research/subject-graph.md) |
| Document text | An optional `--narrative-review` checks the decoded XHTML of one independently reviewed, coded document section. Exact text and whitespace changes are detectable. [Narrative review example](examples/eu-narrative-review.json) |

The supported scope covers direct quantitative results and explicit absence. Panels with component results, qualitative observations and unhandled modifier extensions require separate interpretation. Clinical appropriateness, vocabulary membership, OCR accuracy and real-world patient matching require independent evidence. The checker expects a prepared reference and a FHIR Bundle as inputs.

## Examples and evidence

- **Trace a result to the page.** The Spanish starter includes a synthetic PDF, image and row/cell coordinates. Locate a source row in PDF points or image pixels with the [row locator](scripts/locate_row.py). [Starter image](examples/starter/report.jpg) · [Coordinate file](examples/starter/coordinates.json)
- **Inspect an EU laboratory document.** A seven-resource teaching example received zero errors, three warnings and two informational messages from validator 7.0.6 with the EU Laboratory Report guide 2.1.0 and remote terminology disabled. [FHIR document](examples/eu-teaching.document.json) · [Field provenance](examples/eu-context.md) · [Validation results](evidence/eu-teaching-results.json)
- **Review the synthetic replay.** A recorded run spans 1,000 synthetic reports and 18,329 rows. All unmodified reports passed, and one seeded error per report was located on its expected row. These figures measure this fixture and mutation set. [Corpus results](evidence/starter-results.json) · [Replay script](scripts/check_starter.py)
- **Reproduce the benchmarks.** The recorded release-candidate runs compare direct and vendor-bound checks and measure peak Python allocations for full and aggregate-only suite output. Each includes its workload and replay command. [Timing and memory by report size](evidence/performance.json) · [Suite memory results](evidence/suite-summary-performance.json)

## Contributing and licensing

A useful regression case includes an invented source, independently reviewed expected rows, a correct export and a copy with one deliberate change. Run `python -m unittest discover -s tests` to execute the test suite. [Contribution guide](CONTRIBUTING.md)

The original code and technical documentation use the MIT license. The original teaching report and annotations use CC BY 4.0. Included datasets, LOINC, UCUM and other third-party materials retain their applicable terms. [Code license](LICENSE) · [Data attribution and terminology notices](NOTICE.md)

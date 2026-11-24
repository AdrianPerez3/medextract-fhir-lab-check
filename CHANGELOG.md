# Change history

## 0.3.0rc2 · 24 November 2026

- Malformed FHIR resource addresses produce a diagnostic that identifies the failed comparison stage without printing the submitted address.
- The starter row locator reports an unreadable input without printing its filesystem path.
- The README includes a checkout-first demo, a passing control, a deliberately changed control and the exit codes to expect in CI.
- The version test checks the CLI against the package's declared version. Earlier timing and memory measurements cover the rc1 baseline.

## 0.3.0rc1 · 24 November 2026

- The wheel includes the synthetic pilot, its expected output, schema, and license notices. Run `medextract-fhir-lab demo` from an installed environment to verify the five cases. `--version` identifies the build.
- Single-report and suite commands now share the validation path. A valid narrative discrepancy survives an unsupported row comparison and the reverse case also retains its known findings. Suite summary-only mode retains the same denominators and exit code using less memory.
- Vendor-bound comparisons reuse one validated resource index and add the necessary benchmark identifiers to an internal view. The public `bind()` function continues to return an independent copy.
- The release includes additional controls for contradicting references, starter report identity, implicit rules and reviewed narrative scope. Consult the [release plan and verification record](PRODUCTION_PLAN.md) for exact checks and outstanding gates.

## 0.2.0 · 24 November 2026

This preview adds a second source-reference format and a multi-report CI command. Existing v1 numeric references remain usable. The subject-graph changes also apply to v1 candidates, so earlier passes that contained inconsistent references can now fail.

| Change | What a receiving team can demonstrate |
| --- | --- |
| Typed source results | Distinguish a documented absence, a measured zero, a numeric bound and an omitted row. When explicitly attested, test the human-readable unit or decimal places separately from the UCUM code and numeric value. [Source and test pair](examples/absent-source.txt) · [Portable v2 schema](schemas/reference-v2.schema.json) · [HL7 validator outcomes](evidence/result-states-validation.json) |
| Reviewed document section | Detect an altered clinician-facing value in one pre-reviewed, plain-paragraph EU lab section. The fingerprint binds the exact decoded XHTML, so legitimate editorial changes can also prompt review. [Case](examples/eu-narrative-review.json) · [Research and controls](research/next-improvements.md) |
| Relationships across the report | Detect contradictory subjects, invalid local references and use of an invalidated specimen. External identity resolution and multi-subject clinical interpretation require different evidence. [Graph research](research/subject-graph.md) |
| CI suite | Run multiple exports offline. A missing candidate, unsupported shape or bad optional input stays in the denominator. Known row findings survive an unevaluable optional narrative check. [Example run](evidence/pilot-results.json) |
| Independent software replays | A third-party FHIR model reproduced the decimal-place difference already introduced by default JSON decoding. [SDK round trip](research/sdk-roundtrip.md) |

The full starter replay returned the same archived results for 1,000 reports, 1,015 pages and 18,329 rows. It measures synthetic compatibility and seeded error detection. Evidence of clinical safety or adoption in independently operated systems requires a separate evaluation. [Starter receipt](evidence/starter-results.json) · [Adoption plan](research/adoption.md)

## 0.1.0 · 24 November 2026

The initial preview introduced the offline quantitative checker, independent bindings for candidate identifiers, the Spanish source PDF and JPEG, the row locator, a seven-resource European teaching document and the 1,000-report starter replay. The original preview archive has SHA-256 `2da7b16952aca79082fae3a0a23d72b410623c384cae7f880e62159cc8efe0f0`. All 49 archived members matched the project files before this work began. [Baseline validation](research/validation.md) · [Ecosystem review](research/ecosystem.md)

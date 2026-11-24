# What a JavaScript FHIR consumer reads

On 24 November 2026 we ran HL7's JavaScript FHIRPath engine against both hand-authored R4 collection Bundles. The source report prints C-reactive protein as **≤0,10 mg/L**. Both Bundles give the consumer the same numeric value and UCUM unit. Only one carries the upper-bound comparator. [Source transcription](../examples/source.txt) · [HL7 engine](https://github.com/HL7/fhirpath.js) · [Pinned npm release](https://www.npmjs.com/package/fhirpath/v/5.2.3)

| Fixture | Numeric value | Unit / UCUM code | FHIRPath comparator collection | Separate Python source check |
| --- | --- | --- | --- | --- |
| [Correct](../examples/correct.bundle.json) | 0.1 | mg/L | `["<="]` | Pass, 2 expected rows, 0 findings, exit 0 |
| [Lost limit](../examples/lost-limit.bundle.json) | 0.1 | mg/L | `[]` | Fail, 2 expected rows, 1 finding, `comparator-changed` on `r01`, exit 1 |

An empty FHIRPath collection means the consumer found no comparator. Both fixtures use `http://unitsofmeasure.org` as the unit system. JavaScript reports the numeric value as 0.1. This test measures how the chosen reader sees the numeric Quantity and its qualifier. It does not measure recovery of the source's printed decimal precision.

## Reproduce from the project root

The measured environment used Node 22.20.0, npm 10.9.3 and `fhirpath@5.2.3`. The temporary directory holds the engine and its dependency lock. The time cutoff limits registry resolution to packages published before the research date. The SHA-512 value below matches both the npm lock entry and the tarball bytes verified during this run. The actual bundle queries require only local files. [Registry release metadata](https://registry.npmjs.org/fhirpath/5.2.3) · [Reader source](../scripts/read-fhirpath.cjs)

```sh
consumer_dir="$(cd "$(mktemp -d)" && pwd -P)"
npm install --prefix "$consumer_dir" --registry=https://registry.npmjs.org \
  --before=2026-11-24T00:00:00Z --save-exact --ignore-scripts --no-fund --no-audit fhirpath@5.2.3
node - "$consumer_dir/package-lock.json" <<'JS'
const { createHash } = require('node:crypto');
const packages = require(process.argv[2]).packages;
const engine = packages['node_modules/fhirpath'];
const expected = 'sha512-l1j7vAn7NDGE+vo6S+5IJH1AP5awFBsNlXCTuqVgItB5EE42ZTJ+1XXcUJZXrLiIl4ezcdbZ2vbKdzoFLEYfoA==';
if (engine.version !== '5.2.3' || engine.integrity !== expected) throw Error('Engine integrity differs');
const tree = Object.keys(packages).filter(Boolean).sort()
  .map(k => [k, packages[k].version, packages[k].integrity]);
const digest = createHash('sha256').update(JSON.stringify(tree)).digest('hex');
if (digest !== '512645cbe9185be46a488c4f5dcb117b3f7d32bd7a0eab654f06fc2645fccf14') {
  throw Error('Dependency tree differs from the 30 packages measured here');
}
JS
NODE_PATH="$consumer_dir/node_modules" node scripts/read-fhirpath.cjs \
  examples/correct.bundle.json examples/lost-limit.bundle.json
python3 -m medextract_fhir_lab check --reference examples/reference.json --bundle examples/correct.bundle.json
python3 -m medextract_fhir_lab check --reference examples/reference.json --bundle examples/lost-limit.bundle.json
```

The first FHIRPath expression selects `Bundle.entry.resource.ofType(DiagnosticReport).result.reference`. The reader supplies that collection as `%reported` for the next expression. These single-report fixtures use relative `Observation/id` references. The reader also accepts a matching entry `fullUrl`. It expects exactly one linked CRP Quantity and then evaluates its `.value`, `.unit`, `.system`, `.code` and `.comparator` fields independently.

```fhirpath
Bundle.entry.where(fullUrl in %reported or ('Observation/' & resource.id) in %reported)
  .resource.ofType(Observation)
  .where(code.coding.where(system = 'http://loinc.org' and code = '1988-5').exists())
  .value.ofType(Quantity)
```

As a control, adding an unreferenced CRP Observation with value 999 left the readout at 0.1. Removing the original CRP result link caused the script to exit 2 with a missing-target diagnostic. This establishes that one independent, third-party engine can consume these fixtures. External implementation, vendor deployment and adoption remain unmeasured.

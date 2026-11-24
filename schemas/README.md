# Validate a version 2 source reference

Use the [standalone JSON Schema](reference-v2.schema.json) when building a fixture editor or a converter test in another language. It validates an independently recorded laboratory source reference. Every reference within the schema resolves inside the file. A validator with Draft 2020-12 support can run offline. The accompanying example includes a cancelled result with a reason and a measured zero with two decimal places. [Worked reference](../examples/absent-reference.json) · [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12)

Every row must contain a unique source row ID, LOINC string, status (possibly null) and specimen (possibly null). A quantity row requires a value as a **decimal string**, a UCUM unit code and a comparator (possibly null). Use a string such as `"0.00"` to preserve the declared precision. Optional `preserve_decimal_places` enables decimal-place checking and optional `display_unit` attests the exact human-facing unit. An absent row instead requires one of 14 supported R4 absence codes. The remaining R4 code `as-text` requires interpretation of a separate narrative. Unknown properties and mixed quantity/absence fields fail validation. The vocabulary membership and clinical appropriateness of a supplied LOINC or UCUM code require independent review. [R4 absence reasons](https://hl7.org/fhir/R4/valueset-data-absent-reason.html)

## Try a JavaScript validator

Start in the unpacked source distribution with Node and npm installed. Wheel users can run the same commands from `share/medextract-fhir-lab-check` in their installation. The following POSIX shell commands install Ajv in a temporary directory and validate local files.

```sh
schema_tools=$(mktemp -d)
npm install --prefix "$schema_tools" --save-exact --ignore-scripts --no-audit --no-fund ajv@8.17.1
NODE_PATH="$schema_tools/node_modules" node - <<'JS'
const fs = require('node:fs');
const Ajv2020 = require('ajv/dist/2020');
const read = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const schema = read('schemas/reference-v2.schema.json');
const reference = read('examples/absent-reference.json');
const validate = new Ajv2020({strict: true}).compile(schema);
if (!validate(reference)) throw new Error(JSON.stringify(validate.errors));
const absent = reference.rows.find(row => row.kind === 'absent');
absent.value = '0';
if (validate(reference)) throw new Error('Mixed absent/quantity fields unexpectedly passed');
console.log('Valid source accepted. Absent row with invented zero rejected.');
JS
```

## Checks that require the runtime or parser

- Enforce **unique row IDs** across the report. JSON Schema array uniqueness applies to entire elements. Two different rows can share an ID and satisfy the schema. The MedExtract validator rejects duplicate IDs.
- Emit the literal integer token `2` for `schema_version`. JSON Schema regards `2.0` and `2e0` as the same integral value. The project CLI preserves the distinction when decoding JSON and accepts only the integer token. Catch duplicate object keys at parse time as well. An ordinary parser that discards an earlier key cannot recover it during schema validation. The parser is in `medextract_fhir_lab/jsonio.py` in the source distribution. [JSON Schema numeric semantics](https://json-schema.org/understanding-json-schema/reference/numeric)
- Keep the independently attested report identity, clinical values, terminology choices and row associations under review. Schema acceptance establishes the input shape. The full CLI also compares the candidate and checks its resource graph. The implementation is in `medextract_fhir_lab/checker.py` in the source distribution.

On 24 November 2026, Python `jsonschema` 4.26.0 and JavaScript Ajv 8.17.1 agreed on all 58 local test inputs, comprising 30 schema-valid and 28 schema-invalid inputs. The Python runtime also rejected the two deliberately included schema-valid exceptions for a duplicate row ID and the version token `2.0`. The corpus included all 14 supported absence codes and seven comparator representations including null, rejected incompatible fields and numeric representations, and exercised the optional quantity-display properties. The ordinary test suite checks the published fields and enum tables against the implementation using only the Python standard library. Run `python -m unittest discover -s tests -p test_reference_schema.py` from the source distribution to reproduce those checks.

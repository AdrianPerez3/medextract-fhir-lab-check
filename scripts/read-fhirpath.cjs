// Read the two demonstration Bundles with HL7's JavaScript FHIRPath engine.
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const fhirpath = require("fhirpath");
const r4 = require("fhirpath/fhir-context/r4");

const reportResults = "Bundle.entry.resource.ofType(DiagnosticReport).result.reference";
const crpQuantity = [
  "Bundle.entry.where(fullUrl in %reported or ('Observation/' & resource.id) in %reported)",
  "resource.ofType(Observation)",
  "where(code.coding.where(system = 'http://loinc.org' and code = '1988-5').exists())",
  "value.ofType(Quantity)",
].join(".");

function readFixture(filename) {
  const bundle = JSON.parse(fs.readFileSync(filename, "utf8"));
  const evaluate = (expression, variables) => fhirpath.evaluate(bundle, expression, variables, r4);
  const reported = evaluate(reportResults, {});
  const read = (suffix) => evaluate(crpQuantity + "." + suffix, { reported });

  if (read("count()")[0] !== 1) {
    throw new Error("Expected one report-linked C-reactive protein Quantity in the example");
  }
  return {
    input: path.basename(filename),
    value: read("value"),
    unit: read("unit"),
    unitSystem: read("system"),
    unitCode: read("code"),
    comparator: read("comparator"),
  };
}

const args = process.argv.slice(2);
if (args.length === 0 || args.includes("--help")) {
  console.error("Usage: node scripts/read-fhirpath.cjs BUNDLE.json [BUNDLE.json ...]");
  process.exit(args.length === 0 ? 2 : 0);
}

try {
  for (const file of args) {
    console.log(JSON.stringify(readFixture(file)));
  }
} catch (error) {
  console.error(error.message);
  process.exitCode = 2;
}

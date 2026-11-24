#!/usr/bin/env bash
# Run the pinned HL7 validator on one synthetic example and retain its OperationOutcome.
set -eu

if [[ $# -lt 3 || $# -gt 4 ]]; then
  echo "Usage: $0 VALIDATOR_JAR SYNTHETIC_INPUT_JSON NEW_OUTCOME_JSON [EU_LAB_TGZ]" >&2
  exit 2
fi

jar=$1
input=$2
outcome=$3
if [[ ! -f "$input" || -e "$outcome" || -L "$outcome" ]]; then
  echo "Supply an existing input file and a new output path." >&2
  exit 2
fi

verify_sha256() {
  python3 - "$1" "$2" <<'PY'
import hashlib
import sys

with open(sys.argv[1], "rb") as source:
    digest = hashlib.sha256()
    for block in iter(lambda: source.read(1024 * 1024), b""):
        digest.update(block)
if digest.hexdigest() != sys.argv[2]:
    sys.exit(f"SHA-256 mismatch for {sys.argv[1]}")
PY
}

verify_sha256 "$jar" 2686590539f0b3ba7683149b25d78249f6886c04e2c326e884c5049d8947df89
args=("$input" -version 4.0.1 -tx n/a -allow-example-urls true -output "$outcome")
if [[ $# -eq 4 ]]; then
  verify_sha256 "$4" 87019c396f4cff934ec5230ce1f97d76b79b40591be08161e694ad661129379c
  args+=(-ig "$4" -profile http://hl7.eu/fhir/laboratory/StructureDefinition/Bundle-eu-lab)
fi

status=0
java -Xmx3g -jar "$jar" "${args[@]}" || status=$?
if [[ ! -s "$outcome" ]]; then
  echo "Validator did not write an OperationOutcome." >&2
  exit 2
fi

python3 - "$outcome" <<'PY'
import json
import sys
from collections import Counter

with open(sys.argv[1], encoding="utf-8") as output:
    result = json.load(output)
if result.get("resourceType") != "OperationOutcome" or not result.get("issue"):
    sys.exit("Expected a single OperationOutcome with at least one issue.")
counts = Counter(issue["severity"] for issue in result["issue"])
print(" ".join(f"{key}={counts[key]}" for key in ("fatal", "error", "warning", "information")))
if counts["error"] or counts["fatal"]:
    sys.exit(1)
PY
exit "$status"

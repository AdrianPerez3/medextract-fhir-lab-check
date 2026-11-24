# Where a FHIR result loses its decimal places

The fixture contains a measured basophil percentage encoded as `0.00` and a separate unperformed examination. We passed both the correct report and the fabricated-zero candidate through the open-source SMART on FHIR Python client and back to JSON. The upstream project documents building model objects from the standard JSON decoder and emitting mappings with `as_json()`. The test used Python 3.11.9, the published `fhirclient` 4.4.0 wheel (SHA-256 `85f25b11b2303ded7780708edc85aaf21be60fbd6439409b44085bcc1a991589`) and requests 2.32.5. All clinical inputs were fictional and all model operations ran locally. [Upstream API examples](https://github.com/smart-on-fhir/client-py#data-model-use) · [Published package](https://pypi.org/project/fhirclient/4.4.0/) · [R4 JSON precision guidance](https://hl7.org/fhir/R4/json.html)

| Candidate | Checked directly from original bytes | Standard JSON decode/encode alone | Standard JSON decode, SDK Bundle and encode |
| --- | --- | --- | --- |
| Correct | Pass | Decimal places changed on r02 | Decimal places changed on r02 |
| Invented zero | Invented value on r01 | Invented value on r01 and decimal places changed on r02 | Same two findings |

Python's default JSON decoder already turns `0.00` into the float `0.0`. The control reproduced the entire change before the SDK processed the object. The measured number remained zero in all runs. Teams that explicitly attest reported decimal places can use this example to find the boundary where that information disappears. The check makes no inference about a laboratory instrument's uncertainty or a vendor's production installation. [Source](../examples/absent-source.txt) · [Independent reference](../examples/absent-reference.json)

## Reproduce

From the project checkout, install the optional SDK in an isolated environment. The checker itself has no runtime dependencies.

```sh
sdk_dir=$(mktemp -d)
python3 -m venv "$sdk_dir/venv"
"$sdk_dir/venv/bin/python" -m pip install "fhirclient==4.4.0" "requests==2.32.5"
"$sdk_dir/venv/bin/python" - <<'PY'
from pathlib import Path
import json
from fhirclient.models.bundle import Bundle
from medextract_fhir_lab.checker import check
from medextract_fhir_lab.jsonio import loads

examples = Path("examples")
reference = loads((examples / "absent-reference.json").read_bytes())
for name in ("absent-correct", "absent-as-zero"):
    wire = (examples / (name + ".bundle.json")).read_bytes()
    decoded = json.loads(wire)
    for label, candidate in (
        ("original", loads(wire)),
        ("decoder control", loads(json.dumps(decoded))),
        ("SDK round trip", loads(json.dumps(Bundle(decoded).as_json()))),
    ):
        print(name, label, [(f["code"], f["row_id"]) for f in check(reference, candidate)])
PY
```

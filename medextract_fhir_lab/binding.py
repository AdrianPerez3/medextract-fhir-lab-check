"""Optional fixture correlation for senders that use their own FHIR identifiers."""

from __future__ import annotations

from copy import deepcopy

from .checker import _Bundle, _identifiers, validate_reference


def _fields(obj, fields, name):
    if not isinstance(obj, dict) or obj.keys() != fields:
        raise ValueError(f"{name} must contain exactly the version 1 fields")


def bind(reference: dict, bundle: dict, manifest: dict) -> dict:
    """Return an independent bundle copy with comparison identifiers added.

    Each manifest link must be attested independently, e.g. by an export trace
    linking a source row to the sender's resource identity. A manifest derived
    from the values under test could conceal a mapping error. Matching is by
    exact Bundle.entry.fullUrl only; this function never guesses from clinical
    content, positions or resource ids. Run check() on the returned graph to
    evaluate the linked results. The sender's input is never edited.
    """
    validate_reference(reference)
    _, additions = _prepare_bindings(reference, bundle, manifest)
    output = deepcopy(bundle)
    for index, identifier in additions:
        resource = output["entry"][index]["resource"]
        resource.setdefault("identifier", []).append(identifier)
    return output


def _bound_graph(reference, bundle, manifest):
    """Index a candidate for read-only comparison with a validated reference."""
    graph, additions = _prepare_bindings(reference, bundle, manifest)
    for index, identifier in additions:
        resource = graph.resources[index]
        # Only this graph sees the added identifier. All other fields remain
        # read-only views of the original, including the sender's narrative.
        graph.resources[index] = {
            **resource,
            "identifier": [*resource.get("identifier", ()), identifier],
        }
    return graph


def _prepare_bindings(reference, bundle, manifest):
    _fields(
        manifest, {"schema_version", "report_id", "report_full_url", "rows"}, "manifest"
    )
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise ValueError("manifest.schema_version must be integer 1")
    if manifest["report_id"] != reference["report_id"]:
        raise ValueError("manifest identifies a different source report")
    if not isinstance(manifest["rows"], list):
        raise ValueError("manifest.rows must be an array")

    graph = _Bundle(bundle)
    expected = {}

    def target(url, kind):
        index = graph.addresses.get(url) if isinstance(url, str) else None
        # The graph also indexes Type/id aliases. Only an exact fullUrl can bind.
        if index is None or bundle["entry"][index].get("fullUrl") != url:
            raise ValueError("manifest target must be an exact fullUrl in this bundle")
        if graph.resources[index]["resourceType"] != kind:
            raise ValueError(f"manifest target must identify a {kind} resource")
        if index in expected:
            raise ValueError("manifest target is bound more than once")
        return index

    row_system = reference["identifier_system"]
    report_system = row_system + "/reports"
    report_id = reference["report_id"]
    expected[target(manifest["report_full_url"], "DiagnosticReport")] = report_id
    attested_ids = {
        "Observation": {row["id"] for row in reference["rows"]},
        "DiagnosticReport": {report_id},
    }
    remaining = attested_ids["Observation"].copy()
    for row in manifest["rows"]:
        _fields(row, {"row_id", "observation_full_url"}, "manifest row")
        key = row["row_id"]
        if not isinstance(key, str) or key not in remaining:
            raise ValueError("manifest row_id is unknown or repeated")
        remaining.remove(key)
        expected[target(row["observation_full_url"], "Observation")] = key
    if remaining:
        raise ValueError("manifest must cover every source row")

    additions = []
    for index, resource in enumerate(graph.resources):
        kind = resource["resourceType"]
        if kind not in attested_ids:
            continue
        system = row_system if kind == "Observation" else report_system
        existing = _identifiers(resource, system)
        identifier = expected.get(index)
        if identifier is None:
            # Extra resources remain in the candidate. Prevent a second
            # resource from claiming a binding this manifest assigns elsewhere.
            if not attested_ids[kind].isdisjoint(existing):
                raise ValueError(
                    "comparison identifier already belongs to another resource"
                )
        elif existing and existing != [identifier]:
            raise ValueError(
                "manifest conflicts with a candidate comparison identifier"
            )
        elif not existing:
            additions.append((index, {"system": system, "value": identifier}))
    return graph, additions

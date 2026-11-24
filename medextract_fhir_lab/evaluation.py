"""Evaluate one local report for both the detailed CLI and the batch summary."""

from dataclasses import dataclass, field
from pathlib import Path

from .binding import _bound_graph
from .checker import _Bundle, _check_graph, validate_reference
from .jsonio import read_json
from .narrative import check_narrative


@dataclass
class Evaluation:
    expected_rows: int | None = None
    findings: list[dict] = field(default_factory=list)
    row_checked: bool = False
    narrative_checked: bool = False
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def result(self):
        if self.errors:
            return "unevaluable"
        return "fail" if self.findings else "pass"

    @property
    def evaluated(self):
        return self.row_checked or self.narrative_checked

    def error_fields(self):
        if not self.errors:
            return {}
        fields = {"error_stage": next(iter(self.errors))}
        if len(self.errors) > 1:
            fields["error_stages"] = list(self.errors)
        return fields


def evaluate(
    reference_path: Path,
    bundle_path: Path,
    *,
    bindings_path: Path | None = None,
    narrative_path: Path | None = None,
    root: Path | None = None,
) -> Evaluation:
    outcome = Evaluation()
    try:
        reference = read_json(reference_path, root=root)
        validate_reference(reference)
        outcome.expected_rows = len(reference["rows"])
    except (ValueError, RecursionError) as exc:
        outcome.errors["reference"] = str(exc)
        if narrative_path is None:
            return outcome
        reference = None

    try:
        bundle = read_json(bundle_path, root=root)
    except (ValueError, RecursionError) as exc:
        outcome.errors["bundle"] = str(exc)
        return outcome

    if reference is not None:
        stage = "comparison"
        try:
            if bindings_path is None:
                graph = _Bundle(bundle)
            else:
                stage = "bindings"
                manifest = read_json(bindings_path, root=root)
                graph = _bound_graph(reference, bundle, manifest)
                stage = "comparison"
            outcome.findings.extend(_check_graph(reference, graph))
            outcome.row_checked = True
        except (ValueError, RecursionError) as exc:
            outcome.errors[stage] = str(exc)

    # The section review is separately anchored in the original, unmodified
    # document. Its result remains meaningful without the reference or bindings.
    if narrative_path is not None:
        try:
            review = read_json(narrative_path, root=root)
            outcome.findings.extend(check_narrative(bundle, review))
            outcome.narrative_checked = True
        except (ValueError, RecursionError) as exc:
            outcome.errors["narrative_review"] = str(exc)
    return outcome

"""Compare one pre-reviewed R4 document section with its exact UTF-8 XHTML.

The independent manifest is specific to a report and one coded, top-level
section. The digest covers the JSON string after decoding, before XHTML
parsing, so paragraph boundaries, entity spelling and whitespace count. Only
a div containing plain paragraphs is supported. No rendering, external resource
resolution or natural-language interpretation takes place.
"""

from hashlib import sha256
import re
import unicodedata
from xml.etree import ElementTree

from .checker import _Bundle, _identifiers, _matches, _object, _objects, _SCHEME, _text

_XHTML = "{http://www.w3.org/1999/xhtml}"


def _review_pair(obj, key):
    if (
        not isinstance(obj, dict)
        or obj.keys() != {"system", key}
        or not _matches(_SCHEME, obj["system"])
        or not _text(obj[key])
    ):
        raise ValueError("invalid narrative review identity or section coding")


def _fingerprint(narrative):
    narrative = _object(narrative, "Composition.section.text")
    div = narrative.get("div")
    if (
        narrative.get("status") not in ("generated", "additional", "extensions")
        or not isinstance(div, str)
        or "<!" in div
        or "<?" in div
    ):
        raise ValueError("unsupported or invalid section narrative")
    try:
        root = ElementTree.fromstring(div)
        original_bytes = div.encode("utf-8")
    except (ElementTree.ParseError, UnicodeError) as exc:
        raise ValueError("invalid narrative XHTML") from exc
    if (
        root.tag != _XHTML + "div"
        or root.attrib
        or not len(root)
        or (root.text or "").strip()
    ):
        raise ValueError("only a plain XHTML div containing paragraphs is supported")
    for paragraph in root:
        if (
            paragraph.tag != _XHTML + "p"
            or paragraph.attrib
            or len(paragraph)
            or not (paragraph.text or "").strip()
            or (paragraph.tail or "").strip()
        ):
            raise ValueError("only plain XHTML narrative paragraphs are supported")
        if any(unicodedata.category(ch) == "Cf" for ch in paragraph.text):
            raise ValueError("invisible format controls in narrative are unsupported")
    return sha256(original_bytes).hexdigest()


def check_narrative(bundle: dict, review: dict) -> list[dict]:
    """Return a scoped finding, or raise ValueError for an unsupported comparison."""
    if (
        not isinstance(review, dict)
        or review.keys()
        != {"schema_version", "report_identifier", "section_coding", "xhtml_sha256"}
        or type(review["schema_version"]) is not int
        or review["schema_version"] != 1
    ):
        raise ValueError("invalid narrative review schema")
    report_id = review["report_identifier"]
    code = review["section_coding"]
    _review_pair(report_id, "value")
    _review_pair(code, "code")
    digest = review["xhtml_sha256"]
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("invalid narrative review SHA-256")

    graph = _Bundle(bundle)
    if bundle["type"] != "document":
        raise ValueError("narrative review requires a document Bundle")
    if any(
        link.get("relation") == "stylesheet"
        for link in _objects(bundle.get("link", []), "Bundle.link")
    ):
        raise ValueError("document stylesheet rendering requires a separate review")
    compositions = [r for r in graph.resources if r["resourceType"] == "Composition"]
    reports = [r for r in graph.resources if r["resourceType"] == "DiagnosticReport"]
    if len(compositions) != 1 or len(reports) != 1:
        raise ValueError(
            "narrative review requires one Composition and one DiagnosticReport"
        )
    composition = compositions[0]
    comp_id = _object(composition.get("identifier", {}), "Composition.identifier")
    if any(comp_id.get(key) != val for key, val in report_id.items()):
        return [{"code": "narrative-report-changed", "field": "Composition.identifier"}]
    if _identifiers(reports[0], report_id["system"]) != [report_id["value"]]:
        return [
            {"code": "narrative-report-changed", "field": "DiagnosticReport.identifier"}
        ]

    matches = []
    for section in _objects(composition.get("section", []), "Composition.section"):
        if "section" in section:
            raise ValueError("nested sections are unsupported by this review format")
        concept = _object(section.get("code", {}), "Composition.section.code")
        codes = [
            c.get("code")
            for c in _objects(concept.get("coding", []), "section.code.coding")
            if c.get("system") == code["system"]
        ]
        if code["code"] in codes:
            if len(codes) != 1:
                raise ValueError("ambiguous coding for the reviewed section")
            matches.append(section)
    if not matches:
        return [
            {"code": "narrative-section-missing", "field": "Composition.section.code"}
        ]
    if len(matches) != 1:
        raise ValueError("the narrative review matches multiple sections")
    section = matches[0]
    if "focus" in section:
        subject, problem = graph.subject(0)
        if (
            problem
            or subject is None
            or graph.resolve(
                section["focus"],
                0,
                graph.resources[subject]["resourceType"],
                "Composition.section.focus",
            )
            != subject
        ):
            raise ValueError(
                "a different or unresolved section focus needs a separate narrative review"
            )
    if "text" not in section:
        return [{"code": "narrative-missing", "field": "Composition.section.text"}]
    if _fingerprint(section["text"]) != digest:
        return [{"code": "narrative-changed", "field": "Composition.section.text.div"}]
    return []

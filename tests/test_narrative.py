"""The expected text here was transcribed separately from the source rows."""

import copy
import hashlib
from pathlib import Path
import unittest

from medextract_fhir_lab.jsonio import loads
from medextract_fhir_lab.narrative import check_narrative


ROOT = Path(__file__).resolve().parents[1]
APPROVED = (
    '<div xmlns="http://www.w3.org/1999/xhtml">'
    "<p>r01 Proteína C reactiva ≤0,10 mg/L (status and specimen unknown). "
    "r02 Glucosa 92 mg/dL (final, serum).</p></div>"
)


class NarrativeTests(unittest.TestCase):
    def setUp(self):
        self.doc = loads((ROOT / "examples/eu-teaching.document.json").read_bytes())
        self.review = loads((ROOT / "examples/eu-narrative-review.json").read_bytes())
        self.comp = self.doc["entry"][0]["resource"]
        self.section = self.comp["section"][0]
        self.text = self.section["text"]

    def codes(self):
        return [f["code"] for f in check_narrative(self.doc, self.review)]

    def test_attested_source_digest_and_unmodified_document(self):
        self.assertEqual(
            hashlib.sha256(APPROVED.encode("utf-8")).hexdigest(),
            self.review["xhtml_sha256"],
        )
        self.assertEqual(self.codes(), [])

    def test_changed_value_and_lost_comparator_only_in_human_view(self):
        for old, new in [("≤", ""), ("≤0,10", "9,99"), ("final, serum", "unknown")]:
            with self.subTest(old=old):
                self.text["div"] = APPROVED.replace(old, new)
                findings = check_narrative(self.doc, self.review)
                self.assertEqual(
                    findings,
                    [
                        {
                            "code": "narrative-changed",
                            "field": "Composition.section.text.div",
                        }
                    ],
                )

    def test_reformatting_and_changed_paragraph_boundaries_are_detectable(self):
        for changed in [
            APPROVED.replace("≤", "&#8804;"),
            APPROVED.replace(". r02", ".</p><p>r02"),
            APPROVED.replace("<p>", "\n<p>"),
        ]:
            self.text["div"] = changed
            self.assertEqual(self.codes(), ["narrative-changed"])

    def test_reordered_distinct_sections_and_reordered_noncomposition_entries(self):
        self.comp["section"].insert(
            0, {"code": {"coding": [{"system": "urn:other", "code": "26436-6"}]}}
        )
        self.doc["entry"][1:] = reversed(self.doc["entry"][1:])
        self.assertEqual(self.codes(), [])

    def test_missing_substitution_ambiguous_or_nested_section(self):
        self.section["code"]["coding"][0]["system"] = "urn:other"
        self.assertEqual(self.codes(), ["narrative-section-missing"])
        self.section["code"]["coding"][0]["system"] = self.review["section_coding"][
            "system"
        ]
        self.comp["section"].append(copy.deepcopy(self.section))
        with self.assertRaises(ValueError):
            self.codes()
        self.comp["section"].pop()
        self.section["section"] = [copy.deepcopy(self.section)]
        with self.assertRaises(ValueError):
            self.codes()

    def test_reject_conflicting_section_codings_in_the_selected_system(self):
        self.section["code"]["coding"].append(
            dict(self.review["section_coding"], code="other")
        )
        with self.assertRaises(ValueError):
            self.codes()

    def test_signed_off_report_identity_is_required_on_both_resources(self):
        for field in ["value", "system"]:
            original = self.comp["identifier"][field]
            self.comp["identifier"][field] = "OTHER"
            self.assertEqual(self.codes(), ["narrative-report-changed"])
            self.comp["identifier"][field] = original
        r = next(
            e["resource"]
            for e in self.doc["entry"]
            if e["resource"]["resourceType"] == "DiagnosticReport"
        )
        del r["identifier"]
        self.assertEqual(self.codes(), ["narrative-report-changed"])

    def test_missing_narrative_and_empty_status_cannot_pass(self):
        del self.section["text"]
        self.assertEqual(self.codes(), ["narrative-missing"])
        self.section["text"] = {"status": "empty", "div": APPROVED}
        with self.assertRaises(ValueError):
            self.codes()

    def test_markup_style_direction_controls_and_malformed_text_unsupported(self):
        for replacement in [
            '<p class="hidden">',
            '<p style="display:none">',
            '<p dir="rtl">',
            '<p><img src="https://example.org/x"/>',
            '<p><a href="#row">x</a>',
            "<p><script/>",
            "<p><i/>",
            "<p><!--extra-->",
            "<p><?read a?>",
            "<p>\u202e",
            "<p>&#x202e;",
            "<p>\u200b",
            "<p>&bad;",
            "<p><div>",
            '<p xmlns="urn:other">',
        ]:
            self.text["div"] = APPROVED.replace("<p>", replacement)
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                self.codes()

    def test_document_stylesheet_needs_its_own_display_review(self):
        for url in ["Binary/stylesheet", "https://example.org/layout.css"]:
            self.doc["link"] = [{"relation": "stylesheet", "url": url}]
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.codes()
        self.doc["link"] = [{"relation": "self", "url": "urn:example:fixture"}]
        self.assertEqual(self.codes(), [])

    def test_prefix_doctype_and_encoding_declarations_unsupported(self):
        for prefix in ["<!DOCTYPE div>", '<?xml version="1.0"?>']:
            self.text["div"] = prefix + APPROVED
            with self.assertRaises(ValueError):
                self.codes()

    def test_no_second_composition_no_collections_no_partial_reviews(self):
        self.doc["type"] = "collection"
        with self.assertRaises(ValueError):
            self.codes()
        self.doc["type"] = "document"
        self.doc["entry"].append(copy.deepcopy(self.doc["entry"][0]))
        with self.assertRaises(ValueError):
            self.codes()
        self.doc["entry"].pop()
        for change in [
            {"schema_version": True},
            {"xhtml_sha256": "abc"},
            {"unreviewed": True},
            {"report_identifier": {"system": [], "value": "x"}},
            {"section_coding": {"code": 3}},
        ]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                check_narrative(self.doc, dict(self.review, **change))

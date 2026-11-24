"""Compare attested synthetic lab rows with direct laboratory results in an R4 Bundle."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from .result_value import (
    check_primitive_metadata,
    compare_result,
    read_result,
    validate_source_result,
)

LOINC = "http://loinc.org"
_RESULT_SUBJECTS = {"Patient", "Group", "Device", "Location"}
_SUBJECT_TYPES = {
    "DiagnosticReport": _RESULT_SUBJECTS,
    "Observation": _RESULT_SUBJECTS,
    "Specimen": _RESULT_SUBJECTS | {"Substance"},
}
# Concrete resource types from https://hl7.org/fhir/R4/codesystem-resource-types.json.
# A capitalized vendor path segment alone does not establish a FHIR REST identity.
_R4_TYPES = frozenset(
    """
Account ActivityDefinition AdverseEvent AllergyIntolerance Appointment
AppointmentResponse AuditEvent Basic Binary BiologicallyDerivedProduct BodyStructure
Bundle CapabilityStatement CarePlan CareTeam CatalogEntry ChargeItem
ChargeItemDefinition Claim ClaimResponse ClinicalImpression CodeSystem Communication
CommunicationRequest CompartmentDefinition Composition ConceptMap Condition Consent
Contract Coverage CoverageEligibilityRequest CoverageEligibilityResponse DetectedIssue
Device DeviceDefinition DeviceMetric DeviceRequest DeviceUseStatement DiagnosticReport
DocumentManifest DocumentReference EffectEvidenceSynthesis Encounter Endpoint
EnrollmentRequest EnrollmentResponse EpisodeOfCare EventDefinition Evidence
EvidenceVariable ExampleScenario ExplanationOfBenefit FamilyMemberHistory Flag Goal
GraphDefinition Group GuidanceResponse HealthcareService ImagingStudy Immunization
ImmunizationEvaluation ImmunizationRecommendation ImplementationGuide InsurancePlan
Invoice Library Linkage List Location Measure MeasureReport Media Medication
MedicationAdministration MedicationDispense MedicationKnowledge MedicationRequest
MedicationStatement MedicinalProduct MedicinalProductAuthorization
MedicinalProductContraindication MedicinalProductIndication MedicinalProductIngredient
MedicinalProductInteraction MedicinalProductManufactured MedicinalProductPackaged
MedicinalProductPharmaceutical MedicinalProductUndesirableEffect MessageDefinition
MessageHeader MolecularSequence NamingSystem NutritionOrder Observation
ObservationDefinition OperationDefinition OperationOutcome Organization
OrganizationAffiliation Parameters Patient PaymentNotice PaymentReconciliation Person
PlanDefinition Practitioner PractitionerRole Procedure Provenance Questionnaire
QuestionnaireResponse RelatedPerson RequestGroup ResearchDefinition
ResearchElementDefinition ResearchStudy ResearchSubject RiskAssessment
RiskEvidenceSynthesis Schedule SearchParameter ServiceRequest Slot Specimen
SpecimenDefinition StructureDefinition StructureMap Subscription Substance
SubstanceNucleicAcid SubstancePolymer SubstanceProtein SubstanceReferenceInformation
SubstanceSourceMaterial SubstanceSpecification SupplyDelivery SupplyRequest Task
TerminologyCapabilities TestReport TestScript ValueSet VerificationResult VisionPrescription
""".split()
)
_REST_TARGET = re.compile(r"(?:^|/)([A-Z][A-Za-z0-9]*)/([A-Za-z0-9.-]{1,64})\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SCHEME = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*:\S+\Z")
_STATUSES = {
    "registered",
    "preliminary",
    "final",
    "amended",
    "corrected",
    "cancelled",
    "entered-in-error",
    "unknown",
}


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and value.strip() == value


def _matches(pattern, value):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _split_address(address):
    try:
        return urlsplit(address)
    except ValueError:
        # The parser can include the submitted host in its error message.
        raise ValueError("invalid resource address") from None


def _rest_identity(parsed):
    if parsed.scheme in ("http", "https") and not parsed.hostname:
        raise ValueError("an HTTP(S) resource address requires a host")
    if parsed.scheme not in ("", "http", "https") or parsed.query or parsed.fragment:
        return None
    match = _REST_TARGET.search(parsed.path)
    if match and match[1] in _R4_TYPES:
        return match.groups()
    return None


def _object(value, path):
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    return value


def _objects(value, path):
    if not isinstance(value, list):
        raise ValueError(f"{path} must be an array")
    for item in value:
        yield _object(item, path)


def validate_reference(reference: dict) -> None:
    """Validate the source contract, independently of the candidate."""
    _object(reference, "reference")
    if type(reference.get("schema_version")) is not int or reference[
        "schema_version"
    ] not in (1, 2):
        raise ValueError("reference.schema_version must be 1 or 2")
    if not _matches(_IDENTIFIER, reference.get("report_id")):
        raise ValueError("invalid reference.report_id")
    if not _matches(_SCHEME, reference.get("identifier_system")):
        raise ValueError("invalid reference.identifier_system")
    if reference.keys() != {"schema_version", "report_id", "identifier_system", "rows"}:
        raise ValueError("unsupported fields in reference")
    seen = set()
    for row in _objects(reference.get("rows"), "reference.rows"):
        validate_source_result(row, reference["schema_version"])
        key = row["id"]
        if not _matches(_IDENTIFIER, key) or key in seen:
            raise ValueError("source row identifiers must be valid and unique")
        seen.add(key)
        if not _text(row["loinc"]):
            raise ValueError("source LOINC must be a nonempty string")
        status = row["status"]
        if status is not None and (not _text(status) or status not in _STATUSES):
            raise ValueError("unsupported source Observation status")
        specimen = row["specimen"]
        if specimen is not None:
            _object(specimen, "source specimen")
            if specimen.keys() != {"system", "code"}:
                raise ValueError("source specimen requires exactly system and code")
            if not _matches(_SCHEME, specimen.get("system")) or not _text(
                specimen.get("code")
            ):
                raise ValueError("source specimen requires a coding system and code")
    if not seen:
        raise ValueError("reference.rows must be nonempty")


def _unsupported_modifiers(node):
    if isinstance(node, dict):
        if (
            "modifierExtension" in node
            or "implicitRules" in node
            or "_implicitRules" in node
        ):
            raise ValueError(
                "modifierExtension and implicitRules require separate interpretation"
            )
        for item in node.values():
            _unsupported_modifiers(item)
    elif isinstance(node, list):
        for item in node:
            _unsupported_modifiers(item)


def _literal(ref, path):
    text = _object(ref, path).get("reference")
    if not _text(text) or text.startswith("#") or "/_history/" in text:
        raise ValueError(f"{path} requires an unversioned literal reference")
    return text


class _Bundle:
    """Index bundle-local identities; ambiguous addresses cannot be compared."""

    def __init__(self, bundle):
        _object(bundle, "Bundle")
        if bundle.get("resourceType") != "Bundle" or bundle.get("type") not in (
            "collection",
            "document",
        ):
            raise ValueError("expected a collection or document Bundle")
        self.bundle_type = bundle["type"]
        _unsupported_modifiers(bundle)
        self.resources = []
        self.addresses = {}
        self.rest_bases = {}
        for index, entry in enumerate(_objects(bundle.get("entry"), "Bundle.entry")):
            resource = _object(entry.get("resource"), "Bundle.entry.resource")
            kind, rid = resource.get("resourceType"), resource.get("id")
            if not _text(kind):
                raise ValueError("bundle entry needs a resourceType")
            if "contained" in resource:
                raise ValueError("contained resources are unsupported")
            aliases = []
            url = entry.get("fullUrl")
            http_url = isinstance(url, str) and url[:8].lower().startswith(
                ("http:", "https:")
            )
            if "id" in resource:
                if not _text(rid):
                    raise ValueError("invalid bundle entry resource id")
                if not http_url:
                    aliases.append(f"{kind}/{rid}")
            if "fullUrl" in entry:
                url = entry["fullUrl"]
                if not _matches(_SCHEME, url) or "/_history/" in url:
                    raise ValueError("invalid bundle entry fullUrl")
                aliases.append(url)
                if http_url:
                    identity = _rest_identity(_split_address(url))
                    if identity and (
                        identity[0] != kind or (rid and identity[1] != rid)
                    ):
                        raise ValueError(
                            "bundle entry fullUrl disagrees with its resource type or id"
                        )
                    self.rest_bases[index] = url.rsplit("/", 2)[0] if identity else None
            if not aliases:
                raise ValueError("bundle entry requires a resource id or fullUrl")
            for alias in aliases:
                other = self.addresses.setdefault(alias, index)
                if other != index:
                    raise ValueError("ambiguous bundle resource identity")
            self.resources.append(resource)
        if self.bundle_type == "document" and (
            not self.resources or self.resources[0]["resourceType"] != "Composition"
        ):
            raise ValueError("a document Bundle must begin with Composition")

    def address(self, ref, owner, path):
        address = _literal(ref, path)
        if _matches(_SCHEME, address):
            return address
        if not re.fullmatch(r"[A-Z][A-Za-z0-9]*/[A-Za-z0-9.-]{1,64}", address):
            raise ValueError(f"{path} uses an unsupported relative reference")
        if owner in self.rest_bases:
            base = self.rest_bases[owner]
            if base is None:
                raise ValueError("relative reference requires a RESTful base")
            return base + "/" + address
        # The offline fixture convention also permits a unique bundle-local Type/id.
        return address

    def resolve(self, ref, owner, kind, path):
        address = self.address(ref, owner, path)
        index = self.addresses.get(address)
        if index is None or self.resources[index]["resourceType"] != kind:
            return None
        declared = ref.get("type")
        if declared is not None and declared != kind:
            return None
        return index

    def subject(self, index):
        """Return an identity for graph comparison and any problem verifying its reference."""
        resource = self.resources[index]
        if "subject" not in resource:
            return None, None
        ref = resource["subject"]
        address = self.address(ref, index, "subject")
        target = self.addresses.get(address)
        declared = ref.get("type")
        if "type" in ref and not _text(declared):
            raise ValueError("subject.type must name its expected resource type")
        parsed = _split_address(address)
        rest = _rest_identity(parsed)
        types = {declared} if declared is not None else set()
        if rest:
            types.add(rest[0])
        if target is not None:
            types.add(self.resources[target]["resourceType"])
        owner = resource["resourceType"]
        allowed = _SUBJECT_TYPES.get(owner)  # Composition.subject permits any resource.
        if len(types) > 1 or (allowed is not None and not types <= allowed):
            return None, "subject-type-mismatch"
        if target is not None:
            return target, None
        # A document must carry its Composition subject. A missing urn or fixture-local
        # Type/id has no external resolution path. Keep the token for comparison only.
        if owner == "Composition" or parsed.scheme not in ("http", "https"):
            return address, "unresolved-reference"
        if not types:
            raise ValueError(
                "external subject reference requires a discernible resource type"
            )
        return address, None


def _identifiers(resource, system):
    result = []
    for ident in _objects(resource.get("identifier", []), "identifier"):
        if ident.get("system") == system:
            if not _text(ident.get("value")):
                raise ValueError("comparison-system identifier lacks a value")
            result.append(ident["value"])
    return result


def _coded_field(element, system, expected, changed, field, add):
    concept = _object(element, field)
    codes = set()
    for coding in _objects(concept.get("coding", []), field + ".coding"):
        if coding.get("system") == system:
            if not _text(coding.get("code")):
                raise ValueError(f"{field} contains a coding without a code")
            codes.add(coding["code"])
    if len(codes) > 1:
        add("ambiguous-code", field)
    elif expected not in codes:
        add(changed, field)


def _read_observation(observation, version):
    if "focus" in observation:
        raise ValueError("Observation.focus requires a separate subject contract")
    check_primitive_metadata(observation, "status", "Observation")
    if "status" in observation:
        status = observation["status"]
        if not isinstance(status, str) or status not in _STATUSES:
            raise ValueError("invalid R4 Observation.status")
    if "hasMember" in observation or "component" in observation:
        raise ValueError("only direct results are supported")
    return read_result(observation, version)


def _check_row(row, observation, quantity, result, specimen, add):
    _coded_field(
        observation.get("code", {}), LOINC, row["loinc"], "loinc-changed", "code", add
    )
    compare_result(row, quantity, result, add)
    if observation.get("status") != (row["status"] or "unknown"):
        add("status-changed", "status")
    expected = row["specimen"]
    if expected is None:
        if "specimen" in observation:
            add("specimen-changed", "specimen")
    elif specimen is None:
        add("specimen-changed", "specimen")
    else:
        _coded_field(
            specimen.get("type", {}),
            expected["system"],
            expected["code"],
            "specimen-changed",
            "specimen",
            add,
        )


def check(reference: dict, bundle: dict) -> list[dict]:
    """Return ordered discrepancies. Load JSON with parse_float=Decimal for exactness.

    ValueError signals a malformed source or unsupported graph. The comparison
    checks the source fields and their direct relationships. Report status and
    independently sourced patient identity are outside the row comparison.
    """
    validate_reference(reference)
    return _check_graph(reference, _Bundle(bundle))


def _check_graph(reference, graph):
    """Compare a validated reference with an indexed, read-only candidate."""
    reports = [
        i
        for i, r in enumerate(graph.resources)
        if r["resourceType"] == "DiagnosticReport"
    ]
    if len(reports) != 1:
        raise ValueError("expected exactly one DiagnosticReport")
    report_index = reports[0]
    report = graph.resources[report_index]
    rows = {row["id"]: row for row in reference["rows"]}
    system = reference["identifier_system"]
    findings = []

    def add(code, field, row_id=None):
        item = {"code": code, "field": field}
        if row_id is not None:
            item["row_id"] = row_id
        findings.append(item)

    identifiers = _identifiers(report, system + "/reports")
    if len(identifiers) > 1:
        add("ambiguous-identifier", "DiagnosticReport.identifier")
    elif identifiers != [reference["report_id"]]:
        add("report-id-changed", "DiagnosticReport.identifier")

    result_identifiers = {}

    def targets(field, kind):
        linked = set()
        path = "DiagnosticReport." + field
        for ref in _objects(report.get(field, []), path):
            index = graph.resolve(ref, report_index, kind, path)
            if index is None:
                add("unresolved-reference", path)
            elif index in linked:
                add("duplicate-reference", path)
            else:
                linked.add(index)
                if field == "result" and "identifier" in ref:
                    identifier = _object(ref["identifier"], path + ".identifier")
                    if identifier.get("system") == system:
                        if not _text(identifier.get("value")):
                            raise ValueError(
                                "comparison-system result reference lacks an identifier value"
                            )
                        result_identifiers[index] = identifier["value"]
        return linked

    results = targets("result", "Observation")
    declared_specimens = targets("specimen", "Specimen")

    def subject_of(index, field, row_id=None):
        identity, problem = graph.subject(index)
        if problem is not None:
            add(problem, field, row_id)
        return identity

    report_subject = subject_of(report_index, "DiagnosticReport.subject")
    if graph.bundle_type == "document":
        composition_subject = subject_of(0, "Composition.subject")
        if report_subject is None:
            report_subject = composition_subject
        elif composition_subject is not None and composition_subject != report_subject:
            add("subject-conflict", "Composition.subject")
    observed_subjects = set()
    seen_rows, seen_specimens = set(), set()
    for index, obs in enumerate(graph.resources):
        if obs["resourceType"] != "Observation":
            continue
        quantity, result = _read_observation(obs, reference["schema_version"])
        identifiers = _identifiers(obs, system)
        row_id = (
            identifiers[0] if len(identifiers) == 1 and identifiers[0] in rows else None
        )
        if index not in results:
            add("unlinked-observation", "DiagnosticReport.result", row_id)
            continue
        if (
            row_id is not None
            and index in result_identifiers
            and result_identifiers[index] != row_id
        ):
            add(
                "reference-identifier-conflict",
                "DiagnosticReport.result.identifier",
                row_id,
            )
        subject = subject_of(index, "subject", row_id)
        if subject is not None:
            observed_subjects.add(subject)
            if report_subject is not None and subject != report_subject:
                add("subject-conflict", "subject", row_id)
        specimen = None
        if "specimen" in obs:
            target = graph.resolve(
                obs["specimen"], index, "Specimen", "Observation.specimen"
            )
            if target is None:
                add("unresolved-reference", "specimen", row_id)
            else:
                seen_specimens.add(target)
                specimen = graph.resources[target]
                check_primitive_metadata(specimen, "status", "Specimen")
                if "status" in specimen:
                    status = specimen["status"]
                    if status == "entered-in-error":
                        add("invalidated-specimen", "specimen.status", row_id)
                    elif status not in ("available", "unavailable", "unsatisfactory"):
                        raise ValueError("invalid R4 Specimen.status")
                specimen_subject = subject_of(target, "specimen.subject", row_id)
                if specimen_subject is not None:
                    if subject is None:
                        observed_subjects.add(specimen_subject)
                    if any(
                        s is not None and s != specimen_subject
                        for s in (subject, report_subject)
                    ):
                        add("subject-conflict", "specimen.subject", row_id)
        if len(identifiers) > 1:
            add("ambiguous-identifier", "identifier")
        elif not identifiers:
            add("missing-identifier", "identifier")
        elif row_id is None:
            add("extra-row", "identifier")
        else:
            if row_id in seen_rows:
                add("duplicate-row", "identifier", row_id)
            seen_rows.add(row_id)

            def row_finding(code, field):
                add(code, field, row_id)

            _check_row(rows[row_id], obs, quantity, result, specimen, row_finding)
    if report_subject is None and len(observed_subjects) > 1:
        add("subject-conflict", "subject")
    for _ in declared_specimens - seen_specimens:
        add("unlinked-specimen", "DiagnosticReport.specimen")
    for missing in rows.keys() - seen_rows:
        add("missing-row", "DiagnosticReport.result", missing)
    return sorted(findings, key=lambda f: (f.get("row_id", ""), f["code"], f["field"]))

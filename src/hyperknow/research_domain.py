import hashlib
from typing import Literal

from pydantic import Field, computed_field, model_validator

from .domain import Schema


class ResearchQuestion(Schema):
    id: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$",
                    description="Stable identifier used to connect this question to research tool calls and findings.")
    question: str = Field(min_length=1, max_length=800)
    priority: Literal["high", "medium", "low"]
    status: Literal["answered", "partial", "unresolved"]
    claim_ids: list[str] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def valid_claims(self):
        if len(set(self.claim_ids)) != len(self.claim_ids):
            raise ValueError("research question claim IDs must be unique")
        if (self.status == "answered" and not self.claim_ids
                or self.status == "unresolved" and self.claim_ids):
            raise ValueError("question status must match its linked claims")
        return self


class EvidenceReference(Schema):
    source_id: str = Field(min_length=1, max_length=80,
                           description="Identifier of a page read during this research run.")
    quote: str = Field(min_length=8, max_length=1500,
                       description="A verbatim, continuous passage from the saved page text.")
    relation: Literal["supports", "contradicts"] = Field(
        description="Whether the quoted passage supports or contradicts the finding.")


class ResearchFinding(Schema):
    claim_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    question_ids: list[str] = Field(min_length=1, max_length=6,
                                    description="Research questions this finding answers or informs.")
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2000)
    evidence: list[EvidenceReference] = Field(
        min_length=1, max_length=2,
        description="Verbatim evidence passages supporting or contradicting this finding.")

    @model_validator(mode="before")
    @classmethod
    def ignore_source_ids(cls, data):
        if isinstance(data, dict):
            return {key: value for key, value in data.items() if key != "source_ids"}
        return data

    @computed_field
    @property
    def source_ids(self) -> list[str]:
        return list(dict.fromkeys(item.source_id for item in self.evidence))

    @model_validator(mode="after")
    def unique_references(self):
        if len(set(self.question_ids)) != len(self.question_ids):
            raise ValueError("claim question IDs must be unique")
        if len(self.source_ids) > 8:
            raise ValueError("claims may cite at most eight distinct sources")
        return self


class ResearchReport(Schema):
    summary: str = Field(min_length=1, max_length=4000)
    questions: list[ResearchQuestion] = Field(min_length=1, max_length=6)
    findings: list[ResearchFinding] = Field(min_length=1, max_length=6)
    suggested_sequence: list[str] = Field(min_length=1, max_length=12)
    limitations: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="before")
    @classmethod
    def derive_question_claim_ids(cls, data):
        if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
            return data
        linked: dict[str, list[str]] = {}
        for finding in data.get("findings", []):
            if not isinstance(finding, dict):
                continue
            claim_id = finding.get("claim_id")
            question_ids = finding.get("question_ids")
            if not isinstance(claim_id, str) or not isinstance(question_ids, list):
                continue
            for question_id in question_ids:
                if isinstance(question_id, str):
                    linked.setdefault(question_id, []).append(claim_id)
        normalized = dict(data)
        normalized["questions"] = [
            {**question, "claim_ids": list(dict.fromkeys(linked.get(question.get("id"), [])))}
            if isinstance(question, dict) and isinstance(question.get("id"), str) else question
            for question in data["questions"]
        ]
        return normalized

    @model_validator(mode="after")
    def valid_links(self):
        questions = {item.id: item for item in self.questions}
        findings = {item.claim_id: item for item in self.findings}
        if len(questions) != len(self.questions) or len(findings) != len(self.findings):
            raise ValueError("research question and claim IDs must be unique")
        for finding in self.findings:
            if not set(finding.question_ids) <= questions.keys():
                raise ValueError("claims may reference only declared research questions")
        for question in self.questions:
            if not set(question.claim_ids) <= findings.keys():
                raise ValueError("research questions may reference only declared claims")
            linked = {finding.claim_id for finding in self.findings
                      if question.id in finding.question_ids}
            if linked != set(question.claim_ids):
                raise ValueError("question and claim links must be reciprocal")
        if any(question.status != "answered" for question in self.questions) and not self.limitations:
            raise ValueError("partial or unresolved questions require a stated limitation")
        if any(not value.strip() for value in self.suggested_sequence + self.limitations):
            raise ValueError("sequence and limitation items cannot be empty")
        return self


def validate_report(report: ResearchReport, research: dict) -> ResearchReport:
    sources = {source["source_id"]: source for source in research["sources"]}
    searched = any(step["tool"] == "web_search" and step["status"] == "ready"
                   for step in research["steps"])
    if not searched or not sources:
        raise ValueError("research requires an actual successful search and page read")
    question_ids = {question.id for question in report.questions}
    current_round = research.get("round", 1)
    missing_question_ids: set[str] = set()
    for step in research["steps"]:
        if step.get("research_round", 1) != current_round:
            continue
        arguments = step.get("arguments") or {}
        question_id = arguments.get("question_id") if isinstance(arguments, dict) else None
        if question_id is not None and question_id not in question_ids:
            missing_question_ids.add(question_id)
    if missing_question_ids:
        raise ValueError("tool calls may reference only declared research questions; "
                         "missing question IDs: " + ", ".join(sorted(missing_question_ids)))
    for finding in report.findings:
        if not set(finding.source_ids) <= sources.keys():
            raise ValueError("claims may cite only sources read in this run")
        for reference in finding.evidence:
            source_text = sources[reference.source_id].get("text", "")
            if reference.quote not in source_text:
                raise ValueError("evidence quote must occur verbatim in the saved source excerpt")
    return report


def build_evidence_bundle(report: ResearchReport, sources: list[dict]) -> list[dict]:
    by_id = {source["source_id"]: source for source in sources}
    result = []
    for finding in report.findings:
        for reference in finding.evidence:
            source = by_id[reference.source_id]
            start = source["text"].find(reference.quote)
            if start < 0:
                raise ValueError("evidence quote must occur verbatim in the saved source excerpt")
            end = start + len(reference.quote)
            identity = "\x00".join((finding.claim_id, reference.source_id, str(start),
                                     str(end), reference.relation))
            result.append({
                "evidence_id": "evidence_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
                "claim_id": finding.claim_id,
                "question_ids": finding.question_ids,
                "source_id": reference.source_id,
                "relation": reference.relation,
                "quote": reference.quote,
                "start_char": start,
                "end_char": end,
                "url": source["url"],
                "title": source["title"],
                "fetched_at": source["fetched_at"],
                "content_sha256": source["content_sha256"],
                "provider": source.get("provider", "page"),
                "content_mode": source.get("content_mode", "page_text"),
            })
    return result


def build_claim_context(claims: list[dict], evidence: list[dict], claim_ids: list[str]) -> list[dict]:
    if len(set(claim_ids)) != len(claim_ids):
        raise ValueError("selected research claim IDs must be unique")
    by_claim = {claim["claim_id"]: claim for claim in claims}
    evidence_by_claim: dict[str, list[dict]] = {}
    for item in evidence:
        evidence_by_claim.setdefault(item["claim_id"], []).append(item)
    unknown = set(claim_ids) - by_claim.keys()
    if unknown:
        raise ValueError("selected research claims must belong to this course")
    result = []
    for claim_id in claim_ids:
        passages = evidence_by_claim.get(claim_id, [])
        if not passages:
            raise ValueError("selected research claims must have verified evidence")
        claim = by_claim[claim_id]
        result.append({"claim_id": claim_id, "question_ids": claim["question_ids"],
                       "title": claim["title"], "summary": claim["summary"],
                       "evidence": [{key: item[key] for key in (
                           "evidence_id", "source_id", "relation", "quote", "start_char", "end_char",
                           "url", "title", "fetched_at", "content_sha256", "provider", "content_mode")}
                           for item in passages]})
    return result

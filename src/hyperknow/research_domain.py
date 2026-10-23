"""Typed research deliverables; references must resolve to actually read pages."""

from pydantic import Field, model_validator

from .domain import Schema


class ResearchFinding(Schema):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2000)
    source_ids: list[str] = Field(min_length=1, max_length=8)


class ResearchReport(Schema):
    summary: str = Field(min_length=1, max_length=4000)
    findings: list[ResearchFinding] = Field(min_length=1, max_length=12)
    suggested_sequence: list[str] = Field(min_length=1, max_length=12)
    limitations: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def nonempty_items(self):
        if any(not value.strip() for value in self.suggested_sequence + self.limitations):
            raise ValueError("sequence and limitation items cannot be empty")
        for finding in self.findings:
            if len(set(finding.source_ids)) != len(finding.source_ids):
                raise ValueError("finding source IDs must be unique")
        return self


def validate_report(report: ResearchReport, research: dict) -> ResearchReport:
    read_ids = {source["source_id"] for source in research["sources"]}
    searched = any(step["tool"] == "web_search" and step["status"] == "ready"
                   for step in research["steps"])
    if not searched or not read_ids:
        raise ValueError("research requires an actual successful search and page read")
    if any(not set(finding.source_ids) <= read_ids for finding in report.findings):
        raise ValueError("findings may cite only source IDs of successfully read pages")
    return report

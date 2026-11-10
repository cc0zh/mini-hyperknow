from copy import deepcopy
import json
import unittest

from pydantic import ValidationError

from hyperknow.blueprint_domain import (BlueprintDraft, UnitExpansionDraft,
                                        validate_expansion)
from hyperknow.model_output import validate_model_output
from hyperknow.research_domain import (ResearchReport, build_evidence_bundle,
                                       validate_report)
from test_blueprint import blueprint_input, expansion_input
from test_research import page_input, read_step, report_input, search_step


class ModelOutputTests(unittest.TestCase):
    def test_empty_lecture_extras_preserve_teaching_and_claims(self):
        unit = blueprint_input()["units"][1]
        canonical = expansion_input(unit["exam_goal"])
        canonical["lectures"].append(deepcopy(canonical["lectures"][0]))
        expected = UnitExpansionDraft.model_validate(canonical).model_dump()
        for extras in ({"project_stages": []}, {"sessions_note": None},
                       {"project_stages": [], "sessions_note": None}):
            raw = deepcopy(canonical)
            for lecture in raw["lectures"]:
                lecture.update(deepcopy(extras))
            before = deepcopy(raw)
            response = json.dumps(raw, ensure_ascii=False)
            with self.subTest(extras=extras):
                draft = validate_model_output(UnitExpansionDraft, raw)
                self.assertIs(validate_expansion(draft, unit, 2), draft)
                self.assertEqual(draft.model_dump(), expected)
                self.assertEqual(raw, before)
                self.assertEqual(json.dumps(raw, ensure_ascii=False), response)

    def test_empty_finding_note_preserves_report_and_exact_evidence(self):
        canonical = report_input()
        expected = ResearchReport.model_validate(canonical)
        research = {"steps": [search_step(), read_step()],
                    "sources": [{**page_input(), "source_id": "source_test"}], "report": None}
        raw = deepcopy(canonical)
        raw["findings"][0]["evidence_note"] = ""
        before, research_before = deepcopy(raw), deepcopy(research)

        report = validate_model_output(ResearchReport, raw)

        self.assertIs(validate_report(report, research), report)
        self.assertEqual(report.model_dump(), expected.model_dump())
        self.assertEqual(report.findings[0].source_ids, ["source_test"])
        self.assertEqual(report.findings[0].evidence[0].quote, "await suspends a coroutine")
        self.assertEqual(build_evidence_bundle(report, research["sources"]),
                         build_evidence_bundle(expected, research["sources"]))
        self.assertEqual(raw, before)
        self.assertEqual(research, research_before)

    def test_only_exact_empty_extras_are_removed_at_schema_error_locations(self):
        expected = ResearchReport.model_validate(report_input()).model_dump()
        for empty in (None, "", [], {}):
            raw = report_input()
            raw["report_note"] = deepcopy(empty)
            raw["questions"][0]["question_note"] = deepcopy(empty)
            raw["findings"][0]["evidence_note"] = deepcopy(empty)
            raw["findings"][0]["evidence"][0]["quote_note"] = deepcopy(empty)
            before = deepcopy(raw)
            with self.subTest(empty=empty):
                self.assertEqual(validate_model_output(ResearchReport, raw).model_dump(), expected)
                self.assertEqual(raw, before)

    def test_valid_output_matches_existing_schema_behavior(self):
        report = report_input()
        report["summary"] = "  协程学习  "
        report["findings"][0]["source_ids"] = ["source_unread"]
        for schema, raw in ((BlueprintDraft, blueprint_input()),
                            (UnitExpansionDraft, expansion_input()),
                            (ResearchReport, report)):
            before = deepcopy(raw)
            with self.subTest(schema=schema.__name__):
                self.assertEqual(validate_model_output(schema, raw).model_dump(),
                                 schema.model_validate(raw).model_dump())
                self.assertEqual(raw, before)

    def test_nonempty_or_falsy_nonempty_extras_remain_forbidden(self):
        for value in (0, False, " ", "\t\n", "说明", [None], {"note": None}):
            for schema, raw, target in (
                (UnitExpansionDraft, expansion_input(), "lecture"),
                (ResearchReport, report_input(), "finding"),
            ):
                parent = raw["lectures"][0] if target == "lecture" else raw["findings"][0]
                parent["unknown"] = value
                before = deepcopy(raw)
                with self.subTest(schema=schema.__name__, value=value):
                    with self.assertRaises(ValidationError) as raised:
                        validate_model_output(schema, raw)
                    self.assertEqual(raised.exception.errors()[0]["type"], "extra_forbidden")
                    self.assertEqual(raw, before)

    def test_known_required_type_and_empty_session_errors_remain_rejected(self):
        missing = expansion_input()
        del missing["lectures"][0]["title"]
        wrong_type = expansion_input()
        wrong_type["lectures"] = {}
        empty_sessions = expansion_input()
        empty_sessions["lectures"][0]["sessions"] = []
        for raw in (missing, wrong_type, empty_sessions):
            before = deepcopy(raw)
            with self.subTest(raw=raw):
                with self.assertRaises(ValidationError) as strict:
                    UnitExpansionDraft.model_validate(raw)
                with self.assertRaises(ValidationError) as raised:
                    validate_model_output(UnitExpansionDraft, raw)
                self.assertEqual(raised.exception.errors(), strict.exception.errors())
                self.assertEqual(raw, before)

    def test_mixed_errors_preserve_original_error_details_and_input(self):
        missing = expansion_input()
        del missing["lectures"][0]["title"]
        nonempty_extra = expansion_input()
        nonempty_extra["lectures"][0]["unknown"] = "must not discard"
        empty_sessions = expansion_input()
        empty_sessions["lectures"][0]["sessions"] = []
        for raw in (missing, nonempty_extra, empty_sessions):
            raw["lectures"][0]["sessions_note"] = None
            before = deepcopy(raw)
            with self.subTest(raw=raw):
                with self.assertRaises(ValidationError) as strict:
                    UnitExpansionDraft.model_validate(raw)
                with self.assertRaises(ValidationError) as raised:
                    validate_model_output(UnitExpansionDraft, raw)
                self.assertEqual(raised.exception.errors(), strict.exception.errors())
                self.assertEqual(raw, before)

    def test_report_source_and_verbatim_evidence_rules_still_reject(self):
        research = {"steps": [search_step(), read_step()],
                    "sources": [{**page_input(), "source_id": "source_test"}], "report": None}
        for field, value in (("source_id", "source_unknown"),
                             ("quote", "a paraphrase of the saved page")):
            raw = report_input()
            raw["findings"][0]["evidence_note"] = ""
            raw["findings"][0]["evidence"][0][field] = value
            with self.subTest(field=field):
                report = validate_model_output(ResearchReport, raw)
                with self.assertRaises(ValueError):
                    validate_report(report, research)

    def test_report_link_rules_are_rechecked_after_removing_empty_extras(self):
        raw = report_input()
        raw["findings"][0]["evidence_note"] = ""
        raw["findings"].append(deepcopy(raw["findings"][0]))
        before = deepcopy(raw)
        with self.assertRaises(ValidationError) as raised:
            validate_model_output(ResearchReport, raw)
        self.assertIn("value_error", [error["type"] for error in raised.exception.errors()])
        self.assertEqual(raw, before)

    def test_project_exam_claim_depth_and_session_budget_rules_still_reject(self):
        for case in ("project", "exam", "unapproved_exam", "claim", "exam_claim", "depth", "budget"):
            unit = blueprint_input()["units"][1]
            raw = expansion_input(unit["exam_goal"])
            raw["lectures"][0]["project_stages"] = []
            budget = 1
            if case == "project":
                unit["project_keys"] = ["approved_project"]
            elif case == "exam":
                raw["exams"][0]["goal"] = "没有批准的考核"
            elif case == "unapproved_exam":
                unit["exam_goal"] = ""
            elif case == "claim":
                raw["lectures"][0]["sessions"][0]["research_claim_ids"] = ["claim_unknown"]
            elif case == "exam_claim":
                raw["exams"][0]["research_claim_ids"] = ["claim_unknown"]
            elif case == "depth":
                raw["lectures"][0]["sessions"][0]["depths"] = []
            else:
                budget = 0
            with self.subTest(case=case):
                draft = validate_model_output(UnitExpansionDraft, raw)
                with self.assertRaises(ValueError):
                    validate_expansion(draft, unit, budget)

    def test_schema_text_and_collection_budgets_still_reject(self):
        for schema, raw in ((ResearchReport, {**report_input(), "summary": "x" * 4001}),
                            (ResearchReport, {**report_input(), "findings": report_input()["findings"] * 13}),
                            (UnitExpansionDraft, {**expansion_input(),
                                                  "lectures": expansion_input()["lectures"] * 5})):
            raw["empty_note"] = ""
            with self.subTest(schema=schema.__name__):
                with self.assertRaises(ValidationError):
                    validate_model_output(schema, raw)


if __name__ == "__main__":
    unittest.main()

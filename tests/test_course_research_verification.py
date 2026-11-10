"""Exhaust the stated finite research inputs against the production functions."""

from copy import deepcopy
import hashlib
from itertools import product
import unittest

from hyperknow.research_domain import ResearchReport, build_evidence_bundle, validate_report


def source_snapshot(source_id, text):
    return {
        "source_id": source_id, "text": text,
        "url": "https://example.invalid/" + source_id, "title": "Source " + source_id,
        "fetched_at": "2026-11-10T00:00:0" + ("1" if source_id == "s1" else "2") + "Z",
        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "provider": "page" if source_id == "s1" else "exa",
        "content_mode": "page_text" if source_id == "s1" else "excerpt",
    }


def report_input(declared, references):
    return {
        "summary": "Finite research audit input",
        "questions": [{"id": question_id, "question": "Check " + question_id,
                       "priority": "high",
                       "status": "answered" if question_id == "q1" else "unresolved"}
                      for question_id in declared],
        "findings": [{"claim_id": "c1", "question_ids": ["q1"],
                      "title": "One finite claim", "summary": "A claim with saved evidence",
                      "evidence": references}],
        "suggested_sequence": ["Read the saved evidence"],
        "limitations": ["Unanswered questions remain unresolved."],
    }


def search_step():
    return {"tool": "web_search", "status": "ready", "research_round": 1,
            "arguments": {"question_id": "q1"}}


class ResearchQuestionClosureTests(unittest.TestCase):
    def test_finite_question_event_space(self):
        quote = "Tools  execute calls"
        events = [
            {"tool": tool, "status": status, "research_round": event_round,
             "arguments": {} if question_id is None else {"question_id": question_id}}
            for tool, status, event_round, question_id in product(
                ("web_search", "read_webpage"), ("ready", "failed"), (1, 2),
                (None, "q1", "q2", "unknown"))
        ]
        cases = 0
        for declared, current_round in product((("q1",), ("q1", "q2")), (1, 2)):
            report = ResearchReport.model_validate(report_input(declared, [
                {"source_id": "s1", "quote": quote, "relation": "supports"}]))
            report_before = report.model_dump()
            for length in range(3):
                for indexes in product(range(len(events)), repeat=length):
                    extra = [deepcopy(events[index]) for index in indexes]
                    research = {"round": current_round, "steps": [search_step(), *extra],
                                "sources": [source_snapshot("s1", quote)]}
                    before = deepcopy(research)
                    required = {event["arguments"]["question_id"] for event in extra
                                if event["research_round"] == current_round
                                and "question_id" in event["arguments"]}
                    missing = required - set(declared)
                    context = (declared, current_round, extra)
                    try:
                        result = validate_report(report, research)
                    except ValueError as error:
                        self.assertTrue(missing, context)
                        for question_id in missing:
                            self.assertIn(question_id, str(error), context)
                    else:
                        self.assertFalse(missing, context)
                        self.assertIs(result, report, context)
                    self.assertEqual(research, before, context)
                    self.assertEqual(report.model_dump(), report_before, context)
                    cases += 1
        self.assertEqual(cases, 4228)
        print("RESEARCH_QUESTION_SPACE_PASS cases=" + str(cases), flush=True)


class ResearchEvidenceBindingTests(unittest.TestCase):
    def test_finite_source_quote_space(self):
        corpora = ("Tools  execute calls", "课程工具  由应用执行", "🌱结果行\n工具  调用返回")
        citations = (("s1",), ("s2",), ("unknown",), ("s1", "s2"), ("s1", "s1"))
        cases = 0
        accepted_cases = 0
        for base_quote in corpora:
            texts = ("prefix " + base_quote + " suffix",
                     base_quote + " middle " + base_quote,
                     "prefix " + base_quote.replace("  ", " ") + " suffix",
                     "A saved source without the requested quotation.")
            for source_texts, presence, quote, cited in product(
                    product(texts, repeat=2), product((False, True), repeat=2),
                    (base_quote, base_quote.replace("  ", " "), base_quote + " fabricated"), citations):
                sources = [source_snapshot(source_id, text)
                           for source_id, text, present in zip(("s1", "s2"), source_texts, presence)
                           if present]
                source_by_id = {source["source_id"]: source for source in sources}
                for relations in product(("supports", "contradicts"), repeat=len(cited)):
                    references = [{"source_id": source_id, "quote": quote, "relation": relation}
                                  for source_id, relation in zip(cited, relations)]
                    report = ResearchReport.model_validate(report_input(("q1",), references))
                    research = {"round": 1, "steps": [search_step()], "sources": sources}
                    before = deepcopy(research)
                    report_before = report.model_dump()
                    expected = all(source_id in source_by_id
                                   and quote in source_by_id[source_id]["text"] for source_id in cited)
                    context = (base_quote, source_texts, presence, quote, cited, relations)
                    try:
                        validate_report(report, research)
                    except ValueError:
                        accepted = False
                    else:
                        accepted = True
                    self.assertEqual(accepted, expected, context)
                    if accepted:
                        bundle = build_evidence_bundle(report, sources)
                        self.assertEqual(len(bundle), len(references), context)
                        for entry, reference in zip(bundle, references):
                            source = source_by_id[reference["source_id"]]
                            self.assertEqual(source["text"][entry["start_char"]:entry["end_char"]], quote, context)
                            self.assertEqual(entry["claim_id"], "c1", context)
                            self.assertEqual(entry["question_ids"], ["q1"], context)
                            for key in ("source_id", "quote", "relation"):
                                self.assertEqual(entry[key], reference[key], context)
                            for key in ("url", "title", "fetched_at", "content_sha256", "provider", "content_mode"):
                                self.assertEqual(entry[key], source[key], context)
                        accepted_cases += 1
                    self.assertEqual(research, before, context)
                    self.assertEqual(report.model_dump(), report_before, context)
                    cases += 1
        self.assertEqual(cases, 8064)
        self.assertGreater(accepted_cases, 0)
        self.assertLess(accepted_cases, cases)
        print("RESEARCH_EVIDENCE_SPACE_PASS cases=" + str(cases) + " accepted=" + str(accepted_cases), flush=True)


if __name__ == "__main__":
    unittest.main()

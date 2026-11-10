import ast
from pathlib import Path
import re
import unittest


PROMPT_DIR = Path(__file__).parents[1] / "src" / "hyperknow" / "prompts"
POLICY_PATTERNS = (
    ("schema version", re.compile(r"schema_version", re.IGNORECASE)),
    ("field identifier", re.compile(r"\b[a-zA-Z][a-zA-Z0-9]*_[a-zA-Z0-9_]+\b")),
    ("numeric limit", re.compile(r"\b(?:max|maximum|limit)\s*[0-9]+|(?:最多|至少|不超过|上限|至多)[0-9]+|[0-9]+(?:次|个|项|轮|步|页|栏)")),
    ("protocol assignment", re.compile(r"\b[a-z][a-z_]+\s*=\s*[A-Za-z_-]+", re.IGNORECASE)),
    ("enum protocol", re.compile(r"\b(?:opening|explain|example|check|summary|answered|partial|unresolved)\s*[/=]")),
    ("tool loop mechanics", re.compile(r"tool_call_id|assistant工具调用消息|工具循环|追加带匹配", re.IGNORECASE)),
)


def scan_prompt_literals(source: str, path: str = "<prompt>") -> list[str]:
    tree = ast.parse(source, filename=path)
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        for policy, pattern in POLICY_PATTERNS:
            match = pattern.search(node.value)
            if match:
                violations.append(f"{path}:{node.lineno}: {policy}: {match.group(0)}")
    return violations


class PromptPolicyTests(unittest.TestCase):
    def test_accepts_plain_teaching_intent(self):
        source = 'INSTRUCTION = "Use a concrete example to explain why the result changes."'
        self.assertEqual(scan_prompt_literals(source), [])

    def test_reports_machine_shaped_guidance_with_location_and_reason(self):
        source = 'INSTRUCTION = "schema_version必须是2，maximum 6; opening/explain; some_field"'
        violations = scan_prompt_literals(source, "sample.py")
        self.assertTrue(violations)
        self.assertTrue(all("sample.py:1:" in item for item in violations), violations)
        self.assertTrue(any("schema version" in item for item in violations), violations)
        self.assertTrue(any("field identifier" in item for item in violations), violations)

    def test_prompt_package_contains_no_machine_shaped_instruction_literals(self):
        violations = []
        for path in sorted(PROMPT_DIR.glob("*.py")):
            violations.extend(scan_prompt_literals(path.read_text(encoding="utf-8"), str(path)))
        self.assertEqual(violations, [], violations)


if __name__ == "__main__":
    unittest.main()

## [2026-11-10 11:02] | Task: Separate pedagogy from prompt contracts

### 🤖 Execution Context

- **Agent ID**: Codex implementation agent
- **Base Model**: OpenAI GPT-5
- **Runtime**: EnsoCode

### 📥 User Query

> Keep teaching prompts focused on pedagogy and domain intent. Move output shape and numeric limits to schemas, tool descriptions, and code; add a static prompt regression test and align research report bounds with the existing prompt contract.

### 🛠 Changes Overview

**Scope:** Prompt package, research report validation, prompt and research tests.

**Key Actions:**

- Added an AST-based test scanner for machine-shaped rules embedded in prompt string literals and removed prompt-text assertions from lesson structure tests.
- Reworded prompt instructions to describe teaching and evidence behavior without field names, enum protocol labels, exact schema caps, schema versions, or model tool-loop mechanics.
- Centralized search, page-read, and model-turn budgets in the research runtime while preserving their values.
- Aligned research report limits to six questions, six findings, and two evidence items per finding, with boundary tests.
- Documented the division between prompt pedagogy, generated schemas, tool descriptions, and code-enforced rules.
- Removed remaining tests that asserted exact continuation and clarification prompt wording; their state and flow behavior remains covered by model and storage tests.

### 🧠 Design Intent (Why)

Generated JSON Schema and tool definitions already carry machine contracts, while code enforces permissions and cross-field rules. Keeping those details out of teaching prose reduces duplicated and drifting instructions; a static scan guards the boundary without a production prompt framework.

### 📁 Files Modified

- `src/hyperknow/prompts/assistance.py`
- `src/hyperknow/prompts/classroom.py`
- `src/hyperknow/prompts/course.py`
- `src/hyperknow/prompts/quiz.py`
- `src/hyperknow/prompts/research.py`
- `src/hyperknow/prompts/README.md`
- `src/hyperknow/research.py`
- `src/hyperknow/research_domain.py`
- `tests/test_prompt_policy.py`
- `tests/test_lesson_structure.py`
- `tests/test_assistance_domain.py`
- `tests/test_clarification_flow.py`
- `tests/test_research.py`
- `tests/test_research_runtime.py`

### ✅ Verification

- **Commands or checks:** `uv run --frozen python -m unittest discover -s tests -p 'test_*.py' -q` (470 passed); `node scripts/ci.cjs` passed documentation, repository, and action checks, then reported one tooling test failure because existing workspace documents link to `.agents/skills` files that the packaged template excludes; `git diff --check` passed.
- **Known risks or follow-up:** The research report bounds intentionally tighten accepted reports to the current prompt contract. Search/read/model-turn runtime budgets are unchanged. The tooling test failure comes from pre-existing uncommitted documentation and skill changes outside this task.
- **Pre-commit checks:** Re-ran all 470 Python tests, document checks, repository hygiene checks, GitHub Action pinning checks, and changed JavaScript syntax checks successfully. The full CI command still fails the packaged-template document-link test. Both `scripts/verify_state_machines.py --validate-only` and `scripts/verify_course_research.py --validate-only` exit 2 because the recorded `src/hyperknow/research_domain.py` digest predates these schema changes. Formal coverage needs review before its digest advances. No digest was refreshed to bypass that gate.
- **Captured evidence:** The staged whitespace check also reports trailing spaces and extra final blank lines in the original classroom evidence Markdown. Those captures remain unchanged rather than silently editing recorded source text.

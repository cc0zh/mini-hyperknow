'use strict';

const projectRoots = new Set([
  'AGENTS.md', 'CLAUDE.md', 'README.md', 'CONTRIBUTING.md', 'LICENSE', 'SECURITY.md',
  'CODEOWNERS', '.gitignore', '.gitattributes', '.editorconfig', '.markdownlint.json',
  'package.json', 'pyproject.toml', '.env.example', 'src', 'docs', 'scripts', 'tests', '.github',
]);

// Repository maintenance material is not part of a new project's starting state.
function projectPath(relative) {
  const parts = relative.split('/');
  if (!projectRoots.has(parts[0])) return false;
  if (relative === 'docs/nono-profiles' || relative.startsWith('docs/nono-profiles/')) return false;
  if (relative === 'docs/code-understanding/01-EventStream-讲解版.html') return false;
  const retained = {
    'docs/histories': ['template.md'],
    'docs/learnings': ['README.md', 'WRITING_GUIDE.md'],
    'docs/exec-runs': ['README.md', 'templates'],
    'docs/exec-plans/active': ['.gitkeep'],
    'docs/exec-plans/completed': ['.gitkeep'],
  };
  for (const [directory, names] of Object.entries(retained)) {
    if (relative.startsWith(`${directory}/`)) {
      return names.includes(relative.slice(directory.length + 1).split('/')[0]);
    }
  }
  return true;
}

const documentOverrides = {
  'README.md': 'README.md',
  'docs/QUALITY_SCORE.md': 'QUALITY_SCORE.md',
  'docs/releases/feature-release-notes.md': 'feature-release-notes.md',
};

module.exports = { projectPath, documentOverrides };

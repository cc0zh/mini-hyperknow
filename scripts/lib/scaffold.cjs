'use strict';

const { fs, path, excluded, stat } = require('./common.cjs');

const projectRoots = new Set([
  'AGENTS.md', 'CLAUDE.md', 'README.md', 'CONTRIBUTING.md', 'LICENSE', 'SECURITY.md',
  'CODEOWNERS', '.gitignore', '.gitattributes', '.editorconfig', '.markdownlint.json',
  'package.json', 'pyproject.toml', 'uv.lock', '.python-version', '.env.example', 'src', 'web', 'docs', 'scripts', 'tests', '.github',
]);

// Repository maintenance material is not part of a new project's starting state.
function projectPath(relative, linked = new Set()) {
  if ([...linked].some((target) => target === relative || target.startsWith(`${relative}/`))) return true;
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

// Preserve linked knowledge while still omitting unreferenced maintenance history.
function linkedDocuments(root) {
  const linked = new Set();
  const pending = [];
  function visit(directory) {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      if (excluded(entry.name)) continue;
      const file = path.join(directory, entry.name);
      const relative = path.relative(root, file).split(path.sep).join('/');
      if (!projectPath(relative)) continue;
      if (entry.isDirectory()) visit(file);
      else if (entry.isFile() && file.endsWith('.md')) pending.push(file);
    }
  }
  visit(root);
  const seen = new Set();
  while (pending.length) {
    const file = pending.pop();
    if (seen.has(file)) continue;
    seen.add(file);
    for (const match of fs.readFileSync(file, 'utf8').matchAll(/\[[^\]]*\]\(([^)\s]+)\)/g)) {
      const href = match[1].split('#')[0];
      if (!href || /^(?:[a-z]+:|\/)/i.test(href)) continue;
      const target = path.resolve(path.dirname(file), href);
      const relative = path.relative(root, target).split(path.sep).join('/');
      if (!relative.startsWith('docs/') || !target.endsWith('.md')) continue;
      const info = stat(target);
      if (!info?.isFile() || info.isSymbolicLink()) continue;
      const resolved = path.relative(fs.realpathSync(root), fs.realpathSync(target));
      if (resolved.startsWith('..') || path.isAbsolute(resolved)) continue;
      linked.add(relative);
      pending.push(target);
    }
  }
  return linked;
}

module.exports = { projectPath, documentOverrides, linkedDocuments };

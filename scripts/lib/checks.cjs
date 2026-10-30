'use strict';

const { fs, path, stat, filesIn } = require('./common.cjs');

const requiredDocs = [
  'AGENTS.md', 'CLAUDE.md', 'README.md', 'CONTRIBUTING.md', 'SECURITY.md',
  'docs/REPO_COLLAB_GUIDE.md',
  'docs/HISTORY_GUIDE.md', 'docs/PLANS_GUIDE.md', 'docs/ARCHITECTURE.md',
  'docs/CICD.md', 'docs/WINDOWS.md', 'docs/PRODUCT_SENSE.md', 'docs/QUALITY_SCORE.md',
  'docs/RELIABILITY.md', 'docs/SECURITY.md', 'docs/SUPPLY_CHAIN_SECURITY.md',
  'docs/CODING_BEHAVIOR.md', 'docs/coding-standards/README.md',
  'docs/code-understanding/README.md', 'docs/exec-plans/README.md',
  'docs/exec-runs/README.md', 'docs/learnings/README.md',
  'docs/learnings/WRITING_GUIDE.md', 'docs/releases/README.md',
  'docs/design-docs/core-beliefs.md', 'docs/design-docs/index.md',
  'docs/references/README.md',
  'docs/exec-plans/templates/execution-plan.md', 'docs/exec-plans/tech-debt-tracker.md',
  'docs/histories/template.md', 'docs/releases/feature-release-notes.md',
];

function checkDocs(root) {
  const errors = requiredDocs.filter((file) => !stat(path.join(root, file))?.isFile())
    .map((file) => `缺少必要文件: ${file}`);
  for (const dir of ['docs/exec-plans/active', 'docs/exec-plans/completed', 'docs/histories']) {
    if (!stat(path.join(root, dir))?.isDirectory()) errors.push(`缺少必要目录: ${dir}`);
  }
  const agents = path.join(root, 'AGENTS.md');
  if (stat(agents)?.isFile() && !fs.readFileSync(agents, 'utf8').includes('docs/')) {
    errors.push('AGENTS.md 应明确指向 docs/，说明它是仓库知识的正式来源');
  }
  errors.push(...checkMarkdownLinks(root));
  if (errors.length) throw new Error(errors.join('\n'));
}

function headingSlugs(file) {
  const slugs = new Set();
  let inFence = false;
  for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    if (/^\s*(```|~~~)/.test(line)) {
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;
    const match = line.match(/^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$/);
    if (!match) continue;
    const base = match[1].replace(/[`*_~]/g, '').trim()
      .toLowerCase().replace(/[^\p{L}\p{N}\s_-]/gu, '').replace(/[\s_-]+/g, '-');
    let slug = base;
    let suffix = 1;
    while (slugs.has(slug)) slug = `${base}-${suffix++}`;
    slugs.add(slug);
  }
  return slugs;
}

function checkMarkdownLinks(root) {
  const errors = [];
  for (const file of filesIn(root).filter((entry) => entry.endsWith('.md'))) {
    const lines = fs.readFileSync(file, 'utf8').split(/\r?\n/);
    let inFence = false;
    lines.forEach((line, index) => {
      if (/^\s*(```|~~~)/.test(line)) {
        inFence = !inFence;
        return;
      }
      if (inFence) return;
      for (const match of line.matchAll(/\[[^\]]*\]\((<[^>]+>|[^)\s]+)(?:\s+["'][^)]*["'])?\)/g)) {
        let target = match[1];
        if (target.startsWith('<')) target = target.slice(1, -1);
        if (/^(?:[a-z][a-z\d+.-]*:|\/\/)/i.test(target)) continue;
        const hash = target.indexOf('#');
        const fragment = hash === -1 ? '' : decodeURIComponent(target.slice(hash + 1));
        const relative = hash === -1 ? target : target.slice(0, hash);
        const destination = relative
          ? path.resolve(path.dirname(file), decodeURIComponent(relative))
          : file;
        const privateRoots = ['data', 'eval_result'].map((name) => path.join(root, name));
        if (privateRoots.some((directory) => destination === directory || destination.startsWith(`${directory}${path.sep}`))) {
          errors.push(`${path.relative(root, file)}:${index + 1}: 私有运行工件请使用代码路径，不建立Markdown链接: ${target}`);
          continue;
        }
        if (!stat(destination)) {
          errors.push(`${path.relative(root, file)}:${index + 1}: 本地文档链接不存在: ${target}`);
          continue;
        }
        if (fragment && stat(destination)?.isFile() && destination.endsWith('.md')
          && !headingSlugs(destination).has(fragment.toLowerCase())) {
          errors.push(`${path.relative(root, file)}:${index + 1}: 文档锚点不存在: ${target}`);
        }
      }
    });
  }
  return errors;
}

function checkRepo(root) {
  const missing = ['.gitignore', '.editorconfig', 'CODEOWNERS']
    .filter((file) => !stat(path.join(root, file))?.isFile());
  if (missing.length) throw new Error(`缺少必要文件: ${missing.join(', ')}`);
}

function checkActions(root) {
  const errors = [];
  const workflows = filesIn(path.join(root, '.github/workflows')).filter((file) => /\.ya?ml$/.test(file));
  if (!workflows.length) throw new Error('没有找到 GitHub Actions workflow');
  for (const file of workflows) {
    fs.readFileSync(file, 'utf8').split(/\r?\n/).forEach((line, index) => {
      const match = line.match(/^\s*(?:-\s*)?uses:\s*["']?([^\s"'#]+)/);
      if (!match) return;
      const reference = match[1];
      if (reference.startsWith('./')) return;
      const pinned = reference.startsWith('docker://')
        ? /@sha256:[0-9a-f]{64}$/.test(reference)
        : /^[^@]+@[0-9a-f]{40}$/.test(reference);
      if (!pinned) errors.push(`${path.relative(root, file)}:${index + 1}: ${reference}`);
    });
  }
  if (errors.length) throw new Error(`发现未固定 SHA 的 GitHub Action 引用:\n${errors.join('\n')}`);
}

module.exports = { checkDocs, checkRepo, checkActions, requiredDocs };

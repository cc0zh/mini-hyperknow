'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const os = require('node:os');
const { spawnSync } = require('node:child_process');
const { fs, path, repoRoot, filesIn, run } = require('../scripts/lib/common.cjs');
const { createProject } = require('../scripts/create-project.cjs');
const { packageRelease } = require('../scripts/release-package.cjs');
const { checkDocs, checkRepo, checkActions, requiredDocs } = require('../scripts/lib/checks.cjs');

function temp(t) {
  const parent = fs.realpathSync(os.tmpdir());
  const dir = fs.mkdtempSync(path.join(parent, 'harness-test-'));
  t.after(() => {
    assert.equal(path.dirname(dir), parent);
    assert.ok(path.basename(dir).startsWith('harness-test-'));
    fs.rmSync(dir, { recursive: true, force: true });
  });
  return dir;
}

function write(root, file, content) {
  const target = path.join(root, file);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, content);
}

function fixture(t) {
  const dir = temp(t);
  const source = path.join(dir, '模板 source');
  write(source, 'package.json', '{"name":"starter-template"}\n');
  write(source, 'README.md', '# starter-template\n');
  write(source, '.env.example', 'OPENAI_MODEL=example\n');
  write(source, '.env', 'OPENAI_API_KEY=secret\n');
  write(source, 'docs/guide.md', 'starter-template\n');
  write(source, '.editorconfig', 'root = true\n');
  write(source, 'docs/image.bin', Buffer.from([0, 255, 1, 128]));
  return { dir, source };
}

function docsFixture(t) {
  const dir = temp(t);
  for (const file of requiredDocs) write(dir, file, `# ${path.basename(file, '.md')}\n`);
  for (const directory of ['docs/exec-plans/active', 'docs/exec-plans/completed', 'docs/histories']) {
    fs.mkdirSync(path.join(dir, directory), { recursive: true });
  }
  return dir;
}

test('new project supports spaces, Unicode and literal replacement characters', (t) => {
  const { dir, source } = fixture(t);
  const name = "示例 app $& 'test'";
  const result = createProject([name, dir], source);
  assert.equal(fs.readFileSync(path.join(result.target, 'README.md'), 'utf8'), `# ${name}\n`);
  assert.equal(JSON.parse(fs.readFileSync(path.join(result.target, 'package.json'), 'utf8')).name, name);
  assert.deepEqual(fs.readFileSync(path.join(result.target, 'docs/image.bin')), Buffer.from([0, 255, 1, 128]));
  assert.ok(fs.existsSync(path.join(result.target, '.git')));
  assert.ok(fs.existsSync(path.join(result.target, '.editorconfig')));
  assert.equal(fs.readFileSync(path.join(result.target, '.env.example'), 'utf8'), 'OPENAI_MODEL=example\n');
  assert.equal(fs.existsSync(path.join(result.target, '.env')), false);
});

test('--into preserves existing bytes, Git metadata and conflicting paths; is idempotent', (t) => {
  const { dir, source } = fixture(t);
  const target = path.join(dir, 'existing');
  write(target, 'README.md', 'keep starter-template\r\n');
  write(target, 'package.json', '{"name":"existing","type":"module"}\n');
  write(target, '.git', 'gitdir: keep-this-marker\n');
  write(target, 'docs', 'this file blocks the template directory');
  const original = fs.readFileSync(path.join(target, 'README.md'));
  createProject(['--into', target], source);
  assert.deepEqual(fs.readFileSync(path.join(target, 'README.md')), original);
  assert.equal(JSON.parse(fs.readFileSync(path.join(target, 'package.json'))).type, 'module');
  assert.equal(fs.readFileSync(path.join(target, '.git'), 'utf8'), 'gitdir: keep-this-marker\n');
  assert.equal(fs.readFileSync(path.join(target, 'docs'), 'utf8'), 'this file blocks the template directory');
  assert.equal(createProject(['--into'], source, target).copied, 0);
});

test('template-local caches and credentials are excluded at every depth', (t) => {
  const { dir, source } = fixture(t);
  for (const name of ['.git', 'node_modules', 'dist', '.tmp', '.venv', 'coverage', '__pycache__']) {
    write(source, `${name}/secret`, 'do not copy');
  }
  write(source, 'src/generated.pyc', 'do not copy');
  write(source, '.env', 'TOKEN=private');
  write(source, '.env.production.local', 'TOKEN=private');
  write(source, 'docs/node_modules/secret', 'do not copy');
  const { target } = createProject(['clean', dir], source);
  for (const name of ['node_modules', 'dist', '.tmp', '.venv', 'coverage', '__pycache__', '.env', '.env.production.local', 'docs/node_modules', 'src/generated.pyc']) {
    assert.equal(fs.existsSync(path.join(target, name)), false, name);
  }
  assert.equal(fs.existsSync(path.join(target, '.git/secret')), false);
});

test('--into replaces names only in new files and initializes a missing Git repository', (t) => {
  const { dir, source } = fixture(t);
  const target = path.join(dir, 'existing-app');
  write(target, 'README.md', 'keep starter-template');
  createProject(['--into', target], source);
  assert.equal(fs.readFileSync(path.join(target, 'README.md'), 'utf8'), 'keep starter-template');
  assert.equal(fs.readFileSync(path.join(target, 'docs/guide.md'), 'utf8'), 'existing-app\n');
  assert.ok(fs.existsSync(path.join(target, '.git')));
});

test('initialization and packaging share a clean payload without deleting source history', (t) => {
  const { dir, source } = fixture(t);
  const omitted = [
    'private-notes.txt', '.env.production',
    'public/demo.gif', 'docs/nono-profiles/profile.jsonc',
    'docs/histories/2026-09/old.md', 'docs/histories/undated.md',
    'docs/learnings/2026-09/note.md',
    'docs/exec-plans/active/current-task.md', 'docs/exec-plans/completed/old-task.md',
    'docs/exec-runs/old-task/execution-summary.md',
    'docs/code-understanding/01-EventStream-讲解版.html',
  ];
  for (const file of omitted) write(source, file, 'maintenance material');
  const retained = [
    'docs/histories/template.md', 'docs/learnings/README.md',
    'docs/learnings/WRITING_GUIDE.md', 'docs/exec-plans/active/.gitkeep',
    'docs/exec-plans/completed/.gitkeep', 'docs/exec-runs/templates/execution-summary.md',
  ];
  for (const file of retained) write(source, file, 'project skeleton');
  write(source, '.template/README.md', '# starter-template\nClean project\n');
  write(source, '.template/QUALITY_SCORE.md', '# Not evaluated\n');
  write(source, '.template/feature-release-notes.md', '# No releases\n');
  write(source, 'docs/QUALITY_SCORE.md', 'Maintainer score: B');
  write(source, 'docs/releases/feature-release-notes.md', 'Maintainer release history');
  const { target } = createProject(['starter-template', dir], source);
  packageRelease(source);
  const extracted = path.join(dir, 'extracted');
  fs.mkdirSync(extracted);
  run('tar', ['-xzf', path.join(source, 'dist/repo-metadata.tgz'), '-C', extracted]);
  for (const root of [target, extracted]) {
    for (const file of omitted) assert.equal(fs.existsSync(path.join(root, file)), false, file);
    for (const file of retained) assert.ok(fs.existsSync(path.join(root, file)), file);
    assert.equal(fs.existsSync(path.join(root, '.template')), false);
    assert.equal(fs.readFileSync(path.join(root, 'README.md'), 'utf8'), '# starter-template\nClean project\n');
    assert.equal(fs.readFileSync(path.join(root, 'docs/QUALITY_SCORE.md'), 'utf8'), '# Not evaluated\n');
    assert.equal(fs.readFileSync(path.join(root, 'docs/releases/feature-release-notes.md'), 'utf8'), '# No releases\n');
  }
  const snapshot = (root) => Object.fromEntries(filesIn(root).sort().map((file) => [
    path.relative(root, file), fs.readFileSync(file).toString('base64'),
  ]));
  assert.deepEqual(snapshot(target), snapshot(extracted));
  for (const file of omitted) assert.ok(fs.existsSync(path.join(source, file)), file);
});

test('--into document overrides preserve existing project content', (t) => {
  const { dir, source } = fixture(t);
  write(source, '.template/README.md', '# starter-template\nClean\n');
  write(source, '.template/QUALITY_SCORE.md', 'New project');
  write(source, 'docs/QUALITY_SCORE.md', 'Maintainer scores');
  const target = path.join(dir, 'existing');
  write(target, 'README.md', 'My README\r\n');
  write(target, 'docs/QUALITY_SCORE.md', 'My quality data');
  createProject(['--into', target], source);
  assert.equal(fs.readFileSync(path.join(target, 'README.md'), 'utf8'), 'My README\r\n');
  assert.equal(fs.readFileSync(path.join(target, 'docs/QUALITY_SCORE.md'), 'utf8'), 'My quality data');
});

test('document override directories cannot follow a junction outside the template', (t) => {
  const { dir, source } = fixture(t);
  const outside = path.join(dir, 'outside');
  write(outside, 'README.md', 'external contents');
  fs.symlinkSync(outside, path.join(source, '.template'), process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => createProject(['new', dir], source), /\.template 必须是普通目录/);
  assert.equal(fs.existsSync(path.join(dir, 'new')), false);
});

test('invalid names, extra arguments and existing targets fail without overwriting', (t) => {
  const { dir, source } = fixture(t);
  for (const name of ['../escape', '..', '.', 'CON', 'nul.txt', 'bad:name', 'trailing.', '--bad']) {
    assert.throws(() => createProject([name, dir], source));
  }
  assert.throws(() => createProject([], source));
  assert.throws(() => createProject(['x', dir, 'extra'], source));
  assert.throws(() => createProject(['--into', path.join(dir, 'missing')], source));
  write(dir, 'exists', 'preserve');
  assert.throws(() => createProject(['exists', dir], source));
  assert.equal(fs.readFileSync(path.join(dir, 'exists'), 'utf8'), 'preserve');
});

test('self, ancestor and descendant targets are rejected before writes', (t) => {
  const { dir, source } = fixture(t);
  for (const args of [['--into', source], ['--into', dir], ['nested', source]]) {
    assert.throws(() => createProject(args, source), /相互包含/);
  }
  assert.equal(fs.existsSync(path.join(source, 'nested')), false);
});

test('--into does not write through directory junctions', (t) => {
  const { dir, source } = fixture(t);
  const target = path.join(dir, 'existing');
  const outside = path.join(dir, 'outside');
  fs.mkdirSync(target);
  fs.mkdirSync(outside);
  fs.symlinkSync(outside, path.join(target, 'docs'), process.platform === 'win32' ? 'junction' : 'dir');
  createProject(['--into', target], source);
  assert.deepEqual(fs.readdirSync(outside), []);
});

test('source links fail before creating a target', (t) => {
  const { dir, source } = fixture(t);
  const outside = path.join(dir, 'outside');
  fs.mkdirSync(outside);
  fs.symlinkSync(outside, path.join(source, 'docs/linked'), process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => createProject(['new', dir], source), /符号链接/);
  assert.equal(fs.existsSync(path.join(dir, 'new')), false);
});

test('a junction alias cannot bypass template nesting protection', (t) => {
  const { dir, source } = fixture(t);
  const alias = path.join(dir, 'alias');
  fs.symlinkSync(source, alias, process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => createProject(['nested', alias], source), /相互包含/);
  assert.equal(fs.existsSync(path.join(source, 'nested')), false);
});

test('missing git reports a useful failure before creating project files', (t) => {
  const { dir } = fixture(t);
  const result = spawnSync(process.execPath, [path.join(repoRoot, 'scripts/create-project.cjs'), 'new', dir], {
    env: { ...process.env, PATH: '' }, encoding: 'utf8', windowsHide: true,
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /git/);
  assert.equal(fs.existsSync(path.join(dir, 'new')), false);
});

test('action checker reports CRLF/unpinned actions and accepts immutable/local references', (t) => {
  const dir = temp(t);
  const workflow = '.github/workflows/ci.yml';
  write(dir, workflow, `steps:\r\n  - uses: actions/checkout@${'a'.repeat(40)}\r\n  - uses: ./local\r\n  - uses: docker://image@sha256:${'b'.repeat(64)}\r\n`);
  checkActions(dir);
  write(dir, workflow, 'steps:\r\n  - uses: "actions/checkout@main"\r\n');
  assert.throws(() => checkActions(dir), /:2: actions\/checkout@main/);
  assert.throws(() => checkDocs(dir), /缺少必要文件/);
  assert.throws(() => checkRepo(dir), /缺少必要文件/);
});

test('document checker catches broken local links and anchors without parsing code examples', (t) => {
  const dir = docsFixture(t);
  write(dir, 'AGENTS.md', [
    '# Entry',
    '',
    '本仓库知识的正式来源是 docs/。',
    '[Architecture](docs/ARCHITECTURE.md#architecture)',
    '[Missing](docs/missing.md)',
    '[Missing anchor](docs/ARCHITECTURE.md#does-not-exist)',
    '',
    '```md',
    '[Example](docs/not-a-real-file.md)',
    '```',
  ].join('\n'));
  assert.throws(() => checkDocs(dir), (error) => {
    assert.match(error.message, /docs[\\/]missing\.md/);
    assert.match(error.message, /does-not-exist/);
    assert.doesNotMatch(error.message, /not-a-real-file/);
    return true;
  });
});

test('document checker accepts external links and same-document anchors', (t) => {
  const dir = docsFixture(t);
  write(dir, 'AGENTS.md', [
    '# Entry',
    '',
    'docs/ is the repository knowledge source.',
    '',
    '[External](https://example.com/docs#anything)',
    '[Same document](#entry)',
  ].join('\n'));
  assert.doesNotThrow(() => checkDocs(dir));
});

test('packaging preserves unrelated dist files and escapes manifest values', (t) => {
  const { source } = fixture(t);
  write(source, 'dist/keep.txt', 'preserve');
  const previous = process.env.GITHUB_REPOSITORY;
  process.env.GITHUB_REPOSITORY = 'owner/"quoted"';
  try { packageRelease(source); } finally {
    if (previous === undefined) delete process.env.GITHUB_REPOSITORY;
    else process.env.GITHUB_REPOSITORY = previous;
  }
  const manifest = JSON.parse(fs.readFileSync(path.join(source, 'dist/release-manifest.json'), 'utf8'));
  assert.equal(manifest.repository, 'owner/"quoted"');
  assert.equal(fs.readFileSync(path.join(source, 'dist/keep.txt'), 'utf8'), 'preserve');
  const entries = run('tar', ['-tzf', path.join(source, 'dist/repo-metadata.tgz')]);
  assert.match(entries, /README.md/);
  assert.doesNotMatch(entries, /dist\/|\.git\//);
  packageRelease(source);
  assert.equal(fs.readFileSync(path.join(source, 'dist/keep.txt'), 'utf8'), 'preserve');
});

test('missing tar leaves existing release output unchanged', (t) => {
  const { source } = fixture(t);
  write(source, 'dist/repo-metadata.tgz', 'old archive');
  const result = spawnSync(process.execPath, [
    '-e', 'require(process.argv[1]).packageRelease(process.argv[2])',
    path.join(repoRoot, 'scripts/release-package.cjs'), source,
  ], { env: { ...process.env, PATH: '' }, encoding: 'utf8', windowsHide: true });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /tar/);
  assert.equal(fs.readFileSync(path.join(source, 'dist/repo-metadata.tgz'), 'utf8'), 'old archive');
});

test('packaging refuses a directory occupying an artifact path', (t) => {
  const { source } = fixture(t);
  write(source, 'dist/repo-metadata.tgz/keep', 'preserve');
  assert.throws(() => packageRelease(source), /拒绝覆盖非普通文件/);
  assert.equal(fs.readFileSync(path.join(source, 'dist/repo-metadata.tgz/keep'), 'utf8'), 'preserve');
});

test('packaging rejects a dist junction without touching its destination', (t) => {
  const { dir, source } = fixture(t);
  const outside = path.join(dir, 'outside');
  fs.mkdirSync(outside);
  fs.symlinkSync(outside, path.join(source, 'dist'), process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => packageRelease(source), /dist 必须是普通目录/);
  assert.deepEqual(fs.readdirSync(outside), []);
});

test('real CLI, generated template and extracted release work outside the source cwd', (t) => {
  const dir = temp(t);
  const cli = path.join(repoRoot, 'scripts/create-project.cjs');
  assert.match(run(process.execPath, [cli, '--help'], { cwd: dir }), /用法/);
  run(process.execPath, [cli, 'generated-app', dir], { cwd: dir });
  const generated = path.join(dir, 'generated-app');
  for (const script of ['check-docs', 'check-repo-hygiene', 'check-action-pinning']) {
    run(process.execPath, [path.join(generated, `scripts/${script}.cjs`)], { cwd: dir });
  }
  // CommonJS entries must work when --into preserves an ESM project's package.json.
  const pkg = JSON.parse(fs.readFileSync(path.join(generated, 'package.json'), 'utf8'));
  pkg.type = 'module';
  fs.writeFileSync(path.join(generated, 'package.json'), JSON.stringify(pkg));
  run(process.execPath, [path.join(generated, 'scripts/check-docs.cjs')]);
  run(process.execPath, [path.join(generated, 'scripts/release-package.cjs')]);
  const extracted = path.join(dir, '解包 release');
  fs.mkdirSync(extracted);
  run('tar', ['-xzf', path.join(generated, 'dist/repo-metadata.tgz'), '-C', extracted]);
  checkDocs(extracted);
  checkRepo(extracted);
  checkActions(extracted);
  assert.ok(fs.existsSync(path.join(extracted, 'tests/tooling.test.cjs')));
  assert.ok(fs.existsSync(path.join(extracted, 'evals/README.md')));
  assert.ok(fs.existsSync(path.join(extracted, 'evals/concept-explanation/case.json')));
  assert.equal(fs.existsSync(path.join(extracted, 'data/evals')), false);
  assert.equal(fs.existsSync(path.join(extracted, 'public')), false);
  assert.equal(fs.existsSync(path.join(extracted, 'docs/nono-profiles')), false);
  assert.equal(fs.existsSync(path.join(extracted, 'scripts/ci.sh')), false);
  assert.match(fs.readFileSync(path.join(extracted, 'README.md'), 'utf8'), /^# generated-app/);
  assert.doesNotMatch(fs.readFileSync(path.join(extracted, 'README.md'), 'utf8'), /public\//);
  run(process.execPath, [path.join(extracted, 'scripts/create-project.cjs'), 'from-release', dir]);
  checkDocs(path.join(dir, 'from-release'));
});

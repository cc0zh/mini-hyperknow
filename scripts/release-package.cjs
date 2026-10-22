#!/usr/bin/env node
'use strict';

const { fs, path, repoRoot, stat, run, main } = require('./lib/common.cjs');
const { copyTemplate } = require('./create-project.cjs');

function packageRelease(root = repoRoot) {
  const dist = path.join(root, 'dist');
  const distStat = stat(dist);
  if (distStat && (!distStat.isDirectory() || distStat.isSymbolicLink())) {
    throw new Error('dist 必须是普通目录，不能是文件或符号链接');
  }
  for (const name of ['repo-metadata.tgz', 'release-manifest.json']) {
    const existing = stat(path.join(dist, name));
    if (existing && (!existing.isFile() || existing.isSymbolicLink())) throw new Error(`拒绝覆盖非普通文件: ${name}`);
  }
  run('tar', ['--version']);
  fs.mkdirSync(dist, { recursive: true });
  const staging = fs.mkdtempSync(path.join(dist, '.package-'));
  try {
    const payload = path.join(staging, 'payload');
    copyTemplate(root, payload);
    run('tar', ['-czf', path.join(staging, 'repo-metadata.tgz'), '-C', payload, '.']);
    let sha = process.env.GITHUB_SHA;
    if (!sha) {
      try { sha = run('git', ['rev-parse', 'HEAD'], { cwd: root }).trim(); }
      catch { sha = 'unknown'; }
    }
    const manifest = {
      repository: process.env.GITHUB_REPOSITORY || 'local',
      git_sha: sha,
      generated_at_utc: new Date().toISOString(),
      artifact: 'repo-metadata.tgz',
      note: 'Replace scripts/release-package.cjs with the real project build packaging when the stack is known.',
    };
    fs.writeFileSync(path.join(staging, 'release-manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
    for (const name of ['repo-metadata.tgz', 'release-manifest.json']) {
      fs.copyFileSync(path.join(staging, name), path.join(dist, name));
    }
  } finally {
    // Only the exact temporary directory created above is removed.
    fs.rmSync(staging, { recursive: true, force: true });
  }
  console.log(path.join(dist, 'repo-metadata.tgz'));
}

if (require.main === module) main(() => packageRelease());
module.exports = { packageRelease };

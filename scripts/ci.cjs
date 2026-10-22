#!/usr/bin/env node
'use strict';

const { path, repoRoot, filesIn, run, main } = require('./lib/common.cjs');
const { checkDocs, checkRepo, checkActions } = require('./lib/checks.cjs');

main(() => {
  checkDocs(repoRoot);
  checkRepo(repoRoot);
  checkActions(repoRoot);
  for (const dir of ['scripts', 'tests']) {
    for (const file of filesIn(path.join(repoRoot, dir)).filter((file) => file.endsWith('.cjs'))) {
      run(process.execPath, ['--check', file]);
    }
  }
  run(process.execPath, ['--test', 'tests/tooling.test.cjs'], { stdio: 'inherit' });
  run('uv', ['run', '--frozen', 'python', '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py', '-v'], {
    stdio: 'inherit',
    env: { ...process.env, PYTHONPATH: path.join(repoRoot, 'src') },
  });
  console.log('静态、真实逻辑与本地服务检查通过；不代表真实模型或浏览器业务验收通过');
});

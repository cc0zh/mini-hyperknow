#!/usr/bin/env node
'use strict';
const { repoRoot, main } = require('./lib/common.cjs');
const { checkRepo } = require('./lib/checks.cjs');
main(() => {
  checkRepo(repoRoot);
  console.log('仓库基础卫生检查通过');
});

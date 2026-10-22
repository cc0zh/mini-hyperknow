#!/usr/bin/env node
'use strict';
const { repoRoot, main } = require('./lib/common.cjs');
const { checkActions } = require('./lib/checks.cjs');
main(() => {
  checkActions(repoRoot);
  console.log('GitHub Action 固定 SHA 检查通过');
});

#!/usr/bin/env node
'use strict';
const { repoRoot, main } = require('./lib/common.cjs');
const { checkDocs } = require('./lib/checks.cjs');
main(() => {
  checkDocs(repoRoot);
  console.log('文档骨架检查通过');
});

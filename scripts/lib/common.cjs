'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const repoRoot = path.resolve(__dirname, '../..');
const excludedNames = new Set([
  '.git', 'node_modules', 'dist', '.tmp', 'tmp', 'temp', 'coverage',
  '.venv', 'venv', '.cache', '.npm', '.env', '.env.local', '__pycache__',
  '.verification', 'test-results', 'playwright-report',
]);

function excluded(name) {
  return excludedNames.has(name) || name.endsWith('.pyc') || name.endsWith('.pyo')
    || name.endsWith('.egg-info') || (/^\.env(?:\.|$)/.test(name) && name !== '.env.example');
}

function stat(file) {
  try {
    return fs.lstatSync(file);
  } catch (error) {
    if (error.code === 'ENOENT') return undefined;
    throw error;
  }
}

function filesIn(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    if (excluded(entry.name)) return [];
    const file = path.join(directory, entry.name);
    if (entry.isSymbolicLink()) throw new Error(`不支持模板中的符号链接: ${file}`);
    return entry.isDirectory() ? filesIn(file) : [file];
  });
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: repoRoot, encoding: 'utf8', windowsHide: true, ...options, shell: false,
  });
  if (result.error) throw new Error(`无法运行 ${command}: ${result.error.message}`);
  if (result.status !== 0) {
    throw new Error(`${command} 执行失败 (${result.status ?? result.signal}): ${result.stderr || result.stdout || ''}`);
  }
  return result.stdout || '';
}

function main(action) {
  try {
    action();
  } catch (error) {
    console.error(`错误: ${error.message}`);
    process.exitCode = 1;
  }
}

module.exports = { fs, path, repoRoot, excluded, stat, filesIn, run, main };

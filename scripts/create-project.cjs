#!/usr/bin/env node
'use strict';

const { fs, path, repoRoot, excluded, stat, run, main } = require('./lib/common.cjs');
const { projectPath, documentOverrides } = require('./lib/scaffold.cjs');

function usage() {
  console.log(`用法:
  code-harness-init <项目名> [目标目录]   创建新项目
  code-harness-init --into [目标目录]     补齐已有项目（默认当前目录）
  code-harness-init --help                显示帮助

已有文件全部保留。目标路径含空格时请加引号；目标与模板目录不能相互包含。`);
}

function canonical(file) {
  const absolute = path.resolve(file);
  if (stat(absolute)) return fs.realpathSync(absolute);
  return path.join(canonical(path.dirname(absolute)), path.basename(absolute));
}

function contains(parent, child) {
  const relative = path.relative(parent, child);
  return relative === '' || (!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative));
}

function validateName(name) {
  if (!name || /[<>:"/\\|?*\x00-\x1f]/.test(name) || /[. ]$/.test(name)
    || name.startsWith('-') || /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(name)) {
    throw new Error('项目名必须是有效的单层目录名，不能包含 Windows 保留字符、设备名或路径分隔符');
  }
}

// Plan first: never traverse existing links/junctions or overwrite target files.
function planCopy(source, target, entries = [], templateRoot = source) {
  for (const entry of fs.readdirSync(source, { withFileTypes: true })) {
    if (excluded(entry.name)) continue;
    let from = path.join(source, entry.name);
    const relative = path.relative(templateRoot, from).split(path.sep).join('/');
    if (!projectPath(relative)) continue;
    const to = path.join(target, entry.name);
    const existing = stat(to);
    if (entry.isDirectory()) {
      if (existing && (!existing.isDirectory() || existing.isSymbolicLink())) continue;
      entries.push({ from, to, directory: true });
      planCopy(from, to, entries, templateRoot);
    } else if (!existing) {
      if (!entry.isFile()) throw new Error(`不支持模板中的符号链接或特殊文件: ${from}`);
      if (documentOverrides[relative]) {
        const overrideDir = path.join(templateRoot, '.template');
        const overrideStat = stat(overrideDir);
        if (overrideStat) {
          if (!overrideStat.isDirectory() || overrideStat.isSymbolicLink()) throw new Error('.template 必须是普通目录');
          const override = path.join(overrideDir, documentOverrides[relative]);
          const fileStat = stat(override);
          if (fileStat && !fileStat.isFile()) throw new Error(`文档模板必须是普通文件: ${override}`);
          if (fileStat) from = override;
        }
      }
      entries.push({ from, to, directory: false });
    }
  }
  return entries;
}

function copyTemplate(source, target, name, entries = planCopy(source, target)) {
  const templateName = JSON.parse(fs.readFileSync(path.join(source, 'package.json'), 'utf8')).name;
  fs.mkdirSync(target, { recursive: true });
  let copied = 0;
  for (const { from, to, directory } of entries) {
    if (directory) { fs.mkdirSync(to, { recursive: true }); continue; }
    const textFile = /\.(md|json|jsonc|ya?ml)$/.test(from);
    const content = textFile
      ? fs.readFileSync(from, 'utf8').split(templateName).join(name ?? templateName)
      : fs.readFileSync(from);
    fs.writeFileSync(to, content, { flag: 'wx', mode: fs.statSync(from).mode });
    copied += 1;
  }
  return copied;
}

function createProject(args, templateRoot = repoRoot, cwd = process.cwd()) {
  if (args.length === 1 && ['--help', '-h'].includes(args[0])) { usage(); return; }
  if (args.length < 1 || args.length > 2 || (args[0].startsWith('-') && args[0] !== '--into')) {
    throw new Error('参数错误；运行 code-harness-init --help 查看用法');
  }
  const into = args[0] === '--into';
  if (!into) validateName(args[0]);
  const target = path.resolve(cwd, args[1] || '.', ...(into ? [] : [args[0]]));
  const source = fs.realpathSync(templateRoot);
  const realTarget = canonical(target);
  if (contains(source, realTarget) || contains(realTarget, source)) {
    throw new Error('目标与模板目录不能相同或相互包含，请选择模板之外的目录');
  }
  if (into && !stat(target)?.isDirectory()) throw new Error(`目标目录不存在或不是普通目录: ${target}`);
  if (!into && stat(target)) throw new Error(`目标已存在: ${target}；补齐已有项目请使用 --into`);

  const name = into ? path.basename(realTarget) : args[0];
  const entries = planCopy(source, realTarget);
  run('git', ['--version']);
  const copied = copyTemplate(source, realTarget, name, entries);
  if (!stat(path.join(realTarget, '.git'))) run('git', ['init', '--quiet'], { cwd: realTarget });
  console.log(`${into ? '模板已补齐' : '新项目已创建'}: ${realTarget}\n新增 ${copied} 个文件（已有文件保留）。`);
  console.log('下一步：进入项目目录，运行 npm run ci；补齐 docs/ARCHITECTURE.md 和 CODEOWNERS。');
  if (into) console.log('已有 package.json 不会合并；可直接运行 node scripts/ci.cjs，或按模板补齐 npm scripts。');
  return { target: realTarget, copied };
}

if (require.main === module) main(() => createProject(process.argv.slice(2)));
module.exports = { createProject, copyTemplate };

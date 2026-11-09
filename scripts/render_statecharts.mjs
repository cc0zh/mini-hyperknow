import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const directory = path.join(root, 'docs/formal-verification');
const packageRoot = process.env.PELE_ROOT;
if (!packageRoot) throw new Error('Set PELE_ROOT to the external installation of pele@1.9.0.');
const require = createRequire(path.resolve(packageRoot, 'package.json'));
const manifest = JSON.parse(fs.readFileSync(path.join(packageRoot, 'node_modules/pele/package.json'), 'utf8'));
if (manifest.version !== '1.9.0') throw new Error('Expected pele@1.9.0.');
const { render } = await import(pathToFileURL(require.resolve('pele')).href);
const systems = ['course-flow', 'classroom-flow', 'quiz-flow', 'assistance-flow', 'research-flow', 'run-lifecycle'];
const escape = value => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const colors = `.pele{--pele-bg:#fff;--pele-fg:#172334;--pele-muted:#526173;--pele-line:#74859a;--pele-surface:#fff;--pele-surface-alt:#edf2f7;--pele-border:#a2b0c0}
.pele .blue rect{fill:#dbeafe}.pele .orange rect{fill:#ffedd5}.pele .purple rect{fill:#ede9fe}.pele .yellow rect{fill:#fef3c7}.pele .teal rect{fill:#ccfbf1}.pele .tan rect{fill:#e5d9ce}.pele .pink rect{fill:#fce7f3}
.pele .breaks rect{fill:#ffecee!important;stroke:#e72e3b!important;stroke-width:2.5px!important}.pele .breaks text{fill:#cd2834!important}.pele .mayBreak rect{fill:#fff3e6!important;stroke:#e8730c!important;stroke-width:2.5px!important}.pele .mayBreak text{fill:#b85a06!important}.pele .bugPath rect{stroke:#1680f3!important;stroke-width:2.5px!important}.pele .repeats rect{stroke:#9b35d6!important;stroke-width:2.5px!important;stroke-dasharray:6 3}`;
const cards = [];
const markdown = ['# 已检查的用户流程', '', '由 `scripts/render_statecharts.mjs` 从实际 statechart 工件生成。', '', '有界安全性质通过不等于整个产品正确。故障目录中的反例属于主动注入的故障，不是当前产品缺陷。', ''];
for (const id of systems) {
  const folder = path.join(directory, 'charts', id);
  const source = fs.readFileSync(path.join(folder, 'chart.mmd'), 'utf8');
  const title = JSON.parse(source.match(/^title: (.+)$/m)[1]);
  let normal;
  for (const variant of ['', 'mutation']) {
    const destination = path.join(folder, variant);
    const mermaid = fs.readFileSync(path.join(destination, 'chart.mmd'), 'utf8');
    const result = render(mermaid, {
      limit: 1_000_000, outputLimit: 8_000_000, maxEdges: 10_000,
      idPrefix: `${id}-${variant || 'baseline'}`, fontFamily: 'Microsoft YaHei, sans-serif',
      fontSize: 16, maxWidth: 1200, links: false, images: false,
    });
    const svg = result.svg.replace(/(<svg\b[^>]*>)/, `$1<style>${colors}</style>`);
    fs.writeFileSync(path.join(destination, 'chart.svg'), svg + '\n');
    if (!variant) normal = svg;
    console.log(`${id}/${variant || 'baseline'} ${result.width}x${result.height}`);
  }
  const report = fs.readFileSync(path.join(folder, 'report.md'), 'utf8');
  const mutation = fs.readFileSync(path.join(folder, 'mutation/report.md'), 'utf8');
  cards.push(`<section id="${id}"><div class="card-title"><h2>${escape(title)}</h2><span class="badge">有界性质通过</span></div><div class="diagram">${normal}</div><details><summary>查看 Mermaid 文本和检查报告</summary><pre>${escape(source)}</pre><h3>基线</h3><pre>${escape(report)}</pre><h3>主动故障注入的最短反例</h3><pre>${escape(mutation)}</pre></details></section>`);
  markdown.push(`## ${title}`, '', `![${title}](charts/${id}/chart.svg)`, '', '```mermaid', source.trim(), '```', '', `[基线报告](charts/${id}/report.md) · [主动故障见证](charts/${id}/mutation/report.md)`, '');
}
const html = `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Hyperknow 用户流程状态图</title><style>
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#f2f5f9;color:#172334;font:16px/1.65 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1320px;margin:auto;padding:40px 24px}header{padding:8px 8px 24px}h1{font-size:32px;line-height:1.3;margin:0 0 12px}p{max-width:920px;color:#526173}nav{display:flex;gap:10px;flex-wrap:wrap;margin:24px 0}nav a{background:#fff;border:1px solid #d2dce8;border-radius:8px;padding:8px 14px;color:#234c79;text-decoration:none}section{background:#fff;border:1px solid #d2dce8;border-radius:12px;padding:24px;margin-bottom:28px;scroll-margin-top:20px}.card-title{display:flex;align-items:center;justify-content:space-between;gap:20px}h2{font-size:22px;margin:0}h3{font-size:17px}.badge{color:#076448;background:#dff7ec;border-radius:999px;padding:4px 12px;white-space:nowrap;font-size:13px}.diagram{overflow:auto;padding:20px 0}.diagram>svg{display:block;width:100%;height:auto;min-width:640px}details{border-top:1px solid #e3eaf2;padding-top:14px}summary{cursor:pointer;color:#234c79}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.65 ui-monospace,monospace;background:#f5f7fa;padding:16px;border-radius:8px}footer{font-size:14px;color:#526173}
</style></head><body><main><header><h1>Hyperknow 用户流程状态图</h1><p>六个子系统分别建模。造课、课堂和测验优先展示。图由 TLC 检查结果生成，不是手绘的目标流程。</p><p>每个子系统验证一个明确的安全性质。取消、失败与重启保留为可见分支。图中合并了同标签状态，没有删除动作；标签不变的内部步骤不画箭头。</p><nav>${systems.map((id, i) => `<a href="#${id}">${['造课与蓝图','白板课堂','练习与考核','即时协助','网页调研','任务与幂等'][i]}</a>`).join('')}</nav></header>${cards.join('')}<footer>2026-11-09。范围为有限模型，不证明教学质量、外部模型正确性或所有并发行为。故障反例来自主动注入，原产品代码没有修改。离线查看无需网络。</footer></main></body></html>`;
fs.writeFileSync(path.join(directory, 'index.html'), html);
fs.writeFileSync(path.join(directory, 'flows.md'), markdown.join('\n') + '\n');

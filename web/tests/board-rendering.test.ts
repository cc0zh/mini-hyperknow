import assert from 'node:assert/strict'
import test from 'node:test'
import katex from 'katex'
import { fitToWidth, formulaOptions, naturalSvgWidth } from '../src/lib/board-rendering.ts'

test('actual formula ink fits its available width without enlarging or losing hidden content', () => {
  assert.equal(fitToWidth(960, 480), .5)
  assert.equal(fitToWidth(200, 600), 1)
  for (const width of [0, -1, NaN, Infinity]) {
    assert.equal(fitToWidth(width, 600), 1)
    assert.equal(fitToWidth(600, width), 1)
  }
})

test('narrow diagrams keep their natural width rather than stretching to the board', () => {
  assert.equal(naturalSvgWidth('4.5 4 212.60000610351562 876.2000122070312'), 212.60000610351562)
  assert.equal(naturalSvgWidth('0,0,1200,300'), 1200)
})

test('invalid or zero-size SVG viewboxes never create a numeric layout override', () => {
  for (const value of [null, '', '0 0 0 10', '0 0 -1 10', '0 0 10 0', '0 0 NaN 10', '0 0 10px 20', '0 0 20']) {
    assert.equal(naturalSvgWidth(value), null)
  }
})

test('the real KaTeX renderer produces mathematical markup with trust disabled', () => {
  const html = katex.renderToString(String.raw`E = mc^2 + \frac{a}{b}`, formulaOptions)
  assert.match(html, /class="katex"/)
  assert.match(html, /<math/)
  assert.match(html, /class="mfrac"/)
})

test('the real KaTeX renderer rejects malformed formulas instead of pretending to render', () => {
  assert.throws(() => katex.renderToString(String.raw`\frac{a}{`, formulaOptions))
})

test('actual Unicode classroom labels render without weakening untrusted HTML or malformed TeX rules', () => {
  for (const formula of ['顺序、分支、重试、停止 = 代码编排', '停止条件_{程序} = (round ≥ R_{max}) ∨ (elapsed > T_{max})']) {
    const html = katex.renderToString(formula, formulaOptions)
    assert.match(html, /class="katex"/)
    assert.match(html, /cjk_fallback/)
  }
  assert.equal(formulaOptions.trust, false)
  assert.equal(formulaOptions.throwOnError, true)
  const dangerous = katex.renderToString(String.raw`\href{javascript:alert(1)}{x}`, formulaOptions)
  assert.doesNotMatch(dangerous, /<a\b|<script\b|<img\b/)
  assert.throws(() => katex.renderToString(String.raw`\htmlStyle{position:fixed}{x}`, formulaOptions))
})

import assert from 'node:assert/strict'
import test from 'node:test'
import katex from 'katex'
import { naturalSvgWidth } from '../src/lib/board-rendering.ts'

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
  const html = katex.renderToString(String.raw`E = mc^2 + \frac{a}{b}`, { trust: false, throwOnError: true, strict: 'error' })
  assert.match(html, /class="katex"/)
  assert.match(html, /<math/)
  assert.match(html, /class="mfrac"/)
})

test('the real KaTeX renderer rejects malformed formulas instead of pretending to render', () => {
  assert.throws(() => katex.renderToString(String.raw`\frac{a}{`, { trust: false, throwOnError: true, strict: 'error' }))
})

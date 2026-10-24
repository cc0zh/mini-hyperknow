import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFileSync, readdirSync } from 'node:fs'
import test from 'node:test'
import { boardFontFamily, boardFonts } from '../src/lib/board-fonts.ts'

test('HTML and Mermaid share Excalifont followed by the Chinese Xiaolai fallback', () => {
  assert.equal(boardFontFamily, 'Excalifont, Xiaolai, sans-serif')
  assert.deepEqual(boardFonts.map(font => font.family), ['Excalifont', 'Xiaolai'])
  const css = readFileSync(new URL('../src/styles/classroom.css', import.meta.url), 'utf8')
  assert.equal(css.match(/font-family: Excalifont, Xiaolai, sans-serif/g)?.length, 3)
  // Code keeps a monospace stack; it now comes from the --font-mono token, so the
  // assertion accepts either the token reference or a literal monospace family.
  assert.match(css, /\.board-code \{[^}]*font-family:.*(monospace|--font-mono)/s)
  assert.match(css, /\.board-formula \.katex[^}]*KaTeX_Main/s)
})

test('the two real font binaries match the pinned upstream downloads and retain OFL notices', () => {
  const files = [
    ['Excalifont-Regular.woff2', 'e4423b318e11432aff2e6e865e300b7ca270f92321a3f56632268fede01c1b48', 'wOF2', 'Excalifont-OFL.txt'],
    ['Xiaolai-Regular.ttf', 'e2f68daf0e72777a8cf58bc83de1b98634b251e537ddbfca24b0ae50d1802da2', '\x00\x01\x00\x00', 'Xiaolai-OFL.txt'],
  ]
  for (const [file, hash, signature, notice] of files) {
    const bytes = readFileSync(new URL(`../public/fonts/${file}`, import.meta.url))
    assert.equal(bytes.subarray(0, 4).toString('latin1'), signature)
    assert.equal(createHash('sha256').update(bytes).digest('hex'), hash)
    assert.match(readFileSync(new URL(`../public/fonts/${notice}`, import.meta.url), 'utf8'), /SIL OPEN FONT LICENSE Version 1\.1/)
  }
  assert.deepEqual(readdirSync(new URL('../public/fonts/', import.meta.url)).sort(),
    ['Excalifont-OFL.txt', 'Excalifont-Regular.woff2', 'NOTICE.md', 'Xiaolai-OFL.txt', 'Xiaolai-Regular.ttf'])
})

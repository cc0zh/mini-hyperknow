import assert from 'node:assert/strict'
import test from 'node:test'
import { progressLabel } from '../src/lib/format.ts'

test('course progress is rounded only for presentation', () => {
  assert.equal(progressLabel(100 / 13), '7.7%')
  assert.equal(progressLabel(25), '25%')
  assert.equal(progressLabel(0), '0%')
  assert.equal(progressLabel(100), '100%')
})

test('a partial course has no fabricated percentage', () => {
  assert.equal(progressLabel(null), '目录完善中')
})

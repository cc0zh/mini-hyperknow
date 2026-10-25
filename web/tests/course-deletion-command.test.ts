import assert from 'node:assert/strict'
import test from 'node:test'
import { ownsCommand, prepareCommand } from '../src/lib/commands.ts'

test('an uncertain course deletion retries the same path, version and identity', () => {
  const original = prepareCommand(null, '/courses/course-a/delete', { expected_version: 4 }, 'deletion-a')!
  const retry = prepareCommand(original, '/courses/course-b/delete', { expected_version: 99 }, 'deletion-b')
  assert.equal(retry, original)
  assert.deepEqual(retry, { path: '/courses/course-a/delete', body: { expected_version: 4, client_command_id: 'deletion-a' } })
})

test('an old deletion acknowledgement does not own a subsequent pending command', () => {
  const original = prepareCommand(null, '/courses/course-a/delete', { expected_version: 4 }, 'deletion-a')!
  const next = prepareCommand(null, '/courses/course-b/delete', { expected_version: 1 }, 'deletion-b')!
  assert.equal(ownsCommand(original, original), true)
  assert.equal(ownsCommand(next, original), false)
  assert.equal(ownsCommand({ ...original, path: next.path }, original), false)
  assert.equal(ownsCommand(null, original), false)
})

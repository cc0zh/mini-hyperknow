import { test } from 'node:test'
import assert from 'node:assert/strict'
import { ApiError, isInputRejection } from '../src/lib/api.ts'

test('only confirmed input rejection permits editing an uncommitted command', () => {
  const error = { code: 'invalid_request', message: '输入不符合要求', retryable: false }
  assert.equal(isInputRejection(new ApiError(error, 400)), true)
  assert.equal(isInputRejection(new ApiError(error, 404)), true)
  assert.equal(isInputRejection(new ApiError(error, 422)), true)
  assert.equal(isInputRejection(new ApiError(error, 409)), false)
  assert.equal(isInputRejection(new ApiError(error, 503)), false)
  assert.equal(isInputRejection(new Error('response unknown')), false)
})

import test from 'node:test'
import assert from 'node:assert/strict'
import { setTimeout as delay } from 'node:timers/promises'
import { acknowledgeInteraction, activeInteraction, activeRun, boardPrefix, heldInteraction, interactionIdentity, lessonCommand, mergeLesson, nextCursor, PlaybackClock, readingDelay, resumeIntent } from '../src/lib/lesson-state.ts'
import type { BoardScript, BoardStep, Interaction, LessonSnapshot } from '../src/lib/types.ts'

// Domain transition data only. No provider, network interception, substitute
// service or synthetic course is used by these directly invoked logic checks.
const snapshot = (version: number, progressVersion = 2): LessonSnapshot => ({
  version, course_id: 'state-only', course_title: '', unit_title: '', lecture_title: '',
  session: { session_id: 'cursor-state', title: '', description: '', outline: '', key_points: [], estimated_minutes: 0 },
  script: null, progress: { script_id: null, cursor: -1, play_intent: 'paused', version: progressVersion, updated_at: '' },
  interactions: [], generation_run: null, completed: false,
})
const step = (id: string, page: number, column: 1 | 2): BoardStep => ({ step_id: id, title: '', narration: '', page, column, operations: [{ kind: 'text', content: '', items: [], language: '' }] })
const script: BoardScript = { script_id: 'prefix-state', session_id: 'cursor-state', course_id: 'state-only', content_version: 1, schema_version: 1, title: '', created_at: '', steps: [step('a', 1, 1), step('b', 1, 2), step('c', 2, 1), step('d', 1, 1)] }

test('reload starts paused even when saved backend intent was playing', () => {
  const clock = new PlaybackClock()
  const saved = snapshot(2)
  saved.progress.play_intent = 'playing'
  assert.equal(clock.playing, false)
  assert.equal(resumeIntent(saved.progress.play_intent === 'playing', false), 'paused')
  assert.equal(saved.progress.play_intent, 'playing')
})

test('PUT GET and replay may share one authoritative playing snapshot without starting a clock', () => {
  const confirmed = snapshot(3)
  confirmed.progress.play_intent = 'playing'
  const get = JSON.parse(JSON.stringify(confirmed)) as LessonSnapshot
  const replay = JSON.parse(JSON.stringify(confirmed)) as LessonSnapshot
  const clock = new PlaybackClock()
  assert.deepEqual(get, confirmed)
  assert.equal(mergeLesson(confirmed, get), confirmed)
  assert.equal(mergeLesson(confirmed, replay), confirmed)
  assert.equal(confirmed.progress.play_intent, 'playing')
  assert.equal(clock.playing, false)
})

test('prefix reconstruction is idempotent and never reveals future operations', () => {
  assert.deepEqual(boardPrefix(script, -1), [])
  assert.deepEqual(boardPrefix(script, 1), boardPrefix(script, 1))
  const prefix = boardPrefix(script, 1)
  assert.deepEqual(prefix.flatMap(column => column.steps.map(item => item.step_id)), ['a', 'b'])
  assert.equal(prefix.flatMap(column => column.steps).length, 2)
  assert.equal(script.steps.length, 4)
})

test('page and column reconstruction is independent of review selection', () => {
  const prefix = boardPrefix(script, 3)
  assert.deepEqual(prefix.map(column => [column.page, column.column]), [[1, 1], [1, 2], [2, 1]])
  assert.deepEqual(prefix[0].steps.map(item => item.step_id), ['a', 'd'])
  assert.equal(nextCursor(1, 4), 2)
  assert.equal(nextCursor(3, 4), null)
  assert.equal(nextCursor(-1, 4), 0)
})

test('only one in-flight progress transition may reserve the player', () => {
  const clock = new PlaybackClock()
  assert.equal(clock.reserve(), true)
  assert.equal(clock.reserve(), false)
  assert.equal(clock.reserve(), false)
  clock.release()
  assert.equal(clock.reserve(), true)
  clock.release()
})

test('Next cancels the old real timer before reserving a step', async () => {
  const clock = new PlaybackClock()
  let fired = 0
  clock.play()
  clock.schedule(10, () => { fired += 1 })
  clock.reserve()
  await delay(30)
  assert.equal(fired, 0)
  clock.release()
  clock.pause()
})

test('replacing a scheduled timer cannot create two advances', async () => {
  const clock = new PlaybackClock()
  let fired = 0
  clock.play()
  clock.schedule(10, () => { fired += 100 })
  clock.schedule(10, () => { fired += 1 })
  await delay(30)
  assert.equal(fired, 1)
  clock.pause()
})

test('pause and disconnect cancellation prevent automatic advancement', async () => {
  const clock = new PlaybackClock()
  let fired = 0
  clock.play()
  clock.schedule(10, () => { fired += 1 })
  clock.pause()
  await delay(30)
  assert.equal(fired, 0)
  clock.schedule(1, () => { fired += 1 })
  await delay(10)
  assert.equal(fired, 0)
})

test('questions require explicit continuation and preserve original pause intent', () => {
  assert.equal(resumeIntent(true, false), 'paused')
  assert.equal(resumeIntent(true, true), 'playing')
  assert.equal(resumeIntent(false, true), 'paused')
  assert.equal(resumeIntent(false, false), 'paused')
})

test('a late save cannot restart playback after a disconnect and reconnect', () => {
  const clock = new PlaybackClock()
  clock.play()
  clock.reserve()
  const started = clock.pauseVersion
  clock.pause()
  clock.release()
  assert.notEqual(clock.pauseVersion, started)
  assert.equal(clock.playing, false)
  // Scheduling/cancelling presentation timers is not a user pause intent.
  const paused = clock.pauseVersion
  clock.cancel()
  assert.equal(clock.pauseVersion, paused)
})

test('reading time is bounded local text rhythm, not rendering or font timing', () => {
  assert.equal(readingDelay(''), 4000)
  assert.equal(readingDelay('字'.repeat(100)), 9500)
  assert.equal(readingDelay('字'.repeat(1000)), 30000)
  assert.equal(readingDelay('𠮷'.repeat(100)), 9500)
})

test('session version guards the whole snapshot even at equal progress version', () => {
  const old = snapshot(8, 3)
  const answered = snapshot(9, 3)
  answered.completed = true
  assert.equal(mergeLesson(answered, old), answered)
  assert.equal(mergeLesson(old, answered), answered)
  assert.equal(mergeLesson(answered, snapshot(9, 3)), answered)
  assert.equal(mergeLesson(null, old), old)
})

test('newer session facts cannot be suppressed just because progress did not change', () => {
  const before = snapshot(10, 4)
  const after = snapshot(11, 4)
  const interaction: Interaction = { interaction_id: 'answer-state', run_id: 'run-state', script_id: 'prefix-state', step_id: 'a', cursor: 0, question: '', answer: '', was_playing: false, status: 'ready', error: null, created_at: '' }
  after.interactions = [interaction]
  assert.deepEqual(mergeLesson(before, after).interactions, [interaction])
  assert.deepEqual(mergeLesson(after, before).interactions, [interaction])
  assert.equal(activeInteraction({ ...interaction, status: 'pending' }), true)
  assert.equal(activeInteraction(interaction), false)
  assert.equal(activeRun(null), false)
})

test('unknown write results retry the same method body cursor version and ID', () => {
  const original = { method: 'PUT' as const, path: '/sessions/cursor-state/progress', body: { client_command_id: 'same-command', cursor: 2, expected_version: 8, play_intent: 'playing' } }
  const changed = { method: 'POST' as const, path: '/sessions/cursor-state/complete', body: { client_command_id: 'different-command' } }
  assert.equal(lessonCommand(original, changed), original)
  const reloaded = JSON.parse(JSON.stringify(original)) as typeof original
  assert.deepEqual(lessonCommand(reloaded, changed), original)
  assert.equal(lessonCommand(null, changed), changed)
})

const interaction = (id: string, runId: string, status: Interaction['status'] = 'ready'): Interaction => ({ interaction_id: id, run_id: runId, script_id: 'prefix-state', step_id: 'a', cursor: 0, question: '', answer: null, was_playing: true, status, error: null, created_at: '' })

test('retrying an earlier interaction locks playback even when it is not last', () => {
  const earlier = interaction('earlier', 'retry-run', 'pending')
  const latest = interaction('latest', 'latest-run')
  assert.equal(heldInteraction([earlier, latest], [interactionIdentity(latest)]), earlier)
  assert.equal(heldInteraction([earlier, latest], []), earlier)
})

test('an old run acknowledgement cannot acknowledge the retried answer', () => {
  const original = interaction('same-question', 'original-run')
  const retry = interaction('same-question', 'retry-run', 'pending')
  const acknowledged = acknowledgeInteraction([], interactionIdentity(original))
  assert.equal(heldInteraction([retry], acknowledged), retry)
  const answered = { ...retry, status: 'ready' as const, answer: '保存后的回答' }
  assert.equal(heldInteraction([answered], acknowledged), answered)
  const continued = acknowledgeInteraction(acknowledged, interactionIdentity(answered))
  assert.equal(heldInteraction([answered], continued), undefined)
})

test('multiple explicit confirmations survive reload as an idempotent set', () => {
  const first = interaction('first', 'run-1')
  const second = interaction('second', 'run-2')
  let acknowledged = acknowledgeInteraction([], interactionIdentity(first))
  acknowledged = acknowledgeInteraction(acknowledged, interactionIdentity(second))
  acknowledged = acknowledgeInteraction(acknowledged, interactionIdentity(first))
  const restored = JSON.parse(JSON.stringify(acknowledged)) as string[]
  assert.equal(restored.length, 2)
  assert.equal(heldInteraction([first, second], restored), undefined)
})

test('after pending answers finish, each unconfirmed terminal answer still holds', () => {
  const earlier = interaction('earlier', 'run-1', 'failed')
  const latest = interaction('latest', 'run-2')
  assert.equal(heldInteraction([earlier, latest], []), latest)
  assert.equal(heldInteraction([earlier, latest], [interactionIdentity(latest)]), earlier)
  assert.equal(heldInteraction([earlier, latest], [interactionIdentity(latest), interactionIdentity(earlier)]), undefined)
})

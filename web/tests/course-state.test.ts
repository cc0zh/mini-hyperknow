import assert from 'node:assert/strict'
import test from 'node:test'
import { canReviewBlueprint, courseProgress, depthLabels, newerCourse, readyUnitCount, structurePending, unitGenerationLabels, unitSessionCount } from '../src/lib/course-state.ts'
import { progressLabel } from '../src/lib/format.ts'
import type { Course, Session, SessionDepth, Unit, UnitGenerationStatus } from '../src/lib/types.ts'

// Deterministic presentation/snapshot rules only, no mocked API or generated courses.
test('incomplete structures suppress percentage even if all currently saved lessons are complete', () => {
  for (const structure_status of ['blueprint', 'expanding'] as const) {
    assert.equal(structurePending({ structure_status }), true)
    assert.equal(courseProgress({ structure_status, progress: 100 }), null)
    assert.equal(progressLabel(courseProgress({ structure_status, progress: null })), '目录完善中')
  }
  assert.equal(structurePending({ structure_status: 'ready' }), false)
  assert.equal(courseProgress({ structure_status: 'ready', progress: 25 }), 25)
  assert.equal(courseProgress({ structure_status: 'ready', progress: 100 }), 100)
  assert.equal(courseProgress({ structure_status: 'ready', progress: null }), null)
})

test('each unit generation status has a label; only actually ready units count', () => {
  const statuses: UnitGenerationStatus[] = ['pending', 'generating', 'ready', 'failed', 'cancelled', 'interrupted']
  assert.equal(statuses.every(status => !!unitGenerationLabels[status]), true)
  assert.equal(readyUnitCount(statuses.map(generation_status => ({ generation_status }) as Unit)), 1)
  assert.equal(readyUnitCount([]), 0)
})

test('estimated scale never counts as generated sessions', () => {
  const blueprint = { estimated_sessions: 20, lectures: [] } as unknown as Unit
  assert.equal(unitSessionCount(blueprint), 0)
  const expanded = { ...blueprint, lectures: [{ lecture_id: 'lecture-count', title: '', description: '', sessions: [{} as Session, {} as Session] }] }
  assert.equal(unitSessionCount(expanded), 2)
})

test('depth tags use the five agreed learner-facing labels', () => {
  const depths: SessionDepth[] = ['intuition', 'definition', 'derivation', 'theory', 'practice']
  assert.deepEqual(depths.map(depth => depthLabels[depth]), ['建立直觉', '正式定义', '公式推导', '进阶理论', '应用实操'])
})

test('course HTTP snapshots cannot overwrite a newer version with stale or equal data', () => {
  const current = { course_id: 'course-snapshot', version: 8, structure_status: 'expanding' } as Course
  assert.equal(newerCourse(null, current), current)
  assert.equal(newerCourse(current, { ...current, version: 7 }), current)
  assert.equal(newerCourse(current, { ...current }), current)
  const ready = { ...current, version: 9, structure_status: 'ready' as const }
  assert.equal(newerCourse(current, ready), ready)
})

test('blueprint review follows exact saved version and owner, including recovery after an absent snapshot', () => {
  const run = { run_id: 'review-run', status: 'awaiting_blueprint' as const, blueprint_version: 2 }
  const course = { creation_run_id: run.run_id, structure_status: 'blueprint' as const, blueprint_version: 2 }
  assert.equal(canReviewBlueprint(run, null), false)
  assert.equal(canReviewBlueprint(run, { ...course, blueprint_version: 1 }), false)
  assert.equal(canReviewBlueprint(run, { ...course, creation_run_id: 'old-parent' }), false)
  assert.equal(canReviewBlueprint({ ...run, status: 'generating' }, course), false)
  assert.equal(canReviewBlueprint(run, { ...course, structure_status: 'expanding' }), false)
  assert.equal(canReviewBlueprint(run, course), true)
  // Any later successful authoritative read can recover review; no stale local flag.
  assert.equal(canReviewBlueprint(run, null), false)
  assert.equal(canReviewBlueprint(run, course), true)
})

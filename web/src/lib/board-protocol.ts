import type { BoardFrame, BoardScript } from './types.ts'

const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(item => typeof item === 'string')
const kinds = new Set(['text', 'list', 'code', 'formula', 'box', 'arrow', 'highlight', 'mermaid', 'table', 'diagram', 'circle'])
const stages = new Set(['opening', 'explain', 'example', 'check', 'summary'])

/** The only accepted classroom format. This is a rejection boundary, not a
 * migration/defaulting function: saved legacy data is never rewritten. */
export function isBoardScriptV2(value: unknown): value is BoardScript {
  if (!record(value) || value.schema_version !== 2 || typeof value.title !== 'string' || !strings(value.objectives) || !value.objectives.length || !Array.isArray(value.roadmap) || !value.roadmap.length || !Array.isArray(value.steps) || !value.steps.length || value.steps.length > 36) return false
  if (!value.roadmap.every(point => record(point) && typeof point.keypoint_id === 'string' && typeof point.title === 'string' && typeof point.question === 'string' && Number.isInteger(point.source_keypoint_index) && Number(point.source_keypoint_index) >= 0)) return false
  if (!isBoardFrames(value.steps)) return false
  const ids = new Set<string>()
  for (const step of value.steps) {
    if (!record(step) || typeof step.step_id !== 'string' || typeof step.title !== 'string' || typeof step.narration !== 'string' || !stages.has(String(step.stage)) ||
      !(step.keypoint_id === null || typeof step.keypoint_id === 'string') || !strings(step.focus_ids) || !Number.isInteger(step.page) || ![1, 2].includes(Number(step.column)) || !Array.isArray(step.operations) ||
      !(step.check === null || record(step.check) && typeof step.check.question === 'string' && typeof step.check.expected_answer === 'string')) return false
    for (const operation of step.operations) {
      ids.add(operation.object_id)
      for (const node of operation.nodes) ids.add(node.id)
    }
    if (!step.focus_ids.every(id => ids.has(id))) return false
  }
  return true
}

/** Independent assistance uses frames, not a fabricated course script. New
 * object IDs and payloads are still required; legacy frames are rejected. */
export function isBoardFrames(value: unknown): value is BoardFrame[] {
  if (!Array.isArray(value) || !value.length || value.length > 36) return false
  const ids = new Set<string>()
  for (const frame of value) {
    if (!record(frame) || typeof frame.title !== 'string' || typeof frame.narration !== 'string' ||
      !Number.isInteger(frame.page) || Number(frame.page) < 1 || ![1, 2].includes(Number(frame.column)) ||
      !Array.isArray(frame.operations) || !frame.operations.length || frame.operations.length > 6) return false
    for (const operation of frame.operations) {
      if (!record(operation) || !kinds.has(String(operation.kind)) || typeof operation.object_id !== 'string' || !operation.object_id.trim() || ids.has(operation.object_id) ||
        !strings(operation.target_ids) || !operation.target_ids.every(id => ids.has(id)) || typeof operation.content !== 'string' || !strings(operation.items) ||
        typeof operation.language !== 'string' || !strings(operation.columns) || !Array.isArray(operation.rows) || !operation.rows.every(strings) ||
        !Array.isArray(operation.nodes) || !Array.isArray(operation.edges)) return false
      ids.add(operation.object_id)
      for (const node of operation.nodes) {
        if (!record(node) || typeof node.id !== 'string' || !node.id.trim() || ids.has(node.id) || typeof node.label !== 'string') return false
        ids.add(node.id)
      }
      const nodeIds = new Set(operation.nodes.map(node => (node as Record<string, unknown>).id))
      if (!operation.edges.every(edge => record(edge) && nodeIds.has(edge.from_id) && nodeIds.has(edge.to_id) && typeof edge.label === 'string')) return false
    }
  }
  return true
}

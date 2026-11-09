import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { test, expect } from '@playwright/test'
import type { LessonSnapshot } from '../src/lib/types'

const evidencePath = process.env.HYPERKNOW_TEACHER_CLASSROOM_EVIDENCE
const evidence = evidencePath ? JSON.parse(readFileSync(resolve(evidencePath), 'utf8')) as {
  course_id: string; session_id: string; status: string; basis_reference_count: number
  turns: { index: number; student_answer: string; action: string; response: string; board_object_ids: string[] }[]
} : null

test.describe('teacher-led classroom on a real model run', () => {
  test.skip(!evidence, 'Run verify_teacher_classroom.py and explicitly select its evidence first.')
  test.setTimeout(180_000)

  test('renders source basis, adaptive turns and committed board after refresh without a paid read', async ({ page }, info) => {
    const writes: string[] = []
    page.on('request', request => { if (request.method() !== 'GET') writes.push(`${request.method()} ${new URL(request.url()).pathname}`) })
    const before = await page.request.get(`/api/sessions/${evidence!.session_id}`)
    expect(before.ok()).toBeTruthy()
    const snapshot = await before.json() as LessonSnapshot
    expect(snapshot.protocol).toBe('teacher_led')
    expect(snapshot.teacher?.basis?.references.length).toBe(evidence!.basis_reference_count)
    expect(snapshot.teacher?.turns.length).toBe(evidence!.turns.length)
    await page.goto(`/courses/${evidence!.course_id}/sessions/${evidence!.session_id}`)
    await expect(page.locator('.teacher-classroom')).toBeVisible()
    await expect(page.locator('.teacher-turn')).toHaveCount(evidence!.turns.length)
    await expect(page.locator('.teacher-basis')).toBeVisible()
    await expect(page.locator('.board-render-error')).toHaveCount(0)
    await expect.poll(() => page.locator('.scene-object').count()).toBeGreaterThan(0)
    await page.screenshot({ path: info.outputPath('teacher-classroom.png'), fullPage: true })
    const turnTexts = await page.locator('.teacher-turn').allTextContents()
    for (const turn of evidence!.turns) expect(turnTexts[turn.index]).toContain(turn.response.slice(0, 24))
    const writesBeforeReload = writes.length
    await page.reload()
    await expect(page.locator('.teacher-turn')).toHaveCount(evidence!.turns.length)
    expect(writes.length).toBe(writesBeforeReload)
  })
})

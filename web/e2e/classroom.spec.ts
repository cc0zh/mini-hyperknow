import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { test, expect } from '@playwright/test'
import type { Page, TestInfo } from '@playwright/test'
import type { Course, LessonSnapshot } from '../src/lib/types'

// Explicit opt-in: only actual generated scripts in an isolated acceptance
// database. No route interception, provider doubles or response replay.
const evidencePath = process.env.HYPERKNOW_CLASSROOM_EVIDENCE
const evidence = evidencePath ? JSON.parse(readFileSync(resolve(evidencePath), 'utf8')) as {
  course_id: string; sessions: Record<string, { script_id: string; status: string }>
} : null
const legacyEvidence = !!evidence && !!evidence.sessions
const sessions = Object.keys(evidence?.sessions ?? {})
const allowModel = process.env.HYPERKNOW_CLASSROOM_ALLOW_MODEL === '1'

async function snapshot(page: Page, id: string): Promise<LessonSnapshot> {
  const response = await page.request.get(`/api/sessions/${id}`)
  expect(response.ok()).toBeTruthy()
  const result = await response.json() as LessonSnapshot
  // A wrong proxy must never write to an author's database with the same
  // course id. The exact acceptance script identity is required first.
  expect(result.script?.script_id).toBe(evidence!.sessions[id].script_id)
  return result
}

async function visit(page: Page, id: string) {
  const state = await snapshot(page, id)
  await page.goto(`/courses/${evidence!.course_id}/sessions/${id}`)
  await expect(page.locator('.classroom-screen')).toBeVisible()
  await expect(page.getByRole('navigation', { name: '主导航' })).toHaveCount(0)
  await expect(page.locator('.font-notice')).toHaveCount(0)
  await expect(page.locator('.board-render-error')).toHaveCount(0)
  return state
}

async function continueHeld(page: Page) {
  while (await page.locator('.classroom-hold').count()) {
    const previous = await page.locator('.classroom-hold').getAttribute('data-interaction-id')
    const resume = page.getByRole('button', { name: '继续课堂', exact: true })
    await expect(resume).toBeEnabled({ timeout: 180_000 })
    await resume.click()
    // A fresh browser may have several persisted terminal answers. Each one
    // needs its own explicit acknowledgement, not one blanket dismissal.
    await expect.poll(() => page.locator('.classroom-hold').evaluateAll(elements => elements[0]?.getAttribute('data-interaction-id') ?? null)).not.toBe(previous)
  }
}

async function next(page: Page, id: string) {
  const before = await snapshot(page, id)
  await page.getByRole('button', { name: '下一步', exact: true }).click()
  await expect.poll(async () => (await snapshot(page, id)).progress.cursor).toBe(before.progress.cursor + 1)
  await expect(page.locator('#narration-title')).toHaveText(before.script!.steps[before.progress.cursor + 1].title)
}

async function capture(page: Page, testInfo: TestInfo, name: string) {
  await page.locator('.board-scene').evaluate(async element => {
    await document.fonts.ready
    await Promise.allSettled(element.getAnimations({ subtree: true }).map(animation => animation.finished))
  })
  await expect.poll(() => page.locator('.board-viewport').evaluate(viewport => {
    const frame = viewport.getBoundingClientRect()
    return [...viewport.querySelectorAll('.scene-object')].filter(element => {
      const object = element.getBoundingClientRect()
      return object.width > 0 && object.left < frame.right && object.right > frame.left && object.top < frame.bottom && object.bottom > frame.top
    }).length
  })).toBeGreaterThan(0)
  await page.screenshot({ path: testInfo.outputPath(name), fullPage: true, animations: 'disabled' })
}

test.describe('complete classroom on actual generated lessons', () => {
  test.skip(!legacyEvidence, 'This file only covers retained legacy BoardScript evidence; use teacher-classroom.spec.ts for teacher-led evidence.')
  test.setTimeout(360_000)

  test('board and explanation review together; camera and refresh preserve confirmed position', async ({ page }, info) => {
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    const id = sessions[0]
    let state = await visit(page, id)
    await continueHeld(page)
    while (state.progress.cursor < 2) { await next(page, id); state = await snapshot(page, id) }
    await capture(page, info, 'classroom-current.png')
    await page.locator('.confirmed-history button').first().click()
    await expect(page.locator('#narration-title')).toHaveText(state.script!.steps[0].title)
    const visibleIds = await page.locator('.scene-object[data-object-id]').evaluateAll(elements => elements.map(element => element.getAttribute('data-object-id')))
    expect(visibleIds).toEqual(state.script!.steps[0].operations.filter(operation => !operation.target_ids.length).map(operation => operation.object_id))
    expect((await snapshot(page, id)).progress.cursor).toBe(state.progress.cursor)
    await page.getByRole('button', { name: '向右浏览白板' }).click()
    await expect(page.locator('.board-toolbar')).toContainText('自由浏览')
    await page.getByRole('button', { name: '回到当前讲解', exact: true }).click()
    await expect(page.locator('#narration-title')).toHaveText(state.script!.steps[state.progress.cursor].title)
    await expect(page.locator('.board-toolbar')).toContainText('自动跟随')
    const modelWrites: string[] = []
    page.on('request', request => { if (request.method() === 'POST' && /\/(prepare|regenerate|questions)$/.test(new URL(request.url()).pathname)) modelWrites.push(request.url()) })
    await page.reload()
    const stage = state.script!.steps[state.progress.cursor]?.stage
    await expect(page.locator('.classroom-play-state')).toContainText(stage === 'summary' ? '最终总结已展示' : stage === 'check' ? '自动暂停' : '已暂停')
    await expect(page.locator('.classroom-play-actions').getByRole('button', { name: '暂停', exact: true })).toHaveCount(0)
    expect((await snapshot(page, id)).progress.cursor).toBe(state.progress.cursor)
    expect(modelWrites).toEqual([])
    await page.getByRole('button', { name: '收起讲解' }).click()
    await expect(page.locator('#classroom-sidebar')).toHaveCount(0)
    await capture(page, info, 'classroom-board-only.png')
    await page.setViewportSize({ width: 1024, height: 768 })
    await page.getByRole('button', { name: '展开讲解' }).click()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    await expect(page.getByRole('button', { name: '下一步', exact: true })).toBeInViewport()
    await page.emulateMedia({ reducedMotion: 'reduce' })
    expect(await page.locator('.board-scene').evaluate(element => getComputedStyle(element).transitionDuration)).toBe('0s')
    await capture(page, info, 'classroom-1024-reduced-motion.png')
    expect(errors).toEqual([])
  })

  test('actual anchored question and check feedback persist; explicit return and final completion', async ({ page }, info) => {
    test.skip(!allowModel, 'Explicit model authorization is required; this test can create two real paid answers.')
    const id = sessions[0]
    let state = await visit(page, id)
    await continueHeld(page)
    const question = '课堂验收提问：请结合这块板书，用一个具体反例解释为什么使用工具并不必然就是智能体。'
    if (!state.interactions.some(item => item.question === question)) {
      await page.locator('.confirmed-history button').first().click()
      const object = state.script!.steps[0].operations[0]
      await page.locator(`[data-object-id="${object.object_id}"]`).click()
      await page.getByRole('button', { name: '插问', exact: true }).click()
      await page.getByLabel('你的问题', { exact: true }).fill(question)
      await page.getByRole('button', { name: '暂停并提问', exact: true }).click()
    } else await page.getByRole('button', { name: /问答历史/ }).click()
    await expect.poll(async () => (await snapshot(page, id)).interactions.find(item => item.question === question)?.status, { timeout: 180_000 }).toBe('ready')
    state = await snapshot(page, id)
    const interaction = state.interactions.find(item => item.question === question)!
    expect(interaction.anchor_step_id).toBe(state.script!.steps[0].step_id)
    expect(interaction.anchor_object_id).toBe(state.script!.steps[0].operations[0].object_id)
    expect(interaction.answer!.length).toBeGreaterThan(30)
    await capture(page, info, 'classroom-real-question-answer.png')
    await continueHeld(page)
    await page.getByRole('button', { name: '同步讲解', exact: true }).click()
    const checkIndex = state.script!.steps.findIndex(step => step.stage === 'check')
    while ((await snapshot(page, id)).progress.cursor < checkIndex) await next(page, id)
    state = await snapshot(page, id)
    if (state.progress.cursor > checkIndex) await page.locator('.confirmed-history button').nth(checkIndex).click()
    await expect(page.locator('.classroom-check')).toBeVisible()
    await expect(page.locator('.classroom-check details')).not.toHaveAttribute('open')
    const check = state.script!.steps[checkIndex].check!
    const answerPrefix = `理解检查：${check.question}\n我的回答：`
    if (!state.interactions.some(item => item.question.startsWith(answerPrefix))) {
      await page.getByLabel('你的思考').fill('我的判断依据是控制权与路径来源：模型提出请求，程序执行；使用工具本身不能证明模型拥有运行时选择权。请检查我的推理。')
      await page.getByRole('button', { name: '提交回答，获得真实反馈' }).click()
    }
    await expect.poll(async () => (await snapshot(page, id)).interactions.find(item => item.question.startsWith(answerPrefix))?.status, { timeout: 180_000 }).toBe('ready')
    await continueHeld(page)
    await page.getByRole('button', { name: '同步讲解', exact: true }).click()
    while ((await snapshot(page, id)).progress.cursor < state.script!.steps.length - 1) await next(page, id)
    if (!(await snapshot(page, id)).completed) await page.getByRole('button', { name: '确认完成本课', exact: true }).click()
    await expect.poll(async () => (await snapshot(page, id)).completed).toBe(true)
    await page.reload()
    await expect(page.locator('.classroom-progress-label')).toContainText('课时已完成 · 不代表掌握')
    state = await snapshot(page, id)
    expect(state.interactions.some(item => item.question.startsWith(answerPrefix) && item.answer)).toBe(true)
    await capture(page, info, 'classroom-summary-completed.png')
  })

  test('actual flow and code lessons render diagrams, formulae and tables without runtime errors', async ({ page }, info) => {
    test.skip(sessions.length < 3, 'This check requires actual concept, flow and code lesson identities, not an empty loop.')
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    for (const id of sessions.slice(1)) {
      const state = await visit(page, id)
      const kinds = new Set(state.script!.steps.flatMap(step => step.operations.map(operation => operation.kind)))
      for (const kind of ['diagram', 'code', 'formula', 'table']) {
        if (!kinds.has(kind as never)) continue
        const index = state.script!.steps.findIndex(step => step.operations.some(operation => operation.kind === kind))
        await page.locator('.confirmed-history button').nth(index).click()
        await expect(page.locator('#narration-title')).toHaveText(state.script!.steps[index].title)
        // Keyboard selection also exercises real object focus, even when an
        // earlier object in this step is initially outside the clipped camera.
        const object = state.script!.steps[index].operations.find(operation => operation.kind === kind)!
        await page.locator(`[data-object-id="${object.object_id}"]`).press('Enter')
        await expect(page.locator('.board-render-error')).toHaveCount(0)
        if (kind === 'formula') await expect(page.locator('.katex').first()).toBeAttached()
        await capture(page, info, `${id}-${kind}.png`)
      }
    }
    expect(errors).toEqual([])
  })

  test('every confirmed step fits one ordered board; overview, resize and cache updates stay explicit', async ({ page }, info) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    const writes: string[] = [], errors: string[] = []
    page.on('request', request => { if (['POST', 'PUT', 'DELETE'].includes(request.method())) writes.push(`${request.method()} ${request.url()}`) })
    page.on('pageerror', error => errors.push(error.message))
    let confirmations = 0
    async function geometry(index: number) {
      await page.locator('.board-scene').evaluate(async element => {
        await document.fonts.ready
        await Promise.allSettled(element.getAnimations({ subtree: true }).map(animation => animation.finished))
      })
      await expect.soft.poll(() => page.locator('.board-viewport').evaluate((viewport, step) => {
        const frame = viewport.getBoundingClientRect()
        const sheet = viewport.querySelector(`[data-step-region="${step}"]`)
        const blocks = [...viewport.querySelectorAll<HTMLElement>(`.scene-object[data-step-index="${step}"]`)]
        const problems: string[] = []
        const inside = (rect: DOMRect) => rect.width > 0 && rect.height > 0 && rect.left >= frame.left - 1 && rect.right <= frame.right + 1 && rect.top >= frame.top - 1 && rect.bottom <= frame.bottom + 1
        if (!sheet || !inside(sheet.getBoundingClientRect())) problems.push('step sheet cropped')
        if (!blocks.length) problems.push('no actual board objects')
        for (const block of blocks) {
          const id = block.dataset.objectId!
          if (!inside(block.getBoundingClientRect())) problems.push(`${id}: block cropped`)
          if (block.scrollHeight > block.clientHeight + 2 || block.scrollWidth > block.clientWidth + 2) problems.push(`${id}: internal content overflow ${block.scrollWidth}x${block.scrollHeight}/${block.clientWidth}x${block.clientHeight}`)
          for (const content of block.querySelectorAll<HTMLElement>('.board-code pre, .board-formula')) {
            if (content.scrollWidth > content.clientWidth + 2 || content.scrollHeight > content.clientHeight + 2) problems.push(`${id}: nested ${content.className || content.tagName} overflow ${content.scrollWidth}x${content.scrollHeight}/${content.clientWidth}x${content.clientHeight}, font ${getComputedStyle(content).fontSize}`)
          }
          for (const svg of block.querySelectorAll<SVGSVGElement>('.board-diagram')) {
            const area = svg.getBoundingClientRect()
            for (const text of svg.querySelectorAll('text')) {
              const box = text.getBoundingClientRect()
              if (box.left < area.left - 2 || box.right > area.right + 2 || box.top < area.top - 2 || box.bottom > area.bottom + 2) problems.push(`${id}: diagram text clipped: ${text.textContent}`)
            }
          }
        }
        return problems
      }, index), { timeout: 1000, message: `Step ${index + 1} must fit without hidden text or clipped SVG labels` }).toEqual([])
    }
    for (const id of sessions) {
      const before = await visit(page, id)
      expect(before.progress.cursor).toBeGreaterThanOrEqual(0)
      for (const viewport of [{ width: 1440, height: 1000 }, { width: 1024, height: 768 }]) {
        await page.setViewportSize(viewport)
        for (let index = 0; index <= before.progress.cursor; index += 1) {
          await page.locator('.confirmed-history button').nth(index).click()
          await expect(page.locator('#narration-title')).toHaveText(before.script!.steps[index].title)
          await expect(page.locator('#narration-title')).toBeInViewport()
          await geometry(index)
          if ([0, Math.floor(before.progress.cursor / 2), before.progress.cursor].includes(index)) await capture(page, info, `${id}-step-${index + 1}-${viewport.width}.png`)
          const ids = await page.locator(`.scene-object[data-step-index="${index}"]`).evaluateAll(elements => elements.map(element => element.getAttribute('data-object-id')))
          expect(ids).toEqual(before.script!.steps[index].operations.filter(operation => !operation.target_ids.length).map(operation => operation.object_id))
        }
      }
      const index = before.progress.cursor
      const object = page.locator(`.scene-object[data-step-index="${index}"]`).first()
      const selectedId = await object.getAttribute('data-object-id')
      await object.press('Enter')
      await expect(page.locator('.board-viewport')).toHaveAttribute('data-view-mode', 'detail')
      await page.getByRole('button', { name: '本步全览', exact: true }).click()
      await expect(page.locator('.board-viewport')).toHaveAttribute('data-view-mode', 'overview')
      await expect(page.locator(`.scene-object[data-object-id="${selectedId}"]`)).toHaveClass(/selected/)
      await geometry(index)
      await page.getByRole('button', { name: '收起讲解', exact: true }).click()
      await geometry(index)
      await page.getByRole('button', { name: '展开讲解', exact: true }).click()
      await geometry(index)
      await page.locator('.classroom-script-settings summary').click()
      await expect(page.locator('.classroom-script-settings')).toContainText('不是每点下一步都请求模型')
      const regenerate = page.getByRole('button', { name: '使用新版讲解重新生成', exact: true })
      if (await regenerate.isEnabled()) {
        await regenerate.click()
        await expect(page.getByRole('group', { name: '确认重新生成讲义' })).toContainText('可能收费')
        await page.getByRole('button', { name: '保留当前讲义', exact: true }).click()
        await expect(page.getByRole('group', { name: '确认重新生成讲义' })).toHaveCount(0)
        confirmations += 1
      }
      const after = await snapshot(page, id)
      expect(after.progress).toEqual(before.progress)
      expect(after.completed).toBe(before.completed)
    }
    expect(confirmations).toBeGreaterThan(0)
    expect(writes).toEqual([])
    expect(errors).toEqual([])
  })

  test('an actual unprepared session opens safely and never prepares a paid lesson on read or refresh', async ({ page }, info) => {
    await snapshot(page, sessions[0])
    const response = await page.request.get(`/api/courses/${evidence!.course_id}`)
    expect(response.ok()).toBeTruthy()
    const course = await response.json() as Course
    expect(course.course_id).toBe(evidence!.course_id)
    const candidates = course.units.flatMap(unit => unit.lectures.flatMap(lecture => lecture.sessions.map(session => session.session_id)))
    let id: string | undefined
    for (const candidate of candidates.filter(candidate => !sessions.includes(candidate))) {
      const state = await (await page.request.get(`/api/sessions/${candidate}`)).json() as LessonSnapshot
      if (!state.script && !state.format_error && !state.generation_run) { id = candidate; break }
    }
    test.skip(!id, 'This actual course has no unprepared session; do not manufacture a model result.')
    const writes: string[] = [], errors: string[] = []
    page.on('request', request => { if (['POST', 'PUT', 'DELETE'].includes(request.method())) writes.push(request.url()) })
    page.on('pageerror', error => errors.push(error.message))
    await page.goto(`/courses/${evidence!.course_id}/sessions/${id}`)
    await expect(page.getByRole('button', { name: '准备本课讲义', exact: true })).toBeVisible()
    await page.reload()
    await expect(page.getByRole('button', { name: '准备本课讲义', exact: true })).toBeVisible()
    await expect(page.locator('.scene-object')).toHaveCount(0)
    await page.screenshot({ path: info.outputPath('classroom-unprepared.png'), fullPage: true })
    expect(writes).toEqual([])
    expect(errors).toEqual([])
  })
})

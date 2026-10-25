import { test, expect } from '@playwright/test'

// Actual local service only. No intercepted requests, synthetic course API, or
// recorded provider responses. The paid scenario is explicitly opt-in.
const errors: string[] = []
test.beforeEach(({ page }) => {
  errors.length = 0
  page.on('pageerror', error => errors.push(error.message))
})
test.afterEach(() => { expect(errors).toEqual([]) })

test('saved real course can be explored without writes or losing the fixed action area', async ({ page }, testInfo) => {
  const runs = (await (await page.request.get('/api/runs')).json()).runs
  const run = runs.find((item: { kind: string; status: string; course_id: string | null }) => item.kind === 'course' && item.status === 'ready' && item.course_id)
  test.skip(!run, 'Requires an already saved real course run; no example course is manufactured.')
  const course = await (await page.request.get(`/api/courses/${run.course_id}`)).json()
  const writes: string[] = []
  let courseReads = 0
  page.on('request', request => { if (request.method() === 'GET' && new URL(request.url()).pathname === `/api/courses/${run.course_id}`) courseReads += 1 })
  page.on('request', request => { if (request.method() !== 'GET' && request.url().includes('/api/')) writes.push(request.url()) })
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto(`/course-runs/${run.run_id}`)
  const footer = page.getByRole('region', { name: '当前阶段操作' })
  await expect(footer.getByRole('link', { name: '开始学习' })).toBeVisible()
  await expect(page.locator('.sidebar')).toHaveCount(0)
  await expect(page.locator('.bx-unit-card')).toHaveCount(course.units.length)
  const actionBox = await footer.boundingBox()
  for (const unit of await page.locator('.bx-unit-card').all()) {
    const box = await unit.boundingBox()
    expect(box!.y + box!.height).toBeLessThanOrEqual(actionBox!.y)
  }
  const unit = page.locator('.bx-unit-card').last()
  await unit.click()
  await expect(unit).toHaveAttribute('aria-pressed', 'true')
  const session = page.locator('.bx-session').first()
  if (await session.count()) {
    await session.click()
    await expect(session).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByRole('region', { name: '所选节点完整详情' }).getByRole('link', { name: '进入课堂' })).toHaveAttribute('href', /\/sessions\//)
    const reads = courseReads
    await expect.poll(() => courseReads, { timeout: 12_000 }).toBeGreaterThan(reads)
    await expect(session).toHaveAttribute('aria-pressed', 'true')
    await expect(session).toBeFocused()
  }
  await page.locator('.wb-research-disclosure > summary').click()
  await page.locator('.wb-context').evaluate(element => { element.scrollTop = element.scrollHeight })
  await expect(footer.getByRole('link', { name: '开始学习' })).toBeInViewport()
  await expect(page.locator('.wb-result-heading')).toBeInViewport()
  await page.screenshot({ path: testInfo.outputPath('saved-workbench.png'), fullPage: true })
  expect(writes).toEqual([])
  await page.reload()
  await expect(footer.getByRole('link', { name: '开始学习' })).toBeVisible()
  expect(writes).toEqual([])
  await page.setViewportSize({ width: 1024, height: 768 })
  await expect(footer.getByRole('link', { name: '开始学习' })).toBeInViewport()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1024)
  await page.screenshot({ path: testInfo.outputPath('saved-workbench-1024.png'), fullPage: true })
  await page.setViewportSize({ width: 1440, height: 600 })
  await page.locator('.bx-session').first().click()
  await expect(footer.getByRole('link', { name: '开始学习' })).toBeInViewport()
  await page.getByRole('region', { name: '所选节点完整详情' }).locator('.bx-detail-scroll').evaluate(element => { element.scrollTop = element.scrollHeight })
  await expect(page.getByRole('region', { name: '所选节点完整详情' }).getByRole('link', { name: '进入课堂' })).toBeInViewport()
  await page.screenshot({ path: testInfo.outputPath('saved-workbench-low-height.png'), fullPage: true })
})

test('real stopped runs preserve the reason and guide readers away from a superseded owner', async ({ page }, testInfo) => {
  const runs = (await (await page.request.get('/api/runs')).json()).runs
  const stopped = runs.filter((run: { kind: string; status: string }) => run.kind === 'course' && ['failed', 'cancelled', 'interrupted'].includes(run.status))
  test.skip(!stopped.length, 'Requires real stopped runs; does not create failures for presentation.')
  const writes: string[] = []
  page.on('request', request => { if (request.method() !== 'GET' && request.url().includes('/api/')) writes.push(request.url()) })
  for (const run of stopped) {
    await page.goto(`/course-runs/${run.run_id}?history=1`)
    await expect(page.locator('.wb-current')).toContainText(/没有完成|已停止|已中断/)
    await expect(page.locator('.bx-generating')).toHaveCount(0)
    if (run.error) await expect(page.locator('.error-notice')).toContainText(run.error.message)
    if (run.course_id) {
      const course = await (await page.request.get(`/api/courses/${run.course_id}`)).json()
      await expect(page.locator('.bx-unit-card')).toHaveCount(course.units.length)
      if (course.creation_run_id !== run.run_id) {
        await expect(page.getByRole('link', { name: '查看最新生成状态' })).toHaveAttribute('href', `/course-runs/${course.creation_run_id}`)
        await expect(page.getByRole('button', { name: '继续生成剩余内容' })).toHaveCount(0)
      }
    }
    await page.screenshot({ path: testInfo.outputPath(`${run.run_id}-stopped.png`), fullPage: true })
  }
  expect(writes).toEqual([])
})

test('real creation keeps choices, waits for one approval and expands automatically', async ({ page }, testInfo) => {
  test.skip(process.env.HYPERKNOW_VERIFY_WORKBENCH !== '1', 'Explicit paid model/search acceptance; set HYPERKNOW_VERIFY_WORKBENCH=1.')
  test.setTimeout(1_200_000)
  await page.setViewportSize({ width: 1440, height: 900 })
  const health = await (await page.request.get('/api/health')).json()
  expect(health.model.configured).toBe(true)
  const writes: { path: string; body: Record<string, unknown> }[] = []
  page.on('request', request => {
    if (request.method() === 'POST' && request.url().includes('/api/')) writes.push({ path: new URL(request.url()).pathname, body: request.postDataJSON() })
  })
  const chosen: string[] = []
  const resume = process.env.HYPERKNOW_WORKBENCH_RUN_ID
  if (resume) {
    await page.goto(`/course-runs/${encodeURIComponent(resume)}`)
    const retry = page.getByRole('button', { name: '继续生成剩余内容' })
    await expect(retry.or(page.getByRole('button', { name: '确认并完善课程' }))).toBeEnabled()
    if (await retry.count()) {
      await retry.click()
      await expect(page).not.toHaveURL(new RegExp(`${resume}$`))
    }
  } else {
    await page.goto('/')
    await page.getByLabel('你想探索什么？').fill(process.env.HYPERKNOW_WORKBENCH_GOAL ?? '我会 Python 基础，希望用两小时理解迭代器、生成器、惰性求值和资源清理。请安排四个紧凑单元，每个单元一个小节，使用中文，以官方 Python 文档与 PEP 为主要依据；不安排全局项目和考核。')
    await page.getByRole('button', { name: '打造课程' }).click()
    await expect(page).toHaveURL(/\/course-runs\//)
    await expect(page.locator('.wb-questions')).toBeVisible({ timeout: 180_000 })
    for (const field of await page.locator('.question-field').all()) {
      const option = field.locator('.answer-option').first()
      chosen.push((await option.locator('b').textContent())!)
      await option.click()
    }
    await page.screenshot({ path: testInfo.outputPath('real-clarification.png'), fullPage: true })
    await page.getByRole('button', { name: '提交偏好并继续' }).click()
  }
  const runId = page.url().split('/').at(-1)!
  await expect(page.locator('.wb-preference-tags')).toBeVisible()
  for (const choice of chosen) await expect(page.locator('.wb-preference-tags')).toContainText(choice)
  const confirm = page.getByRole('button', { name: '确认并完善课程' })
  await expect(confirm.or(page.getByRole('button', { name: '继续生成剩余内容' }))).toBeVisible({ timeout: 600_000 })
  await expect(confirm).toBeEnabled()
  const waiting = await (await page.request.get(`/api/runs/${runId}`)).json()
  const before = await (await page.request.get(`/api/courses/${waiting.course_id}`)).json()
  expect(waiting.status).toBe('awaiting_blueprint')
  expect(before.session_count).toBe(0)
  expect(before.units.every((unit: { lectures: unknown[] }) => unit.lectures.length === 0)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('real-waiting-blueprint.png'), fullPage: true })
  await page.getByRole('button', { name: '调整方向', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '调整课程方向' })
  await expect(dialog.getByRole('button', { name: '提交修改意见' })).toBeDisabled()
  await dialog.getByLabel('修改意见').fill('保持四个紧凑单元及每单元一个小节。每个单元先给最小可运行例子，再解释边界；不要增加项目或考核。')
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
  await expect(page.getByRole('button', { name: '调整方向', exact: true })).toBeFocused()
  await page.getByRole('button', { name: '调整方向', exact: true }).click()
  await expect(dialog.getByLabel('修改意见')).toHaveValue(/保持四个/)
  await dialog.getByRole('button', { name: '提交修改意见' }).click()
  await expect(page.getByRole('button', { name: '确认并完善课程' })).toBeEnabled({ timeout: 180_000 })
  const revised = await (await page.request.get(`/api/courses/${waiting.course_id}`)).json()
  expect(revised.blueprint_version).toBeGreaterThan(before.blueprint_version)
  expect(revised.session_count).toBe(0)
  await page.reload()
  await expect(page.getByRole('button', { name: '确认并完善课程' })).toBeEnabled()
  const unit = page.locator('.bx-unit-card').last()
  await unit.click()
  await expect(unit).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: '确认并完善课程' }).click()
  await expect(page.getByRole('button', { name: '停止生成', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '确认并完善课程' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: '开始学习' }).or(page.getByRole('button', { name: '继续生成剩余内容' }))).toBeVisible({ timeout: 600_000 })
  const terminal = await (await page.request.get(`/api/runs/${runId}`)).json()
  await testInfo.attach('real-terminal-state', { body: JSON.stringify({ runId, chosen, writes, terminal }, null, 2), contentType: 'application/json' })
  expect(terminal.status, JSON.stringify(terminal.error)).toBe('ready')
  await expect(page.getByRole('link', { name: '开始学习' })).toBeVisible()
  await expect(unit).toHaveAttribute('aria-pressed', 'true')
  const final = await (await page.request.get(`/api/courses/${waiting.course_id}`)).json()
  expect(final.structure_status).toBe('ready')
  expect(final.units.every((item: { generation_status: string }) => item.generation_status === 'ready')).toBe(true)
  expect(writes.filter(item => item.path.endsWith('/blueprint') && item.body.approve === true)).toHaveLength(1)
  await page.screenshot({ path: testInfo.outputPath('real-ready-workbench.png'), fullPage: true })
  await testInfo.attach('real-workbench-evidence', { body: JSON.stringify({ runId, chosen, before, revised, final, writes }, null, 2), contentType: 'application/json' })
})

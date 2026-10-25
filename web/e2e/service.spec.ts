import { test, expect } from '@playwright/test'
import { recoverableCourseRuns } from '../src/lib/run-state'

const diagnostics = new Map<string, { console: string[]; errors: string[]; failedResponses: string[] }>()
test.beforeEach(({ page }, testInfo) => {
  const log = { console: [] as string[], errors: [] as string[], failedResponses: [] as string[] }
  diagnostics.set(testInfo.testId, log)
  page.on('console', message => {
    if (message.type() === 'error' || message.type() === 'warning') log.console.push(`${message.type()}: ${message.text()}`)
  })
  page.on('pageerror', error => log.errors.push(error.message))
  page.on('response', response => {
    if (response.status() >= 400) log.failedResponses.push(`${response.status()} ${new URL(response.url()).pathname}`)
  })
})
test.afterEach(async ({ page: _page }, testInfo) => {
  const log = diagnostics.get(testInfo.testId)!
  await testInfo.attach('console-diagnostics', { body: JSON.stringify(log, null, 2), contentType: 'application/json' })
  expect(log.errors).toEqual([])
  diagnostics.delete(testInfo.testId)
})

// These tests require the REAL local backend. No request interception, mock
// responses, generated example courses, or simulated model dependencies.
test('goal constraints match the real API before sending a command', async ({ page }) => {
  await page.goto('/')
  const goal = page.getByLabel('你想探索什么？')
  const submit = page.getByRole('button', { name: '打造课程' })
  await expect(goal).toHaveAttribute('maxlength', '4000')
  await goal.fill('学')
  await expect(submit).toBeDisabled()
  await goal.fill('学习')
  await expect(submit).toBeEnabled()
})

test('home and course library read the real local service', async ({ page }, testInfo) => {
  const consoleErrors: string[] = []
  page.on('pageerror', error => consoleErrors.push(error.message))
  const health = await page.request.get('/api/health')
  expect(health.status()).toBe(200)
  await page.goto('/')
  await expect(page).toHaveTitle('Hyperknow · 你的学习路径')
  await expect(page.getByRole('heading', { name: /让一个学习目标/ })).toBeVisible()
  await expect(page.getByRole('button', { name: '打造课程' })).toBeDisabled()
  await expect(page.getByRole('navigation', { name: '主导航' }).getByRole('link')).toHaveCount(3)
  await page.screenshot({ path: testInfo.outputPath('home-unconfigured.png'), fullPage: true })
  await page.getByRole('navigation').getByRole('link', { name: '我的课程' }).click()
  await expect(page.getByRole('heading', { name: '我的课程.' })).toBeVisible()
  await expect(page.locator('.loading')).toHaveCount(0)
  const courses = await (await page.request.get('/api/courses')).json()
  const runs = await (await page.request.get('/api/runs')).json()
  await expect(page.locator('.course-card')).toHaveCount(courses.courses.length)
  await expect(page.locator('.recoverable-run')).toHaveCount(recoverableCourseRuns(runs.runs, courses.courses).length)
  if (courses.courses.length === 0) await expect(page.getByRole('heading', { name: '你的学习旅程，尚待启程' })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('courses-real-list.png'), fullPage: true })
  await testInfo.attach('browser-errors', { body: JSON.stringify(consoleErrors), contentType: 'application/json' })
  expect(consoleErrors).toEqual([])
  expect(diagnostics.get(testInfo.testId)?.console).toEqual([])
})

test('unconfigured model shows real 503 and retries the same command after refresh', async ({ page }, testInfo) => {
  const health = await (await page.request.get('/api/health')).json()
  test.skip(health.model.configured, 'Only applicable to the real no-configuration environment; does not validate successful generation.')
  const requests: { goal: string; client_command_id: string }[] = []
  page.on('request', request => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/course-runs') requests.push(request.postDataJSON())
  })
  await page.goto('/')
  await expect(page.locator('#main').getByText('模型尚未配置', { exact: true })).toBeVisible()
  await page.getByLabel('你想探索什么？').fill('真实浏览器无模型验证：学习线性代数的几何直觉')
  const first = page.waitForResponse(response => response.url().endsWith('/api/course-runs') && response.request().method() === 'POST')
  // Two synchronous user activations must still produce a single HTTP write.
  await page.getByRole('button', { name: '打造课程' }).evaluate(button => {
    ;(button as HTMLButtonElement).click()
    ;(button as HTMLButtonElement).click()
  })
  expect((await first).status()).toBe(503)
  await expect(page.locator('.error-notice')).toContainText(/\.env|模型/)
  await page.screenshot({ path: testInfo.outputPath('real-create-503.png'), fullPage: true })
  await page.reload()
  await expect(page.getByLabel('你想探索什么？')).toBeDisabled()
  await expect(page.getByLabel('你想探索什么？')).toHaveValue(requests[0].goal)
  const retry = page.waitForResponse(response => response.url().endsWith('/api/course-runs') && response.request().method() === 'POST')
  await page.getByRole('button', { name: '重试同一请求' }).click()
  expect((await retry).status()).toBe(503)
  expect(requests).toHaveLength(2)
  expect(requests[1]).toEqual(requests[0])
  await page.screenshot({ path: testInfo.outputPath('same-command-after-refresh.png'), fullPage: true })
  await testInfo.attach('real-submitted-command-identities', { body: JSON.stringify(requests), contentType: 'application/json' })
  const courses = await (await page.request.get('/api/courses')).json()
  expect(courses.courses.every((course: { goal: string }) => course.goal !== requests[0].goal)).toBe(true)
})

test('missing resources show actual errors rather than a normal empty view', async ({ page }, testInfo) => {
  await page.goto('/courses/missing-course-browser-check')
  await expect(page.locator('.error-notice')).toContainText('课程加载失败')
  await expect(page.locator('.empty-state')).toHaveCount(0)
  await page.goto('/course-runs/missing-run-browser-check')
  await expect(page.locator('.error-notice')).toContainText('运行加载失败', { timeout: 15_000 })
  await expect(page.getByRole('button', { name: '重新加载' })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('missing-run-real-error.png'), fullPage: true })
})

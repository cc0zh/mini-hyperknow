import { test, expect } from '@playwright/test'
import type { Course } from '../src/lib/types'

// Read existing, real courses only. Never generate courses, intercept the API,
// or invoke a model to make a missing acceptance state appear.
const logs = new Map<string, { errors: string[]; writes: string[] }>()
test.beforeEach(({ page }, info) => {
  const log = { errors: [] as string[], writes: [] as string[] }
  logs.set(info.testId, log)
  page.on('pageerror', error => log.errors.push(error.message))
  page.on('request', request => {
    if (request.url().includes('/api/') && request.method() !== 'GET') log.writes.push(`${request.method()} ${request.url()}`)
  })
})
test.afterEach(async ({ page: _page }, info) => {
  const log = logs.get(info.testId)!
  await info.attach('read-only-browser-check', { body: JSON.stringify(log), contentType: 'application/json' })
  expect(log.errors).toEqual([])
  expect(log.writes).toEqual([])
  logs.delete(info.testId)
})

test('unit selection survives refresh and history, and invalid URLs recover without losing other parameters', async ({ page }) => {
  const { courses }: { courses: Course[] } = await (await page.request.get('/api/courses')).json()
  const course = courses.find(item => !['blueprint', 'expanding'].includes(item.structure_status ?? '') && item.units.length > 1)
  test.skip(!course, 'Requires an existing complete real course with multiple units.')
  const saved = course!
  const base = `/courses/${encodeURIComponent(saved.course_id)}`
  const initial = saved.units.find(unit => unit.unit_id === saved.next_item?.unit_id) ?? saved.units[0]
  const other = saved.units.find(unit => unit.unit_id !== initial.unit_id)!
  await page.goto(base)
  await expect(page.locator('#current-unit-title')).toHaveText(initial.title)
  await expect.poll(() => new URL(page.url()).searchParams.get('unit')).toBe(initial.unit_id)
  const navigation = page.getByRole('navigation', { name: '课程单元', exact: true })
  await expect(navigation.getByRole('link')).toHaveCount(saved.units.length)
  const selectOther = navigation.getByRole('link').filter({ hasText: other.title })
  await selectOther.focus()
  await page.keyboard.press('Enter')
  await expect(selectOther).toHaveAttribute('aria-current', 'step')
  await expect(page.locator('#current-unit-title')).toHaveText(other.title)
  await expect(page.locator('.cp-session')).toHaveCount(other.lectures.reduce((count, lecture) => count + lecture.sessions.length, 0))
  await page.reload()
  await expect(page.locator('#current-unit-title')).toHaveText(other.title)
  await page.goBack()
  await expect(page.locator('#current-unit-title')).toHaveText(initial.title)
  await page.goForward()
  await expect(page.locator('#current-unit-title')).toHaveText(other.title)
  await page.goto(`${base}?unit=missing-unit&source=overview-check`)
  await expect(page.locator('#current-unit-title')).toHaveText(initial.title)
  await expect.poll(() => new URL(page.url()).searchParams.get('unit')).toBe(initial.unit_id)
  expect(new URL(page.url()).searchParams.get('source')).toBe('overview-check')
  const after: Course = await (await page.request.get(`/api/courses/${saved.course_id}`)).json()
  expect(after.version).toBe(saved.version)
})

test('real lesson actions and progressive details remain usable across desktop and narrow layouts', async ({ page }, info) => {
  const { courses }: { courses: Course[] } = await (await page.request.get('/api/courses')).json()
  const course = courses.find(item => item.units.some(unit => unit.lectures.some(lecture => lecture.sessions.length)))
  test.skip(!course, 'Requires real saved lessons; none are manufactured.')
  const saved = course!
  const unit = saved.units.find(item => item.lectures.some(lecture => lecture.sessions.length))!
  const session = unit.lectures.flatMap(lecture => lecture.sessions)[0]
  const base = `/courses/${encodeURIComponent(saved.course_id)}`
  await page.goto(`${base}?unit=${encodeURIComponent(unit.unit_id)}`)
  await expect(page.locator('#current-unit-title')).toHaveText(unit.title)
  const lesson = page.locator('.cp-session').first()
  await expect(lesson.getByRole('link').first()).toHaveAttribute('href', `${base}/sessions/${encodeURIComponent(session.session_id)}`)
  await expect(lesson.getByRole('link', { name: `课后练习：${session.title}`, exact: true })).toHaveAttribute('href', `${base}/sessions/${encodeURIComponent(session.session_id)}/practice`)
  await expect(lesson.locator('details')).not.toHaveAttribute('open', '')
  await lesson.locator('summary').focus()
  await page.keyboard.press('Enter')
  await expect(lesson.locator('details')).toHaveAttribute('open', '')
  if (session.description) await expect(lesson.locator('.cp-detail-body')).toContainText(session.description)
  await lesson.locator('summary').click()
  await page.getByRole('button', { name: /^展开简介/ }).click()
  await expect(page.getByRole('button', { name: /^收起简介/ })).toHaveAttribute('aria-expanded', 'true')
  await page.getByRole('button', { name: /^收起简介/ }).click()
  for (const [width, height] of [[1440, 900], [1024, 768], [768, 1024], [390, 844], [320, 740]]) {
    await page.setViewportSize({ width, height })
    await expect(page.locator('#current-unit-title')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    if (width === 1440 || width === 390) await page.screenshot({ path: info.outputPath(`course-overview-${width}.png`), fullPage: true })
  }
  if (saved.units.length > 1) {
    const other = saved.units.find(item => item.unit_id !== unit.unit_id)!
    await page.getByLabel('当前单元', { exact: true }).selectOption(other.unit_id)
    await expect(page.locator('#current-unit-title')).toHaveText(other.title)
    expect(new URL(page.url()).searchParams.get('unit')).toBe(other.unit_id)
  }
  await page.goto(`${base}?unit=${encodeURIComponent(unit.unit_id)}`)
  await page.locator('.cp-session').first().getByRole('link').first().click()
  await expect(page).toHaveURL(`${new URL(page.url()).origin}${base}/sessions/${encodeURIComponent(session.session_id)}`)
  await expect(page.locator('.classroom-heading h1')).toHaveText(session.title)
})

test('real unconfirmed blueprint shows eight-unit navigation when present and never invents lessons or progress', async ({ page }, info) => {
  const { courses }: { courses: Course[] } = await (await page.request.get('/api/courses')).json()
  const course = courses.find(item => item.structure_status === 'blueprint')
  test.skip(!course, 'Requires an existing real unconfirmed blueprint; no API response is simulated.')
  const saved = course!
  await page.goto(`/courses/${encodeURIComponent(saved.course_id)}`)
  await expect(page.locator('#current-unit-title')).toHaveText(saved.units[0].title)
  await expect(page.getByRole('navigation', { name: '课程单元', exact: true }).getByRole('link')).toHaveCount(saved.units.length)
  await expect(page.locator('.progress-incomplete')).toBeVisible()
  await expect(page.locator('.ov-progress progress')).toHaveCount(0)
  await expect(page.locator('.cp-session')).toHaveCount(0)
  await expect(page.getByRole('link', { name: /审阅课程蓝图/ })).toHaveAttribute('href', `/course-runs/${saved.creation_run_id}`)
  await expect(page.getByRole('link', { name: /^继续学习/ })).toHaveCount(0)
  await page.getByRole('navigation', { name: '课程单元', exact: true }).getByRole('link').last().click()
  await expect(page.locator('#current-unit-title')).toHaveText(saved.units.at(-1)!.title)
  await page.screenshot({ path: info.outputPath('course-blueprint-desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByLabel('当前单元', { exact: true }).selectOption(saved.units[0].unit_id)
  await expect(page.locator('#current-unit-title')).toHaveText(saved.units[0].title)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.screenshot({ path: info.outputPath('course-blueprint-mobile.png'), fullPage: true })
  const after: Course = await (await page.request.get(`/api/courses/${saved.course_id}`)).json()
  expect(after.version).toBe(saved.version)
  expect(after.structure_status).toBe('blueprint')
})

test('real partial directory keeps generated lessons separate from units awaiting expansion', async ({ page }) => {
  const { courses }: { courses: Course[] } = await (await page.request.get('/api/courses')).json()
  const course = courses.find(item => item.structure_status === 'expanding')
  test.skip(!course, 'Requires an existing real partial directory.')
  const saved = course!
  const base = `/courses/${encodeURIComponent(saved.course_id)}`
  for (const unit of saved.units) {
    await page.goto(`${base}?unit=${encodeURIComponent(unit.unit_id)}`)
    await expect(page.locator('#current-unit-title')).toHaveText(unit.title)
    await expect(page.locator('.ov-progress progress')).toHaveCount(0)
    await expect(page.locator('.cp-session')).toHaveCount(unit.lectures.reduce((count, lecture) => count + lecture.sessions.length, 0))
    await expect(page.getByRole('link', { name: /查看生成状态/ })).toHaveAttribute('href', `/course-runs/${saved.creation_run_id}`)
    if (!unit.lectures.length && unit.generation_status !== 'ready') await expect(page.locator('.cp-empty')).toContainText('学习路径尚未就绪')
  }
})

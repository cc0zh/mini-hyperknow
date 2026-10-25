import { test, expect } from '@playwright/test'
import type { Course, Run } from '../src/lib/types'

test('real retried courses resolve old links and remove obsolete failures from the library', async ({ page }, info) => {
  const runs: Run[] = (await (await page.request.get('/api/runs')).json()).runs
  const courses: Course[] = (await (await page.request.get('/api/courses')).json()).courses
  const obsolete = runs.filter(run => (!run.kind || run.kind === 'course') && courses.some(course =>
    course.course_id === run.course_id && course.creation_run_id && course.creation_run_id !== run.run_id))
  test.skip(!obsolete.length, 'Requires saved real retry history; no generation or replacement API is used.')
  const writes: string[] = []
  const errors: string[] = []
  page.on('request', request => { if (request.url().includes('/api/') && request.method() !== 'GET') writes.push(request.url()) })
  page.on('pageerror', error => errors.push(error.message))
  for (const old of obsolete) {
    const course = courses.find(item => item.course_id === old.course_id)!
    const latest: Run = await (await page.request.get(`/api/runs/${course.creation_run_id}`)).json()
    await page.goto(`/course-runs/${old.run_id}`)
    await expect(page).toHaveURL(new RegExp(`/course-runs/${latest.run_id}$`))
    await expect(page.locator('.bx-unit-card')).toHaveCount(course.units.length)
    if (latest.status === 'ready') {
      await expect(page.locator('.wb-current')).toContainText('课程准备好了')
      await expect(page.getByRole('link', { name: '开始学习' })).toBeVisible()
      await expect(page.getByRole('button', { name: '继续生成剩余内容' })).toHaveCount(0)
      await expect(page.locator('.error-notice')).toHaveCount(0)
    }
    await page.reload()
    await expect(page).toHaveURL(new RegExp(`/course-runs/${latest.run_id}$`))
    await expect(page.locator('.wb-actionbar')).toBeVisible()
    const unchanged: Run = await (await page.request.get(`/api/runs/${old.run_id}`)).json()
    expect(unchanged.status).toBe(old.status)
    if (latest.parent_run_id === old.run_id) {
      await page.locator('.run-details > summary').click()
      await page.getByRole('link', { name: '查看上次运行' }).click()
      await expect(page).toHaveURL(new RegExp(`/course-runs/${old.run_id}\\?history=1$`))
      await expect(page.locator('.wb-header-state')).toHaveText('历史生成记录')
      await expect(page.getByRole('link', { name: '查看最新生成状态' })).toHaveAttribute('href', `/course-runs/${latest.run_id}`)
      await expect(page.getByRole('button', { name: '继续生成剩余内容' })).toHaveCount(0)
    }
  }
  const readyRetry = obsolete.find(old => courses.some(course => course.course_id === old.course_id && course.structure_status === 'ready'))
  if (readyRetry) {
    await page.goto(`/course-runs/${readyRetry.run_id}`)
    await expect(page.getByRole('link', { name: '开始学习' })).toBeVisible()
    await page.screenshot({ path: info.outputPath('recovered-ready-workbench.png'), fullPage: true })
  }
  await page.goto('/courses')
  await expect(page.locator('.course-card')).toHaveCount(courses.length)
  for (const old of obsolete) await expect(page.locator(`.recoverable-run[href="/course-runs/${old.run_id}"]`)).toHaveCount(0)
  await page.screenshot({ path: info.outputPath('current-course-library.png'), fullPage: true })
  expect(writes).toEqual([])
  expect(errors).toEqual([])
})

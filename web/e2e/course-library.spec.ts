import { test, expect } from '@playwright/test'
import type { Course } from '../src/lib/types'

// Existing real course data only. These shared-service checks never confirm a
// deletion; destructive acceptance runs against a separate database copy.
test('library rows align and deletion requires an explicit cancellable confirmation', async ({ page }, info) => {
  const errors: string[] = []
  const writes: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('request', request => {
    if (request.url().includes('/api/') && request.method() !== 'GET') writes.push(request.method() + ' ' + request.url())
  })
  const { courses }: { courses: Course[] } = await (await page.request.get('/api/courses')).json()
  test.skip(!courses.length, 'Requires existing saved courses; no examples are manufactured.')
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/courses')
  await expect(page.locator('.course-card')).toHaveCount(courses.length)
  await expect(page.locator('.course-card a button')).toHaveCount(0)
  await expect(page.locator('.course-delete')).toHaveCount(courses.length)

  for (const width of [1440, 1024]) {
    await page.setViewportSize({ width, height: 1000 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    const geometry = await page.locator('.course-card').evaluateAll(cards => cards.map(card => {
      const rect = card.getBoundingClientRect()
      return {
        top: Math.round(rect.top), height: rect.height,
        title: card.querySelector('h2')!.getBoundingClientRect().top,
        progress: card.querySelector('.progress-label')!.getBoundingClientRect().top,
        stub: card.querySelector('.ticket-stub')!.getBoundingClientRect().top,
        actions: card.querySelector('.course-card-actions')!.getBoundingClientRect().top,
      }
    }))
    for (const row of new Set(geometry.map(card => card.top))) {
      const cards = geometry.filter(card => card.top === row)
      for (const field of ['height', 'title', 'progress', 'stub', 'actions'] as const) {
        const positions = cards.map(card => card[field])
        expect(Math.max(...positions) - Math.min(...positions), `${width}px row ${row}: ${field}`).toBeLessThanOrEqual(1)
      }
    }
    await page.screenshot({ path: info.outputPath(`library-${width}.png`), fullPage: true })
  }

  const trigger = page.locator('.course-delete').first()
  await trigger.click()
  const dialog = page.getByRole('dialog', { name: '删除这门课程？' })
  await expect(dialog).toBeVisible()
  await expect(dialog.locator('.delete-course-name')).toHaveText(courses[0].title)
  await expect(dialog).toContainText('无法撤销')
  await expect(dialog.getByRole('button', { name: '保留课程' })).toBeFocused()
  await page.screenshot({ path: info.outputPath('delete-confirm-desktop.png'), fullPage: false })
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()
  await trigger.click()
  await page.getByRole('button', { name: '保留课程' }).click()
  await expect(dialog).toHaveCount(0)
  await page.reload()
  await expect(page.locator('.course-card')).toHaveCount(courses.length)
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.screenshot({ path: info.outputPath('library-dark.png'), fullPage: true })
  expect(writes).toEqual([])
  expect(errors).toEqual([])
})

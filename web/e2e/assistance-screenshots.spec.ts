import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'

// Screenshots of the saved real-model conversation for the change record. This
// suite never creates a turn and never intercepts an API response.
test('capture the saved conversation, step trace, callouts and every artifact', async ({ page }, testInfo) => {
  test.skip(!process.env.HK_ASSISTANCE_EVIDENCE, 'Requires explicit real-model evidence')
  const evidence = JSON.parse(readFileSync(process.env.HK_ASSISTANCE_EVIDENCE!, 'utf8'))
  expect(evidence.passed).toBe(true)
  const id: string = evidence.conversations[0]
  await page.goto(`/assistance/${id}`)
  await expect(page.locator('.assistance-turn').first()).toBeVisible()

  // A saved trace is legible after the run finished, which is the point of
  // persisting steps on the turn.
  const trace = page.locator('.assistance-trace').first()
  if (await trace.count()) {
    await trace.locator('summary').click()
    await expect(trace.locator('.assistance-timeline')).toBeVisible()
    await trace.scrollIntoViewIfNeeded()
    await trace.screenshot({ path: testInfo.outputPath('step-trace.png') })
  }
  const callout = page.locator('.assistance-callout').first()
  if (await callout.count()) {
    // The composer is position: sticky, so an element screenshot near the
    // viewport bottom can be covered by it. Capture the containing turn area
    // with the callouts scrolled into view instead.
    await callout.evaluate(node => node.scrollIntoView({ block: 'center' }))
    await page.waitForTimeout(300)
    await page.locator('.turn-assistant').filter({ has: page.locator('.assistance-callout') }).first()
      .screenshot({ path: testInfo.outputPath('teaching-turn.png') })
  }
  const identity = page.locator('.artifact-identity').first()
  await identity.scrollIntoViewIfNeeded()
  await identity.screenshot({ path: testInfo.outputPath('artifact-identity.png') })
  for (const kind of ['flashcards', 'quiz', 'diagram', 'animation', 'whiteboard']) {
    const artifact = evidence.artifacts.find((item: { kind: string }) => item.kind === kind)
    if (!artifact) continue
    const pane = page.locator(`[data-artifact-id="${artifact.artifact_id}"]`)
    if (!(await pane.count())) continue
    await pane.scrollIntoViewIfNeeded()
    await pane.screenshot({ path: testInfo.outputPath(`artifact-${kind}.png`) })
  }
  await page.setViewportSize({ width: 1440, height: 1200 })
  await page.goto(`/assistance/${id}`)
  await expect(page.locator('.assistance-turn').first()).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('conversation-full.png'), fullPage: true })
  await page.goto('/assistance')
  await page.screenshot({ path: testInfo.outputPath('entry.png'), fullPage: true })
})

import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'

// Read only artifacts produced by scripts/verify_assistance.py against the real
// provider. This suite never creates a teaching turn or intercepts an API.
test('real saved assistance artifacts work, refresh resets local answers, and board progress survives', async ({ page }, testInfo) => {
  test.skip(!process.env.HK_ASSISTANCE_EVIDENCE, 'Requires explicit real-model evidence, not fixture responses')
  const evidence = JSON.parse(readFileSync(process.env.HK_ASSISTANCE_EVIDENCE!, 'utf8'))
  expect(evidence.passed).toBe(true)
  const id: string = evidence.conversations[0]
  const artifacts: { artifact_id: string; kind: string; title: string; data: any }[] = evidence.artifacts
  const cards = artifacts.find(artifact => artifact.kind === 'flashcards')!
  const quiz = artifacts.find(artifact => artifact.kind === 'quiz')!
  const animation = artifacts.find(artifact => artifact.kind === 'animation')!
  const board = artifacts.find(artifact => artifact.kind === 'whiteboard')!
  const errors: string[] = []
  const modelCommands: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('request', request => {
    if (request.method() === 'POST' && /\/turns$|\/retry$/.test(new URL(request.url()).pathname)) modelCommands.push(request.url())
  })
  const before = await (await page.request.get('/api/runs')).json()
  await page.goto(`/assistance/${id}`)
  await expect(page.locator('.assistance-turn')).toHaveCount(evidence.turns.filter((turn: any) => turn.conversation_id === id).length)
  const flashcards = page.getByRole('region', { name: '闪卡', exact: true })
  await expect(flashcards.getByRole('button', { name: '翻转显示答案' })).toContainText(cards.data.cards[0].question)
  await flashcards.getByRole('button', { name: '翻转显示答案' }).click()
  // The answer is rendered as prose; $$ display formulas become typeset math
  // while inline $…$ stays literal source. Assert one contiguous plain-text
  // run instead of the whole answer so neither behaviour is over-specified.
  const prose = String(cards.data.cards[0].answer).split(/\$\$[\s\S]*?\$\$|\$[^$]*\$/).map(part => part.trim()).filter(part => part.length >= 6)
  await expect(flashcards.getByRole('button', { name: '显示问题' })).toContainText(prose[0].slice(0, 6))
  await flashcards.getByRole('button', { name: '下一张' }).click()
  await expect(flashcards.getByRole('button', { name: '翻转显示答案' })).toContainText(cards.data.cards[1].question)
  await flashcards.screenshot({ path: testInfo.outputPath('real-flashcards.png') })

  // A saved conversation may hold more than one quiz: the model also decides
  // on its own that a quiz is the right move. Scope to this saved artifact by
  // its stable id instead of assuming one quiz per page.
  const quizPane = page.locator(`[data-artifact-id="${quiz.artifact_id}"]`)
  await expect(quizPane).toHaveCount(1)
  // The composer is position: sticky and covers the viewport bottom, so every
  // quiz interaction is preceded by centring the pane instead of trusting
  // auto-scroll to land somewhere clickable.
  await quizPane.evaluate(node => node.scrollIntoView({ block: 'center' }))
  for (let index = 0; index < quiz.data.questions.length; index++) {
    const question = quiz.data.questions[index]
    // The question is rendered with typeset math, so compare one plain-text
    // run rather than the raw $…$ source.
    const heading = quizPane.getByRole('heading', { level: 3 })
    const plain = String(question.question).split(/\$[^$]*\$/).map(part => part.trim()).filter(part => part.length >= 4)
    if (plain.length) await expect(heading).toContainText(plain[0].slice(0, 4))
    else await expect(heading).not.toBeEmpty()
    await expect(quizPane.getByRole('button', { name: '提交答案' })).toBeDisabled()
    // Options are addressable by their saved ids through the DOM order the
    // component renders, so typeset math never has to be matched as text.
    for (const optionId of question.correct_ids) {
      const position = question.options.findIndex((value: any) => value.id === optionId)
      await quizPane.locator('label.answer-option input').nth(position).check()
    }
    await quizPane.getByRole('button', { name: '提交答案' }).click()
    await expect(quizPane.locator('.quiz-feedback')).toContainText('回答正确')
    await expect(quizPane.locator('.quiz-feedback')).toContainText(question.explanation.replace(/\$/g, '').slice(0, 3))
    if (index < quiz.data.questions.length - 1) await quizPane.getByRole('button', { name: '下一题' }).click()
  }
  await quizPane.screenshot({ path: testInfo.outputPath('real-quiz-feedback.png') })

  const preview = page.getByRole('region', { name: '动画预览', exact: true })
  const iframe = preview.locator('iframe')
  await expect(iframe).toHaveAttribute('sandbox', 'allow-scripts')
  await expect(iframe).toHaveAttribute('referrerpolicy', 'no-referrer')
  const frame = page.frameLocator(`iframe[title="${animation.title.replace(/"/g, '\\"')}"]`)
  await expect(frame.locator('body')).not.toBeEmpty()
  expect(await (await iframe.elementHandle())!.contentFrame().then(frame => frame!.evaluate(() => {
    try { void window.parent.document.title; return false } catch { return true }
  }))).toBe(true)
  expect(await frame.locator('button,input[type="range"]').count()).toBeGreaterThan(0)
  await preview.getByRole('button', { name: '展开预览' }).click()
  await expect(preview).toHaveClass(/expanded/)
  await preview.getByRole('button', { name: '重置动画' }).click()
  await expect(frame.locator('body')).not.toBeEmpty()
  await preview.screenshot({ path: testInfo.outputPath('real-animation.png') })

  await page.reload()
  await expect(page.getByRole('region', { name: '闪卡', exact: true }).getByRole('button', { name: '翻转显示答案' })).toContainText(cards.data.cards[0].question)
  await expect(page.locator(`[data-artifact-id="${quiz.artifact_id}"]`).getByRole('button', { name: '提交答案' })).toBeDisabled()
  await expect(page.locator('.quiz-feedback')).toHaveCount(0)
  await expect(page.locator('.assistance-composer')).toBeVisible()
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('real-assistance-desktop.png') })

  await page.getByRole('link', { name: '打开独立白板', exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`/assistance/boards/${board.artifact_id}$`))
  const player = page.getByLabel('独立白板播放器', { exact: true })
  const saved = await (await page.request.get(`/api/assistance/artifacts/${board.artifact_id}`)).json()
  await expect(player).toContainText(`已确认 ${saved.data.cursor + 1} / ${saved.data.steps.length} 步`)
  if (saved.data.cursor < saved.data.steps.length - 1) {
    await expect(player).toContainText('已暂停')
    const confirmed = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith(`/artifacts/${board.artifact_id}/progress`))
    await player.getByRole('button', { name: '下一步' }).click()
    expect((await confirmed).status()).toBe(200)
    await expect(player).toContainText(`已确认 ${saved.data.cursor + 2} / ${saved.data.steps.length} 步`)
    await page.reload()
    await expect(page.getByLabel('独立白板播放器', { exact: true })).toContainText(`已确认 ${saved.data.cursor + 2} / ${saved.data.steps.length} 步`)
    await expect(page.getByRole('button', { name: '暂停', exact: true })).toHaveCount(0)
  }
  await page.screenshot({ path: testInfo.outputPath('real-standalone-board.png'), fullPage: true })
  const after = await (await page.request.get('/api/runs')).json()
  expect(after.runs.map((run: any) => run.run_id).sort()).toEqual(before.runs.map((run: any) => run.run_id).sort())
  expect(modelCommands).toEqual([])
  expect(errors).toEqual([])
  await testInfo.attach('real-artifact-diagnostics', { body: JSON.stringify({ errors, modelCommands, kinds: artifacts.map(artifact => artifact.kind) }), contentType: 'application/json' })
})

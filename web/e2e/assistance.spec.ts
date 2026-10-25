import { test, expect } from '@playwright/test'
import type { AssistanceConversation } from '../src/lib/assistance'

// Real browser, local HTTP service and native iframe policies. These tests do
// not intercept requests, populate backend fixtures, or invoke a paid model.
test('assistance entry, empty conversation and refresh perform only explicit creation', async ({ page }) => {
  const mutations: string[] = []
  const errors: string[] = []
  page.on('request', request => { if (['POST', 'PUT'].includes(request.method())) mutations.push(new URL(request.url()).pathname) })
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/')
  await page.getByRole('navigation', { name: '主导航', exact: true }).getByRole('link', { name: '即时协助' }).click()
  await expect(page.getByRole('heading', { name: '即时协助', exact: true })).toBeVisible()
  await expect(page.locator('.loading')).toHaveCount(0)
  expect(mutations).toEqual([])
  const accepted = page.waitForResponse(response => new URL(response.url()).pathname === '/api/assistance/conversations' && response.request().method() === 'POST')
  await page.getByRole('button', { name: '开始新会话', exact: true }).evaluate(button => { (button as HTMLButtonElement).click(); (button as HTMLButtonElement).click() })
  expect((await accepted).ok()).toBe(true)
  await expect(page).toHaveURL(/\/assistance\/conversation_[^/]+$/)
  await expect(page.getByLabel('你的问题', { exact: true })).toBeVisible()
  expect(mutations).toEqual(['/api/assistance/conversations'])
  await page.reload()
  await expect(page.getByLabel('你的问题', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '发送', exact: true })).toBeDisabled()
  // Artifact kind is not a learner-facing control: typing is the only way to
  // ask, and no request is sent until the learner submits.
  await expect(page.getByLabel('本轮操作', { exact: true })).toHaveCount(0)
  await expect(page.getByLabel('教学方式', { exact: true })).toHaveCount(0)
  await page.getByLabel('你的问题', { exact: true }).fill('给我三道关于二分的自测题')
  await expect(page.getByRole('button', { name: '发送', exact: true })).toBeEnabled()
  await expect(page.getByRole('button', { name: '继续讲解', exact: true })).toHaveCount(0)
  expect(mutations).toEqual(['/api/assistance/conversations'])
  expect(errors).toEqual([])
})

test('a restored accepted creation receipt retries the exact body and does not duplicate a conversation', async ({ page, request }) => {
  const body = { client_command_id: crypto.randomUUID() }
  const initialResponse = await request.post('/api/assistance/conversations', { data: body })
  expect(initialResponse.ok()).toBe(true)
  const initial = await initialResponse.json() as AssistanceConversation
  await page.goto('/assistance')
  await page.evaluate(command => sessionStorage.setItem('hyperknow.assistance.command.create', JSON.stringify(command)), { method: 'POST', path: '/assistance/conversations', conversationId: '', body })
  await page.reload()
  const sent: unknown[] = []
  page.on('request', value => { if (value.method() === 'POST' && new URL(value.url()).pathname === '/api/assistance/conversations') sent.push(value.postDataJSON()) })
  await expect(page.getByRole('button', { name: '重试同一创建请求', exact: true })).toBeVisible()
  expect(sent).toEqual([])
  await page.getByRole('button', { name: '重试同一创建请求', exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`/assistance/${initial.conversation_id}$`))
  await expect(page.getByLabel('你的问题', { exact: true })).toBeVisible()
  expect(sent).toEqual([body])
  expect(await page.evaluate(() => sessionStorage.getItem('hyperknow.assistance.command.create'))).toBeNull()
})

test('missing board uses the static board route and renders a real HTTP error', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/assistance/boards/missing-assistance-artifact')
  await expect(page.locator('.error-notice')).toContainText('白板读取失败')
  await expect(page.locator('.error-notice')).not.toContainText('会话读取失败')
  await expect(page.getByRole('link', { name: '返回即时协助' })).toBeVisible()
  expect(errors).toEqual([])
})

test('restored turn command stays read-only until explicit retry and preserves its identity after a real version conflict', async ({ page, request }) => {
  const response = await request.post('/api/assistance/conversations', { data: { client_command_id: crypto.randomUUID() } })
  expect(response.ok()).toBe(true)
  const conversation = await response.json() as AssistanceConversation
  const command = { method: 'POST', path: `/assistance/conversations/${conversation.conversation_id}/turns`, conversationId: conversation.conversation_id, body: { client_command_id: crypto.randomUUID(), expected_version: conversation.version + 1, text: '保留这条真实冲突请求', action: 'message', skill_hint: 'auto' } }
  await page.goto('/assistance')
  await page.evaluate(value => sessionStorage.setItem(`hyperknow.assistance.command.conversation:${value.conversationId}`, JSON.stringify(value)), command)
  const sent: unknown[] = []
  page.on('request', value => { if (value.method() === 'POST' && new URL(value.url()).pathname.endsWith('/turns')) sent.push(value.postDataJSON()) })
  await page.goto(`/assistance/${conversation.conversation_id}`)
  await expect(page.getByLabel('你的问题', { exact: true })).toHaveValue(command.body.text)
  await expect(page.getByLabel('你的问题', { exact: true })).toBeDisabled()
  expect(sent).toEqual([])
  // The deliberately future version is rejected before any model scheduling.
  const conflict = page.waitForResponse(value => value.request().method() === 'POST' && new URL(value.url()).pathname.endsWith('/turns'))
  await page.getByRole('button', { name: '重试同一命令', exact: true }).click()
  expect((await conflict).status()).toBe(409)
  expect(sent).toEqual([command.body])
  await page.getByRole('button', { name: '确认已拒绝，重新同步后修改' }).click()
  await expect(page.getByLabel('你的问题', { exact: true })).toBeEnabled()
  await expect(page.getByLabel('你的问题', { exact: true })).toHaveValue(command.body.text)
  const saved = await (await request.get(`/api/assistance/conversations/${conversation.conversation_id}`)).json() as AssistanceConversation
  expect(saved.turns).toEqual([])
  expect(saved.active_run).toBeNull()
})

test('animation parser removes static navigation, external resources and inline handlers from full documents', async ({ page }) => {
  await page.goto('/assistance')
  const result = await page.evaluate(async () => {
    const sourcePath = '/src/lib/assistance-animation.ts'
    const { animationSrcDoc, animationScriptIssue } = await import(sourcePath)
    const preview = animationSrcDoc(`<!doctype html><html><head><meta http-equiv="refresh" content="0;url=https://preview.invalid/nav"><base href="https://preview.invalid/"><style>@import url('https://preview.invalid/a.css'); .x{color:green}</style><script>const count = 1;</script></head><body><form action="https://preview.invalid/send"><input name="secret"></form><a href="https://preview.invalid/nav" target="_top" ping="https://preview.invalid/ping">外部链接</a><img src="//preview.invalid/i.png" srcset="https://preview.invalid/2.png 2x" onerror="alert(1)"><script src="/api/health"></script><iframe src="https://preview.invalid/frame"></iframe><button onclick="location.href='/';">按钮</button><svg><a href="https://preview.invalid/svg">SVG link</a></svg></body></html>`)
    const parsed = new DOMParser().parseFromString(preview, 'text/html')
    return {
      blocked: parsed.querySelectorAll('base,form,iframe,link,meta[http-equiv="refresh"],a[href],a[target],a[ping],[onerror],[onclick],[srcset],script[src],img[src]').length,
      inlineScript: parsed.querySelector('script')?.textContent,
      csp: parsed.querySelector('meta[http-equiv="Content-Security-Policy"]')?.getAttribute('content'),
      style: parsed.querySelectorAll('style')[1]?.textContent,
      navigationIssue: animationScriptIssue('window.location.assign("/")'),
    }
  })
  expect(result.blocked).toBe(0)
  expect(result.inlineScript).toBe('const count = 1;')
  expect(result.csp).toContain("default-src 'none'")
  expect(result.style).not.toContain('@import')
  expect(result.navigationIssue).toBeTruthy()
})

test('native opaque iframe executes local scripts while denying host access, eval and third-party requests', async ({ page }) => {
  await page.goto('/assistance')
  const responses: string[] = []
  page.on('response', response => { if (response.url().includes('preview.invalid')) responses.push(response.url()) })
  await page.evaluate(async () => {
    const sourcePath = '/src/lib/assistance-animation.ts'
    const { animationSrcDoc, ANIMATION_SANDBOX } = await import(sourcePath)
    const iframe = document.createElement('iframe')
    iframe.id = 'assistance-security-preview'
    iframe.sandbox.value = ANIMATION_SANDBOX
    iframe.srcdoc = animationSrcDoc(`<div id="result">starting</div><script>
      const result = document.getElementById('result');
      const facts = {hostDenied: false, storageDenied: false, evalDenied: false, networkDenied: false};
      try { globalThis['parent'].document.title; } catch { facts.hostDenied = true; }
      try { localStorage.getItem('assistance-security-test'); } catch { facts.storageDenied = true; }
      try { new Function('return 1')(); } catch { facts.evalDenied = true; }
      fetch('https://preview.invalid/probe').then(() => { result.textContent = JSON.stringify(facts); }).catch(() => { facts.networkDenied = true; result.textContent = JSON.stringify(facts); });
    </script>`)
    document.body.append(iframe)
  })
  const frame = page.frameLocator('#assistance-security-preview')
  await expect(frame.locator('#result')).toContainText('"networkDenied":true')
  const facts = JSON.parse(await frame.locator('#result').innerText())
  expect(facts).toEqual({ hostDenied: true, storageDenied: true, evalDenied: true, networkDenied: true })
  expect(responses).toEqual([])
  expect(await page.locator('#assistance-security-preview').getAttribute('sandbox')).toBe('allow-scripts')
  // No arbitrary-JS or iframe-self-navigation guarantee is asserted here.
})

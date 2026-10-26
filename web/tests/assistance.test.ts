import test from 'node:test'
import assert from 'node:assert/strict'
import { assistanceStepLabel, clarificationText, commandScope, isAdvanceAllowed, makeAssistanceCommand, makeTurnCommand, mergeArtifact, mergeConversation, matchesAssistanceResource, ownsAssistanceCommand, pendingCommandForScope, prepareAssistanceCommand, quizAnswerCorrect, selectQuizOption, validBoardCursor, validTurn } from '../src/lib/assistance.ts'
import { animationScriptIssue, ANIMATION_CSP, ANIMATION_SANDBOX } from '../src/lib/assistance-animation.ts'
import type { AssistanceConversation, AssistanceSuggestion, AssistanceTurn, PendingAssistanceCommand, WhiteboardArtifact } from '../src/lib/assistance.ts'

const conversation = (version: number, title = '学习问题', conversation_id = 'c-1'): AssistanceConversation => ({
  conversation_id, title, version, created_at: '', updated_at: '', turns: [], active_run: null,
})

test('conversation snapshots do not roll state back to an older version', () => {
  const latest = conversation(4, '最新标题')
  assert.equal(mergeConversation(latest, conversation(3, '旧标题')).title, latest.title)
  assert.equal(mergeConversation(latest, conversation(4, '同版本标题')).title, latest.title)
  assert.equal(mergeConversation(latest, conversation(1, '另一个会话', 'c-2')).title, '另一个会话')
})

test('retry ownership matches the exact endpoint and command identity', () => {
  const command: PendingAssistanceCommand = { conversationId: 'c-1', method: 'POST', path: '/turns', body: { client_command_id: 'same', text: 'x' } }
  assert.equal(ownsAssistanceCommand(command, command), true)
  assert.equal(ownsAssistanceCommand(command, { ...command, body: { ...command.body, client_command_id: 'different' } }), false)
})

test('whiteboard progression stays or advances one step; active questions hold playback', () => {
  assert.equal(isAdvanceAllowed(-1, 3, false), true)
  assert.equal(isAdvanceAllowed(0, 3, true), false)
  assert.equal(isAdvanceAllowed(2, 3, false), false)
  assert.equal(validBoardCursor(0, 0, 3), true)
  assert.equal(validBoardCursor(0, 1, 3), true)
  assert.equal(validBoardCursor(0, 2, 3), false)
  assert.equal(validBoardCursor(0, -1, 3), false)
  assert.equal(validBoardCursor(-1, -1, 3), true)
  assert.equal(validBoardCursor(1, 1.5, 3), false)
})

test('animation policy keeps an opaque origin and blocks third-party resource capabilities', () => {
  assert.equal(ANIMATION_SANDBOX, 'allow-scripts')
  for (const directive of ["default-src 'none'", "connect-src 'none'", "form-action 'none'", "frame-src 'none'", "worker-src 'none'", "img-src data:"]) assert.ok(ANIMATION_CSP.includes(directive))
  assert.doesNotMatch(ANIMATION_CSP, /unsafe-eval|https?:|navigate-to/)
  assert.ok(animationScriptIssue('window.location = "https://example.org"'))
  assert.ok(animationScriptIssue('open("https://example.org")'))
  assert.equal(animationScriptIssue('const canvas = document.querySelector("canvas"); requestAnimationFrame(draw);'), null)
})

const board = (version: number, cursor: number): WhiteboardArtifact => ({ artifact_id: 'b-1', conversation_id: 'c-1', turn_id: 't-1', title: '板书', kind: 'whiteboard', version, data: { steps: [], cursor } })
const turn = (artifact: WhiteboardArtifact): AssistanceTurn => ({ turn_id: 't-1', run_id: 'r-1', user_text: '讲解', action: 'message', status: 'ready', response: null, artifacts: [artifact], skill_uses: [], steps: [], error: null })

test('a replay for another board can finish its command without replacing the current route resource', () => {
  assert.equal(matchesAssistanceResource('/assistance/artifacts/b-1', board(2, 0)), true)
  assert.equal(matchesAssistanceResource('/assistance/artifacts/b-2', board(2, 0)), false)
  assert.equal(matchesAssistanceResource('/assistance/conversations/c-1', board(2, 0)), false)
  assert.equal(matchesAssistanceResource('/assistance/conversations/c-1', conversation(3)), true)
  assert.equal(matchesAssistanceResource('/assistance/conversations/c-2', conversation(3)), false)
})

test('independent artifact versions merge even when conversation version does not increase', () => {
  const current = { ...conversation(4), turns: [turn(board(1, -1))] }
  const incoming = { ...conversation(4, '迟到标题'), turns: [turn(board(2, 0))] }
  const merged = mergeConversation(current, incoming)
  assert.equal(merged.title, current.title)
  assert.equal(merged.turns[0].artifacts[0].version, 2)
  assert.equal(mergeConversation(merged, current).turns[0].artifacts[0].version, 2)
  assert.equal(mergeArtifact(board(3, 1), board(2, 0)).data.cursor, 1)
})

test('an artifact update cannot overwrite a newer active run or add an obsolete turn', () => {
  const current = { ...conversation(8), active_run: { run_id: 'new-run', version: 1, status: 'queued' as const }, turns: [turn(board(1, -1))] }
  const stale = { ...conversation(5), turns: [turn(board(2, 0))] }
  const merged = mergeConversation(current, stale)
  assert.equal(merged.version, 8)
  assert.equal(merged.active_run?.run_id, 'new-run')
  assert.equal(merged.turns[0].artifacts[0].version, 2)
})

test('unknown commands retain complete body, path, method, question chain and identity', () => {
  const pending = makeAssistanceCommand('c-1', '/assistance/artifacts/b/progress', { expected_version: 4, cursor: 2 }, 'PUT')
  pending.question_after_save = { text: '为什么？', artifact_id: 'b' }
  const proposed = makeAssistanceCommand('c-1', '/different', { expected_version: 5 })
  assert.equal(prepareAssistanceCommand(pending, proposed), pending)
  assert.deepEqual(JSON.parse(JSON.stringify(pending)), pending)
  assert.equal(ownsAssistanceCommand(proposed, pending), false)
  assert.notEqual(commandScope('c-1'), commandScope('c-2'))
  assert.equal(prepareAssistanceCommand(null, null), null)
})

test('turn commands use saved version, actual user text and optional whiteboard identity', () => {
  const command = makeTurnCommand(conversation(7), '', 'continue')
  assert.equal(command.body.expected_version, 7)
  assert.equal(command.body.text, '')
  assert.equal(command.body.action, 'continue')
  assert.equal('artifact_id' in command.body, false)
  assert.equal(makeTurnCommand(conversation(8), '解释当前步骤', 'message', 'board-a').body.artifact_id, 'board-a')
  // Both remaining intents carry the learner's words; there is no artifact
  // action left that could be valid with empty text.
  assert.equal(validTurn(' '), false)
  assert.equal(validTurn('问'), true)
  assert.equal(validTurn('继续下一步'), true)
  assert.equal(validTurn('x'.repeat(12001)), false)
})

test('command recovery validates the exact scope and write endpoint without changing its body', () => {
  const command = makeTurnCommand(conversation(7), '为什么', 'message')
  assert.equal(pendingCommandForScope(command, commandScope('c-1')), command)
  assert.equal(pendingCommandForScope(command, commandScope('c-2')), null)
  assert.equal(pendingCommandForScope({ ...command, method: 'GET' }, commandScope('c-1')), null)
  assert.equal(pendingCommandForScope({ ...command, path: '/courses/c-1' }, commandScope('c-1')), null)
  assert.equal(pendingCommandForScope(null, commandScope('c-1')), null)
  assert.equal(pendingCommandForScope({ method: 'POST', body: {} }, 'create'), null)
  const progress = makeAssistanceCommand('c-1', '/assistance/artifacts/b-1/progress', { expected_version: 1, cursor: -1 }, 'PUT')
  progress.question_after_save = { text: '解释当前步', artifact_id: 'b-1' }
  assert.deepEqual(pendingCommandForScope(JSON.parse(JSON.stringify(progress)), commandScope('c-1')), progress)
})

test('feedback recovery preserves its exact verdict, version, endpoint and command identity', () => {
  for (const vote of ['up', 'down']) {
    const command = makeAssistanceCommand('c-1', '/assistance/artifacts/artifact-a/feedback', { expected_version: 6, vote }, 'PUT')
    const stored = JSON.parse(JSON.stringify(command))
    const restored = pendingCommandForScope(stored, commandScope('c-1'))
    assert.equal(restored, stored)
    assert.deepEqual(restored, command)
    assert.equal(ownsAssistanceCommand(restored, command), true)
    assert.equal(prepareAssistanceCommand(restored, makeTurnCommand(conversation(10), '新问题', 'message')), restored)
    assert.equal(pendingCommandForScope(stored, commandScope('c-2')), null)
  }
})

test('recovery rejects unapproved method and path combinations', () => {
  const command = makeAssistanceCommand('c-1', '/assistance/artifacts/b-1/feedback', { expected_version: 1, vote: 'up' }, 'PUT')
  for (const method of ['POST', 'GET', 'PATCH', 'DELETE']) assert.equal(pendingCommandForScope({ ...command, method }, commandScope('c-1')), null)
  for (const path of ['/assistance/artifacts/b-1', '/assistance/artifacts/b-1/feedback/extra', '/assistance/artifacts/b-1/feedback?x=1', '/assistance/artifacts/b-1?x/feedback', '/assistance/artifacts//feedback', '/assistance/conversations/c-1/turns', '/runs/r-1/cancel', '/courses/c-1']) {
    assert.equal(pendingCommandForScope({ ...command, path }, commandScope('c-1')), null, path)
  }
  for (const expected_version of [0, -1, 1.5, '1', null]) assert.equal(pendingCommandForScope({ ...command, body: { ...command.body, expected_version } }, commandScope('c-1')), null)
})

test('a restored question belongs only to its exact progress command and produces a linked message', () => {
  const command = makeAssistanceCommand('c-1', '/assistance/artifacts/b-1/progress', { expected_version: 3, cursor: 0 }, 'PUT')
  command.question_after_save = { text: '解释已确认的步骤', artifact_id: 'b-1' }
  const restored = pendingCommandForScope(JSON.parse(JSON.stringify(command)), commandScope('c-1'))!
  assert.deepEqual(restored, command)
  const question = restored.question_after_save!
  const next = makeTurnCommand(conversation(9), question.text, 'message', question.artifact_id)
  assert.equal(next.body.expected_version, 9)
  assert.equal(next.body.text, question.text)
  assert.equal(next.body.artifact_id, question.artifact_id)
  assert.equal(next.body.action, 'message')
  assert.notEqual(next.body.client_command_id, command.body.client_command_id)
  assert.equal(pendingCommandForScope({ ...command, path: '/assistance/artifacts/b-1/feedback' }, commandScope('c-1')), null)
  assert.equal(pendingCommandForScope({ ...command, question_after_save: { ...question, artifact_id: 'b-2' } }, commandScope('c-1')), null)
  for (const text of ['', ' ', 'x'.repeat(12001)]) assert.equal(pendingCommandForScope({ ...command, question_after_save: { ...question, text } }, commandScope('c-1')), null)
})

test('suggestion intent is explicit even when labels and message text resemble another action', () => {
  const suggestions: AssistanceSuggestion[] = [{ label: '继续下一步', text: '继续下一步', action: 'message' }, { label: '看看例子', text: '看看例子', action: 'continue' }]
  for (const suggestion of suggestions) {
    const command = makeTurnCommand(conversation(4), suggestion.text, suggestion.action)
    assert.equal(command.body.action, suggestion.action)
    assert.equal(command.body.text, suggestion.text)
    assert.deepEqual(Object.keys(command.body).sort(), ['action', 'client_command_id', 'expected_version', 'text'])
  }
})

test('recorded skill traces retain arbitrary trusted names without fixed teaching aliases', () => {
  assert.equal(assistanceStepLabel({ tool: 'get_skills', status: 'ready', name: 'trusted-visualization' }), '加载技能 · trusted-visualization')
  assert.equal(assistanceStepLabel({ tool: 'get_skills', status: 'running' }), '加载技能')
})

test('quiz selection and checking use correct_ids; no answer is inferred from its order', () => {
  assert.deepEqual(selectQuizOption(['c'], 'a', ['b']), ['a'])
  assert.deepEqual(selectQuizOption(['c'], 'a', ['a', 'c']), ['c', 'a'])
  assert.deepEqual(selectQuizOption(['c', 'a'], 'c', ['a', 'c']), ['a'])
  assert.equal(quizAnswerCorrect(['c', 'a'], ['a', 'c']), true)
  assert.equal(quizAnswerCorrect(['a'], ['a', 'c']), false)
})

test('clarification preserves selected answers for multiple questions and optional free text', () => {
  const questions = [{ question_id: 'q1', question: '基础？', options: ['初学', '熟练'], multiple: false }, { question_id: 'q2', question: '目标？', options: ['直觉', '计算'], multiple: true }]
  assert.equal(clarificationText(questions, { q1: ['初学'], q2: ['直觉', '计算'] }, '请举例'), '基础？\n初学\n\n目标？\n直觉、计算\n\n请举例')
})

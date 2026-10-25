import { useEffect, useRef } from 'react'
import type { Course } from '../lib/types'
import { useCommand } from '../lib/use-command'
import { IconTrash } from './icons'
import { ErrorNotice } from './ui'

export type CourseDeletion = { course_id: string; deleted: true }
type DeleteCommand = ReturnType<typeof useCommand<CourseDeletion>>

export function CourseDeleteDialog({ course, trigger, command, close, refresh }: {
  course: Course
  trigger: HTMLButtonElement | null
  command: DeleteCommand
  close: () => void
  refresh: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const element = dialog.current!
    element.showModal()
    return () => { element.close(); if (trigger?.isConnected) trigger.focus() }
  }, [trigger])

  return <dialog ref={dialog} className="course-delete-dialog" aria-labelledby="delete-course-title" aria-describedby="delete-course-description" onCancel={event => {
    event.preventDefault()
    if (!command.busy) close()
  }}>
    <div className="delete-dialog-icon"><IconTrash size={24} /></div>
    <h2 id="delete-course-title">删除这门课程？</h2>
    <p className="delete-course-name">{course.title}</p>
    <p id="delete-course-description">将永久删除课程目录、已保存讲义、学习进度、练习与考核记录，以及关联的生成记录。此操作无法撤销，不影响其他课程。</p>
    <p className="delete-course-hint">如果课程仍有生成任务，请先前往生成页停止任务，再进行删除。</p>
    {command.error && <ErrorNotice title={command.conflict || command.rejected ? '本次删除未执行' : '删除结果尚未确认'} message={command.error} />}
    {command.pending && !command.busy && !command.conflict && !command.rejected && <p className="delete-course-hint">关闭窗口不会撤销已发送的请求，请稍后重试同一请求确认结果。</p>}
    <div className="delete-dialog-actions">
      <button type="button" className="button secondary" autoFocus disabled={command.busy} onClick={close}>{command.pending && !command.conflict && !command.rejected ? '稍后确认' : '保留课程'}</button>
      {command.conflict || command.rejected
        ? <button type="button" className="button secondary" onClick={refresh}>刷新课程列表</button>
        : <button type="button" className="button danger" disabled={command.busy} onClick={() => {
          void command.execute(`/courses/${encodeURIComponent(course.course_id)}/delete`, { expected_version: course.version })
        }}>{command.busy ? '正在删除…' : command.pending ? '重试同一删除请求' : '永久删除课程'}</button>}
    </div>
  </dialog>
}

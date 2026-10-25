import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Link, Route, Routes } from 'react-router-dom'
import { EmptyState, Shell } from './components/ui'
import Home from './pages/Home'
import CourseRun from './pages/CourseRun'
import Courses from './pages/Courses'
import CourseOverview from './pages/CourseOverview'
import Classroom from './pages/Classroom'
import QuizPage from './pages/Quiz'
import Assistance from './pages/Assistance'
import AssistanceBoard from './pages/AssistanceBoard'
import './styles/tokens.css'
import './styles/app.css'
import './styles/classroom.css'
import './styles/quiz.css'
import './styles/assistance.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode><BrowserRouter><Routes>
    <Route element={<Shell />}>
      <Route path="/" element={<Home />} />
      <Route path="/assistance" element={<Assistance />} />
      <Route path="/assistance/boards/:artifactId" element={<AssistanceBoard />} />
      <Route path="/assistance/:conversationId" element={<Assistance />} />
      <Route path="/course-runs/:runId" element={<CourseRun />} />
      <Route path="/courses" element={<Courses />} />
      <Route path="/courses/:courseId" element={<CourseOverview />} />
      <Route path="/courses/:courseId/sessions/:sessionId" element={<Classroom />} />
      <Route path="/courses/:courseId/sessions/:sessionId/practice" element={<QuizPage />} />
      <Route path="/courses/:courseId/exams/:examId" element={<QuizPage />} />
      <Route path="*" element={<div className="page"><EmptyState title="没有这个页面" action={<Link className="button primary" to="/">回到首页</Link>}>当前版本提供课程创建、课程目录和白板课堂。</EmptyState></div>} />
    </Route>
  </Routes></BrowserRouter></StrictMode>,
)

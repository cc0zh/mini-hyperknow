import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Link, Route, Routes } from 'react-router-dom'
import { EmptyState, Shell } from './components/ui'
import Home from './pages/Home'
import CourseRun from './pages/CourseRun'
import Courses from './pages/Courses'
import CourseOverview from './pages/CourseOverview'
import './styles/app.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode><BrowserRouter><Routes>
    <Route element={<Shell />}>
      <Route path="/" element={<Home />} />
      <Route path="/course-runs/:runId" element={<CourseRun />} />
      <Route path="/courses" element={<Courses />} />
      <Route path="/courses/:courseId" element={<CourseOverview />} />
      <Route path="*" element={<div className="page"><EmptyState title="没有这个页面" action={<Link className="button primary" to="/">回到首页</Link>}>当前版本提供课程创建、课程列表与目录总览。</EmptyState></div>} />
    </Route>
  </Routes></BrowserRouter></StrictMode>,
)

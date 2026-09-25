import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import AuthGuard from './components/AuthGuard'
import AdminPanel from './pages/AdminPanel'
import Login from './pages/Login'
import NotAuthorized from './pages/NotAuthorized'
import StudentDashboard from './pages/StudentDashboard'
import TeacherDashboard from './pages/TeacherDashboard'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/no-autorizado" element={<NotAuthorized />} />

        <Route element={<AuthGuard allowedRoles={['student']} />}>
          <Route path="/estudiante" element={<StudentDashboard />} />
        </Route>

        <Route element={<AuthGuard allowedRoles={['teacher']} />}>
          <Route path="/docente" element={<TeacherDashboard />} />
        </Route>

        <Route element={<AuthGuard allowedRoles={['admin']} />}>
          <Route path="/admin" element={<AdminPanel />} />
        </Route>

        <Route path="/" element={<Navigate to="/login" replace />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

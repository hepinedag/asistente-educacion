import { useAuthStore } from '../store/authStore'

const TITLE_BY_ROLE = {
  student: 'Panel del estudiante',
  teacher: 'Panel del docente',
  admin: 'Panel de administración',
}

export default function Layout({ title, children }) {
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="no-imprimir flex items-center justify-between border-b border-slate-200 bg-white px-8 py-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Asistente de Educación</p>
          <h1 className="text-xl font-semibold text-slate-800">{title || TITLE_BY_ROLE[user?.role] || ''}</h1>
        </div>

        <div className="flex items-center gap-4">
          <span className="text-sm text-slate-500">
            {user?.full_name} · {user?.role}
          </span>
          <button onClick={logout} className="rounded bg-slate-200 px-3 py-1 text-sm text-slate-700">
            Cerrar sesión
          </button>
        </div>
      </header>

      <main className="p-8">{children}</main>
    </div>
  )
}

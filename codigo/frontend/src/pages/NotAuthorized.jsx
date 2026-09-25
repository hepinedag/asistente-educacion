import { Link } from 'react-router-dom'

export default function NotAuthorized() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-100">
      <h1 className="text-2xl font-semibold text-slate-800">No autorizado</h1>
      <p className="text-slate-600">Tu rol no tiene acceso a esta zona del sistema.</p>
      <Link to="/login" className="text-sm text-slate-800 underline">
        Volver al inicio de sesión
      </Link>
    </div>
  )
}

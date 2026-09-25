import { useEffect, useState } from 'react'

import Layout from '../components/Layout'
import { usersApi } from '../lib/api'
import { useAuthStore } from '../store/authStore'

export default function AdminPanel() {
  const token = useAuthStore((state) => state.accessToken)
  const [users, setUsers] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    usersApi
      .list(token)
      .then(setUsers)
      .catch((err) => setError(err.message))
  }, [token])

  return (
    <Layout>
      {error && <p className="text-sm text-red-600">{error}</p>}

      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-slate-300 text-slate-500">
            <th className="py-2">Correo</th>
            <th className="py-2">Nombre</th>
            <th className="py-2">Rol</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} className="border-b border-slate-100">
              <td className="py-2">{u.email}</td>
              <td className="py-2">{u.full_name}</td>
              <td className="py-2">{u.role}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Layout>
  )
}

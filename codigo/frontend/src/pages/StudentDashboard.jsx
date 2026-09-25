import { useEffect, useRef, useState } from 'react'

import ArtifactPanel from '../components/ArtifactPanel'
import ConversationPanel from '../components/ConversationPanel'
import Layout from '../components/Layout'
import { artifactsApi } from '../lib/api'
import { useAuthStore } from '../store/authStore'

// La propuesta depende de lo que el estudiante acaba de conversar, asi que no
// basta consultarla al montar: se revisa cada tanto mientras el trabaja. Mismo
// intervalo que usa ConversationPanel para detectar cambios en el corpus.
const SUGGESTION_POLL_MS = 30000

const TABS = [
  { id: 'conversacion', label: 'Conversación' },
  { id: 'portafolio', label: 'Portafolio' },
]

export default function StudentDashboard() {
  const [tab, setTab] = useState('conversacion')
  const [suggestion, setSuggestion] = useState(null)
  // Tema que el estudiante descarto con "Ahora no", para no repetirselo en la
  // siguiente revision periodica.
  const descartadoRef = useRef(null)
  const token = useAuthStore((state) => state.accessToken)
  const environmentId = useAuthStore((state) => state.user?.environment_id)

  // La propuesta se consulta aqui, no dentro del portafolio, para poder avisar en
  // la pestaña mientras el estudiante sigue conversando: una propuesta que solo se
  // ve al entrar al portafolio no es proactiva, es un cartel esperando visita.
  useEffect(() => {
    if (!environmentId) return

    let cancelado = false
    const revisar = () =>
      artifactsApi
        .suggestion(token, environmentId)
        .then((data) => {
          if (cancelado) return
          // Si el estudiante ya dijo "ahora no", no se le vuelve a insistir con lo
          // mismo: solo se muestra cuando el tema propuesto es otro.
          setSuggestion((previa) => {
            if (!data.should_propose) return null
            if (previa === null && descartadoRef.current === data.topic) return null
            return data
          })
        })
        .catch(() => {})

    revisar()
    const id = setInterval(revisar, SUGGESTION_POLL_MS)
    return () => {
      cancelado = true
      clearInterval(id)
    }
  }, [token, environmentId])

  return (
    <Layout>
      <nav className="no-imprimir mb-5 flex gap-1 border-b border-slate-200">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setTab(item.id)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm ${
              tab === item.id
                ? 'border-slate-800 font-medium text-slate-800'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            {item.label}
            {item.id === 'portafolio' && suggestion && (
              <span
                aria-label="El sistema propone un artefacto"
                title="El sistema propone un artefacto"
                className="ml-1.5 inline-block h-2 w-2 rounded-full bg-emerald-500 align-middle"
              />
            )}
          </button>
        ))}
      </nav>

      {tab === 'conversacion' ? (
        <ConversationPanel />
      ) : (
        <ArtifactPanel
          suggestion={suggestion}
          onSuggestionUsed={() => {
            descartadoRef.current = suggestion?.topic || null
            setSuggestion(null)
          }}
        />
      )}
    </Layout>
  )
}

import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'

import { conversationApi, corpusApi, environmentsApi } from '../lib/api'
import { useAuthStore } from '../store/authStore'

const CORPUS_UPDATE_POLL_MS = 30000

const MARKDOWN_COMPONENTS = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  ul: ({ children }) => <ul className="mb-2 list-disc pl-4 last:mb-0">{children}</ul>,
  ol: ({ children }) => <ol className="mb-2 list-decimal pl-4 last:mb-0">{children}</ol>,
  li: ({ children }) => <li className="mb-0.5">{children}</li>,
  h1: ({ children }) => <h1 className="mb-1 text-base font-semibold">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-1 text-base font-semibold">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-1 text-sm font-semibold">{children}</h3>,
  code: ({ children }) => <code className="rounded bg-slate-200 px-1 py-0.5 text-xs">{children}</code>,
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer" className="underline">
      {children}
    </a>
  ),
}

function SourceList({ sources }) {
  if (!sources || sources.length === 0) return null

  return (
    <ul className="mt-1 space-y-0.5 text-xs text-slate-400">
      {sources.map((source, index) => (
        <li key={source.chunk_id || index}>
          Fuente: {source.filename || 'desconocida'}
          {source.page_number != null ? `, página ${source.page_number}` : ''}
        </li>
      ))}
    </ul>
  )
}

function SuggestionChips({ suggestions, onSelect }) {
  if (!suggestions || suggestions.length === 0) return null

  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {suggestions.map((suggestion, index) => (
        <button
          key={index}
          type="button"
          onClick={() => onSelect(suggestion)}
          className="rounded-full border border-slate-300 bg-white px-3 py-1 text-xs text-slate-600 hover:bg-slate-100"
        >
          {suggestion}
        </button>
      ))}
    </div>
  )
}

function ProgressSidebar({ welcome, progress }) {
  const hasProgress =
    progress && (progress.active || progress.completed.length > 0 || progress.pending.length > 0)

  return (
    <aside className="h-[65vh] space-y-4 overflow-y-auto text-sm">
      {welcome && (
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">Última sesión</h3>
          <p className="line-clamp-3 text-xs text-slate-600">{welcome}</p>
        </div>
      )}

      <div>
        <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">Temas</h3>
        {!hasProgress && <p className="text-xs text-slate-400">Aún no hay temas para mostrar.</p>}

        {progress?.active && (
          <p className="mb-1 flex items-start gap-1.5 text-xs font-bold text-emerald-700" title={progress.active.filename}>
            <span aria-hidden="true" className="mt-0.5">●</span>
            <span>{progress.active.display_title}</span>
          </p>
        )}
        {progress?.completed.map((doc) => (
          <p key={doc.filename} className="mb-1 flex items-start gap-1.5 text-xs text-slate-500" title={doc.filename}>
            <span aria-hidden="true" className="text-emerald-600">✓</span>
            <span>{doc.display_title}</span>
          </p>
        ))}
        {progress?.pending.map((doc) => (
          <p key={doc.filename} className="mb-1 flex items-start gap-1.5 text-xs text-slate-400" title={doc.filename}>
            <span aria-hidden="true" className="mt-0.5">○</span>
            <span>{doc.display_title}</span>
          </p>
        ))}
      </div>
    </aside>
  )
}

export default function ConversationPanel() {
  const token = useAuthStore((state) => state.accessToken)
  const user = useAuthStore((state) => state.user)
  const environmentId = user?.environment_id

  const [history, setHistory] = useState([])
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const [welcome, setWelcome] = useState(null)
  const [welcomeLoaded, setWelcomeLoaded] = useState(false)
  // La bienvenida la redacta el modelo de lenguaje: se pide una sola vez. En
  // desarrollo, React.StrictMode ejecuta cada efecto dos veces antes de que
  // welcomeLoaded cambie, y sin esta marca se generaban dos bienvenidas.
  const welcomeRequested = useRef(false)
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState(null)
  const [corpusUpdateNotice, setCorpusUpdateNotice] = useState(null)
  const [corpusLastUpdatedAt, setCorpusLastUpdatedAt] = useState(null)
  const [environment, setEnvironment] = useState(null)
  const [progress, setProgress] = useState(null)

  function refreshProgress() {
    if (!environmentId) return
    conversationApi
      .progress(token, environmentId)
      .then(setProgress)
      .catch(() => {})
  }

  useEffect(() => {
    if (!environmentId || historyLoaded) return
    conversationApi
      .history(token, environmentId)
      .then((data) => {
        setHistory(
          data.messages.map((msg) => ({
            speaker: msg.speaker,
            text: msg.text,
            sources: [],
            belowThreshold: msg.below_threshold,
          }))
        )
      })
      .catch(() => {})
      .finally(() => setHistoryLoaded(true))
  }, [token, environmentId, historyLoaded])

  useEffect(() => {
    if (!environmentId || welcomeLoaded || welcomeRequested.current) return
    welcomeRequested.current = true
    conversationApi
      .welcome(token, environmentId)
      .then((data) => setWelcome(data.message))
      .catch(() => {})
      .finally(() => setWelcomeLoaded(true))
  }, [token, environmentId, welcomeLoaded])

  useEffect(() => {
    if (!environmentId) return
    environmentsApi
      .get(token, environmentId)
      .then(setEnvironment)
      .catch(() => {})
  }, [token, environmentId])

  useEffect(() => {
    refreshProgress()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, environmentId])

  useEffect(() => {
    if (!environmentId || !user?.id) return

    const seenKey = `corpus_seen:${environmentId}:${user.id}`

    function checkForCorpusUpdate() {
      corpusApi
        .lastUpdated(token, environmentId)
        .then((data) => {
          const lastUpdatedAt = data.last_updated_at
          setCorpusLastUpdatedAt(lastUpdatedAt)
          if (!lastUpdatedAt) return
          const seen = localStorage.getItem(seenKey)
          if (seen !== lastUpdatedAt) {
            setCorpusUpdateNotice(
              'El docente actualizó el material de este entorno. Es posible que haya nueva información disponible.'
            )
            localStorage.setItem(seenKey, lastUpdatedAt)
          }
        })
        .catch(() => {})
    }

    checkForCorpusUpdate()
    const intervalId = setInterval(checkForCorpusUpdate, CORPUS_UPDATE_POLL_MS)
    return () => clearInterval(intervalId)
  }, [token, environmentId, user?.id])

  async function handleSubmit(event) {
    event.preventDefault()
    const text = message.trim()
    if (!text || !environmentId || sending) return

    setHistory((prev) => [...prev, { speaker: 'student', text }])
    setMessage('')
    setError(null)
    setSending(true)

    try {
      const result = await conversationApi.sendMessage(token, { message: text, environmentId })
      setHistory((prev) => [
        ...prev,
        {
          speaker: 'system',
          text: result.answer,
          sources: result.sources,
          belowThreshold: result.below_threshold,
          suggestions: result.suggestions,
        },
      ])
      refreshProgress()
    } catch (err) {
      setError(err.message)
    } finally {
      setSending(false)
    }
  }

  function handleSuggestionClick(suggestion) {
    setMessage(suggestion)
  }

  if (!environmentId) {
    return (
      <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-800">
        Tu cuenta no tiene un entorno académico asignado todavía. Contacta a tu docente o administrador
        para poder conversar con el asistente.
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 px-4 py-3">
        <h2 className="text-sm font-semibold text-slate-800">{environment?.name || 'Entorno académico'}</h2>
        {corpusLastUpdatedAt && (
          <p className="text-xs text-slate-400">
            Corpus actualizado el{' '}
            {new Date(corpusLastUpdatedAt).toLocaleDateString('es-ES', {
              day: 'numeric',
              month: 'long',
              year: 'numeric',
            })}
          </p>
        )}
      </div>

      <div className="grid grid-cols-[200px_1fr] gap-4 p-4">
        <ProgressSidebar welcome={welcome} progress={progress} />

        <div className="flex h-[65vh] flex-col">
          <div className="mb-3 flex items-center gap-2 border-b border-slate-200 pb-3">
            <span className="h-2 w-2 rounded-full bg-emerald-500" aria-hidden="true" />
            <span className="text-sm font-medium text-slate-800">Asistente de Educación</span>
          </div>

          <div className="flex-1 space-y-3 overflow-y-auto">
            {corpusUpdateNotice && (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">
                {corpusUpdateNotice}
              </div>
            )}

            {welcome && (
              <div className="rounded-lg border border-sky-200 bg-sky-50 p-3 text-sm text-sky-900">{welcome}</div>
            )}

            {history.length === 0 && (
              <p className="text-sm text-slate-400">Escribe tu primera pregunta sobre el corpus académico.</p>
            )}

            {history.map((entry, index) => (
              <div key={index} className={entry.speaker === 'student' ? 'text-right' : 'text-left'}>
                <div
                  className={
                    'inline-block max-w-[80%] rounded-lg px-3 py-2 text-sm ' +
                    (entry.speaker === 'student' ? 'bg-slate-800 text-white' : 'bg-slate-100 text-slate-800')
                  }
                >
                  {entry.speaker === 'system' ? (
                    <ReactMarkdown components={MARKDOWN_COMPONENTS}>{entry.text}</ReactMarkdown>
                  ) : (
                    entry.text
                  )}
                </div>
                {entry.speaker === 'system' && entry.belowThreshold && (
                  <p className="mt-1 text-xs text-amber-600">No se encontró suficiente información en el corpus.</p>
                )}
                {entry.speaker === 'system' && <SourceList sources={entry.sources} />}
                {entry.speaker === 'system' && (
                  <SuggestionChips suggestions={entry.suggestions} onSelect={handleSuggestionClick} />
                )}
              </div>
            ))}
          </div>

          {error && <p className="pb-2 pt-2 text-sm text-red-600">{error}</p>}

          <form onSubmit={handleSubmit} className="flex gap-2 border-t border-slate-200 pt-3">
            <input
              type="text"
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder="Escribe tu pregunta..."
              disabled={sending}
              className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
            />
            <button
              type="submit"
              disabled={sending || !message.trim()}
              className="rounded bg-slate-800 px-4 py-2 text-sm text-white disabled:opacity-50"
            >
              {sending ? 'Enviando...' : 'Enviar'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}

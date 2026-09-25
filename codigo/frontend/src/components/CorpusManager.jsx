import { useEffect, useState } from 'react'

import { corpusApi } from '../lib/api'
import { useAuthStore } from '../store/authStore'

// Mismo tope que el backend (MAX_BATCH_FILES): se avisa aqui para no gastar una
// subida entera y enterarse al final.
const MAX_ARCHIVOS = 30

export default function CorpusManager() {
  const token = useAuthStore((state) => state.accessToken)
  const user = useAuthStore((state) => state.user)

  const [environmentId, setEnvironmentId] = useState(user?.environment_id || '')
  const [files, setFiles] = useState([])
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState(null)
  const [feedback, setFeedback] = useState(null)
  const [resultados, setResultados] = useState([])

  const [status, setStatus] = useState(null)
  const [statusError, setStatusError] = useState(null)
  const [loadingStatus, setLoadingStatus] = useState(false)

  const [seleccion, setSeleccion] = useState([])
  const [depurando, setDepurando] = useState(false)
  const [editando, setEditando] = useState(null)
  const [borrador, setBorrador] = useState('')

  async function loadStatus(envId) {
    if (!envId) return
    setLoadingStatus(true)
    setStatusError(null)
    try {
      const result = await corpusApi.status(token, envId)
      setStatus(result)
      setSeleccion([])
    } catch (err) {
      setStatusError(err.message)
    } finally {
      setLoadingStatus(false)
    }
  }

  useEffect(() => {
    if (environmentId) loadStatus(environmentId)
    // Carga inicial unicamente; refrescos posteriores via el boton "Actualizar" o tras subir un documento.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleUpload(event) {
    event.preventDefault()
    if (!files.length || !environmentId || uploading) return

    setUploading(true)
    setUploadError(null)
    setFeedback(null)
    setResultados([])

    try {
      // Un solo archivo tambien va por la carga multiple: una sola ruta, un solo
      // comportamiento, y con ella la regla de que un archivo ya registrado se
      // reemplaza en vez de duplicarse.
      const result = await corpusApi.uploadBatch(token, { environmentId, files })
      setResultados(result.results)
      setFeedback(
        result.failed === 0
          ? `${result.indexed} de ${result.total} documentos indexados correctamente.`
          : `${result.indexed} de ${result.total} indexados; ${result.failed} con error.`,
      )
      setFiles([])
      event.target.reset()
      await loadStatus(environmentId)
    } catch (err) {
      setUploadError(err.message)
    } finally {
      setUploading(false)
    }
  }

  function alternar(documentId) {
    setSeleccion((actual) =>
      actual.includes(documentId) ? actual.filter((id) => id !== documentId) : [...actual, documentId],
    )
  }

  async function borrarSeleccionados() {
    if (!seleccion.length || depurando) return
    if (!window.confirm(`Se eliminarán ${seleccion.length} documento(s) del corpus. No hay deshacer. ¿Continuar?`)) return

    setDepurando(true)
    setStatusError(null)
    try {
      const result = await corpusApi.deleteDocuments(token, seleccion)
      setFeedback(`${result.deleted.length} documento(s) eliminados (${result.total_chunks_deleted} fragmentos).`)
      await loadStatus(environmentId)
    } catch (err) {
      setStatusError(err.message)
    } finally {
      setDepurando(false)
    }
  }

  async function vaciarCorpus() {
    if (!environmentId || depurando) return
    if (!window.confirm('Se eliminará TODO el corpus de este entorno. No hay deshacer. ¿Continuar?')) return

    setDepurando(true)
    setStatusError(null)
    try {
      const result = await corpusApi.deleteEnvironmentCorpus(token, environmentId)
      setFeedback(`Corpus vaciado: ${result.deleted.length} documento(s), ${result.total_chunks_deleted} fragmentos.`)
      await loadStatus(environmentId)
    } catch (err) {
      setStatusError(err.message)
    } finally {
      setDepurando(false)
    }
  }

  async function guardarTitulo(documentId) {
    const previo = documentos.find((d) => d.document_id === documentId)?.visible_title || ''
    setEditando(null)
    if (borrador.trim() === previo.trim()) return
    try {
      const actualizado = await corpusApi.updateTitle(token, documentId, borrador.trim())
      setStatus((actual) => ({
        ...actual,
        documents: actual.documents.map((d) => (d.document_id === documentId ? actualizado : d)),
      }))
    } catch (err) {
      setStatusError(err.message)
    }
  }

  const documentos = status?.documents ?? []

  return (
    <div className="space-y-6">
      <form onSubmit={handleUpload} className="space-y-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <h2 className="text-lg font-medium text-slate-800">Subir documentos al corpus</h2>

        <div>
          <label className="block text-sm font-medium text-slate-700">ID del entorno académico</label>
          <input
            type="text"
            required
            value={environmentId}
            onChange={(event) => setEnvironmentId(event.target.value)}
            placeholder="uuid del entorno"
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700">
            Archivos (PDF, Word o Markdown) — puede seleccionar varios
          </label>
          <input
            type="file"
            accept=".pdf,.docx,.md"
            multiple
            required
            onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
            className="mt-1 w-full text-sm"
          />
          {files.length > 0 && (
            <p className="mt-1 text-xs text-slate-500">
              {files.length} archivo(s) seleccionado(s)
              {files.length > MAX_ARCHIVOS && (
                <span className="text-red-600"> — el máximo por operación es {MAX_ARCHIVOS}</span>
              )}
            </p>
          )}
          <p className="mt-1 text-xs text-slate-400">
            Un archivo que ya esté en el corpus se reemplaza y sube de versión; no se duplica.
          </p>
        </div>

        {uploadError && <p className="text-sm text-red-600">{uploadError}</p>}
        {feedback && <p className="text-sm text-green-700">{feedback}</p>}

        <button
          type="submit"
          disabled={uploading || !files.length || files.length > MAX_ARCHIVOS || !environmentId}
          className="rounded bg-slate-800 px-4 py-2 text-sm text-white disabled:opacity-50"
        >
          {uploading ? `Subiendo e indexando ${files.length} archivo(s)...` : 'Subir e indexar'}
        </button>

        {resultados.length > 0 && (
          <ul className="mt-2 space-y-1 text-xs">
            {resultados.map((r) => (
              <li key={r.filename} className={r.ok ? 'text-slate-600' : 'text-red-600'}>
                {r.ok ? '✓' : '✗'} {r.filename}
                {r.ok
                  ? ` — ${r.chunks_created} fragmentos${r.action === 'update' ? ` (reemplazo, v${r.version_number})` : ''}`
                  : ` — ${r.error}`}
              </li>
            ))}
          </ul>
        )}
      </form>

      <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-medium text-slate-800">Estado del corpus</h2>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => loadStatus(environmentId)}
              disabled={!environmentId || loadingStatus}
              className="rounded bg-slate-200 px-3 py-1 text-sm text-slate-700 disabled:opacity-50"
            >
              {loadingStatus ? 'Actualizando...' : 'Actualizar'}
            </button>
            <button
              type="button"
              onClick={borrarSeleccionados}
              disabled={!seleccion.length || depurando}
              className="rounded bg-amber-600 px-3 py-1 text-sm text-white disabled:opacity-40"
            >
              Eliminar selección ({seleccion.length})
            </button>
            <button
              type="button"
              onClick={vaciarCorpus}
              disabled={!documentos.length || depurando}
              className="rounded bg-red-700 px-3 py-1 text-sm text-white disabled:opacity-40"
            >
              Vaciar corpus
            </button>
          </div>
        </div>

        {statusError && <p className="mt-2 text-sm text-red-600">{statusError}</p>}

        {status && (
          <p className="mt-2 text-sm text-slate-500">
            {status.total_documents} documentos · {status.total_chunks} fragmentos indexados
          </p>
        )}

        <table className="mt-4 w-full text-left text-sm">
          <thead>
            <tr className="border-b border-slate-300 text-slate-500">
              <th className="w-8 py-2">
                <input
                  type="checkbox"
                  checked={documentos.length > 0 && seleccion.length === documentos.length}
                  onChange={(event) =>
                    setSeleccion(event.target.checked ? documentos.map((d) => d.document_id) : [])
                  }
                />
              </th>
              <th className="py-2">Archivo</th>
              <th className="py-2">Tema que aborda</th>
              <th className="py-2">Estado</th>
              <th className="py-2">Fragmentos</th>
              <th className="py-2">Indexado</th>
            </tr>
          </thead>
          <tbody>
            {documentos.map((doc) => (
              <tr key={doc.document_id} className="border-b border-slate-100 align-top">
                <td className="py-2">
                  <input
                    type="checkbox"
                    checked={seleccion.includes(doc.document_id)}
                    onChange={() => alternar(doc.document_id)}
                  />
                </td>
                {/* El corpus se compone de ARCHIVOS: aqui va el nombre del
                    documento cargado, que es la fuente real, no el titulo del tema. */}
                <td className="py-2">{doc.filename}</td>
                {/* De que trata el documento, que es distinto de como se llama el
                    archivo. Lo sugiere el sistema leyendo el propio documento y el
                    docente lo confirma, lo corrige o lo borra; vacio = se muestra el
                    nombre del archivo. */}
                <td className="py-2">
                  {editando === doc.document_id ? (
                    <input
                      autoFocus
                      value={borrador}
                      onChange={(e) => setBorrador(e.target.value)}
                      onBlur={() => guardarTitulo(doc.document_id)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') guardarTitulo(doc.document_id)
                        if (e.key === 'Escape') setEditando(null)
                      }}
                      className="w-full rounded border border-slate-300 px-1 py-0.5 text-sm"
                    />
                  ) : (
                    <button
                      type="button"
                      onClick={() => {
                        setEditando(doc.document_id)
                        setBorrador(doc.visible_title || '')
                      }}
                      className="w-full text-left hover:underline"
                      title="Clic para editar"
                    >
                      {doc.visible_title || <span className="text-slate-400">sin tema</span>}
                    </button>
                  )}
                </td>
                <td className="py-2">
                  {doc.status}
                  {doc.error_message && (
                    <span className="block text-xs text-red-600" title={doc.error_message}>
                      {doc.error_message.slice(0, 80)}
                    </span>
                  )}
                </td>
                <td className="py-2">{doc.chunk_count ?? '-'}</td>
                <td className="py-2">{doc.indexed_at ? new Date(doc.indexed_at).toLocaleString() : '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {documentos.length === 0 && !loadingStatus && (
          <p className="mt-3 text-sm text-slate-400">Aún no se han subido documentos a este entorno.</p>
        )}
      </div>
    </div>
  )
}

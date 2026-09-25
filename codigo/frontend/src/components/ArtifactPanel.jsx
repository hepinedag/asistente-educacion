import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
// El glosario se genera como tabla de Markdown, y react-markdown no entiende
// tablas sin este plugin: sin el, el artefacto se ve como un muro de barras.
// Se usa solo aqui, no en ConversationPanel, que no las necesita.
import remarkGfm from 'remark-gfm'

import { artifactsApi } from '../lib/api'
import { useAuthStore } from '../store/authStore'

// Los mismos siete tipos de app/models/artifact.py. "" = que lo deduzca el backend
// a partir del texto, que es el caso normal cuando el estudiante escribe su peticion.
const ARTIFACT_TYPES = [
  { value: '', label: 'Detectar según lo que escriba' },
  { value: 'resumen', label: 'Resumen estructurado' },
  { value: 'mapa_conceptual', label: 'Mapa conceptual' },
  { value: 'ejercicio_aplicacion', label: 'Ejercicio de aplicación' },
  { value: 'caso_practico', label: 'Caso práctico' },
  { value: 'autovaloracion', label: 'Instrumento de autovaloración' },
  { value: 'glosario', label: 'Glosario temático' },
  { value: 'flash_cards', label: 'Flash cards' },
  { value: 'cuestionario', label: 'Cuestionario de opción múltiple' },
]

const TYPE_LABELS = ARTIFACT_TYPES.reduce((acc, type) => {
  if (type.value) acc[type.value] = type.label
  return acc
}, {})

const MARKDOWN_COMPONENTS = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  ul: ({ children }) => <ul className="mb-2 list-disc pl-4 last:mb-0">{children}</ul>,
  ol: ({ children }) => <ol className="mb-2 list-decimal pl-4 last:mb-0">{children}</ol>,
  li: ({ children }) => <li className="mb-0.5">{children}</li>,
  h1: ({ children }) => <h1 className="mb-2 text-base font-semibold">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-2 text-base font-semibold">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-1 mt-3 text-sm font-semibold">{children}</h3>,
  code: ({ children }) => <code className="rounded bg-slate-200 px-1 py-0.5 text-xs">{children}</code>,
  table: ({ children }) => (
    <div className="mb-2 overflow-x-auto">
      <table className="w-full border-collapse text-xs">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border border-slate-300 bg-slate-100 px-2 py-1 text-left font-semibold">{children}</th>
  ),
  td: ({ children }) => <td className="border border-slate-200 px-2 py-1 align-top">{children}</td>,
}

// Red de seguridad: si por lo que sea el bloque de continuacion llega dentro del
// contenido en vez de separado por el motor, se separa aqui. El estudiante nunca
// debe ver los marcadores en crudo, ni perder los temas por un fallo de reparto.
const CONTINUATION_BLOCK = /\[\[CONTINUACION\]\]([\s\S]*?)\[\[\/CONTINUACION\]\]/

function splitContinuations(artifact) {
  const content = artifact?.content || ''
  const match = CONTINUATION_BLOCK.exec(content)
  if (!match) return { content, suggestions: artifact?.suggestions || [] }

  const temas = match[1]
    .split(/\r?\n/)
    .map((linea) => linea.replace(/^\s*(?:[-*•]|\d+[.)])\s*/, '').trim())
    .filter(Boolean)
  return {
    content: (content.slice(0, match.index) + content.slice(match.index + match[0].length)).trim(),
    suggestions: artifact?.suggestions?.length ? artifact.suggestions : temas.slice(0, 3),
  }
}

function formatDate(value) {
  if (!value) return ''
  return new Date(value).toLocaleString('es-ES', { dateStyle: 'medium', timeStyle: 'short' })
}

function slugify(text) {
  return (text || 'artefacto')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 50)
}

function downloadMarkdown(artifact) {
  // El artefacto ya viene en Markdown desde el motor: se descarga tal cual, sin
  // procesarlo aqui, para que lo que el estudiante guarda sea lo que ve.
  const header = `# ${TYPE_LABELS[artifact.artifact_type] || 'Artefacto'}\n\n> Tema: ${artifact.topic}\n> Generado: ${formatDate(artifact.created_at)}\n\n---\n\n`
  const blob = new Blob([header + artifact.content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${slugify(artifact.topic)}.md`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

// El motor emite el mapa como lineas indentadas con la forma
// "concepto -- relacion --> concepto", y el concepto padre se repite en cada
// hija. Aqui se parte esa linea para mostrar solo la relacion y el concepto
// nuevo: el padre ya esta encima, repetirlo es lo que hacia el mapa ilegible.
const CONCEPT_LINE = /^(\s*)(.+?)\s+--\s*(.+?)\s*-->\s+(.+)$/
const TRAILING_SOURCE = /\s*\(([^()]*(?:\.pdf|Sesi[oó]n|p\.)[^()]*)\)\s*$/

// La jerarquia es un arbol; los enlaces cruzados conectan ramas distintas y van
// en su propia seccion al final, porque la indentacion no puede expresarlos.
const CROSS_LINK_HEADING = /^enlaces\s+cruzados\s*:?/i

function splitConceptMap(content) {
  const lines = (content || '').split('\n')
  const index = lines.findIndex((line) => CROSS_LINK_HEADING.test(line.trim()))
  if (index === -1) return { hierarchy: content || '', crossLinks: [] }

  const heading = lines[index].trim().replace(CROSS_LINK_HEADING, '').trim()
  const rest = [heading, ...lines.slice(index + 1)].filter((line) => line.trim())
  const crossLinks = rest
    .map((line) => {
      const match = CONCEPT_LINE.exec(line)
      if (!match) return null
      return { from: match[2].trim(), relation: match[3], to: match[4].trim() }
    })
    .filter(Boolean)
  return { hierarchy: lines.slice(0, index).join('\n'), crossLinks }
}

function parseConceptMap(content) {
  return (content || '')
    .split('\n')
    .filter((line) => line.trim())
    .map((line) => {
      const match = CONCEPT_LINE.exec(line)
      const indent = line.length - line.trimStart().length
      const level = Math.floor(indent / 2)
      if (!match) {
        const [, source] = line.trim().match(TRAILING_SOURCE) || []
        return { level, relation: null, concept: line.trim().replace(TRAILING_SOURCE, ''), source }
      }
      const raw = match[4]
      const [, source] = raw.match(TRAILING_SOURCE) || []
      return {
        level,
        relation: match[3],
        concept: raw.replace(TRAILING_SOURCE, '').trim(),
        // El origen de la linea: normalmente ya esta escrito encima como concepto
        // padre, pero en la primera linea no hay nada encima y hace falta.
        parent: match[2].replace(TRAILING_SOURCE, '').trim(),
        source,
      }
    })
}

// El modelo unas veces abre el mapa con el concepto raiz a secas y otras con una
// proposicion completa ("Proceso ETL -- es una metodologia de --> Gestion de
// datos"). En el segundo caso la raiz real es el ORIGEN de esa linea, y si no se
// recupera aqui desaparece del mapa: el titulo mostraria el destino y todo el
// arbol quedaria colgando de un concepto que no es el tema.
function withExplicitRoot(nodes) {
  if (!nodes.length || !nodes[0].relation || !nodes[0].parent) return nodes
  return [
    { level: 0, relation: null, concept: nodes[0].parent },
    ...nodes.map((node) => ({ ...node, level: node.level + 1 })),
  ]
}

// Un enlace cruzado cuyo extremo no esta en la jerarquia no cruza nada: es un
// concepto nuevo colado en la seccion equivocada. Se descarta al mostrar, para
// que el mapa no afirme relaciones sobre conceptos que no contiene.
function normalizeConcept(text) {
  return (text || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9 ]/g, '')
    .trim()
}

function ConceptMap({ content }) {
  const { hierarchy, crossLinks } = splitConceptMap(content)
  const nodes = withExplicitRoot(parseConceptMap(hierarchy))
  const known = new Set(nodes.map((node) => normalizeConcept(node.concept)))
  const validCrossLinks = crossLinks.filter(
    (link) => known.has(normalizeConcept(link.from)) && known.has(normalizeConcept(link.to))
  )

  return (
    <div className="space-y-1 text-sm">
      {nodes.map((node, index) => (
        <div
          key={index}
          style={{ marginLeft: `${node.level * 20}px` }}
          className={
            node.level === 0
              ? 'rounded bg-slate-800 px-3 py-1.5 font-semibold text-white'
              : 'border-l-2 border-slate-200 pl-3'
          }
        >
          {node.relation && (
            <span className="mr-2 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-500">
              {node.relation}
            </span>
          )}
          <span className={node.level === 0 ? '' : 'text-slate-700'}>{node.concept}</span>
          {node.source && <span className="ml-2 text-[11px] text-slate-400">{node.source}</span>}
        </div>
      ))}

      {validCrossLinks.length > 0 && (
        <div className="mt-4 rounded border border-dashed border-slate-300 bg-slate-50 p-3">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
            Enlaces cruzados entre ramas
          </h4>
          <ul className="space-y-1">
            {validCrossLinks.map((link, index) => (
              <li key={index} className="text-slate-700">
                <span className="font-medium">{link.from}</span>
                <span className="mx-2 rounded-full bg-white px-2 py-0.5 text-[11px] text-slate-500">
                  {link.relation}
                </span>
                <span className="font-medium">{link.to}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

// El motor emite las flash cards como tabla de dos columnas -- es lo que mejor
// viaja en Markdown y en la descarga .md --, pero una tabla no se lee como un
// juego de tarjetas. Aqui se parte en fichas: pregunta arriba, respuesta debajo
// de una linea de corte, y cada ficha entera sin partirse entre dos paginas.
function parseFlashCards(content) {
  const filas = (content || '')
    .split(/\r?\n/)
    .map((linea) => linea.trim())
    .filter((linea) => linea.startsWith('|'))
    .filter((linea) => !/^\|[\s\-:|]+\|$/.test(linea))

  const tarjetas = filas
    .map((linea) => linea.replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim()))
    .filter((celdas) => celdas.length >= 2 && celdas[0] && celdas[1])
    .map(([pregunta, respuesta]) => ({ pregunta, respuesta }))

  // La primera fila es el encabezado de la tabla, no una tarjeta.
  if (tarjetas.length && /^(pregunta|anverso|frente)$/i.test(tarjetas[0].pregunta)) {
    return tarjetas.slice(1)
  }
  return tarjetas
}

function FlashCards({ content }) {
  const tarjetas = parseFlashCards(content)

  // Si el contenido no tiene forma de tabla, se muestra tal cual antes que nada.
  if (tarjetas.length === 0) {
    return (
      <div className="text-sm leading-relaxed text-slate-700">
        <ReactMarkdown components={MARKDOWN_COMPONENTS} remarkPlugins={[remarkGfm]}>
          {content}
        </ReactMarkdown>
      </div>
    )
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {tarjetas.map((tarjeta, index) => (
        <article
          key={index}
          className="tarjeta flex flex-col rounded-lg border border-slate-300 bg-white shadow-sm"
        >
          <div className="px-4 pb-3 pt-3">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              {index + 1} de {tarjetas.length}
            </span>
            <p className="mt-1 text-sm font-semibold leading-snug text-slate-800">
              {tarjeta.pregunta}
            </p>
          </div>
          <div className="border-t border-dashed border-slate-300 px-4 pb-3 pt-2 text-xs leading-relaxed text-slate-600">
            <ReactMarkdown components={MARKDOWN_COMPONENTS} remarkPlugins={[remarkGfm]}>
              {tarjeta.respuesta}
            </ReactMarkdown>
          </div>
        </article>
      ))}
    </div>
  )
}

function ArtifactSources({ sources }) {
  if (!sources || sources.length === 0) return null

  return (
    <div className="mt-4 border-t border-slate-200 pt-3">
      <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
        Material del corpus que lo sustenta
      </h4>
      <ul className="space-y-0.5 text-xs text-slate-500">
        {sources.map((source, index) => (
          <li key={source.chunk_id || index}>
            {source.filename || 'desconocida'}
            {source.page_number != null ? `, página ${source.page_number}` : ''}
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function ArtifactPanel({ suggestion = null, onSuggestionUsed = () => {} }) {
  const token = useAuthStore((state) => state.accessToken)
  const user = useAuthStore((state) => state.user)
  const environmentId = user?.environment_id

  const [topic, setTopic] = useState('')
  const [artifactType, setArtifactType] = useState('')
  const [artifacts, setArtifacts] = useState([])
  const [selected, setSelected] = useState(null)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!environmentId) return
    artifactsApi
      .list(token, environmentId)
      .then((data) => setArtifacts(data.artifacts))
      .catch(() => setArtifacts([]))
  }, [token, environmentId])

  // Retirar NO borra: el artefacto y las fuentes que lo sustentan siguen en la
  // base. Lo que cambia es que deja de estar vigente y sale del portafolio.
  const retirar = async (artifactId, event) => {
    event.stopPropagation()
    if (!window.confirm('Se retirará este artefacto de tu portafolio. ¿Continuar?')) return
    setError('')
    try {
      await artifactsApi.retire(token, artifactId)
      setArtifacts((actuales) => actuales.filter((a) => a.id !== artifactId))
      setSelected((actual) => (actual?.id === artifactId ? null : actual))
    } catch (err) {
      setError(err.message)
    }
  }

  const vaciarPortafolio = async () => {
    if (!artifacts.length) return
    if (!window.confirm(`Se retirarán los ${artifacts.length} artefactos de tu portafolio. ¿Continuar?`)) return
    setError('')
    try {
      await artifactsApi.retireAll(token, environmentId)
      setArtifacts([])
      setSelected(null)
    } catch (err) {
      setError(err.message)
    }
  }

  const openArtifact = (artifactId) => {
    setError('')
    artifactsApi
      .get(token, artifactId)
      .then(setSelected)
      .catch((err) => setError(err.message))
  }

  const runGeneration = async (requestedTopic, requestedType, focus = [], anchorFilename = null) => {
    if (!requestedTopic.trim() || generating) return

    setGenerating(true)
    setError('')
    try {
      const artifact = await artifactsApi.create(token, {
        environmentId,
        topic: requestedTopic.trim(),
        artifactType: requestedType,
        focus,
        anchorFilename,
      })
      setSelected(artifact)
      setTopic('')
      const data = await artifactsApi.list(token, environmentId)
      setArtifacts(data.artifacts)
    } catch (err) {
      // El 404 del backend significa "no hay material suficiente en el corpus":
      // se muestra tal cual, porque es informacion util y no un fallo tecnico.
      setError(err.message)
    } finally {
      setGenerating(false)
    }
  }

  const generate = (event) => {
    event.preventDefault()
    runGeneration(topic, artifactType)
  }

  const acceptSuggestion = async () => {
    // La propuesta desaparece en cuanto se acepta: una vez generado el artefacto,
    // el backend dejaria de proponerlo igualmente en la siguiente consulta.
    onSuggestionUsed()
    // Las preguntas que motivaron la propuesta viajan como foco: el resumen debe
    // tratar lo que el estudiante pregunto, no el tema entero del corpus.
    await runGeneration(
      suggestion.topic,
      suggestion.artifact_type,
      suggestion.focus || [],
      suggestion.anchor_filename || null
    )
  }

  if (!environmentId) {
    return (
      <p className="text-sm text-slate-500">
        Todavía no tienes un entorno académico asignado. Pídeselo a tu docente para poder generar
        artefactos.
      </p>
    )
  }

  return (
    <div className="grid gap-6 md:grid-cols-[300px_1fr]">
      <aside className="no-imprimir space-y-4">
        {suggestion && (
          <div className="space-y-2 rounded border border-emerald-200 bg-emerald-50 p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-emerald-700">
              El sistema te propone
            </p>
            <p className="text-sm text-slate-700">{suggestion.reason}</p>
            <p className="text-xs text-slate-500">
              ¿Quieres un resumen de «{suggestion.topic}» que puedas guardar y revisar más
              adelante?
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={acceptSuggestion}
                disabled={generating}
                className="rounded bg-emerald-700 px-3 py-1.5 text-xs text-white disabled:bg-slate-300"
              >
                Generarlo
              </button>
              <button
                type="button"
                onClick={onSuggestionUsed}
                className="rounded border border-emerald-300 px-3 py-1.5 text-xs text-emerald-800"
              >
                Ahora no
              </button>
            </div>
          </div>
        )}

        <form onSubmit={generate} className="space-y-2 rounded border border-slate-200 bg-white p-3">
          <label className="block text-xs font-semibold uppercase tracking-wide text-slate-400">
            Nuevo artefacto
          </label>
          <input
            type="text"
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
            placeholder="Ej.: un mapa conceptual de groupby en pandas"
            className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
            disabled={generating}
          />
          <select
            value={artifactType}
            onChange={(event) => setArtifactType(event.target.value)}
            className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm text-slate-600"
            disabled={generating}
          >
            {ARTIFACT_TYPES.map((type) => (
              <option key={type.value} value={type.value}>
                {type.label}
              </option>
            ))}
          </select>
          <button
            type="submit"
            disabled={generating || !topic.trim()}
            className="w-full rounded bg-slate-800 px-3 py-1.5 text-sm text-white disabled:bg-slate-300"
          >
            {generating ? 'Generando…' : 'Generar'}
          </button>
          {generating && (
            <p className="text-xs text-slate-400">
              Se está construyendo a partir del corpus del entorno. Tarda unos segundos.
            </p>
          )}
          {error && <p className="text-xs text-amber-700">{error}</p>}
        </form>

        <div>
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
              Portafolio ({artifacts.length})
            </h3>
            {artifacts.length > 0 && (
              <button
                type="button"
                onClick={vaciarPortafolio}
                className="no-imprimir text-[11px] text-slate-400 underline hover:text-red-600"
              >
                Vaciar
              </button>
            )}
          </div>
          {artifacts.length === 0 && (
            <p className="text-xs text-slate-400">
              Aún no has generado ningún artefacto en este entorno.
            </p>
          )}
          {/* La lista crece sin limite con el uso: con altura fija y desplazamiento
              propio, el visor de la derecha no se descuelga por debajo del portafolio.
              No se imprime, asi que no hace falta soltar la altura para el PDF. */}
          <ul className="max-h-[58vh] space-y-1 overflow-y-auto pr-1">
            {artifacts.map((artifact) => (
              <li key={artifact.id} className="group relative">
                <button
                  type="button"
                  onClick={(evento) => retirar(artifact.id, evento)}
                  title="Retirar del portafolio"
                  className="no-imprimir absolute right-1 top-1 text-xs leading-none text-slate-400 hover:text-red-600"
                >
                  ×
                </button>
                <button
                  type="button"
                  onClick={() => openArtifact(artifact.id)}
                  className={`w-full rounded border px-2 py-1.5 text-left text-xs ${
                    selected?.id === artifact.id
                      ? 'border-slate-400 bg-slate-100'
                      : 'border-slate-200 bg-white hover:bg-slate-50'
                  }`}
                >
                  <span className="block font-medium text-slate-700">
                    {TYPE_LABELS[artifact.artifact_type] || artifact.artifact_type}
                  </span>
                  <span className="block truncate text-slate-500" title={artifact.topic}>
                    {artifact.topic}
                  </span>
                  <span className="block text-[11px] text-slate-400">
                    {formatDate(artifact.created_at)} · {artifact.source_count} fuente
                    {artifact.source_count === 1 ? '' : 's'}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </aside>

      <section className="zona-imprimible min-h-[65vh] rounded border border-slate-200 bg-white p-5">
        {!selected && (
          <p className="text-sm text-slate-400">
            Escribe un tema y genera un artefacto, o abre uno de tu portafolio para verlo aquí.
          </p>
        )}

        {selected && (() => {
          const vista = splitContinuations(selected)
          return (
          <article>
            <header className="mb-4 flex items-start justify-between gap-4 border-b border-slate-200 pb-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                  {TYPE_LABELS[selected.artifact_type] || selected.artifact_type}
                </p>
                <h2 className="text-base font-semibold text-slate-800">{selected.topic}</h2>
                <p className="text-xs text-slate-400">{formatDate(selected.created_at)}</p>
              </div>
              <div className="no-imprimir flex shrink-0 gap-2">
                <button
                  type="button"
                  onClick={() => downloadMarkdown(selected)}
                  className="rounded border border-slate-300 px-3 py-1 text-xs text-slate-600 hover:bg-slate-50"
                >
                  Descargar .md
                </button>
                {/* El PDF lo fabrica el navegador con la hoja de estilo de impresion
                    (ver index.css): sin dependencias y sin carga en el servidor. */}
                <button
                  type="button"
                  onClick={() => window.print()}
                  className="rounded border border-slate-300 px-3 py-1 text-xs text-slate-600 hover:bg-slate-50"
                >
                  Descargar PDF
                </button>
              </div>
            </header>

            {/* Solo el mapa conceptual tiene estructura propia que Markdown no sabe
                representar; el resto son documentos y se renderizan como tales. */}
            {selected.artifact_type === 'mapa_conceptual' ? (
              <ConceptMap content={vista.content} />
            ) : selected.artifact_type === 'flash_cards' ? (
              <FlashCards content={vista.content} />
            ) : (
              <div className="text-sm leading-relaxed text-slate-700">
                <ReactMarkdown components={MARKDOWN_COMPONENTS} remarkPlugins={[remarkGfm]}>
                  {vista.content}
                </ReactMarkdown>
              </div>
            )}

            <ArtifactSources sources={selected.sources} />

            {vista.suggestions?.length > 0 && (
              <div className="no-imprimir mt-4 border-t border-slate-200 pt-3">
                <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
                  Continuar con
                </h4>
                <div className="flex flex-wrap gap-1.5">
                  {vista.suggestions.map((tema, index) => (
                    <button
                      key={index}
                      type="button"
                      disabled={generating}
                      onClick={() => runGeneration(tema, '')}
                      className="rounded-full border border-slate-300 bg-white px-3 py-1 text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-50"
                    >
                      {tema}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </article>
          )
        })()}
      </section>
    </div>
  )
}

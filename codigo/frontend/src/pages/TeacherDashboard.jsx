import { useEffect, useState } from 'react'
import { useAuthStore } from '../store/authStore'
import { authApi, corpusApi, environmentsApi, teacherApi } from '../lib/api'
import CorpusManager from '../components/CorpusManager'
import Layout from '../components/Layout'

const DASHBOARD_POLL_MS = 30000

export default function TeacherDashboard() {
  const { accessToken, refreshToken, user, setSession } = useAuthStore()
  const [dashboard, setDashboard] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [corpusStatus, setCorpusStatus] = useState(null)

  useEffect(() => {
    if (!user?.environment_id) return

    function loadDashboard(isFirstLoad) {
      if (isFirstLoad) setLoading(true)
      teacherApi
        .dashboard(accessToken, user.environment_id)
        .then((data) => {
          setDashboard(data)
          setError(null)
        })
        .catch((err) => setError(err.message))
        .finally(() => {
          if (isFirstLoad) setLoading(false)
        })
    }

    loadDashboard(true)
    const intervalId = setInterval(() => loadDashboard(false), DASHBOARD_POLL_MS)
    return () => clearInterval(intervalId)
  }, [accessToken, user?.environment_id])

  useEffect(() => {
    if (!user?.environment_id) return
    corpusApi
      .status(accessToken, user.environment_id)
      .then(setCorpusStatus)
      .catch(() => {})
  }, [accessToken, user?.environment_id])

  function handleEnvironmentCreated(updatedUser) {
    setSession({ accessToken, refreshToken, user: updatedUser })
  }

  return (
    <Layout>
      <h2 className="text-xl font-semibold text-slate-800 mb-6">Panel del Docente</h2>

      <EnvironmentPanel
        user={user}
        accessToken={accessToken}
        onEnvironmentCreated={handleEnvironmentCreated}
      />

      {loading && <p className="text-slate-400 text-sm mb-6">Cargando métricas...</p>}
      {error && <p className="text-red-600 text-sm mb-6">{error}</p>}

      {dashboard && (
        <>
          <section className="mb-8">
            <div className="grid grid-cols-3 gap-4">
              <PlainMetric label="Estudiantes activos" value={dashboard.metrics.active_students} />
              <PlainMetric label="Retención (7 días)" value={`${dashboard.metrics.retention_pct}%`} />
              <PlainMetric label="Consultas hoy" value={dashboard.metrics.queries_today} />
            </div>
          </section>

          {/* Fila 1: Actividad del grupo | Alertas del sistema */}
          {/* Fila 2: Estado del corpus | Temas más consultados */}
          <section className="mb-8 grid grid-cols-2 gap-4">
            <Card title="Actividad del grupo">
              {dashboard.student_activity.length === 0 ? (
                <EmptyNotice text="Sin estudiantes registrados en este entorno." />
              ) : (
                <div className="max-h-64 space-y-1 overflow-y-auto">
                  {dashboard.student_activity.map((student) => (
                    <StudentRow key={student.student_id} student={student} />
                  ))}
                </div>
              )}
            </Card>

            <Card title="Alertas del sistema">
              <AlertsPanel alerts={dashboard.alerts} />
            </Card>

            <Card title="Estado del corpus">
              <CorpusStatusCard corpusStatus={corpusStatus} />
            </Card>

            <Card title="Temas más consultados">
              <DocumentList documents={dashboard.extended_metrics.top_cited_documents} />
            </Card>
          </section>

          {/* Fila 3: Métricas ampliadas */}
          <section className="mb-8">
            <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wide mb-3">
              Métricas ampliadas
            </h3>
            <div className="grid grid-cols-2 gap-4 mb-4">
              <PlainMetricOrNotice
                label="Promedio de consultas por estudiante"
                value={dashboard.extended_metrics.avg_queries_per_student}
              />
              <PlainMetricOrNotice
                label="Hora pico de actividad del grupo"
                value={
                  dashboard.extended_metrics.peak_activity_hour
                    ? `${String(dashboard.extended_metrics.peak_activity_hour.hour).padStart(2, '0')}:00 (${
                        dashboard.extended_metrics.peak_activity_hour.message_count
                      } mensajes)`
                    : null
                }
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Card title="Documentos con más below_threshold">
                <DocumentList documents={dashboard.extended_metrics.top_below_threshold_documents} />
              </Card>
              <Card title="Evolución de actividad semanal">
                {dashboard.extended_metrics.weekly_activity.length === 0 ? (
                  <EmptyNotice text="Acumulando datos desde el despliegue." />
                ) : (
                  <WeeklyActivityChart points={dashboard.extended_metrics.weekly_activity} />
                )}
              </Card>
            </div>
          </section>

          {/* Fila 4: Tendencias de comportamiento */}
          <section className="mb-8">
            <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wide mb-3">
              Tendencias de comportamiento
            </h3>
            <Card title="Evolución del ratio below_threshold">
              {dashboard.extended_metrics.weekly_below_threshold.length === 0 ? (
                <EmptyNotice text="Acumulando datos desde el despliegue." />
              ) : (
                <WeeklyBelowThresholdChart points={dashboard.extended_metrics.weekly_below_threshold} />
              )}
            </Card>
          </section>

          {/* Fila 5: Factores relevantes de comportamiento */}
          <section className="mb-8">
            <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wide mb-3">
              Factores relevantes de comportamiento
            </h3>
            <div className="grid grid-cols-3 gap-4">
              <Card title="Estudiantes que profundizan">
                <BehaviorList students={dashboard.behavior_insights.deep_students} valueClassName="text-emerald-600" />
              </Card>
              <Card title="Estudiantes superficiales">
                <BehaviorList students={dashboard.behavior_insights.superficial_students} valueClassName="text-amber-600" />
              </Card>
              <Card title="Documentos que generan seguimiento">
                <DocumentList documents={dashboard.behavior_insights.followed_up_documents} />
              </Card>
            </div>
          </section>
        </>
      )}

      <div className="border-t border-[#e0e0dc] pt-6 mt-2">
        <CorpusManager />
      </div>

      <p className="mt-6 text-xs text-slate-400">
        <code>EnvironmentDesigner</code> y <code>LearningMonitor</code> (Capa 1, P2_Arquitectura.md)
        se construyen en fases posteriores.
      </p>
    </Layout>
  )
}

function EnvironmentPanel({ user, accessToken, onEnvironmentCreated }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState(null)

  if (user?.environment_id) {
    return (
      <div className="rounded-lg border border-[#e0e0dc] bg-white p-4 mb-6">
        <p className="text-xs text-slate-400 mb-1">Entorno activo</p>
        <p className="text-slate-800 text-sm font-mono break-all">{user.environment_id}</p>
        <p className="text-slate-400 text-xs mt-2">
          Comparte este ID con tus estudiantes para que se registren en el entorno.
        </p>
      </div>
    )
  }

  async function handleCreate(e) {
    e.preventDefault()
    const trimmedName = name.trim()
    if (!trimmedName || creating) return
    setCreating(true)
    setCreateError(null)
    try {
      await environmentsApi.create(accessToken, {
        name: trimmedName,
        description: description.trim() || undefined,
      })
      const updatedUser = await authApi.me(accessToken)
      onEnvironmentCreated(updatedUser)
    } catch (err) {
      setCreateError(err.message)
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="rounded-lg border border-[#e0e0dc] bg-white p-4 mb-6">
      <h3 className="text-sm font-medium text-slate-800 mb-3">Crear entorno académico</h3>
      <form onSubmit={handleCreate} className="space-y-3">
        <div>
          <label className="text-xs text-slate-400 block mb-1">Nombre del entorno</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Ej. Análisis de Datos 2026"
            className="w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:border-emerald-500"
          />
        </div>
        <div>
          <label className="text-xs text-slate-400 block mb-1">Descripción (opcional)</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Breve descripción del entorno..."
            rows={2}
            className="w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:border-emerald-500 resize-none"
          />
        </div>
        {createError && <p className="text-red-600 text-xs">{createError}</p>}
        <button
          type="submit"
          disabled={creating || !name.trim()}
          className="rounded bg-emerald-600 px-4 py-2 text-sm text-white hover:bg-emerald-500 disabled:opacity-50"
        >
          {creating ? 'Creando...' : 'Crear entorno'}
        </button>
      </form>
    </div>
  )
}

function Card({ title, children }) {
  return (
    <div className="rounded-lg border border-[#e0e0dc] bg-white p-4">
      <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wide mb-3">{title}</h3>
      {children}
    </div>
  )
}

function PlainMetric({ label, value }) {
  return (
    <div>
      <p className="text-3xl font-semibold text-slate-800">{value}</p>
      <p className="text-slate-400 text-xs mt-1">{label}</p>
    </div>
  )
}

function EmptyNotice({ text }) {
  return <p className="text-slate-400 text-xs italic">{text}</p>
}

function PlainMetricOrNotice({ label, value }) {
  return (
    <div>
      {value == null ? (
        <EmptyNotice text="Acumulando datos desde el despliegue." />
      ) : (
        <p className="text-3xl font-semibold text-slate-800">{value}</p>
      )}
      <p className="text-slate-400 text-xs mt-1">{label}</p>
    </div>
  )
}

function DocumentList({ documents }) {
  if (documents.length === 0) return <EmptyNotice text="Acumulando datos desde el despliegue." />
  return (
    <ul className="space-y-2">
      {documents.map((doc) => (
        <li key={doc.filename}>
          <div className="flex items-center justify-between gap-2 text-xs">
            <span className="text-slate-600 truncate" title={doc.filename}>
              {doc.display_title}
            </span>
            <span className="text-slate-400 shrink-0">{doc.count}</span>
          </div>
          {doc.top_questions?.length > 0 && (
            <ul className="mt-0.5 space-y-0.5">
              {doc.top_questions.map((question, i) => (
                <li key={i} className="truncate text-[11px] text-slate-400" title={question}>
                  {question}
                </li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ul>
  )
}

function BehaviorList({ students, valueClassName }) {
  if (students.length === 0) return <EmptyNotice text="Acumulando datos desde el despliegue." />
  return (
    <ul className="space-y-1.5">
      {students.map((s) => (
        <li key={s.student_id} className="flex items-center justify-between gap-2 text-xs">
          <span className="text-slate-600 truncate">{s.full_name}</span>
          <span className={`shrink-0 font-medium ${valueClassName}`}>{s.avg_queries_per_session}/sesión</span>
        </li>
      ))}
    </ul>
  )
}

function WeeklyActivityChart({ points }) {
  const maxCount = Math.max(...points.map((p) => p.message_count), 1)
  return (
    <div className="flex h-24 gap-2">
      {points.map((point) => (
        <div key={point.week_start} className="flex flex-1 flex-col items-center justify-end gap-1">
          <div
            className="w-full rounded-t bg-emerald-500"
            style={{ height: `${Math.max((point.message_count / maxCount) * 100, 4)}%` }}
            title={`${point.message_count} mensajes`}
          />
          <span className="shrink-0 text-[10px] text-slate-400">
            {new Date(point.week_start).toLocaleDateString('es-ES', { day: 'numeric', month: 'short' })}
          </span>
        </div>
      ))}
    </div>
  )
}

function WeeklyBelowThresholdChart({ points }) {
  return (
    <div className="flex h-24 gap-2">
      {points.map((point) => (
        <div key={point.week_start} className="flex flex-1 flex-col items-center justify-end gap-1">
          <div
            className="w-full rounded-t bg-amber-500"
            style={{ height: `${Math.max(point.ratio_pct, 4)}%` }}
            title={`${point.ratio_pct}% (${point.below_threshold_queries}/${point.total_queries} consultas)`}
          />
          <span className="shrink-0 text-[10px] text-slate-400">
            {new Date(point.week_start).toLocaleDateString('es-ES', { day: 'numeric', month: 'short' })}
          </span>
        </div>
      ))}
    </div>
  )
}

function StudentRow({ student }) {
  const pct = student.corpus_coverage_pct
  return (
    <div className="flex items-center justify-between gap-3 border-b border-[#e0e0dc] py-2 last:border-b-0">
      <div className="min-w-0 flex-1">
        <p className="text-slate-800 text-sm font-medium truncate">{student.full_name}</p>
        {student.last_topic && (
          <p className="text-slate-400 text-xs truncate">{student.last_topic}</p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <div className="w-16 rounded-full bg-slate-200 h-1">
          <div className="h-1 rounded-full bg-emerald-500" style={{ width: `${pct}%` }} />
        </div>
        <span className="w-9 text-right text-[11px] text-slate-400">{pct}%</span>
      </div>
    </div>
  )
}

function AlertsPanel({ alerts }) {
  const hasAlerts =
    alerts.unsatisfied_queries.length > 0 || alerts.inactive_students.length > 0

  if (!hasAlerts) {
    return <EmptyNotice text="Sin alertas activas." />
  }

  return (
    <div className="max-h-64 space-y-1.5 overflow-y-auto">
      {alerts.unsatisfied_queries.map((q, i) => (
        <div key={`u-${i}`} className="flex items-start gap-2 text-xs">
          <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-red-500" />
          <p className="text-slate-600">
            <span className="font-medium text-red-700">{q.student_name}</span> — sin respuesta satisfactoria:{' '}
            <span className="truncate">{q.message}</span>
          </p>
        </div>
      ))}
      {alerts.inactive_students.map((s, i) => (
        <div key={`i-${i}`} className="flex items-start gap-2 text-xs">
          <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" />
          <p className="text-slate-600">
            <span className="font-medium text-amber-700">{s.full_name}</span> —{' '}
            {s.days_inactive == null
              ? 'sin actividad registrada todavía'
              : `${s.days_inactive} día(s) sin actividad`}
          </p>
        </div>
      ))}
    </div>
  )
}

const CORPUS_STATUS_BADGE = {
  indexado: 'bg-emerald-50 text-emerald-700',
  procesando: 'bg-amber-50 text-amber-700',
  pendiente: 'bg-amber-50 text-amber-700',
  error: 'bg-red-50 text-red-700',
  eliminado: 'bg-slate-100 text-slate-500',
}

function CorpusStatusCard({ corpusStatus }) {
  const documents = corpusStatus?.documents ?? []
  if (documents.length === 0) {
    return <EmptyNotice text="Aún no se han subido documentos a este entorno." />
  }

  return (
    <div className="max-h-64 space-y-1.5 overflow-y-auto">
      {documents.map((doc) => (
        <div key={doc.document_id} className="flex items-center justify-between gap-2 text-xs">
          {/* El corpus se compone de ARCHIVOS. Aqui va el nombre del documento
              cargado, que es la fuente real; el titulo del tema es de las vistas
              que navegan por temas, no del inventario del corpus. */}
          <span className="text-slate-600 truncate" title={doc.visible_title || ''}>
            {doc.filename}
          </span>
          <span
            className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${
              CORPUS_STATUS_BADGE[doc.status] || 'bg-slate-100 text-slate-500'
            }`}
          >
            {doc.status}
          </span>
        </div>
      ))}
    </div>
  )
}

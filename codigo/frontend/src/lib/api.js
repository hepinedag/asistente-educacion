import { useAuthStore } from '../store/authStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

async function rawRequest(path, { method = 'GET', body, token, isMultipart = false } = {}) {
  const headers = {}
  if (token) headers.Authorization = `Bearer ${token}`
  if (!isMultipart) headers['Content-Type'] = 'application/json'

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers,
    body: isMultipart ? body : body ? JSON.stringify(body) : undefined,
  })

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}))
    const message = typeof errorBody.detail === 'string' ? errorBody.detail : `Error ${response.status}`
    const apiError = new Error(message)
    apiError.status = response.status
    throw apiError
  }

  return response.json()
}

async function tryRefreshSession() {
  const { refreshToken, user, setSession } = useAuthStore.getState()
  if (!refreshToken) return null

  try {
    const tokens = await rawRequest('/auth/refresh', {
      method: 'POST',
      body: { refresh_token: refreshToken },
    })
    setSession({ accessToken: tokens.access_token, refreshToken: tokens.refresh_token, user })
    return tokens.access_token
  } catch {
    return null
  }
}

async function request(path, options = {}) {
  try {
    return await rawRequest(path, options)
  } catch (err) {
    if (err.status === 401 && options.token) {
      const refreshedToken = await tryRefreshSession()
      if (refreshedToken) {
        return rawRequest(path, { ...options, token: refreshedToken })
      }
      useAuthStore.getState().logout()
    }
    throw err
  }
}

export const authApi = {
  login: (email, password) => request('/auth/login', { method: 'POST', body: { email, password } }),
  me: (token) => request('/auth/me', { token }),
  // Sin register: el alta de usuarios no ocurre por la API, la hace el modulo
  // de administracion.
}

export const usersApi = {
  list: (token) => request('/auth/users', { token }),
}

export const conversationApi = {
  sendMessage: (token, { message, environmentId }) =>
    request('/conversation/message', {
      method: 'POST',
      token,
      body: { message, environment_id: environmentId },
    }),
  history: (token, environmentId) =>
    request(`/conversation/history?environment_id=${encodeURIComponent(environmentId)}`, { token }),
  welcome: (token, environmentId) =>
    request(`/conversation/welcome?environment_id=${encodeURIComponent(environmentId)}`, { token }),
  progress: (token, environmentId) =>
    request(`/conversation/progress?environment_id=${encodeURIComponent(environmentId)}`, { token }),
}

export const artifactsApi = {
  // artifactType puede omitirse: el backend lo deduce del texto del tema.
  // focus: preguntas que el estudiante hizo sobre el tema, cuando el artefacto
  // nace de una propuesta del sistema.
  create: (token, { environmentId, topic, artifactType, focus = [], anchorFilename = null }) =>
    request('/artifacts', {
      method: 'POST',
      token,
      body: {
        environment_id: environmentId,
        topic,
        artifact_type: artifactType || null,
        focus,
        anchor_filename: anchorFilename,
      },
    }),
  list: (token, environmentId) =>
    request(`/artifacts?environment_id=${encodeURIComponent(environmentId)}`, { token }),
  get: (token, artifactId) => request(`/artifacts/${encodeURIComponent(artifactId)}`, { token }),
  // Propuesta del sistema: si hay un tema suficientemente trabajado en la sesion
  // que todavia no tiene artefacto.
  suggestion: (token, environmentId) =>
    request(`/artifacts/suggestion?environment_id=${encodeURIComponent(environmentId)}`, { token }),
  // Retirar NO es borrar: el artefacto y sus fuentes siguen en la base, fuera de
  // la vista del estudiante y fuera de lo que se considera vigente.
  retire: (token, artifactId) =>
    request(`/artifacts/${encodeURIComponent(artifactId)}`, { method: 'DELETE', token }),
  retireAll: (token, environmentId) =>
    request(`/artifacts?environment_id=${encodeURIComponent(environmentId)}`, { method: 'DELETE', token }),
}

export const environmentsApi = {
  create: (token, { name, description }) =>
    request('/environments', {
      method: 'POST',
      token,
      body: { name, description },
    }),
  get: (token, environmentId) => request(`/environments/${encodeURIComponent(environmentId)}`, { token }),
}

export const teacherApi = {
  dashboard: (token, environmentId) =>
    request(`/teacher/dashboard?environment_id=${encodeURIComponent(environmentId)}`, { token }),
}

export const corpusApi = {
  upload: (token, { environmentId, file }) => {
    const formData = new FormData()
    formData.append('environment_id', environmentId)
    formData.append('file', file)
    return request('/corpus/upload', { method: 'POST', token, body: formData, isMultipart: true })
  },
  status: (token, environmentId) => {
    const query = environmentId ? `?environment_id=${encodeURIComponent(environmentId)}` : ''
    return request(`/corpus/status${query}`, { token })
  },
  // Carga multiple: un resultado por archivo, el fallo de uno no detiene los demas.
  uploadBatch: (token, { environmentId, files }) => {
    const formData = new FormData()
    formData.append('environment_id', environmentId)
    files.forEach((file) => formData.append('files', file))
    return request('/corpus/upload_batch', { method: 'POST', token, body: formData, isMultipart: true })
  },
  // El titulo que el sistema propone al cargar es una sugerencia leida del propio
  // documento; aqui el docente la confirma, la corrige o la borra.
  updateTitle: (token, documentId, visibleTitle) =>
    request(`/corpus/document/${encodeURIComponent(documentId)}`, {
      method: 'PATCH',
      token,
      body: { visible_title: visibleTitle },
    }),
  deleteDocuments: (token, documentIds) =>
    request('/corpus/documents', { method: 'DELETE', token, body: { document_ids: documentIds } }),
  deleteEnvironmentCorpus: (token, environmentId) =>
    request(`/corpus/environment/${encodeURIComponent(environmentId)}`, { method: 'DELETE', token }),
  lastUpdated: (token, environmentId) =>
    request(`/corpus/last_updated?environment_id=${encodeURIComponent(environmentId)}`, { token }),
}

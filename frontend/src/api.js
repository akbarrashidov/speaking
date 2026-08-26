const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')

const TOKEN_KEY = 'speaking.jwt'
const EXPIRY_KEY = 'speaking.jwt_expires_at'

let token = null
let expiresAt = 0

/** Token eskirganda kuzatuvchilarni (AuthContext) xabardor qiladi. */
export const authEvents = new EventTarget()

function readStorage(key) {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function writeStorage(key, value) {
  try {
    if (value === null) localStorage.removeItem(key)
    else localStorage.setItem(key, value)
  } catch {
    // Maxfiylik rejimida localStorage yopiq bo'lishi mumkin — xotirada ishlaymiz.
  }
}

export function setSession({ jwt, expires_in: expiresIn }) {
  token = jwt
  expiresAt = Date.now() + (expiresIn || 0) * 1000
  writeStorage(TOKEN_KEY, jwt)
  writeStorage(EXPIRY_KEY, String(expiresAt))
}

export function clearSession() {
  token = null
  expiresAt = 0
  writeStorage(TOKEN_KEY, null)
  writeStorage(EXPIRY_KEY, null)
}

export function getToken() {
  if (token) return token
  token = readStorage(TOKEN_KEY)
  expiresAt = Number(readStorage(EXPIRY_KEY) || 0)
  return token
}

/** Token bormi va hali amal qiladimi (30 s zaxira bilan). */
export function hasValidToken() {
  return Boolean(getToken()) && expiresAt - 30_000 > Date.now()
}

/** Amal qilish muddatining yarmi o'tganini bildiradi — yangilash vaqti. */
export function shouldRefresh() {
  if (!getToken() || !expiresAt) return false
  return Date.now() > expiresAt - 15 * 60_000
}

export class ApiError extends Error {
  constructor(status, payload) {
    super(payload?.detail || payload?.error || `HTTP ${status}`)
    this.status = status
    this.code = payload?.error || 'http_error'
    this.fields = payload?.fields || null
    this.payload = payload || {}
  }

  /** Maydon xatolarini bitta o'qiladigan satrga yig'adi. */
  get fieldMessage() {
    if (!this.fields) return null
    const first = Object.values(this.fields)[0]
    return Array.isArray(first) ? first[0] : first
  }
}

async function request(path, { method = 'GET', body, auth = true } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  if (auth) {
    const jwt = getToken()
    if (jwt) headers.Authorization = `Bearer ${jwt}`
  }

  let response
  try {
    response = await fetch(`${API_BASE}/api${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError(0, { error: 'network_error', detail: 'Internetga ulanib bo‘lmadi' })
  }

  let payload = null
  const text = await response.text()
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = { detail: text }
    }
  }

  if (response.status === 401 && auth) {
    clearSession()
    authEvents.dispatchEvent(new Event('unauthorized'))
  }

  if (!response.ok) throw new ApiError(response.status, payload)
  return payload
}

export const api = {
  register: (payload) => request('/auth/register', { method: 'POST', body: payload, auth: false }),
  login: (payload) => request('/auth/login', { method: 'POST', body: payload, auth: false }),
  refresh: () => request('/auth/refresh', { method: 'POST' }),
  me: () => request('/me'),
  setLanguage: (language) => request('/me/language', { method: 'POST', body: { language } }),
  // Ro'yxatdan o'tishning 2-qadami: aytilgan daraja + qisqacha izoh.
  onboarding: (payload) => request('/me/onboarding', { method: 'POST', body: payload }),
  // Daraja aniqlash suhbati. Mavzu raqami YUBORILMAYDI — u kontent emas,
  // infratuzilma va klient uni bilmasligi kerak (§placement_start).
  startPlacement: () => request('/placement/start', { method: 'POST' }),
  topics: () => request('/topics'),
  // Yo'nalish ro'yxati: grammatika, iboralar, shadowing, rol suhbat.
  track: (name) => request(`/topics?track=${encodeURIComponent(name || 'grammar')}`),
  material: (topicId) => request(`/topics/${topicId}/material`),
  startSession: (topicId) =>
    request('/sessions/start', { method: 'POST', body: { topic_id: topicId } }),
  endSession: (sessionId) => request(`/sessions/${sessionId}/end`, { method: 'POST' }),
  feedback: (sessionId) => request(`/sessions/${sessionId}/feedback`),
  sessions: () => request('/sessions'),
  progress: () => request('/progress'),
}

export function wsUrl(path) {
  const base = import.meta.env.VITE_WS_BASE
  if (base) return `${base.replace(/\/$/, '')}${path}`
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${path}`
}

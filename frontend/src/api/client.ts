export type ThreadStatus = 'active' | 'pending_user' | 'pending_supervisor' | 'closed'

export interface TokenResponse {
  access_token: string
  token_type: string
  user_id: string
  name: string
  is_admin: boolean
}

export interface ThreadItem {
  thread_id: string
  title: string | null
  status: ThreadStatus
  last_message: string | null
  created_at: string
  updated_at: string
}

export interface MessageItem {
  message_id: string
  role: 'user' | 'assistant'
  content: string
  sources: SourceItem[]
}

export interface SourceItem {
  source?: string | null
  section?: string | null
  topic?: string | null
  content?: string | null
}

export interface ToolEventItem {
  tool: string
  result?: unknown
}

export interface PendingAction {
  kind: 'refund_confirmation' | 'supervisor_approval'
  refund_id?: string
  order_id?: string
  amount?: string
  reason?: string
}

export interface StreamEnvelope {
  schema_version: '1'
  event_id: string
  run_id: string
  thread_id: string
  type: 'run.started' | 'message.delta' | 'message.completed' | 'run.failed' | 'stream.done' | 'run.interrupted'
  data: Record<string, unknown>
}

export interface RefundItem {
  refund_id: string
  thread_id?: string | null
  order_id: string
  amount: string
  reason: string
  status: string
  reviewed_by?: string | null
  reviewed_at?: string | null
}

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')
const TOKEN_KEY = 'orbit_access_token'
const USER_KEY = 'orbit_user'

export const authStore = {
  get token() { return localStorage.getItem(TOKEN_KEY) },
  get user() {
    try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null') as { user_id: string; name: string; is_admin: boolean } | null } catch { return null }
  },
  set(data: TokenResponse) {
    localStorage.setItem(TOKEN_KEY, data.access_token)
    localStorage.setItem(USER_KEY, JSON.stringify({ user_id: data.user_id, name: data.name, is_admin: data.is_admin }))
  },
  clear() { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY) },
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Content-Type', 'application/json')
  if (authStore.token) headers.set('Authorization', `Bearer ${authStore.token}`)
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers })
  if (!response.ok) {
    let message = `请求失败（${response.status}）`
    try {
      const body = await response.json() as { detail?: string; error?: { message?: string } }
      message = body.error?.message || body.detail || message
    } catch { /* keep status message */ }
    if (response.status === 401) authStore.clear()
    throw new Error(message)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export async function login(userId: string) {
  const data = await request<TokenResponse>('/auth/login', { method: 'POST', body: JSON.stringify({ user_id: userId }) })
  authStore.set(data)
  return data
}

export function listThreads(limit = 50) {
  return request<{ items: ThreadItem[]; next_cursor: string | null }>(`/threads?limit=${limit}`)
}

export function createThread() {
  return request<{ thread_id: string; status: ThreadStatus }>('/threads', { method: 'POST' })
}

export function deleteThread(threadId: string) {
  return request<void>(`/threads/${encodeURIComponent(threadId)}`, { method: 'DELETE' })
}

export function getThreadMessages(threadId: string) {
  return request<{ thread_id: string; title: string | null; messages: MessageItem[]; pending_action: PendingAction | null }>(`/threads/${encodeURIComponent(threadId)}/messages`)
}

export async function streamConversation(
  threadId: string,
  payload: { message?: string; resume?: PendingAction & { decision: 'confirm' | 'cancel' } },
  onEvent: (event: StreamEnvelope) => void,
) {
  const headers = new Headers({ 'Content-Type': 'application/json', Accept: 'text/event-stream' })
  if (authStore.token) headers.set('Authorization', `Bearer ${authStore.token}`)
  const response = await fetch(`${API_BASE}/threads/${encodeURIComponent(threadId)}/runs/stream`, { method: 'POST', headers, body: JSON.stringify(payload) })
  if (!response.ok || !response.body) {
    throw new Error(`流式请求失败（${response.status}）`)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    const chunks = buffer.split(/\r?\n\r?\n/)
    buffer = chunks.pop() || ''
    for (const chunk of chunks) {
      const dataLine = chunk.split(/\r?\n/).find((line) => line.startsWith('data:'))
      if (!dataLine) continue
      try { onEvent(JSON.parse(dataLine.slice(5).trim()) as StreamEnvelope) } catch { /* ignore malformed keep-alive chunks */ }
    }
    if (done) break
  }
  // Process a final event even if the server closed without a trailing blank line.
  const dataLine = buffer.split(/\r?\n/).find((line) => line.startsWith('data:'))
  if (dataLine) {
    try { onEvent(JSON.parse(dataLine.slice(5).trim()) as StreamEnvelope) } catch { /* ignore malformed chunks */ }
  }
}

export function listPendingRefunds() {
  return request<{ ok: boolean; data: RefundItem[]; message?: string }>('/admin/refunds/pending')
}

export function decideRefund(refundId: string, decision: 'approve' | 'reject') {
  return request<{ approval: { ok: boolean; data?: RefundItem; message?: string }; resume?: { answer?: string; pending_action?: PendingAction | null } | null }>(`/admin/refunds/${encodeURIComponent(refundId)}/decision`, { method: 'POST', body: JSON.stringify({ decision }) })
}

export function formatDate(value: string | null | undefined) {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date)
}

export { API_BASE }

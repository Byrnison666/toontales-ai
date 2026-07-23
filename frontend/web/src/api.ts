import { clearSession, getToken } from './storage'

const API_BASE = '/api/v1'
export const AUTH_EXPIRED_EVENT = 'toontales:auth-expired'

export type RunStatus = 'pending' | 'running' | 'completed' | 'failed' | 'canceled'
export type Stage =
  | 'storyboard_generation'
  | 'image_generation'
  | 'video_generation'
  | 'audio_generation'
  | 'lipsync'
  | 'composition'

export interface AuthResponse {
  user_id: string
  access_token: string
  token_type: 'bearer'
}

export interface GenerateRequest {
  project_name: string
  script_text: string
  duration_seconds: number
}

export interface GenerateResponse {
  project_id: string
  run_id: string
  status: RunStatus
  duration_seconds: number
  price: number
}

export interface DurationPrice {
  duration_seconds: number
  price: number
}

export interface PricingQuote {
  prices: DurationPrice[]
}

export interface SparkPackage {
  sparks: number
  price_rub: number
}

export interface SparkPackages {
  packages: SparkPackage[]
}

export interface RunScene {
  scene_id: string
  scene_index: number
  script_text: string
}

export interface RunTask {
  task_id: string
  scene_id: string | null
  stage: Stage
  status: string
  progress_hint: number | null
  error: unknown
}

export interface RunAsset {
  asset_id: string
  kind: 'image' | 'video' | 'audio' | 'final_render'
  scene_id: string | null
  presigned_url: string
}

export interface RunSnapshot {
  run_id: string
  project_id: string
  status: RunStatus
  trigger: string
  created_at: string
  duration_seconds: number
  price: number
  scenes: RunScene[]
  tasks: RunTask[]
  assets: RunAsset[]
}

export interface WsTicket {
  ticket: string
  expires_in_seconds: number
}

export interface ProgressEvent {
  event_id: number
  project_id: string
  run_id: string
  task_id: string
  stage: Stage
  stage_index: number
  total_stages: number
  status: string
  progress: number
  message: string
  artifact_ids: string[]
  error: unknown
  timestamp: string
}

export interface BalanceResponse {
  user_id: string
  credit_balance: number
}

export interface BillingTransaction {
  id: string
  type: string
  amount: number
  run_id: string | null
  task_id: string | null
  created_at: string
}

export interface TransactionsResponse {
  transactions: BillingTransaction[]
}

interface ErrorPayload {
  detail?: unknown
  message?: unknown
  code?: unknown
}

export class ApiError extends Error {
  readonly status: number
  readonly payload: ErrorPayload | null

  constructor(status: number, payload: ErrorPayload | null) {
    super(getErrorMessage(payload) ?? `Request failed with status ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.payload = payload
  }
}

function getErrorMessage(payload: ErrorPayload | null): string | null {
  if (!payload) return null
  if (typeof payload.detail === 'string') return payload.detail
  if (typeof payload.message === 'string') return payload.message
  if (typeof payload.detail === 'object' && payload.detail !== null) {
    const detail = payload.detail as Record<string, unknown>
    if (typeof detail.message === 'string') return detail.message
  }
  return null
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  authenticated = true,
): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body) headers.set('Content-Type', 'application/json')

  if (authenticated) {
    const token = getToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers })
  if (!response.ok) {
    let payload: ErrorPayload | null = null
    try {
      payload = (await response.json()) as ErrorPayload
    } catch {
      payload = null
    }

    if (response.status === 401 && authenticated) {
      clearSession()
      window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT))
    }
    throw new ApiError(response.status, payload)
  }

  return (await response.json()) as T
}

export const api = {
  register(email: string, password: string): Promise<AuthResponse> {
    return request<AuthResponse>(
      '/auth/register',
      { method: 'POST', body: JSON.stringify({ email, password }) },
      false,
    )
  },

  login(email: string, password: string): Promise<AuthResponse> {
    return request<AuthResponse>(
      '/auth/login',
      { method: 'POST', body: JSON.stringify({ email, password }) },
      false,
    )
  },

  generateProject(payload: GenerateRequest): Promise<GenerateResponse> {
    return request<GenerateResponse>('/projects/generate', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  getRun(runId: string): Promise<RunSnapshot> {
    return request<RunSnapshot>(`/runs/${encodeURIComponent(runId)}`)
  },

  createWsTicket(runId: string): Promise<WsTicket> {
    return request<WsTicket>(`/runs/${encodeURIComponent(runId)}/ws-ticket`, {
      method: 'POST',
    })
  },

  getPricingQuote(durationSeconds?: number): Promise<PricingQuote> {
    const q = durationSeconds ? `?duration_seconds=${durationSeconds}` : ''
    return request<PricingQuote>(`/pricing/quote${q}`)
  },

  getSparkPackages(): Promise<SparkPackages> {
    return request<SparkPackages>('/pricing/packages')
  },

  getBalance(): Promise<BalanceResponse> {
    return request<BalanceResponse>('/billing/balance')
  },

  getTransactions(): Promise<TransactionsResponse> {
    return request<TransactionsResponse>('/billing/transactions')
  },
}

export function getRunWebSocketUrl(runId: string, ticket: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const safeRunId = encodeURIComponent(runId)
  const safeTicket = encodeURIComponent(ticket)
  return `${protocol}//${window.location.host}/ws/runs/${safeRunId}?ticket=${safeTicket}`
}

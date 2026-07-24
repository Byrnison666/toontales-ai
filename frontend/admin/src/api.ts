export const ADMIN_KEY_STORAGE_KEY = 'toontales_admin_key'
export const ADMIN_AUTH_INVALIDATED_EVENT = 'toontales-admin-auth-invalidated'

export const RUN_STATUSES = ['pending', 'running', 'completed', 'failed', 'canceled'] as const
export const TASK_STATUSES = [
  'pending',
  'submitting',
  'waiting_provider',
  'processing',
  'retry_scheduled',
  'completed',
  'failed',
  'canceled',
] as const
export const PIPELINE_STAGES = [
  'storyboard_generation',
  'image_generation',
  'video_generation',
  'audio_generation',
  'lipsync',
  'composition',
] as const

export type RunStatus = (typeof RUN_STATUSES)[number]
export type TaskStatus = (typeof TASK_STATUSES)[number]
export type PipelineStage = (typeof PIPELINE_STAGES)[number]

export interface AdminStats {
  users_total: number
  runs_total: number
  runs_by_status: Record<string, number>
  completed_runs: number
  total_real_cost_usd: string
  avg_cost_per_completed_run_usd: string | null
  cost_by_stage_usd: Record<string, string>
  total_revenue_usd: string
  total_charged_sparks: number
  actual_markup: string | null
}

export interface AdminUser {
  id: string
  email: string
  credit_balance: number
  created_at: string
}

export interface UsersResponse {
  users: AdminUser[]
  total: number
}

export interface Transaction {
  id: string
  type: string
  amount: number
  note: string | null
  run_id: string | null
  created_at: string
}

export interface AdminRun {
  id: string
  project_id: string
  user_email: string
  status: RunStatus
  trigger: string
  estimated_cost: number
  real_cost_usd: string | null
  charged_sparks: number
  actual_markup: string | null
  created_at: string
  finished_at: string | null
}

export interface RunsResponse {
  runs: AdminRun[]
  total: number
}

export interface RunTask {
  id: string
  scene_id: string | null
  stage: PipelineStage
  status: TaskStatus
  real_cost_usd: string | null
  charged_sparks: number | null
  actual_markup: string | null
  error: Record<string, unknown> | null
}

export interface RunDetails {
  id: string
  user_email: string
  status: RunStatus
  total_real_cost_usd: string | null
  total_charged_sparks: number
  actual_markup: string | null
  tasks: RunTask[]
  final_render_url: string | null
}

export interface HealthResponse {
  checks: Record<string, string>
  tasks_by_status: Record<string, number>
}

export interface BalanceEditRequest {
  // delta — начислить (>0) или списать (<0); set — установить точное значение.
  mode: 'delta' | 'set'
  amount: number
  note: string
  idempotency_key: string
}

export interface BalanceEditResponse {
  user_id: string
  credit_balance: number
}

export interface ProviderBalance {
  provider: string
  label: string
  available: boolean
  balance: number | null
  unit: string | null
  balance_usd: string | null
  note: string | null
  reset_at: string | null
  low: boolean
  error: string | null
  console_url: string
  manual?: boolean
  set_at?: string | null
}

export interface ProviderBalancesResponse {
  providers: ProviderBalance[]
}

export interface ProviderManualBalanceRequest {
  provider: 'anthropic'
  amount_usd: number
  note?: string | null
}

interface ErrorBody {
  detail?: unknown
}

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export function getStoredAdminKey(): string | null {
  return localStorage.getItem(ADMIN_KEY_STORAGE_KEY)
}

export function storeAdminKey(key: string): void {
  localStorage.setItem(ADMIN_KEY_STORAGE_KEY, key)
}

export function clearStoredAdminKey(): void {
  localStorage.removeItem(ADMIN_KEY_STORAGE_KEY)
}

function invalidateAuthentication(): void {
  clearStoredAdminKey()
  window.dispatchEvent(new Event(ADMIN_AUTH_INVALIDATED_EVENT))
}

function errorMessage(body: ErrorBody | null, status: number): string {
  if (typeof body?.detail === 'string') {
    return body.detail
  }

  return `API request failed with status ${status}`
}

async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
  adminKey = getStoredAdminKey(),
): Promise<T> {
  if (!adminKey) {
    throw new ApiError('Admin key is missing', 401)
  }

  const headers = new Headers(options.headers)
  headers.set('X-Admin-Key', adminKey)
  if (options.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(path, { ...options, headers })

  if (response.status === 403) {
    invalidateAuthentication()
  }

  if (!response.ok) {
    let body: ErrorBody | null = null
    try {
      body = (await response.json()) as ErrorBody
    } catch {
      body = null
    }
    throw new ApiError(errorMessage(body, response.status), response.status)
  }

  return (await response.json()) as T
}

function paginationQuery(limit: number, offset: number): string {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  })
  return params.toString()
}

export const adminApi = {
  verifyKey: (adminKey: string, signal?: AbortSignal) =>
    apiRequest<HealthResponse>('/api/v1/admin/health', { signal }, adminKey),
  getStats: (signal?: AbortSignal) =>
    apiRequest<AdminStats>('/api/v1/admin/stats', { signal }),
  getUsers: (limit: number, offset: number, signal?: AbortSignal) =>
    apiRequest<UsersResponse>(`/api/v1/admin/users?${paginationQuery(limit, offset)}`, { signal }),
  getUserTransactions: (userId: string, limit: number, offset: number, signal?: AbortSignal) =>
    apiRequest<Transaction[]>(
      `/api/v1/admin/users/${encodeURIComponent(userId)}/transactions?${paginationQuery(limit, offset)}`,
      { signal },
    ),
  getRuns: (status: RunStatus | null, limit: number, offset: number, signal?: AbortSignal) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (status) {
      params.set('status_filter', status)
    }
    return apiRequest<RunsResponse>(`/api/v1/admin/runs?${params.toString()}`, { signal })
  },
  getRun: (runId: string, signal?: AbortSignal) =>
    apiRequest<RunDetails>(`/api/v1/admin/runs/${encodeURIComponent(runId)}`, { signal }),
  getHealth: (signal?: AbortSignal) =>
    apiRequest<HealthResponse>('/api/v1/admin/health', { signal }),
  getProviderBalances: (refresh = false, signal?: AbortSignal) =>
    apiRequest<ProviderBalancesResponse>(
      `/api/v1/admin/provider-balances${refresh ? '?refresh=1' : ''}`,
      { signal },
    ),
  setProviderManualBalance: (payload: ProviderManualBalanceRequest, signal?: AbortSignal) =>
    apiRequest<ProviderBalancesResponse>('/api/v1/admin/provider-balances/manual', {
      method: 'POST',
      body: JSON.stringify(payload),
      signal,
    }),
  editBalance: (userId: string, payload: BalanceEditRequest, signal?: AbortSignal) =>
    apiRequest<BalanceEditResponse>(`/api/v1/admin/users/${encodeURIComponent(userId)}/balance`, {
      method: 'POST',
      body: JSON.stringify(payload),
      signal,
    }),
}

export function getApiErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message
  }
  if (error instanceof Error) {
    return error.message
  }
  return 'Неизвестная ошибка'
}

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

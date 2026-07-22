export const TOKEN_KEY = 'toontales_token'
export const USER_ID_KEY = 'toontales_user_id'
export const RUNS_KEY = 'toontales_my_runs'

export interface StoredRun {
  run_id: string
  project_name: string
  created_at: string
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setSession(token: string, userId: string): void {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_ID_KEY, userId)
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_ID_KEY)
}

export function getStoredRuns(): StoredRun[] {
  const rawRuns = localStorage.getItem(RUNS_KEY)
  if (!rawRuns) return []

  try {
    const parsed: unknown = JSON.parse(rawRuns)
    if (!Array.isArray(parsed)) return []

    return parsed.filter((run): run is StoredRun => {
      if (typeof run !== 'object' || run === null) return false
      const candidate = run as Record<string, unknown>
      return (
        typeof candidate.run_id === 'string' &&
        typeof candidate.project_name === 'string' &&
        typeof candidate.created_at === 'string'
      )
    })
  } catch {
    return []
  }
}

export function rememberRun(run: StoredRun): void {
  const runs = getStoredRuns().filter((storedRun) => storedRun.run_id !== run.run_id)
  localStorage.setItem(RUNS_KEY, JSON.stringify([run, ...runs]))
}

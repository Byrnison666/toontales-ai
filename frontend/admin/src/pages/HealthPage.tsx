import { useCallback, useEffect, useState } from 'react'
import { TASK_STATUSES, adminApi, getApiErrorMessage, isAbortError, type HealthResponse } from '../api'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { PageHeader } from '../components/PageHeader'
import { taskStatusLabels } from '../format'

export function HealthPage(): JSX.Element {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)

  const refresh = useCallback((signal?: AbortSignal) => {
    setError(null)
    setIsRefreshing(true)
    return adminApi
      .getHealth(signal)
      .then(setHealth)
      .catch((requestError: unknown) => {
        if (!isAbortError(requestError)) {
          setError(getApiErrorMessage(requestError))
        }
      })
      .finally(() => {
        if (!signal?.aborted) {
          setIsRefreshing(false)
        }
      })
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void refresh(controller.signal)
    return () => controller.abort()
  }, [refresh, reloadKey])

  const taskCounts = TASK_STATUSES.map((status) => ({
    status,
    count: health?.tasks_by_status[status] ?? 0,
  }))

  return (
    <div className="space-y-6">
      <PageHeader
        title="Здоровье системы"
        description="Доступность зависимостей и состояние фоновых задач."
        action={
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={isRefreshing}
            className="rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-wait disabled:opacity-60"
          >
            {isRefreshing ? 'Обновляем…' : 'Обновить'}
          </button>
        }
      />

      {error ? <ErrorState message={error} onRetry={() => setReloadKey((value) => value + 1)} /> : null}
      {!error && !health ? <LoadingState label="Проверяем состояние сервисов…" /> : null}
      {!error && health ? (
        <>
          <section className="grid gap-4 sm:grid-cols-2">
            {['database', 'redis'].map((dependency) => {
              const status = health.checks[dependency] ?? 'unavailable'
              const isOk = status.toLowerCase() === 'ok'
              return (
                <article key={dependency} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium capitalize text-slate-500">{dependency}</p>
                      <p className={`mt-2 text-lg font-bold ${isOk ? 'text-emerald-700' : 'text-red-700'}`}>{status}</p>
                    </div>
                    <span className={`h-4 w-4 rounded-full ring-4 ${isOk ? 'bg-emerald-500 ring-emerald-100' : 'bg-red-500 ring-red-100'}`} />
                  </div>
                </article>
              )
            })}
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
            <div className="mb-5">
              <h2 className="text-lg font-bold text-slate-950">Задачи по статусам</h2>
              <p className="mt-1 text-sm text-slate-500">Failed и retry scheduled требуют особого внимания.</p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {taskCounts.map(({ status, count }) => {
                const isFailed = status === 'failed' && count > 0
                const isRetry = status === 'retry_scheduled' && count > 0
                return (
                  <div
                    key={status}
                    className={`rounded-xl border px-4 py-3 ${
                      isFailed ? 'border-red-300 bg-red-50' : isRetry ? 'border-orange-300 bg-orange-50' : 'border-slate-200 bg-slate-50'
                    }`}
                  >
                    <p className={`text-xs font-semibold ${isFailed ? 'text-red-700' : isRetry ? 'text-orange-700' : 'text-slate-500'}`}>
                      {taskStatusLabels[status]}
                    </p>
                    <p className={`mt-2 text-2xl font-bold ${isFailed ? 'text-red-800' : isRetry ? 'text-orange-800' : 'text-slate-950'}`}>{count}</p>
                  </div>
                )
              })}
            </div>
          </section>
        </>
      ) : null}
    </div>
  )
}

import { useEffect, useState, type KeyboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  RUN_STATUSES,
  adminApi,
  getApiErrorMessage,
  isAbortError,
  type RunsResponse,
  type RunStatus,
} from '../api'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { PageHeader } from '../components/PageHeader'
import { Pagination } from '../components/Pagination'
import { StatusBadge } from '../components/StatusBadge'
import { formatCurrency, formatDate, runStatusLabels } from '../format'

const LIMIT = 10

export function RunsPage(): JSX.Element {
  const [data, setData] = useState<RunsResponse | null>(null)
  const [statusFilter, setStatusFilter] = useState<RunStatus | 'all'>('all')
  const [offset, setOffset] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const navigate = useNavigate()

  useEffect(() => {
    const controller = new AbortController()
    setError(null)
    adminApi
      .getRuns(statusFilter === 'all' ? null : statusFilter, LIMIT, offset, controller.signal)
      .then(setData)
      .catch((requestError: unknown) => {
        if (!isAbortError(requestError)) {
          setError(getApiErrorMessage(requestError))
        }
      })

    return () => controller.abort()
  }, [offset, reloadKey, statusFilter])

  const openRun = (runId: string) => navigate(`/runs/${runId}`)
  const handleRowKeyDown = (event: KeyboardEvent<HTMLTableRowElement>, runId: string) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      openRun(runId)
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Генерации"
        description="Мониторинг запусков, статусов и фактической себестоимости."
        action={
          <label className="flex items-center gap-3 text-sm font-medium text-slate-600">
            Статус
            <select
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value as RunStatus | 'all')
                setOffset(0)
              }}
              className="rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 font-medium text-slate-800 shadow-sm focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100"
            >
              <option value="all">Все</option>
              {RUN_STATUSES.map((status) => (
                <option key={status} value={status}>{runStatusLabels[status]}</option>
              ))}
            </select>
          </label>
        }
      />

      {error ? <ErrorState message={error} onRetry={() => setReloadKey((value) => value + 1)} /> : null}
      {!error && !data ? <LoadingState label="Загружаем генерации…" /> : null}
      {!error && data ? (
        <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
              <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-5 py-3.5">Статус</th>
                  <th className="px-5 py-3.5">Пользователь</th>
                  <th className="px-5 py-3.5">Себестоимость</th>
                  <th className="px-5 py-3.5">Триггер</th>
                  <th className="px-5 py-3.5">Создан</th>
                  <th className="px-5 py-3.5">Завершён</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.runs.map((run) => (
                  <tr
                    key={run.id}
                    role="link"
                    tabIndex={0}
                    aria-label={`Открыть генерацию ${run.id}`}
                    onClick={() => openRun(run.id)}
                    onKeyDown={(event) => handleRowKeyDown(event, run.id)}
                    className="cursor-pointer transition hover:bg-indigo-50/50 focus:bg-indigo-50 focus:outline-none"
                  >
                    <td className="px-5 py-4"><StatusBadge status={run.status} /></td>
                    <td className="px-5 py-4 font-medium text-slate-900">{run.user_email}</td>
                    <td className="whitespace-nowrap px-5 py-4 font-mono font-semibold text-slate-800">{formatCurrency(run.real_cost_usd)}</td>
                    <td className="px-5 py-4 text-slate-600">{run.trigger}</td>
                    <td className="whitespace-nowrap px-5 py-4 text-slate-600">{formatDate(run.created_at)}</td>
                    <td className="whitespace-nowrap px-5 py-4 text-slate-600">{formatDate(run.finished_at)}</td>
                  </tr>
                ))}
                {data.runs.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-5 py-14 text-center text-slate-500">Генераций с таким статусом нет</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
          <Pagination limit={LIMIT} offset={offset} total={data.total} onOffsetChange={setOffset} />
        </section>
      ) : null}
    </div>
  )
}

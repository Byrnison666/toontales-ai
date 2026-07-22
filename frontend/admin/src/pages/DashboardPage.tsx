import { useEffect, useState } from 'react'
import {
  PIPELINE_STAGES,
  RUN_STATUSES,
  adminApi,
  getApiErrorMessage,
  isAbortError,
  type AdminStats,
} from '../api'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { formatCurrency, formatInteger, stageLabels } from '../format'

interface MetricCardProps {
  label: string
  value: string
  accent?: boolean
}

function MetricCard({ label, value, accent = false }: MetricCardProps): JSX.Element {
  return (
    <article className={`rounded-2xl border p-5 shadow-sm ${accent ? 'border-indigo-200 bg-indigo-600 text-white' : 'border-slate-200 bg-white'}`}>
      <p className={`text-sm font-medium ${accent ? 'text-indigo-100' : 'text-slate-500'}`}>{label}</p>
      <p className={`mt-3 text-2xl font-bold tracking-tight ${accent ? 'text-white' : 'text-slate-950'}`}>{value}</p>
    </article>
  )
}

export function DashboardPage(): JSX.Element {
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setError(null)

    adminApi
      .getStats(controller.signal)
      .then(setStats)
      .catch((requestError: unknown) => {
        if (!isAbortError(requestError)) {
          setError(getApiErrorMessage(requestError))
        }
      })

    return () => controller.abort()
  }, [reloadKey])

  if (error) {
    return <ErrorState message={error} onRetry={() => setReloadKey((value) => value + 1)} />
  }

  if (!stats) {
    return <LoadingState label="Загружаем статистику…" />
  }

  const stageCosts = PIPELINE_STAGES.map((stage) => ({
    stage,
    value: Number(stats.cost_by_stage_usd[stage] ?? '0'),
    rawValue: stats.cost_by_stage_usd[stage] ?? '0',
  })).sort((left, right) => right.value - left.value)
  const maxStageCost = Math.max(...stageCosts.map(({ value }) => value), 0)

  return (
    <div className="space-y-8">
      <PageHeader title="Дашборд" description="Ключевые показатели и структура расходов сервиса." />

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5" aria-label="Ключевые показатели">
        <MetricCard label="Всего пользователей" value={formatInteger(stats.users_total)} />
        <MetricCard label="Всего роликов" value={formatInteger(stats.runs_total)} />
        <MetricCard label="Завершённых роликов" value={formatInteger(stats.completed_runs)} />
        <MetricCard label="Суммарная себестоимость" value={formatCurrency(stats.total_real_cost_usd)} accent />
        <MetricCard label="Средняя себестоимость" value={formatCurrency(stats.avg_cost_per_completed_run_usd)} />
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.65fr)_minmax(320px,1fr)]">
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <div className="mb-6">
            <h2 className="text-lg font-bold text-slate-950">Себестоимость по стадиям</h2>
            <p className="mt-1 text-sm text-slate-500">Распределение фактических расходов пайплайна.</p>
          </div>
          <div className="space-y-5">
            {stageCosts.map(({ stage, value, rawValue }) => {
              const width = maxStageCost > 0 ? Math.max((value / maxStageCost) * 100, value > 0 ? 2 : 0) : 0
              return (
                <div key={stage}>
                  <div className="mb-2 flex items-center justify-between gap-4 text-sm">
                    <span className="font-medium text-slate-700">{stageLabels[stage]}</span>
                    <span className="font-mono font-semibold text-slate-950">{formatCurrency(rawValue)}</span>
                  </div>
                  <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
                    <div
                      className={`h-full rounded-full ${stage === 'video_generation' ? 'bg-indigo-600' : 'bg-indigo-300'}`}
                      style={{ width: `${width}%` }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <div className="mb-6">
            <h2 className="text-lg font-bold text-slate-950">Ролики по статусам</h2>
            <p className="mt-1 text-sm text-slate-500">Текущее распределение генераций.</p>
          </div>
          <div className="space-y-3">
            {RUN_STATUSES.map((status) => (
              <div key={status} className="flex items-center justify-between rounded-xl border border-slate-100 bg-slate-50 px-4 py-3">
                <StatusBadge status={status} />
                <span className="text-lg font-bold text-slate-950">{formatInteger(stats.runs_by_status[status] ?? 0)}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}

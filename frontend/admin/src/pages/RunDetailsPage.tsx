import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { adminApi, getApiErrorMessage, isAbortError, type RunDetails } from '../api'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { StatusBadge } from '../components/StatusBadge'
import { formatCurrency, formatMarkup, formatSparks, stageLabels } from '../format'

export function RunDetailsPage(): JSX.Element {
  const { id } = useParams<{ id: string }>()
  const [run, setRun] = useState<RunDetails | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    if (!id) {
      setError('Идентификатор генерации не указан')
      return undefined
    }

    const controller = new AbortController()
    setError(null)
    adminApi
      .getRun(id, controller.signal)
      .then(setRun)
      .catch((requestError: unknown) => {
        if (!isAbortError(requestError)) {
          setError(getApiErrorMessage(requestError))
        }
      })

    return () => controller.abort()
  }, [id, reloadKey])

  if (error) {
    return <ErrorState message={error} onRetry={() => setReloadKey((value) => value + 1)} />
  }

  if (!run) {
    return <LoadingState label="Загружаем детали генерации…" />
  }

  return (
    <div className="space-y-6">
      <div>
        <Link to="/runs" className="text-sm font-semibold text-indigo-600 transition hover:text-indigo-800">← Все генерации</Link>
        <div className="mt-4 flex flex-col gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:flex-row sm:items-center sm:justify-between sm:p-6">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="truncate text-2xl font-bold tracking-tight text-slate-950">{run.user_email}</h1>
              <StatusBadge status={run.status} />
            </div>
            <p className="mt-2 truncate font-mono text-xs text-slate-400" title={run.id}>{run.id}</p>
          </div>
          <div className="flex shrink-0 gap-8 sm:text-right">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Себестоимость</p>
              <p className="mt-1 font-mono text-2xl font-bold text-slate-950">{formatCurrency(run.total_real_cost_usd)}</p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Списано</p>
              <p className="mt-1 font-mono text-2xl font-bold text-slate-950">{formatSparks(run.total_charged_sparks)}</p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Наценка</p>
              <p className="mt-1 font-mono text-2xl font-bold text-indigo-600">{formatMarkup(run.actual_markup)}</p>
            </div>
          </div>
        </div>
      </div>

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 px-5 py-4">
          <h2 className="text-lg font-bold text-slate-950">Стадии пайплайна</h2>
        </div>
        <div className="divide-y divide-slate-100">
          {run.tasks.map((task) => (
            <article key={task.id} className="p-5 transition hover:bg-slate-50">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="font-semibold text-slate-900">{stageLabels[task.stage]}</p>
                  <p className="mt-1 font-mono text-xs text-slate-400">
                    {task.scene_id ? `Scene: ${task.scene_id}` : task.id}
                  </p>
                </div>
                <div className="flex items-center gap-4">
                  <StatusBadge status={task.status} kind="task" />
                  <span className="min-w-24 text-right font-mono font-semibold text-slate-800">{formatCurrency(task.real_cost_usd)}</span>
                  <span className="min-w-20 text-right font-mono font-semibold text-slate-800">{formatSparks(task.charged_sparks)}</span>
                  <span className="min-w-16 text-right font-mono font-semibold text-indigo-600">{formatMarkup(task.actual_markup)}</span>
                </div>
              </div>
              {task.error ? (
                <details className="mt-4 rounded-xl border border-red-200 bg-red-50">
                  <summary className="px-4 py-3 text-sm font-semibold text-red-700">Детали ошибки</summary>
                  <pre className="overflow-x-auto border-t border-red-200 px-4 py-3 text-xs leading-5 text-red-900">{JSON.stringify(task.error, null, 2)}</pre>
                </details>
              ) : null}
            </article>
          ))}
          {run.tasks.length === 0 ? <p className="p-10 text-center text-slate-500">Задач пайплайна нет</p> : null}
        </div>
      </section>

      {run.final_render_url ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <div className="mb-4 flex items-center justify-between gap-4">
            <h2 className="text-lg font-bold text-slate-950">Готовый ролик</h2>
            <a
              href={run.final_render_url}
              download
              target="_blank"
              rel="noreferrer"
              className="rounded-lg bg-indigo-600 px-3.5 py-2 text-sm font-semibold text-white transition hover:bg-indigo-700"
            >
              Скачать
            </a>
          </div>
          <video controls preload="metadata" className="aspect-video w-full rounded-xl bg-slate-950" src={run.final_render_url}>
            Ваш браузер не поддерживает воспроизведение видео.
          </video>
        </section>
      ) : null}
    </div>
  )
}

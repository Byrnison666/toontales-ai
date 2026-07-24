import { useCallback, useEffect, useState } from 'react'
import {
  adminApi,
  getApiErrorMessage,
  isAbortError,
  type ProviderBalance,
  type ProviderBalancesResponse,
} from '../api'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { PageHeader } from '../components/PageHeader'

function formatNumber(value: number): string {
  return value.toLocaleString('ru-RU')
}

function formatReset(iso: string): string {
  return new Date(iso).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })
}

function ProviderCard({ item }: { item: ProviderBalance }): JSX.Element {
  // Три состояния: ошибка/недоступно (жёлтый), низкий остаток (красный), ок (зелёный).
  const isError = item.error !== null || !item.available
  const isLow = item.available && item.low
  const accent = isError
    ? 'border-amber-300 bg-amber-50'
    : isLow
      ? 'border-red-300 bg-red-50'
      : 'border-emerald-200 bg-white'
  const dot = isError ? 'bg-amber-500 ring-amber-100' : isLow ? 'bg-red-500 ring-red-100' : 'bg-emerald-500 ring-emerald-100'

  return (
    <article className={`rounded-2xl border p-5 shadow-sm ${accent}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-950">{item.label}</p>
          {item.available ? (
            <>
              <p className="mt-2 text-2xl font-bold text-slate-950">
                {formatNumber(item.balance ?? 0)}{' '}
                <span className="text-base font-medium text-slate-500">
                  {item.unit === 'credits' ? 'кредитов' : item.unit === 'characters' ? 'символов' : ''}
                </span>
              </p>
              <p className="mt-1 text-sm text-slate-500">
                {item.balance_usd ? `≈ $${item.balance_usd}` : null}
                {item.note ? ` · ${item.note}` : null}
              </p>
              {item.reset_at ? (
                <p className="mt-1 text-xs text-slate-400">Сброс квоты: {formatReset(item.reset_at)}</p>
              ) : null}
              {isLow ? <p className="mt-2 text-sm font-semibold text-red-700">Пора пополнять</p> : null}
            </>
          ) : (
            <p className="mt-2 text-sm text-amber-800">{item.error ?? item.note ?? 'Остаток недоступен'}</p>
          )}
        </div>
        <span className={`mt-1 h-4 w-4 shrink-0 rounded-full ring-4 ${dot}`} />
      </div>
      <a
        href={item.console_url}
        target="_blank"
        rel="noreferrer"
        className="mt-4 inline-flex text-sm font-semibold text-indigo-600 hover:text-indigo-700"
      >
        Открыть счёт →
      </a>
    </article>
  )
}

export function ProvidersPage(): JSX.Element {
  const [data, setData] = useState<ProviderBalancesResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)

  const refresh = useCallback((forceRefresh: boolean, signal?: AbortSignal) => {
    setError(null)
    setIsRefreshing(true)
    return adminApi
      .getProviderBalances(forceRefresh, signal)
      .then(setData)
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
    void refresh(false, controller.signal)
    return () => controller.abort()
  }, [refresh, reloadKey])

  return (
    <div className="space-y-6">
      <PageHeader
        title="Остатки провайдеров"
        description="Реальные балансы на счетах — чтобы знать, когда и какой пополнять. Данные кешируются на 5 минут."
        action={
          <button
            type="button"
            onClick={() => void refresh(true)}
            disabled={isRefreshing}
            className="rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-wait disabled:opacity-60"
          >
            {isRefreshing ? 'Обновляем…' : 'Обновить'}
          </button>
        }
      />

      {error ? <ErrorState message={error} onRetry={() => setReloadKey((value) => value + 1)} /> : null}
      {!error && !data ? <LoadingState label="Запрашиваем остатки у провайдеров…" /> : null}
      {!error && data ? (
        <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {data.providers.map((item) => (
            <ProviderCard key={item.provider} item={item} />
          ))}
        </section>
      ) : null}
    </div>
  )
}

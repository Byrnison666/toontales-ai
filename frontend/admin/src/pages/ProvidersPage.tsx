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

function unitLabel(unit: string | null): string {
  if (unit === 'credits') return 'кредитов'
  if (unit === 'characters') return 'символов'
  return ''
}

function ProviderCard({
  item,
  onSaved,
}: {
  item: ProviderBalance
  onSaved: (data: ProviderBalancesResponse) => void
}): JSX.Element {
  const [editing, setEditing] = useState(false)
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  // Три состояния: ошибка/недоступно (жёлтый), низкий остаток (красный), ок (зелёный).
  const isError = item.error !== null || (!item.available && !item.manual)
  const isLow = item.available && item.low
  const accent = isError
    ? 'border-amber-300 bg-amber-50'
    : isLow
      ? 'border-red-300 bg-red-50'
      : 'border-emerald-200 bg-white'
  const dot = isError ? 'bg-amber-500 ring-amber-100' : isLow ? 'bg-red-500 ring-red-100' : 'bg-emerald-500 ring-emerald-100'

  const save = () => {
    const value = Number(amount)
    if (!Number.isFinite(value) || value < 0) {
      setSaveError('Введите сумму в долларах (например 20)')
      return
    }
    setSaving(true)
    setSaveError(null)
    adminApi
      .setProviderManualBalance({ provider: 'anthropic', amount_usd: value, note: note || null })
      .then((data) => {
        onSaved(data)
        setEditing(false)
        setAmount('')
        setNote('')
      })
      .catch((e: unknown) => setSaveError(getApiErrorMessage(e)))
      .finally(() => setSaving(false))
  }

  return (
    <article className={`rounded-2xl border p-5 shadow-sm ${accent}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-950">{item.label}</p>
          {item.available ? (
            <>
              <p className="mt-2 text-2xl font-bold text-slate-950">
                {item.unit === 'usd' ? (
                  `$${item.balance_usd ?? '0'}`
                ) : (
                  <>
                    {formatNumber(item.balance ?? 0)}{' '}
                    <span className="text-base font-medium text-slate-500">{unitLabel(item.unit)}</span>
                  </>
                )}
              </p>
              <p className="mt-1 text-sm text-slate-500">
                {item.unit !== 'usd' && item.balance_usd ? `≈ $${item.balance_usd}` : null}
                {item.note ? (item.unit !== 'usd' && item.balance_usd ? ` · ${item.note}` : item.note) : null}
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

      {editing ? (
        <div className="mt-4 space-y-2">
          <label className="block text-xs font-medium text-slate-500">Остаток на счёте, $</label>
          <input
            type="number"
            min={0}
            step="0.01"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="например 20"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
          <input
            type="text"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="примечание (необязательно)"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
          {saveError ? <p className="text-xs text-red-600">{saveError}</p> : null}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={save}
              disabled={saving}
              className="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-60"
            >
              {saving ? 'Сохраняем…' : 'Сохранить'}
            </button>
            <button
              type="button"
              onClick={() => {
                setEditing(false)
                setSaveError(null)
              }}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-600"
            >
              Отмена
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-4 flex items-center gap-4">
          <a
            href={item.console_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex text-sm font-semibold text-indigo-600 hover:text-indigo-700"
          >
            Открыть счёт →
          </a>
          {item.manual ? (
            <button
              type="button"
              onClick={() => setEditing(true)}
              className="text-sm font-semibold text-slate-600 hover:text-slate-900"
            >
              {item.available ? 'Изменить остаток' : 'Задать остаток'}
            </button>
          ) : null}
        </div>
      )}
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
        description="Реальные балансы на счетах — чтобы знать, когда и какой пополнять. Данные кешируются на 5 минут. У Anthropic нет API остатка — задаётся вручную и уменьшается на наш расход."
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
            <ProviderCard key={item.provider} item={item} onSaved={setData} />
          ))}
        </section>
      ) : null}
    </div>
  )
}

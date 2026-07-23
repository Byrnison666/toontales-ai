import { useEffect, useState } from 'react'
import { adminApi, getApiErrorMessage, isAbortError, type AdminUser, type Transaction } from '../api'
import { formatDate } from '../format'
import { ErrorState } from './ErrorState'
import { LoadingState } from './LoadingState'
import { Modal } from './Modal'

interface TransactionsModalProps {
  user: AdminUser
  onClose: () => void
}

const LIMIT = 10

const transactionTypeStyles: Record<string, string> = {
  topup: 'bg-emerald-50 text-emerald-700',
  hold: 'bg-amber-50 text-amber-700',
  charge: 'bg-red-50 text-red-700',
  release: 'bg-blue-50 text-blue-700',
}

export function TransactionsModal({ user, onClose }: TransactionsModalProps): JSX.Element {
  const [transactions, setTransactions] = useState<Transaction[] | null>(null)
  const [offset, setOffset] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setTransactions(null)
    setError(null)
    adminApi
      .getUserTransactions(user.id, LIMIT, offset, controller.signal)
      .then(setTransactions)
      .catch((requestError: unknown) => {
        if (!isAbortError(requestError)) {
          setError(getApiErrorMessage(requestError))
        }
      })

    return () => controller.abort()
  }, [offset, reloadKey, user.id])

  return (
    <Modal title="История транзакций" description={user.email} onClose={onClose} size="lg">
      <div className="p-6">
        {error ? <ErrorState message={error} onRetry={() => setReloadKey((value) => value + 1)} /> : null}
        {!error && !transactions ? <LoadingState label="Загружаем транзакции…" /> : null}
        {!error && transactions ? (
          <>
            <div className="overflow-x-auto rounded-xl border border-slate-200">
              <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
                <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-4 py-3">Тип</th>
                    <th className="px-4 py-3">Сумма</th>
                    <th className="px-4 py-3">Причина</th>
                    <th className="px-4 py-3">Run ID</th>
                    <th className="px-4 py-3">Дата</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {transactions.map((transaction) => (
                    <tr key={transaction.id}>
                      <td className="px-4 py-3">
                        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${transactionTypeStyles[transaction.type] ?? 'bg-slate-100 text-slate-700'}`}>
                          {transaction.type}
                        </span>
                      </td>
                      <td className={`px-4 py-3 font-mono font-semibold ${transaction.amount >= 0 ? 'text-emerald-700' : 'text-red-700'}`}>
                        {transaction.amount > 0 ? '+' : ''}{transaction.amount}
                      </td>
                      <td className="max-w-56 truncate px-4 py-3 text-slate-700" title={transaction.note ?? undefined}>
                        {transaction.note ?? '—'}
                      </td>
                      <td className="max-w-48 truncate px-4 py-3 font-mono text-xs text-slate-500" title={transaction.run_id ?? undefined}>
                        {transaction.run_id ?? '—'}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-slate-600">{formatDate(transaction.created_at)}</td>
                    </tr>
                  ))}
                  {transactions.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-4 py-10 text-center text-slate-500">Транзакций нет</td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
            <div className="mt-4 flex items-center justify-between text-sm text-slate-500">
              <span>Записи {transactions.length === 0 ? 0 : offset + 1}–{offset + transactions.length}</span>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={offset === 0}
                  onClick={() => setOffset((value) => Math.max(0, value - LIMIT))}
                  className="rounded-lg border border-slate-200 px-3 py-2 font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Назад
                </button>
                <button
                  type="button"
                  disabled={transactions.length < LIMIT}
                  onClick={() => setOffset((value) => value + LIMIT)}
                  className="rounded-lg border border-slate-200 px-3 py-2 font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Далее
                </button>
              </div>
            </div>
          </>
        ) : null}
      </div>
    </Modal>
  )
}

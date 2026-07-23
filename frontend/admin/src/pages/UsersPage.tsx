import { useEffect, useState } from 'react'
import { adminApi, getApiErrorMessage, isAbortError, type AdminUser, type UsersResponse } from '../api'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { PageHeader } from '../components/PageHeader'
import { Pagination } from '../components/Pagination'
import { BalanceModal } from '../components/BalanceModal'
import { TransactionsModal } from '../components/TransactionsModal'
import { formatDate, formatInteger } from '../format'

const LIMIT = 10

export function UsersPage(): JSX.Element {
  const [data, setData] = useState<UsersResponse | null>(null)
  const [offset, setOffset] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [balanceUser, setBalanceUser] = useState<AdminUser | null>(null)
  const [transactionsUser, setTransactionsUser] = useState<AdminUser | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setError(null)
    adminApi
      .getUsers(LIMIT, offset, controller.signal)
      .then(setData)
      .catch((requestError: unknown) => {
        if (!isAbortError(requestError)) {
          setError(getApiErrorMessage(requestError))
        }
      })

    return () => controller.abort()
  }, [offset, reloadKey])

  useEffect(() => {
    if (!toast) {
      return undefined
    }
    const timeoutId = window.setTimeout(() => setToast(null), 3500)
    return () => window.clearTimeout(timeoutId)
  }, [toast])

  const handleBalanceSuccess = (creditBalance: number) => {
    if (!balanceUser) {
      return
    }
    const userId = balanceUser.id
    setData((current) => current ? {
      ...current,
      users: current.users.map((user) => user.id === userId ? { ...user, credit_balance: creditBalance } : user),
    } : current)
    setBalanceUser(null)
    setToast(`Баланс ${balanceUser.email} обновлён`)
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Пользователи" description="Баланс кредитов и история операций пользователей." />

      {error ? <ErrorState message={error} onRetry={() => setReloadKey((value) => value + 1)} /> : null}
      {!error && !data ? <LoadingState label="Загружаем пользователей…" /> : null}
      {!error && data ? (
        <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
              <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-5 py-3.5">Email</th>
                  <th className="px-5 py-3.5">Баланс</th>
                  <th className="px-5 py-3.5">Создан</th>
                  <th className="px-5 py-3.5 text-right">Действия</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.users.map((user) => (
                  <tr key={user.id} className="transition hover:bg-slate-50">
                    <td className="px-5 py-4 font-medium text-slate-900">{user.email}</td>
                    <td className="px-5 py-4">
                      <span className="rounded-lg bg-indigo-50 px-2.5 py-1.5 font-mono font-semibold text-indigo-700">
                        {formatInteger(user.credit_balance)}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-5 py-4 text-slate-600">{formatDate(user.created_at)}</td>
                    <td className="whitespace-nowrap px-5 py-4 text-right">
                      <div className="flex justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => setTransactionsUser(user)}
                          className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-100"
                        >
                          Транзакции
                        </button>
                        <button
                          type="button"
                          onClick={() => setBalanceUser(user)}
                          className="rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-indigo-700"
                        >
                          Изменить баланс
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {data.users.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-5 py-14 text-center text-slate-500">Пользователей нет</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
          <Pagination limit={LIMIT} offset={offset} total={data.total} onOffsetChange={setOffset} />
        </section>
      ) : null}

      {balanceUser ? (
        <BalanceModal user={balanceUser} onClose={() => setBalanceUser(null)} onSuccess={handleBalanceSuccess} />
      ) : null}
      {transactionsUser ? (
        <TransactionsModal user={transactionsUser} onClose={() => setTransactionsUser(null)} />
      ) : null}
      {toast ? (
        <div className="fixed bottom-5 right-5 z-[60] max-w-sm rounded-xl bg-emerald-600 px-4 py-3 text-sm font-semibold text-white shadow-xl" role="status">
          {toast}
        </div>
      ) : null}
    </div>
  )
}

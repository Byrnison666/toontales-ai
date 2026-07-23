import { useState, type FormEvent } from 'react'
import { adminApi, getApiErrorMessage, type AdminUser } from '../api'
import { formatInteger } from '../format'
import { Modal } from './Modal'

interface BalanceModalProps {
  user: AdminUser
  onClose: () => void
  onSuccess: (creditBalance: number) => void
}

type Mode = 'delta' | 'set'

export function BalanceModal({ user, onClose, onSuccess }: BalanceModalProps): JSX.Element {
  const [mode, setMode] = useState<Mode>('delta')
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')
  // Ключ живёт весь диалог: ретрай после сетевой ошибки не должен применить
  // правку дважды. Меняется только при переоткрытии модалки.
  const [idempotencyKey] = useState(() => crypto.randomUUID())
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const numericAmount = Number(amount)
  const amountIsValid = amount.trim() !== '' && Number.isInteger(numericAmount)
  const nextBalance = !amountIsValid
    ? null
    : mode === 'set'
      ? numericAmount
      : user.credit_balance + numericAmount

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!amountIsValid) {
      setError('Количество искр должно быть целым числом')
      return
    }
    if (nextBalance !== null && nextBalance < 0) {
      setError('Баланс не может стать отрицательным')
      return
    }
    if (note.trim().length === 0) {
      setError('Укажите причину — она попадёт в историю операций')
      return
    }

    setIsSubmitting(true)
    setError(null)
    try {
      const result = await adminApi.editBalance(user.id, {
        mode,
        amount: numericAmount,
        note: note.trim(),
        idempotency_key: idempotencyKey,
      })
      onSuccess(result.credit_balance)
    } catch (requestError) {
      setError(getApiErrorMessage(requestError))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Modal title="Изменить баланс" description={user.email} onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-5 p-6">
        <p className="text-sm text-slate-600">
          Сейчас на балансе{' '}
          <span className="font-mono font-semibold text-slate-900">{formatInteger(user.credit_balance)} ✦</span>
        </p>

        <div className="flex gap-2" role="group" aria-label="Режим правки">
          {(['delta', 'set'] as const).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setMode(value)}
              disabled={isSubmitting}
              className={`flex-1 rounded-xl border px-3 py-2 text-sm font-semibold transition ${
                mode === value
                  ? 'border-indigo-600 bg-indigo-600 text-white'
                  : 'border-slate-300 text-slate-700 hover:bg-slate-50'
              }`}
            >
              {value === 'delta' ? 'Начислить / списать' : 'Установить точно'}
            </button>
          ))}
        </div>

        <div>
          <label htmlFor="balance-amount" className="mb-2 block text-sm font-semibold text-slate-700">
            {mode === 'delta' ? 'На сколько изменить (минус — списать)' : 'Новое значение баланса'}
          </label>
          <input
            id="balance-amount"
            type="number"
            step="1"
            min={mode === 'set' ? 0 : undefined}
            required
            autoFocus
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            disabled={isSubmitting}
            className="w-full rounded-xl border border-slate-300 px-4 py-3 shadow-sm focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100 disabled:opacity-60"
            placeholder={mode === 'delta' ? '-500' : '3500'}
          />
          {nextBalance !== null ? (
            <p className={`mt-2 text-sm ${nextBalance < 0 ? 'text-red-600' : 'text-slate-600'}`}>
              Станет: <span className="font-mono font-semibold">{formatInteger(nextBalance)} ✦</span>
            </p>
          ) : null}
        </div>

        <div>
          <label htmlFor="balance-note" className="mb-2 block text-sm font-semibold text-slate-700">
            Причина
          </label>
          <input
            id="balance-note"
            type="text"
            required
            maxLength={500}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            disabled={isSubmitting}
            className="w-full rounded-xl border border-slate-300 px-4 py-3 shadow-sm focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100 disabled:opacity-60"
            placeholder="Компенсация за неудачную генерацию"
          />
          <p className="mt-2 text-xs text-slate-500">Попадёт в историю операций — по ней потом разбирают спорные случаи.</p>
        </div>

        {error ? <p className="rounded-xl bg-red-50 px-4 py-3 text-sm font-medium text-red-700">{error}</p> : null}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
            className="rounded-xl border border-slate-300 px-4 py-2.5 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-60"
          >
            Отмена
          </button>
          <button
            type="submit"
            disabled={isSubmitting}
            className="rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:opacity-60"
          >
            {isSubmitting ? 'Сохраняем…' : 'Применить'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

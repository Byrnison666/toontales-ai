import { useState, type FormEvent } from 'react'
import { adminApi, getApiErrorMessage, type AdminUser } from '../api'
import { Modal } from './Modal'

interface TopupModalProps {
  user: AdminUser
  onClose: () => void
  onSuccess: (creditBalance: number) => void
}

export function TopupModal({ user, onClose, onSuccess }: TopupModalProps): JSX.Element {
  const [amount, setAmount] = useState('')
  const [idempotencyKey] = useState(() => crypto.randomUUID())
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const numericAmount = Number(amount)
    if (!Number.isInteger(numericAmount) || numericAmount <= 0) {
      setError('Количество кредитов должно быть целым числом больше нуля')
      return
    }

    setIsSubmitting(true)
    setError(null)
    try {
      const result = await adminApi.topup({
        user_id: user.id,
        amount: numericAmount,
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
    <Modal title="Пополнить баланс" description={user.email} onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-5 p-6">
        <div>
          <label htmlFor="topup-amount" className="mb-2 block text-sm font-semibold text-slate-700">
            Количество кредитов
          </label>
          <input
            id="topup-amount"
            type="number"
            min="1"
            step="1"
            required
            autoFocus
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            disabled={isSubmitting}
            className="w-full rounded-xl border border-slate-300 px-4 py-3 shadow-sm focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100 disabled:opacity-60"
            placeholder="100"
          />
        </div>

        <div>
          <p className="mb-2 text-sm font-semibold text-slate-700">Idempotency key</p>
          <code className="block overflow-x-auto rounded-xl bg-slate-100 px-3 py-2.5 text-xs text-slate-600">{idempotencyKey}</code>
        </div>

        {error ? (
          <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
            {error}
          </p>
        ) : null}

        <div className="flex justify-end gap-3 pt-1">
          <button
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
            className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-50"
          >
            Отмена
          </button>
          <button
            type="submit"
            disabled={isSubmitting}
            className="rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-wait disabled:opacity-60"
          >
            {isSubmitting ? 'Пополняем…' : 'Подтвердить'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

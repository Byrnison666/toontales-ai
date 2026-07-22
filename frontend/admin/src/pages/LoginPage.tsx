import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { adminApi, getApiErrorMessage } from '../api'
import { useAuth } from '../auth'

export function LoginPage(): JSX.Element {
  const [adminKey, setAdminKey] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const { login } = useAuth()
  const navigate = useNavigate()

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const key = adminKey.trim()
    if (!key) {
      setError('Введите admin-ключ')
      return
    }

    setIsSubmitting(true)
    setError(null)
    try {
      await adminApi.verifyKey(key)
      login(key)
      navigate('/', { replace: true })
    } catch (requestError) {
      setError(getApiErrorMessage(requestError))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-950 px-4 py-12">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,_rgba(99,102,241,0.28),_transparent_38%),radial-gradient(circle_at_bottom_right,_rgba(14,165,233,0.18),_transparent_35%)]" />
      <section className="relative w-full max-w-md rounded-3xl border border-white/10 bg-white p-8 shadow-2xl shadow-indigo-950/30 sm:p-10">
        <div className="mb-8">
          <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-2xl bg-indigo-600 text-lg font-black text-white shadow-lg shadow-indigo-200">
            TT
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-950">ToonTales Admin</h1>
          <p className="mt-2 text-sm leading-6 text-slate-500">Введите ключ администратора для доступа к панели управления.</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label htmlFor="admin-key" className="mb-2 block text-sm font-semibold text-slate-700">
              Admin-ключ
            </label>
            <input
              id="admin-key"
              type="password"
              value={adminKey}
              onChange={(event) => setAdminKey(event.target.value)}
              autoComplete="current-password"
              autoFocus
              disabled={isSubmitting}
              className="w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-slate-950 shadow-sm transition placeholder:text-slate-400 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100 disabled:opacity-60"
              placeholder="Введите X-Admin-Key"
            />
          </div>

          {error ? (
            <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
              {error}
            </p>
          ) : null}

          <button
            type="submit"
            disabled={isSubmitting}
            className="flex w-full items-center justify-center rounded-xl bg-indigo-600 px-4 py-3 font-semibold text-white shadow-lg shadow-indigo-200 transition hover:bg-indigo-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 disabled:cursor-wait disabled:opacity-60"
          >
            {isSubmitting ? 'Проверяем ключ…' : 'Войти'}
          </button>
        </form>
      </section>
    </main>
  )
}

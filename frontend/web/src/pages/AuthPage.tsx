import { motion } from 'framer-motion'
import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api'
import { useAuth } from '../auth'
import { MagicButton } from '../components/MagicButton'
import { PageTransition } from '../components/PageTransition'
import { Toast } from '../components/Toast'

interface AuthPageProps {
  mode: 'login' | 'register'
}

function getFriendlyError(error: unknown, mode: AuthPageProps['mode']): string {
  if (error instanceof ApiError) {
    if (error.status === 409) return 'Этот email уже живёт в ToonTales. Попробуй войти.'
    if (error.status === 401) return 'Email или пароль не подошли. Проверь данные и попробуй ещё раз.'
    if (error.status === 422) {
      return mode === 'register'
        ? 'Пароль должен быть не короче 8 символов, а email — настоящим.'
        : 'Проверь формат email и заполнение полей.'
    }
    if (error.status >= 500) return 'Наша мастерская ненадолго закрылась. Попробуй чуть позже.'
  }
  return 'Не удалось связаться с волшебной мастерской. Проверь соединение и попробуй снова.'
}

export function AuthPage({ mode }: AuthPageProps): JSX.Element {
  const isRegister = mode === 'register'
  const { isAuthenticated, saveAuth } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (isAuthenticated) return <Navigate to="/create" replace />

  const handleSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const response = isRegister ? await api.register(email, password) : await api.login(email, password)
      saveAuth(response)
      navigate('/create', { replace: true })
    } catch (requestError) {
      setError(getFriendlyError(requestError, mode))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <PageTransition className="mx-auto grid min-h-[calc(100vh-4.5rem)] max-w-7xl place-items-center px-4 py-14 sm:px-6 lg:px-8">
      <motion.section
        initial={{ opacity: 0, y: 30, scale: 0.94 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ type: 'spring', stiffness: 120, damping: 18, delay: 0.12 }}
        className="glass-card relative w-full max-w-md overflow-hidden px-6 py-8 sm:px-9 sm:py-10"
      >
        <motion.div
          className="absolute -right-10 -top-12 h-36 w-36 rounded-full bg-amber-300/15 blur-3xl"
          animate={{ scale: [0.8, 1.2, 0.8] }}
          transition={{ duration: 4.5, repeat: Infinity }}
          aria-hidden="true"
        />
        <div className="relative text-center">
          <motion.div
            animate={{ y: [0, -8, 0], rotate: [-4, 4, -4] }}
            transition={{ duration: 3.2, repeat: Infinity, ease: 'easeInOut' }}
            className="mx-auto grid h-16 w-16 place-items-center rounded-2xl border border-amber-200/25 bg-gradient-to-br from-amber-200/20 to-rose-300/15 text-3xl shadow-[0_0_28px_rgba(251,191,36,0.14)]"
            aria-hidden="true"
          >
            {isRegister ? '🪄' : '✦'}
          </motion.div>
          <h1 className="font-display mt-5 text-3xl font-bold text-white sm:text-4xl">
            {isRegister ? 'Начнём сказку?' : 'С возвращением'}
          </h1>
          <p className="mt-2 text-sm text-violet-200">
            {isRegister ? 'Создай аккаунт и получи стартовые кредиты на первый ролик.' : 'Твои истории уже ждут продолжения.'}
          </p>
        </div>

        <form className="relative mt-8 space-y-5" onSubmit={handleSubmit}>
          <label className="block">
            <span className="mb-2 block text-sm font-extrabold text-violet-100">Email</span>
            <motion.input
              whileFocus={{ scale: 1.01 }}
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="magic-input"
              placeholder="hero@example.com"
            />
          </label>
          <label className="block">
            <span className="mb-2 block text-sm font-extrabold text-violet-100">Пароль</span>
            <motion.input
              whileFocus={{ scale: 1.01 }}
              type="password"
              autoComplete={isRegister ? 'new-password' : 'current-password'}
              required
              minLength={isRegister ? 8 : undefined}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="magic-input"
              placeholder={isRegister ? 'Не меньше 8 символов' : 'Твой секретный пароль'}
            />
          </label>
          <MagicButton type="submit" fullWidth className="group mt-2" disabled={submitting}>
            {submitting ? (
              <>
                <motion.span animate={{ rotate: 360 }} transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}>
                  ✦
                </motion.span>
                Открываем портал…
              </>
            ) : isRegister ? (
              'Создать аккаунт ✨'
            ) : (
              'Войти в ToonTales ✦'
            )}
          </MagicButton>
        </form>

        <p className="relative mt-7 text-center text-sm text-violet-300">
          {isRegister ? 'Уже создавал сказки?' : 'Ещё нет аккаунта?'}{' '}
          <Link
            to={isRegister ? '/login' : '/register'}
            className="font-extrabold text-amber-200 underline decoration-amber-200/30 underline-offset-4 transition-colors hover:text-amber-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300/50"
          >
            {isRegister ? 'Войти' : 'Зарегистрироваться'}
          </Link>
        </p>
      </motion.section>
      <Toast message={error} tone="error" onClose={() => setError(null)} />
    </PageTransition>
  )
}

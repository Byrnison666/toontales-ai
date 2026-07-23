import { motion } from 'framer-motion'
import { useEffect, useState } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import { MagicButton } from './MagicButton'

const navLinkClasses = ({ isActive }: { isActive: boolean }): string =>
  `rounded-xl px-3 py-2 text-sm font-extrabold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300/50 ${
    isActive ? 'bg-white/10 text-amber-200' : 'text-violet-200 hover:bg-white/5 hover:text-white'
  }`

export function AppHeader(): JSX.Element {
  const { isAuthenticated, logout } = useAuth()
  const [balance, setBalance] = useState<number | null>(null)
  const location = useLocation()
  const navigate = useNavigate()

  useEffect(() => {
    if (!isAuthenticated) {
      setBalance(null)
      return undefined
    }

    let active = true
    void api
      .getBalance()
      .then((response) => {
        if (active) setBalance(response.credit_balance)
      })
      .catch(() => {
        if (active) setBalance(null)
      })
    return () => {
      active = false
    }
  }, [isAuthenticated, location.pathname])

  const handleLogout = (): void => {
    logout()
    navigate('/')
  }

  return (
    <motion.header
      initial={{ opacity: 0, y: -24 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: 'spring', stiffness: 150, damping: 20 }}
      className="sticky top-0 z-40 border-b border-white/8 bg-[#0d0829]/70 backdrop-blur-2xl"
    >
      <div className="mx-auto flex min-h-18 max-w-7xl items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
        <motion.div whileHover={{ scale: 1.04, rotate: -1 }} whileTap={{ scale: 0.96 }}>
          <Link
            to="/"
            className="font-display text-xl font-bold tracking-tight text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300/50 sm:text-2xl"
            aria-label="ToonTales — на главную"
          >
            Toon<span className="text-gradient">Tales</span>
            <motion.span
              className="ml-1 inline-block text-amber-300"
              animate={{ rotate: [0, 18, -10, 0], scale: [1, 1.25, 0.9, 1] }}
              transition={{ duration: 2.4, repeat: Infinity, repeatDelay: 1.2 }}
              aria-hidden="true"
            >
              ✦
            </motion.span>
          </Link>
        </motion.div>

        {isAuthenticated ? (
          <div className="flex items-center gap-1 sm:gap-2">
            <nav className="hidden items-center gap-1 md:flex" aria-label="Основная навигация">
              <NavLink to="/create" className={navLinkClasses}>
                Создать
              </NavLink>
              <NavLink to="/gallery" className={navLinkClasses}>
                Мои мультфильмы
              </NavLink>
            </nav>
            <motion.div
              key={balance ?? 'loading'}
              initial={{ scale: 0.8, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
            >
              <NavLink
                to="/topup"
                className="block rounded-full border border-amber-300/20 bg-amber-300/10 px-3 py-1.5 text-xs font-extrabold text-amber-100 transition hover:bg-amber-300/20 sm:text-sm"
                title="Баланс искр — нажми, чтобы пополнить"
              >
                <span aria-hidden="true">✦ </span>
                {balance === null ? '…' : balance.toLocaleString('ru-RU')}
              </NavLink>
            </motion.div>
            <MagicButton variant="ghost" className="min-h-10 px-3 py-2 text-xs sm:text-sm" onClick={handleLogout}>
              Выйти
            </MagicButton>
          </div>
        ) : (
          <div className="flex items-center gap-1 sm:gap-2">
            <motion.div whileHover={{ y: -2 }} whileTap={{ scale: 0.95 }}>
              <Link className="rounded-xl px-3 py-2 text-sm font-bold text-violet-100 hover:text-white" to="/login">
                Войти
              </Link>
            </motion.div>
            <MagicButton className="min-h-10 px-3 py-2 text-xs sm:px-4 sm:text-sm" onClick={() => navigate('/register')}>
              Начать
            </MagicButton>
          </div>
        )}
      </div>
      {isAuthenticated ? (
        <nav className="flex justify-center gap-2 border-t border-white/5 px-4 py-2 md:hidden" aria-label="Мобильная навигация">
          <NavLink to="/create" className={navLinkClasses}>
            Создать
          </NavLink>
          <NavLink to="/gallery" className={navLinkClasses}>
            Мои мультфильмы
          </NavLink>
        </nav>
      ) : null}
    </motion.header>
  )
}

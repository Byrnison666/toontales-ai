import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'

const navigation = [
  { to: '/', label: 'Дашборд', end: true },
  { to: '/users', label: 'Пользователи', end: false },
  { to: '/runs', label: 'Генерации', end: false },
  { to: '/health', label: 'Здоровье', end: false },
] as const

export function Layout(): JSX.Element {
  const { logout } = useAuth()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/', { replace: true })
  }

  return (
    <div className="min-h-screen bg-slate-50 lg:flex">
      <aside className="border-b border-slate-800 bg-slate-950 text-slate-300 lg:fixed lg:inset-y-0 lg:left-0 lg:w-64 lg:border-b-0 lg:border-r">
        <div className="flex h-full flex-col">
          <div className="hidden border-b border-slate-800 px-6 py-6 lg:block">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-indigo-400">Operations</p>
            <p className="mt-1 text-lg font-bold text-white">ToonTales</p>
          </div>
          <nav className="flex gap-1 overflow-x-auto p-3 lg:flex-1 lg:flex-col lg:gap-1.5 lg:p-4" aria-label="Основная навигация">
            {navigation.map(({ to, label, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  `whitespace-nowrap rounded-lg px-3.5 py-2.5 text-sm font-medium transition ${
                    isActive ? 'bg-indigo-500 text-white shadow-sm' : 'text-slate-300 hover:bg-slate-800 hover:text-white'
                  }`
                }
              >
                {label}
              </NavLink>
            ))}
          </nav>
        </div>
      </aside>

      <div className="min-w-0 flex-1 lg:ml-64">
        <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-slate-200 bg-white/90 px-4 backdrop-blur sm:px-6 lg:px-8">
          <p className="font-bold tracking-tight text-slate-950">ToonTales Admin</p>
          <button
            type="button"
            onClick={handleLogout}
            className="rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50"
          >
            Выйти
          </button>
        </header>
        <main className="mx-auto max-w-7xl p-4 sm:p-6 lg:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

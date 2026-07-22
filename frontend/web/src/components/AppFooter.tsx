import { Link } from 'react-router-dom'

export function AppFooter(): JSX.Element {
  return (
    <footer className="relative z-10 mt-16 border-t border-white/10 bg-black/20 backdrop-blur-md">
      <div className="mx-auto flex max-w-7xl flex-col gap-3 px-4 py-8 text-sm text-violet-300 sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8">
        <div className="flex items-center gap-2">
          <span className="font-display text-base font-bold text-white">
            Toon<span className="text-amber-200">Tales</span>
          </span>
          <span aria-hidden="true">✦</span>
        </div>
        <p className="leading-relaxed">
          Самозанятый · Налог на профессиональный доход · ИНН{' '}
          <span className="font-semibold text-violet-100">782007624604</span>
        </p>
        <Link to="/" className="text-violet-300 transition-colors hover:text-amber-100">
          © {new Date().getFullYear()} ToonTales
        </Link>
      </div>
    </footer>
  )
}

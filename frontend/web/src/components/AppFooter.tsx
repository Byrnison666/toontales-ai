import { Link } from 'react-router-dom'
import { paymentsLive, requisites } from '../lib/legal'

export function AppFooter(): JSX.Element {
  return (
    <footer className="relative z-10 mt-16 border-t border-white/10 bg-black/20 backdrop-blur-md">
      <div className="mx-auto grid max-w-7xl gap-6 px-4 py-9 sm:px-6 lg:grid-cols-[1fr_auto] lg:gap-12 lg:px-8">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="font-display text-base font-bold text-white">
              Toon<span className="text-amber-200">Tales</span>
            </span>
            <span aria-hidden="true">✦</span>
          </div>
          {/* Реквизиты самозанятого показываем только после запуска оплаты (см. legal.ts). */}
          {paymentsLive && (
            <>
              <p className="text-sm leading-relaxed text-violet-300">
                {requisites.taxStatus} · {requisites.fullName} · ИНН{' '}
                <span className="font-semibold text-violet-100">{requisites.inn}</span>
              </p>
              <p className="text-sm text-violet-300">
                {requisites.city} ·{' '}
                <a href={`mailto:${requisites.email}`} className="transition-colors hover:text-amber-100">
                  {requisites.email}
                </a>{' '}
                ·{' '}
                <a href={`tel:${requisites.phoneHref}`} className="transition-colors hover:text-amber-100">
                  {requisites.phone}
                </a>
              </p>
            </>
          )}
        </div>

        {paymentsLive && (
          <nav className="flex flex-wrap gap-x-6 gap-y-2 text-sm text-violet-300 lg:justify-end">
            <Link to="/offer" className="transition-colors hover:text-amber-100">
              Публичная оферта
            </Link>
            <Link to="/payment" className="transition-colors hover:text-amber-100">
              Оплата и получение
            </Link>
            <Link to="/contacts" className="transition-colors hover:text-amber-100">
              Контакты
            </Link>
          </nav>
        )}
      </div>
      <div className="border-t border-white/5 py-4 text-center text-xs text-violet-400">
        © {new Date().getFullYear()} {requisites.brand}
      </div>
    </footer>
  )
}

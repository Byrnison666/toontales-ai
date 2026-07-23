import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { Link } from 'react-router-dom'
import { api, type SparkPackage } from '../api'
import { MagicButton } from '../components/MagicButton'
import { MagicLoader } from '../components/MagicLoader'
import { PageTransition } from '../components/PageTransition'
import { Toast } from '../components/Toast'

// ЗАГЛУШКА: платёжный провайдер ещё не подключён — ждём одобрения ЮKassa.
// Когда касса одобрит, здесь появится создание платежа и редирект на её форму;
// до тех пор кнопка недоступна, а не ведёт в никуда: неработающая кнопка
// «Купить» хуже честного «скоро», потому что выглядит как поломка оплаты.
const CHECKOUT_ENABLED = false

export function TopupPage(): JSX.Element {
  const [packages, setPackages] = useState<SparkPackage[] | null>(null)
  const [balance, setBalance] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    void api
      .getSparkPackages()
      .then((response) => {
        if (active) setPackages(response.packages)
      })
      .catch(() => {
        if (active) setError('Не удалось загрузить пакеты. Обнови страницу.')
      })
    void api
      .getBalance()
      .then((response) => {
        if (active) setBalance(response.credit_balance)
      })
      .catch(() => undefined)
    return () => {
      active = false
    }
  }, [])

  return (
    <PageTransition className="relative mx-auto max-w-4xl px-4 py-12 sm:px-6 lg:py-16">
      <h1 className="font-display text-4xl font-bold text-white sm:text-5xl">
        Пополнить <span className="text-gradient">искры</span>
      </h1>
      <p className="mt-3 max-w-2xl text-violet-200">
        Искры — топливо для мультфильмов. Они не сгорают и не имеют срока действия. Типичный ролик расходует
        около 3 300 искр.
      </p>
      <p className="mt-2 text-sm text-violet-300">
        Сейчас на балансе{' '}
        <span className="font-bold text-amber-100">
          {balance === null ? '…' : balance.toLocaleString('ru-RU')} ✦
        </span>
      </p>

      {!CHECKOUT_ENABLED && (
        <div className="mt-8 rounded-2xl border border-amber-200/25 bg-amber-200/[0.07] p-4 text-sm leading-relaxed text-amber-100">
          Онлайн-оплата скоро заработает — сейчас проходим подключение платёжного сервиса. Чтобы получить искры
          прямо сейчас, напиши нам, и мы пополним баланс вручную.
        </div>
      )}

      {packages === null ? (
        <div className="mt-10">
          <MagicLoader label="Считаем цены…" />
        </div>
      ) : (
        <div className="mt-10 grid gap-5 sm:grid-cols-3">
          {packages.map((item, index) => (
            <motion.section
              key={item.sparks}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.08 * index }}
              className="glass-card flex flex-col p-6"
            >
              <p className="font-display text-3xl font-bold text-amber-100">
                {item.sparks.toLocaleString('ru-RU')} <span className="text-lg text-amber-200/70">✦</span>
              </p>
              <p className="mt-2 text-2xl font-bold text-white">{item.price_rub.toLocaleString('ru-RU')} ₽</p>
              <p className="mt-2 flex-1 text-sm text-violet-300">
                Примерно {Math.max(1, Math.floor(item.sparks / 3300))}{' '}
                {item.sparks < 6600 ? 'мультфильм' : 'мультфильма и больше'}
              </p>
              <MagicButton
                fullWidth
                className="mt-5"
                disabled={!CHECKOUT_ENABLED}
                title={CHECKOUT_ENABLED ? undefined : 'Онлайн-оплата скоро заработает'}
              >
                {CHECKOUT_ENABLED ? 'Купить' : 'Скоро'}
              </MagicButton>
            </motion.section>
          ))}
        </div>
      )}

      <p className="mt-8 text-sm text-violet-300">
        Условия — в <Link to="/offer" className="underline">публичной оферте</Link> и на странице{' '}
        <Link to="/payment" className="underline">«Оплата и получение»</Link>.
      </p>

      <Toast message={error} tone="error" onClose={() => setError(null)} />
    </PageTransition>
  )
}

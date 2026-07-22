import { motion } from 'framer-motion'
import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api'
import { MagicButton } from '../components/MagicButton'
import { MagicLoader } from '../components/MagicLoader'
import { PageTransition } from '../components/PageTransition'
import { Toast } from '../components/Toast'
import { rememberRun } from '../storage'

function getGenerateError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 402) return 'Для этой сказки пока не хватает кредитов. Проверь баланс или выбери историю покороче.'
    if (error.status === 422) return 'Историю нужно немного изменить: проверь длину текста и убери неподходящие детали.'
    if (error.status >= 500) return 'Творческая мастерская перегружена. Попробуй запустить историю ещё раз.'
    if (error.message) return error.message
  }
  return 'Не удалось отправить историю в мастерскую. Проверь соединение и попробуй снова.'
}

export function CreatePage(): JSX.Element {
  const navigate = useNavigate()
  const [projectName, setProjectName] = useState('')
  const [scriptText, setScriptText] = useState('')
  const [balance, setBalance] = useState<number | null>(null)
  const [balanceLoading, setBalanceLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Баланс загружен и равен нулю — пополнение только вручную (стартовый бонус
  // выключен до платёжной системы), поэтому запуск блокируем с понятным текстом,
  // а не молча роняем в 402.
  const noBalance = !balanceLoading && balance === 0

  useEffect(() => {
    let active = true
    void api
      .getBalance()
      .then((response) => {
        if (active) setBalance(response.credit_balance)
      })
      .catch(() => {
        if (active) setError('Не удалось узнать баланс. Создать историю всё равно можно попробовать.')
      })
      .finally(() => {
        if (active) setBalanceLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  const handleSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const response = await api.generateProject({
        project_name: projectName.trim(),
        script_text: scriptText.trim(),
      })
      rememberRun({
        run_id: response.run_id,
        project_name: projectName.trim(),
        created_at: new Date().toISOString(),
      })
      navigate(`/runs/${encodeURIComponent(response.run_id)}`)
    } catch (requestError) {
      setError(getGenerateError(requestError))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <PageTransition className="mx-auto max-w-6xl px-4 py-12 sm:px-6 lg:px-8 lg:py-16">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        className="mx-auto mb-9 max-w-3xl text-center"
      >
        <p className="text-sm font-extrabold uppercase tracking-[0.24em] text-cyan-200">Новая премьера</p>
        <h1 className="font-display mt-3 text-4xl font-bold text-white sm:text-5xl">
          Какую историю <span className="text-gradient">оживим?</span>
        </h1>
        <p className="mt-4 text-violet-200">Дай воображению разгуляться. Детали помогают сделать мир ярче и характернее.</p>
      </motion.div>

      <div className="grid gap-6 lg:grid-cols-[1fr_19rem]">
        <motion.form
          initial={{ opacity: 0, x: -20, scale: 0.98 }}
          animate={{ opacity: 1, x: 0, scale: 1 }}
          transition={{ delay: 0.12 }}
          onSubmit={handleSubmit}
          className="glass-card p-6 sm:p-8"
        >
          <label className="block">
            <span className="mb-2 block font-extrabold text-violet-100">Название проекта</span>
            <motion.input
              whileFocus={{ scale: 1.005 }}
              type="text"
              required
              minLength={1}
              maxLength={200}
              value={projectName}
              onChange={(event) => setProjectName(event.target.value)}
              className="magic-input"
              placeholder="Например, Луна и храбрый светлячок"
            />
          </label>

          <label className="mt-6 block">
            <span className="mb-2 block font-extrabold text-violet-100">Твоя история</span>
            <motion.textarea
              whileFocus={{ scale: 1.003 }}
              required
              minLength={1}
              maxLength={4000}
              rows={12}
              value={scriptText}
              onChange={(event) => setScriptText(event.target.value)}
              className="magic-input min-h-64 resize-y leading-relaxed"
              placeholder="Расскажи свою историю... Кто главный герой? Чего он мечтает достичь? Какие чудеса встретятся ему в пути?"
            />
          </label>
          <div className="mt-2 flex items-center justify-between gap-3 text-xs font-bold text-violet-400">
            <span>Можно писать свободно — как рассказываешь сказку другу.</span>
            <motion.span
              key={scriptText.length}
              initial={{ scale: 0.85 }}
              animate={{ scale: 1 }}
              className={scriptText.length >= 3800 ? 'text-amber-200' : ''}
            >
              {scriptText.length.toLocaleString('ru-RU')} / 4 000
            </motion.span>
          </div>

          {noBalance && (
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              className="mt-6 rounded-2xl border border-amber-200/25 bg-amber-200/[0.07] p-4 text-sm leading-relaxed text-amber-100"
            >
              На балансе пока нет искр. Каждый ролик — это настоящая работа наших волшебников, поэтому
              запуск открывается после пополнения баланса. Напиши нам — и мы зажжём для тебя первые искры.
            </motion.div>
          )}

          <MagicButton
            type="submit"
            fullWidth
            className="group mt-8 min-h-14 text-base sm:text-lg"
            disabled={
              submitting || noBalance || projectName.trim().length === 0 || scriptText.trim().length === 0
            }
          >
            {submitting ? (
              <>
                <motion.span animate={{ rotate: 360 }} transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}>
                  ✦
                </motion.span>
                Запускаем волшебство…
              </>
            ) : noBalance ? (
              'Нужно пополнить баланс ✦'
            ) : (
              'Создать мультфильм ✨'
            )}
          </MagicButton>
        </motion.form>

        <motion.aside
          initial={{ opacity: 0, x: 20, scale: 0.96 }}
          animate={{ opacity: 1, x: 0, scale: 1 }}
          transition={{ delay: 0.22 }}
          className="space-y-5"
        >
          <section className="glass-card overflow-hidden p-5">
            <p className="text-sm font-bold text-violet-300">Твой баланс</p>
            {balanceLoading ? (
              <MagicLoader label="Считаем искры…" compact />
            ) : (
              <motion.p
                initial={{ scale: 0.8, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                className="font-display mt-2 text-4xl font-bold text-amber-100"
              >
                {balance?.toLocaleString('ru-RU') ?? '—'} <span className="text-lg text-amber-200/70">✦</span>
              </motion.p>
            )}
            <div className="my-4 h-px bg-gradient-to-r from-transparent via-white/15 to-transparent" />
            <p className="text-sm leading-relaxed text-violet-300">
              Примерная стоимость появится после анализа сюжета. Запуск не превысит бюджет, рассчитанный сервером.
            </p>
          </section>
          <section className="rounded-3xl border border-cyan-300/15 bg-cyan-300/[0.055] p-5">
            <p className="font-display text-lg font-semibold text-cyan-100">Искра для сюжета</p>
            <p className="mt-2 text-sm leading-relaxed text-violet-200">
              Добавь место действия, мечту героя и неожиданный поворот — так будущие сцены получатся выразительнее.
            </p>
          </section>
        </motion.aside>
      </div>
      <Toast message={error} tone="error" onClose={() => setError(null)} />
    </PageTransition>
  )
}

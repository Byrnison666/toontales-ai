import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import type { ProgressEvent, RunSnapshot } from '../api'
import {
  STAGES,
  STAGE_LABELS,
  calculateOverallProgress,
  getCurrentStage,
  isStageCompleted,
} from '../lib/progress'

interface StageProgressProps {
  snapshot: RunSnapshot
  progressEvent: ProgressEvent | null
  realtimeConnected: boolean
}

export function StageProgress({
  snapshot,
  progressEvent,
  realtimeConnected,
}: StageProgressProps): JSX.Element {
  const reduceMotion = useReducedMotion()
  const overallProgress = calculateOverallProgress(snapshot, progressEvent)
  const currentStage = getCurrentStage(snapshot, progressEvent)
  const currentLabel = snapshot.status === 'pending' ? 'Готовим творческую мастерскую' : STAGE_LABELS[currentStage]

  return (
    <section className="glass-card relative overflow-hidden px-5 py-8 sm:px-8 lg:px-10">
      <div className="absolute inset-x-10 top-12 h-36 rounded-full bg-violet-400/10 blur-3xl" aria-hidden="true" />
      <div className="relative grid items-center gap-10 lg:grid-cols-[1.05fr_0.95fr]">
        <div className="flex flex-col items-center text-center">
          <div className="relative mb-7 grid h-52 w-52 place-items-center sm:h-60 sm:w-60">
            <motion.div
              className="absolute inset-4 rounded-full border border-cyan-200/25"
              animate={reduceMotion ? undefined : { rotate: 360 }}
              transition={{ duration: 13, repeat: Infinity, ease: 'linear' }}
            >
              <span className="absolute -top-2 left-1/2 text-xl text-cyan-200">✦</span>
              <span className="absolute bottom-5 left-3 text-sm text-amber-200">✧</span>
            </motion.div>
            <motion.div
              className="absolute inset-9 rounded-full bg-gradient-to-br from-cyan-300/35 via-violet-400/45 to-rose-300/35 blur-xl"
              animate={reduceMotion ? undefined : { scale: [0.84, 1.08, 0.84], opacity: [0.55, 0.95, 0.55] }}
              transition={{ duration: 2.8, repeat: Infinity, ease: 'easeInOut' }}
            />
            <motion.div
              className="relative grid h-28 w-28 place-items-center rounded-full border border-white/30 bg-[radial-gradient(circle_at_35%_28%,#fff7c2_0%,#f6b5ff_22%,#7c3aed_58%,#16103e_100%)] text-5xl shadow-[0_0_38px_rgba(196,181,253,0.65),inset_0_0_20px_rgba(255,255,255,0.4)]"
              animate={reduceMotion ? undefined : { y: [0, -10, 0], rotate: [-2, 3, -2] }}
              transition={{ duration: 3.4, repeat: Infinity, ease: 'easeInOut' }}
              aria-hidden="true"
            >
              ✦
            </motion.div>
            <div className="absolute inset-0 grid place-items-center">
              <svg className="h-full w-full -rotate-90" viewBox="0 0 100 100" aria-hidden="true">
                <circle cx="50" cy="50" r="46" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="2" />
                <motion.circle
                  cx="50"
                  cy="50"
                  r="46"
                  fill="none"
                  stroke="url(#progress-gradient)"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  pathLength="100"
                  initial={{ pathLength: 0 }}
                  animate={{ pathLength: overallProgress / 100 }}
                  transition={{ type: 'spring', stiffness: 45, damping: 18 }}
                />
                <defs>
                  <linearGradient id="progress-gradient">
                    <stop offset="0%" stopColor="#fde68a" />
                    <stop offset="55%" stopColor="#fb7185" />
                    <stop offset="100%" stopColor="#67e8f9" />
                  </linearGradient>
                </defs>
              </svg>
            </div>
          </div>

          <motion.p
            key={overallProgress}
            initial={{ scale: 0.85, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            className="font-display text-5xl font-bold text-white sm:text-6xl"
          >
            {overallProgress}%
          </motion.p>
          <AnimatePresence mode="wait">
            <motion.h1
              key={currentLabel}
              initial={{ opacity: 0, y: 12, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -10, scale: 0.96 }}
              className="mt-3 font-display text-2xl font-semibold text-gradient sm:text-3xl"
            >
              {currentLabel}
            </motion.h1>
          </AnimatePresence>
          <p className="mt-3 min-h-6 text-sm text-violet-200 sm:text-base">
            {progressEvent?.message || 'Ваша история проходит через волшебные мастерские ToonTales.'}
          </p>
          <span className="mt-5 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-bold text-violet-200">
            <motion.span
              className={`h-2 w-2 rounded-full ${realtimeConnected ? 'bg-emerald-300' : 'bg-amber-300'}`}
              animate={reduceMotion ? undefined : { opacity: [0.35, 1, 0.35] }}
              transition={{ duration: 1.4, repeat: Infinity }}
            />
            {realtimeConnected ? 'Прогресс в реальном времени' : 'Обновляем в фоновом режиме'}
          </span>
        </div>

        <ol className="space-y-3" aria-label="Этапы создания мультфильма">
          {STAGES.map((stage, index) => {
            const completed = isStageCompleted(stage, snapshot, progressEvent)
            const active = currentStage === stage && !completed
            return (
              <motion.li
                key={stage}
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: index * 0.08 }}
                className={`flex items-center gap-4 rounded-2xl border px-4 py-3 transition-colors ${
                  active
                    ? 'border-cyan-300/35 bg-cyan-300/10 shadow-[0_0_22px_rgba(34,211,238,0.1)]'
                    : completed
                      ? 'border-emerald-300/20 bg-emerald-300/5'
                      : 'border-white/7 bg-white/[0.025]'
                }`}
              >
                <motion.span
                  initial={false}
                  animate={completed ? { scale: [0.7, 1.2, 1], rotate: [0, 12, 0] } : { scale: 1 }}
                  className={`grid h-9 w-9 shrink-0 place-items-center rounded-full border font-extrabold ${
                    completed
                      ? 'border-emerald-200/40 bg-emerald-300/20 text-emerald-100'
                      : active
                        ? 'border-cyan-200/40 bg-cyan-300/15 text-cyan-100'
                        : 'border-white/10 bg-white/5 text-violet-400'
                  }`}
                >
                  {completed ? '✓' : active ? '✦' : index + 1}
                </motion.span>
                <div className="min-w-0">
                  <p className={`font-extrabold ${active ? 'text-white' : completed ? 'text-emerald-100' : 'text-violet-300'}`}>
                    {STAGE_LABELS[stage]}
                  </p>
                  <p className="text-xs text-violet-400">
                    {completed ? 'Готово' : active ? 'Сейчас творим' : 'Впереди'}
                  </p>
                </div>
                {active ? (
                  <motion.span
                    className="ml-auto text-cyan-200"
                    animate={reduceMotion ? undefined : { rotate: 360 }}
                    transition={{ duration: 2.8, repeat: Infinity, ease: 'linear' }}
                    aria-hidden="true"
                  >
                    ✧
                  </motion.span>
                ) : null}
              </motion.li>
            )
          })}
        </ol>
      </div>
    </section>
  )
}

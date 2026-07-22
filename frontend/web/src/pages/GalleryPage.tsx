import { motion } from 'framer-motion'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { staggerContainer } from '../animations'
import { api, type RunSnapshot } from '../api'
import { MagicButton } from '../components/MagicButton'
import { MagicLoader } from '../components/MagicLoader'
import { PageTransition } from '../components/PageTransition'
import { VideoCard } from '../components/VideoCard'
import { getStoredRuns, type StoredRun } from '../storage'

interface GalleryRun {
  stored: StoredRun
  snapshot: RunSnapshot | null
  unavailable: boolean
}

export function GalleryPage(): JSX.Element {
  const navigate = useNavigate()
  const [runs, setRuns] = useState<GalleryRun[]>([])
  const [balance, setBalance] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    const loadGallery = async (): Promise<void> => {
      const storedRuns = getStoredRuns()
      const [balanceResult, runResults] = await Promise.all([
        api.getBalance().catch(() => null),
        Promise.all(
          storedRuns.map(async (stored): Promise<GalleryRun> => {
            try {
              return { stored, snapshot: await api.getRun(stored.run_id), unavailable: false }
            } catch {
              return { stored, snapshot: null, unavailable: true }
            }
          }),
        ),
      ])

      if (!active) return
      setBalance(balanceResult?.credit_balance ?? null)
      setRuns(runResults)
      setLoading(false)
    }
    void loadGallery()
    return () => {
      active = false
    }
  }, [])

  return (
    <PageTransition className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8 lg:py-16">
      <div className="flex flex-col justify-between gap-6 sm:flex-row sm:items-end">
        <div>
          <p className="text-sm font-extrabold uppercase tracking-[0.24em] text-cyan-200">Личная коллекция</p>
          <h1 className="font-display mt-2 text-4xl font-bold text-white sm:text-5xl">
            Мои <span className="text-gradient">мультфильмы</span>
          </h1>
          <p className="mt-3 max-w-2xl text-violet-200">Все истории, которые ты отправил в нашу волшебную мастерскую.</p>
        </div>
        <motion.div
          initial={{ opacity: 0, scale: 0.85 }}
          animate={{ opacity: 1, scale: 1 }}
          className="glass-card flex min-w-56 items-center justify-between gap-5 px-5 py-4"
        >
          <div>
            <p className="text-xs font-bold uppercase tracking-wider text-violet-400">Баланс</p>
            <p className="font-display text-2xl font-bold text-amber-100">
              {balance === null ? '—' : balance.toLocaleString('ru-RU')} ✦
            </p>
          </div>
          <motion.span
            animate={{ rotate: [0, 15, -10, 0], scale: [1, 1.15, 1] }}
            transition={{ duration: 2.6, repeat: Infinity }}
            className="text-3xl"
            aria-hidden="true"
          >
            🪙
          </motion.span>
        </motion.div>
      </div>

      {loading ? (
        <MagicLoader label="Открываем твою фильмотеку…" />
      ) : runs.length === 0 ? (
        <motion.section
          initial={{ opacity: 0, y: 24, scale: 0.95 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          className="glass-card mx-auto mt-14 flex max-w-2xl flex-col items-center px-6 py-14 text-center"
        >
          <motion.div
            animate={{ y: [0, -10, 0], rotate: [-3, 3, -3] }}
            transition={{ duration: 3.6, repeat: Infinity, ease: 'easeInOut' }}
            className="text-7xl"
            aria-hidden="true"
          >
            📽️
          </motion.div>
          <h2 className="font-display mt-6 text-3xl font-bold text-white">Ты ещё не создал ни одной сказки</h2>
          <p className="mt-3 max-w-md text-violet-200">Начни с маленькой идеи — иногда целый мир помещается в одном предложении.</p>
          <MagicButton className="group mt-8" onClick={() => navigate('/create')}>
            Создать первую сказку ✨
          </MagicButton>
        </motion.section>
      ) : (
        <motion.div
          variants={staggerContainer}
          initial="hidden"
          animate="visible"
          className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-3"
        >
          {runs.map((run) => (
            <VideoCard
              key={run.stored.run_id}
              run={run.stored}
              snapshot={run.snapshot}
              unavailable={run.unavailable}
            />
          ))}
        </motion.div>
      )}
    </PageTransition>
  )
}

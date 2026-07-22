import { motion } from 'framer-motion'
import { Link } from 'react-router-dom'
import type { RunSnapshot } from '../api'
import type { StoredRun } from '../storage'
import { StatusBadge } from './StatusBadge'

interface VideoCardProps {
  run: StoredRun
  snapshot: RunSnapshot | null
  unavailable?: boolean
}

function formatCost(value: string | null | undefined): string {
  if (!value) return 'Считается'
  const numericValue = Number(value)
  return Number.isFinite(numericValue) ? `$${numericValue.toFixed(2)}` : value
}

function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Дата неизвестна'
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' }).format(date)
}

export function VideoCard({ run, snapshot, unavailable = false }: VideoCardProps): JSX.Element {
  const finalVideo = snapshot?.assets.find((asset) => asset.kind === 'final_render')

  return (
    <motion.article
      variants={{
        hidden: { opacity: 0, y: 22, scale: 0.94 },
        visible: { opacity: 1, y: 0, scale: 1 },
      }}
      whileHover={{ y: -8, scale: 1.015 }}
      transition={{ type: 'spring', stiffness: 220, damping: 20 }}
      className="group overflow-hidden rounded-3xl border border-white/10 bg-[#1a1040]/75 shadow-[0_18px_60px_rgba(7,4,28,0.34)] hover:border-amber-200/25 hover:shadow-[0_20px_70px_rgba(244,114,182,0.16)]"
    >
      <Link
        to={`/runs/${encodeURIComponent(run.run_id)}`}
        className="block focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-inset focus-visible:ring-amber-300/40"
        aria-label={`Открыть мультфильм «${run.project_name}»`}
      >
        <div className="relative aspect-video overflow-hidden bg-[radial-gradient(circle_at_50%_20%,rgba(253,230,138,0.26),transparent_30%),linear-gradient(145deg,#4c1d95,#172554_55%,#164e63)]">
          {finalVideo ? (
            <video
              src={finalVideo.presigned_url}
              muted
              preload="metadata"
              className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-105"
            />
          ) : (
            <div className="absolute inset-0 grid place-items-center">
              <motion.span
                animate={snapshot?.status === 'running' ? { y: [0, -8, 0], rotate: [-3, 3, -3] } : undefined}
                transition={{ duration: 2.8, repeat: Infinity, ease: 'easeInOut' }}
                className="text-6xl drop-shadow-[0_0_18px_rgba(253,230,138,0.45)]"
                aria-hidden="true"
              >
                {unavailable ? '🌙' : snapshot?.status === 'failed' ? '☁️' : '🎬'}
              </motion.span>
            </div>
          )}
          <div className="absolute inset-0 bg-gradient-to-t from-[#120a32]/70 via-transparent to-transparent" />
          {snapshot ? (
            <div className="absolute left-4 top-4">
              <StatusBadge status={snapshot.status} />
            </div>
          ) : null}
          {finalVideo ? (
            <motion.span
              whileHover={{ scale: 1.1 }}
              className="absolute bottom-4 right-4 grid h-11 w-11 place-items-center rounded-full border border-white/25 bg-white/15 text-xl backdrop-blur-md"
              aria-hidden="true"
            >
              ▶
            </motion.span>
          ) : null}
        </div>
        <div className="p-5">
          <h2 className="truncate font-display text-xl font-semibold text-white">{run.project_name}</h2>
          <div className="mt-3 flex items-center justify-between gap-3 text-sm text-violet-300">
            <time dateTime={run.created_at}>
              {formatDate(run.created_at)}
            </time>
            <span className="font-bold text-amber-100">{unavailable ? 'Недоступен' : formatCost(snapshot?.total_real_cost_usd)}</span>
          </div>
        </div>
      </Link>
    </motion.article>
  )
}

import { motion, useReducedMotion } from 'framer-motion'

interface MagicLoaderProps {
  label?: string
  compact?: boolean
}

export function MagicLoader({ label = 'Собираем волшебство…', compact = false }: MagicLoaderProps): JSX.Element {
  const reduceMotion = useReducedMotion()

  return (
    <div
      className={`flex items-center justify-center gap-4 text-violet-100 ${compact ? 'py-4' : 'min-h-[55vh] flex-col'}`}
      role="status"
      aria-live="polite"
    >
      <div className={`relative ${compact ? 'h-9 w-9' : 'h-20 w-20'}`}>
        <motion.div
          className="absolute inset-0 rounded-full bg-gradient-to-br from-amber-200 via-rose-300 to-violet-400 blur-sm"
          animate={reduceMotion ? undefined : { rotate: 360, scale: [0.9, 1.08, 0.9] }}
          transition={{ rotate: { duration: 3, repeat: Infinity, ease: 'linear' }, scale: { duration: 1.8, repeat: Infinity } }}
        />
        <motion.div
          className="absolute inset-[18%] rounded-full bg-[#21104b] shadow-[inset_0_0_16px_rgba(255,255,255,0.25)]"
          animate={reduceMotion ? undefined : { opacity: [0.7, 1, 0.7] }}
          transition={{ duration: 1.4, repeat: Infinity }}
        />
        <span className="absolute inset-0 grid place-items-center text-xl" aria-hidden="true">
          ✦
        </span>
      </div>
      <span className="font-bold">{label}</span>
    </div>
  )
}

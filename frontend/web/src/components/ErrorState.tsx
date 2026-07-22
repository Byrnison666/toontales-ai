import { motion } from 'framer-motion'
import { MagicButton } from './MagicButton'

interface ErrorStateProps {
  title?: string
  message: string
  actionLabel?: string
  onAction?: () => void
}

export function ErrorState({
  title = 'Магия немного рассеялась',
  message,
  actionLabel,
  onAction,
}: ErrorStateProps): JSX.Element {
  return (
    <motion.section
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      className="glass-card mx-auto flex max-w-xl flex-col items-center px-7 py-10 text-center"
      role="alert"
    >
      <motion.div
        animate={{ rotate: [-5, 5, -5], y: [0, -6, 0] }}
        transition={{ duration: 2.8, repeat: Infinity, ease: 'easeInOut' }}
        className="mb-5 text-6xl"
        aria-hidden="true"
      >
        🌙
      </motion.div>
      <h1 className="font-display text-3xl font-bold text-white">{title}</h1>
      <p className="mt-3 max-w-md text-violet-200">{message}</p>
      {actionLabel && onAction ? (
        <MagicButton className="mt-7" onClick={onAction}>
          {actionLabel}
        </MagicButton>
      ) : null}
    </motion.section>
  )
}

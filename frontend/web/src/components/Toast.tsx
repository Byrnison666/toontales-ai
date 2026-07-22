import { AnimatePresence, motion } from 'framer-motion'
import { useEffect } from 'react'

interface ToastProps {
  message: string | null
  tone?: 'error' | 'success' | 'info'
  onClose: () => void
}

const toneClasses = {
  error: 'border-rose-300/40 bg-rose-950/90 text-rose-50 shadow-rose-500/20',
  success: 'border-emerald-300/40 bg-emerald-950/90 text-emerald-50 shadow-emerald-500/20',
  info: 'border-cyan-300/40 bg-[#151044]/95 text-cyan-50 shadow-cyan-500/20',
} as const

export function Toast({ message, tone = 'info', onClose }: ToastProps): JSX.Element {
  useEffect(() => {
    if (!message) return undefined
    const timeoutId = window.setTimeout(onClose, 6000)
    return () => window.clearTimeout(timeoutId)
  }, [message, onClose])

  return (
    <AnimatePresence>
      {message ? (
        <motion.div
          initial={{ opacity: 0, y: 24, scale: 0.9 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, x: 36, scale: 0.92 }}
          transition={{ type: 'spring', stiffness: 260, damping: 20 }}
          className={`fixed bottom-6 right-4 z-50 flex max-w-[calc(100vw-2rem)] items-start gap-3 rounded-2xl border px-5 py-4 font-bold shadow-2xl backdrop-blur-xl sm:right-6 sm:max-w-md ${toneClasses[tone]}`}
          role={tone === 'error' ? 'alert' : 'status'}
        >
          <span aria-hidden="true">{tone === 'error' ? '✦' : tone === 'success' ? '✓' : '✧'}</span>
          <span>{message}</span>
          <motion.button
            type="button"
            onClick={onClose}
            whileHover={{ rotate: 90, scale: 1.15 }}
            whileTap={{ scale: 0.8 }}
            className="ml-1 rounded-md px-1 text-lg leading-none opacity-70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/50"
            aria-label="Закрыть уведомление"
          >
            ×
          </motion.button>
        </motion.div>
      ) : null}
    </AnimatePresence>
  )
}

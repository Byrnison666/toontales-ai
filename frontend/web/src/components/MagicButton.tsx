import { motion, type HTMLMotionProps } from 'framer-motion'
import type { ReactNode } from 'react'

interface MagicButtonProps extends Omit<HTMLMotionProps<'button'>, 'children'> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  fullWidth?: boolean
  children: ReactNode
}

const variantClasses: Record<NonNullable<MagicButtonProps['variant']>, string> = {
  primary:
    'bg-gradient-to-r from-amber-300 via-orange-400 to-rose-400 text-[#24103e] shadow-[0_0_28px_rgba(251,191,36,0.34)] hover:shadow-[0_0_42px_rgba(251,191,36,0.55)]',
  secondary:
    'border border-cyan-300/30 bg-gradient-to-r from-cyan-400/20 to-violet-400/20 text-white shadow-[0_0_24px_rgba(34,211,238,0.14)] hover:border-cyan-200/60 hover:shadow-[0_0_34px_rgba(34,211,238,0.28)]',
  ghost: 'border border-white/10 bg-white/5 text-violet-100 hover:border-white/25 hover:bg-white/10',
  danger:
    'border border-rose-300/25 bg-rose-400/10 text-rose-100 hover:border-rose-200/50 hover:bg-rose-400/20',
}

export function MagicButton({
  variant = 'primary',
  fullWidth = false,
  className = '',
  children,
  disabled,
  ...props
}: MagicButtonProps): JSX.Element {
  return (
    <motion.button
      whileHover={disabled ? undefined : { scale: 1.045, y: -2 }}
      whileTap={disabled ? undefined : { scale: 0.94, y: 1 }}
      transition={{ type: 'spring', stiffness: 360, damping: 17 }}
      className={`group relative inline-flex min-h-12 items-center justify-center gap-2 overflow-hidden rounded-2xl px-6 py-3 font-extrabold tracking-wide transition-colors focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-amber-300/35 disabled:cursor-not-allowed disabled:opacity-55 ${variantClasses[variant]} ${fullWidth ? 'w-full' : ''} ${className}`}
      disabled={disabled}
      {...props}
    >
      <span className="pointer-events-none absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/30 to-transparent transition-transform duration-700 group-hover:translate-x-full" />
      <span className="relative z-10 inline-flex items-center gap-2">{children}</span>
    </motion.button>
  )
}

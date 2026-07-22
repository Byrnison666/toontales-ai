import { motion, useReducedMotion } from 'framer-motion'

const particles = Array.from({ length: 28 }, (_, index) => ({
  id: index,
  x: ((index * 47) % 110) - 55,
  y: -45 - ((index * 29) % 75),
  rotate: 90 + ((index * 71) % 280),
  delay: (index % 9) * 0.06,
  color: ['#fde68a', '#fb7185', '#67e8f9', '#c4b5fd'][index % 4],
}))

export function Celebration(): JSX.Element | null {
  const reduceMotion = useReducedMotion()
  if (reduceMotion) return null

  return (
    <div className="pointer-events-none absolute inset-x-0 top-20 z-20 mx-auto h-52 max-w-4xl overflow-visible" aria-hidden="true">
      {particles.map((particle) => (
        <motion.span
          key={particle.id}
          className="absolute left-1/2 top-1/2 h-2.5 w-2.5 rounded-[3px] shadow-[0_0_10px_currentColor]"
          style={{ backgroundColor: particle.color, color: particle.color }}
          initial={{ x: 0, y: 0, scale: 0, opacity: 0 }}
          animate={{
            x: `${particle.x}vw`,
            y: particle.y,
            rotate: particle.rotate,
            scale: [0, 1.4, 0.8],
            opacity: [0, 1, 0],
          }}
          transition={{ duration: 2.1, delay: particle.delay, ease: [0.12, 0.82, 0.2, 1] }}
        />
      ))}
      <motion.div
        className="absolute left-1/2 top-1/2 h-20 w-20 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-amber-200/60"
        initial={{ scale: 0, opacity: 1 }}
        animate={{ scale: 6, opacity: 0 }}
        transition={{ duration: 1.4, ease: 'easeOut' }}
      />
    </div>
  )
}

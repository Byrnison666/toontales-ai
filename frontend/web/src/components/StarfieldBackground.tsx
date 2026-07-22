import { motion, useReducedMotion } from 'framer-motion'

const stars = [
  { left: '7%', top: '15%', size: 5, duration: 4.2, delay: 0.2 },
  { left: '13%', top: '62%', size: 3, duration: 5.4, delay: 1.3 },
  { left: '21%', top: '32%', size: 7, duration: 6.1, delay: 0.6 },
  { left: '29%', top: '78%', size: 4, duration: 4.7, delay: 2.2 },
  { left: '38%', top: '12%', size: 4, duration: 5.8, delay: 1.8 },
  { left: '46%', top: '52%', size: 6, duration: 4.9, delay: 0.1 },
  { left: '54%', top: '86%', size: 3, duration: 6.6, delay: 2.9 },
  { left: '63%', top: '23%', size: 5, duration: 5.2, delay: 1.1 },
  { left: '71%', top: '68%', size: 7, duration: 6.3, delay: 0.7 },
  { left: '78%', top: '10%', size: 3, duration: 4.4, delay: 2.4 },
  { left: '85%', top: '43%', size: 5, duration: 5.7, delay: 1.5 },
  { left: '92%', top: '76%', size: 4, duration: 4.8, delay: 0.4 },
  { left: '4%', top: '88%', size: 3, duration: 6.4, delay: 3.1 },
  { left: '34%', top: '43%', size: 3, duration: 5.1, delay: 2.7 },
  { left: '58%', top: '38%', size: 4, duration: 5.9, delay: 1.9 },
  { left: '96%', top: '22%', size: 6, duration: 6.8, delay: 0.9 },
] as const

export function StarfieldBackground(): JSX.Element {
  const reduceMotion = useReducedMotion()

  return (
    <div className="pointer-events-none fixed inset-0 -z-20 overflow-hidden" aria-hidden="true">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_15%,rgba(190,70,255,0.2),transparent_28%),radial-gradient(circle_at_82%_22%,rgba(244,114,182,0.14),transparent_25%),radial-gradient(circle_at_55%_88%,rgba(34,211,238,0.12),transparent_30%),linear-gradient(145deg,#0b0824_0%,#1a0e41_45%,#0c1740_100%)]" />
      <motion.div
        className="absolute -left-24 top-[18%] h-72 w-72 rounded-full bg-fuchsia-500/10 blur-3xl"
        animate={reduceMotion ? undefined : { x: [0, 70, 5], y: [0, -25, 0], scale: [1, 1.15, 1] }}
        transition={{ duration: 17, repeat: Infinity, ease: 'easeInOut' }}
      />
      <motion.div
        className="absolute -right-24 bottom-[8%] h-80 w-80 rounded-full bg-cyan-400/10 blur-3xl"
        animate={reduceMotion ? undefined : { x: [0, -55, 0], y: [0, 35, 0], scale: [1, 0.9, 1] }}
        transition={{ duration: 20, repeat: Infinity, ease: 'easeInOut', delay: 1.5 }}
      />
      {stars.map((star) => (
        <motion.span
          key={`${star.left}-${star.top}`}
          className="absolute rounded-full bg-amber-100 shadow-[0_0_10px_2px_rgba(253,230,138,0.65)]"
          style={{ left: star.left, top: star.top, width: star.size, height: star.size }}
          animate={
            reduceMotion
              ? undefined
              : { y: [0, -16, 2, 0], opacity: [0.25, 1, 0.45, 0.25], scale: [0.8, 1.35, 0.9, 0.8] }
          }
          transition={{ duration: star.duration, delay: star.delay, repeat: Infinity, ease: 'easeInOut' }}
        />
      ))}
      <div className="noise-overlay absolute inset-0 opacity-[0.035]" />
    </div>
  )
}

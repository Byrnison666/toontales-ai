import { motion } from 'framer-motion'
import type { PropsWithChildren } from 'react'
import { pageVariants } from '../animations'

interface PageTransitionProps extends PropsWithChildren {
  className?: string
}

export function PageTransition({ children, className = '' }: PageTransitionProps): JSX.Element {
  return (
    <motion.main
      id="main-content"
      variants={pageVariants}
      initial="hidden"
      animate="visible"
      exit="exit"
      className={className}
    >
      {children}
    </motion.main>
  )
}

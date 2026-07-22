import type { PropsWithChildren } from 'react'
import { PageTransition } from './PageTransition'

interface LegalLayoutProps {
  title: string
  subtitle?: string
}

export function LegalLayout({ title, subtitle, children }: PropsWithChildren<LegalLayoutProps>): JSX.Element {
  return (
    <PageTransition className="mx-auto max-w-3xl px-4 py-14 sm:px-6 lg:px-8">
      <header className="mb-8">
        <h1 className="font-display text-3xl font-bold text-white sm:text-4xl">{title}</h1>
        {subtitle && <p className="mt-3 text-violet-300">{subtitle}</p>}
      </header>
      <div className="legal-prose glass-card space-y-5 p-6 text-violet-100 sm:p-8">{children}</div>
    </PageTransition>
  )
}

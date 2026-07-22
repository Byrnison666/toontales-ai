import type { PropsWithChildren } from 'react'
import { AppFooter } from './AppFooter'
import { AppHeader } from './AppHeader'
import { StarfieldBackground } from './StarfieldBackground'

export function AppShell({ children }: PropsWithChildren): JSX.Element {
  return (
    <div className="relative flex min-h-screen flex-col overflow-x-clip text-white">
      <a
        href="#main-content"
        className="fixed left-4 top-3 z-[100] -translate-y-20 rounded-xl bg-amber-300 px-4 py-2 font-bold text-[#1a0e41] transition-transform focus:translate-y-0"
      >
        К содержимому
      </a>
      <StarfieldBackground />
      <AppHeader />
      <div className="flex-1">{children}</div>
      <AppFooter />
    </div>
  )
}

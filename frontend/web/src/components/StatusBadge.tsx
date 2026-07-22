import type { RunStatus } from '../api'

interface StatusBadgeProps {
  status: RunStatus
}

const statusPresentation: Record<RunStatus, { label: string; classes: string }> = {
  pending: { label: 'В очереди', classes: 'border-amber-300/30 bg-amber-300/10 text-amber-100' },
  running: { label: 'Создаётся', classes: 'border-cyan-300/30 bg-cyan-300/10 text-cyan-100' },
  completed: { label: 'Готов', classes: 'border-emerald-300/30 bg-emerald-300/10 text-emerald-100' },
  failed: { label: 'Не получилось', classes: 'border-rose-300/30 bg-rose-300/10 text-rose-100' },
  canceled: { label: 'Отменён', classes: 'border-slate-300/25 bg-slate-300/10 text-slate-200' },
}

export function StatusBadge({ status }: StatusBadgeProps): JSX.Element {
  const presentation = statusPresentation[status]
  return (
    <span className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-extrabold ${presentation.classes}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current shadow-[0_0_8px_currentColor]" aria-hidden="true" />
      {presentation.label}
    </span>
  )
}

import type { RunStatus, TaskStatus } from '../api'
import { runStatusLabels, taskStatusLabels } from '../format'

interface StatusBadgeProps {
  status: RunStatus | TaskStatus
  kind?: 'run' | 'task'
}

const colorClasses: Record<RunStatus | TaskStatus, string> = {
  pending: 'bg-slate-100 text-slate-700 ring-slate-200',
  running: 'bg-blue-50 text-blue-700 ring-blue-200',
  completed: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  failed: 'bg-red-50 text-red-700 ring-red-200',
  canceled: 'bg-slate-100 text-slate-500 ring-slate-200',
  submitting: 'bg-indigo-50 text-indigo-700 ring-indigo-200',
  waiting_provider: 'bg-amber-50 text-amber-700 ring-amber-200',
  processing: 'bg-blue-50 text-blue-700 ring-blue-200',
  retry_scheduled: 'bg-orange-50 text-orange-700 ring-orange-200',
}

export function StatusBadge({ status, kind = 'run' }: StatusBadgeProps): JSX.Element {
  const label = kind === 'run' ? runStatusLabels[status as RunStatus] : taskStatusLabels[status as TaskStatus]

  return (
    <span className={`inline-flex whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${colorClasses[status]}`}>
      {label}
    </span>
  )
}

interface LoadingStateProps {
  label?: string
}

export function LoadingState({ label = 'Загрузка данных…' }: LoadingStateProps): JSX.Element {
  return (
    <div className="flex min-h-56 items-center justify-center rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
      <div className="flex items-center gap-3 text-sm font-medium text-slate-500" role="status">
        <span className="h-5 w-5 animate-spin rounded-full border-2 border-indigo-200 border-t-indigo-600" />
        {label}
      </div>
    </div>
  )
}

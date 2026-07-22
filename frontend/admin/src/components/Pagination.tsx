interface PaginationProps {
  limit: number
  offset: number
  total: number
  onOffsetChange: (offset: number) => void
}

export function Pagination({ limit, offset, total, onOffsetChange }: PaginationProps): JSX.Element {
  const start = total === 0 ? 0 : offset + 1
  const end = Math.min(offset + limit, total)
  const hasPrevious = offset > 0
  const hasNext = offset + limit < total

  return (
    <div className="flex flex-col gap-3 border-t border-slate-200 px-5 py-4 text-sm sm:flex-row sm:items-center sm:justify-between">
      <p className="text-slate-500">
        Показано <span className="font-medium text-slate-700">{start}–{end}</span> из{' '}
        <span className="font-medium text-slate-700">{total}</span>
      </p>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={!hasPrevious}
          onClick={() => onOffsetChange(Math.max(0, offset - limit))}
          className="rounded-lg border border-slate-200 bg-white px-3 py-2 font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Назад
        </button>
        <button
          type="button"
          disabled={!hasNext}
          onClick={() => onOffsetChange(offset + limit)}
          className="rounded-lg border border-slate-200 bg-white px-3 py-2 font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Далее
        </button>
      </div>
    </div>
  )
}

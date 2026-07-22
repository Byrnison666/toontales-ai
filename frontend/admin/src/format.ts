import type { PipelineStage, RunStatus, TaskStatus } from './api'

const dateFormatter = new Intl.DateTimeFormat('ru-RU', {
  dateStyle: 'medium',
  timeStyle: 'short',
})

export const runStatusLabels: Record<RunStatus, string> = {
  pending: 'Ожидает',
  running: 'В работе',
  completed: 'Завершён',
  failed: 'Ошибка',
  canceled: 'Отменён',
}

export const taskStatusLabels: Record<TaskStatus, string> = {
  pending: 'Ожидает',
  submitting: 'Отправляется',
  waiting_provider: 'Ожидает провайдера',
  processing: 'Обрабатывается',
  retry_scheduled: 'Повтор запланирован',
  completed: 'Завершена',
  failed: 'Ошибка',
  canceled: 'Отменена',
}

export const stageLabels: Record<PipelineStage, string> = {
  storyboard_generation: 'Генерация раскадровки',
  image_generation: 'Генерация изображений',
  video_generation: 'Генерация видео',
  audio_generation: 'Генерация аудио',
  lipsync: 'Синхронизация губ',
  composition: 'Композиция',
}

export function formatCurrency(value: string | null): string {
  if (value === null) {
    return '—'
  }

  const amount = Number(value)
  if (!Number.isFinite(amount)) {
    return '—'
  }

  return `$${amount.toLocaleString('en-US', {
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
  })}`
}

export function formatDate(value: string | null): string {
  if (!value) {
    return '—'
  }

  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : dateFormatter.format(date)
}

export function formatInteger(value: number): string {
  return value.toLocaleString('ru-RU')
}

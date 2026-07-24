import type { ProgressEvent, RunSnapshot, Stage } from '../api'

// Реально выполняемые этапы в порядке пайплайна (voiceover-режим, lipsync выключен
// в проде). Должен совпадать с backend ACTIVE_STAGES (domain/enums.py): озвучка
// (audio) идёт до video, т.к. video берёт длину из озвучки. LIPSYNC не показываем —
// синхронизации губ сейчас нет. Индексы этапов должны сходиться с backend
// stage_index/total_stages, иначе процент и отметки «готово» разъедутся.
export const STAGES: readonly Stage[] = [
  'storyboard_generation',
  'image_generation',
  'audio_generation',
  'video_generation',
  'composition',
] as const

export const STAGE_LABELS: Record<Stage, string> = {
  storyboard_generation: 'Придумываем сказку',
  image_generation: 'Рисуем картинки',
  video_generation: 'Оживляем сцены',
  audio_generation: 'Записываем голоса',
  lipsync: 'Синхронизируем губы',
  composition: 'Собираем ролик',
}

export function calculateOverallProgress(
  snapshot: RunSnapshot,
  progressEvent: ProgressEvent | null,
): number {
  if (snapshot.status === 'completed') return 100

  if (progressEvent && progressEvent.total_stages > 0) {
    const stagePosition = Math.max(0, progressEvent.stage_index)
    const stageProgress = clamp(progressEvent.progress, 0, 100) / 100
    return Math.round(clamp(((stagePosition + stageProgress) / progressEvent.total_stages) * 100, 0, 99))
  }

  const completedStages = STAGES.filter((stage) => {
    const tasks = snapshot.tasks.filter((task) => task.stage === stage)
    return tasks.length > 0 && tasks.every((task) => task.status === 'completed')
  }).length

  const activeProgress = snapshot.tasks
    .filter((task) => task.status === 'running' && task.progress_hint !== null)
    .reduce((maximum, task) => Math.max(maximum, clamp(task.progress_hint ?? 0, 0, 100)), 0)

  return Math.round(clamp(((completedStages + activeProgress / 100) / STAGES.length) * 100, 0, 99))
}

export function getCurrentStage(snapshot: RunSnapshot, progressEvent: ProgressEvent | null): Stage {
  if (progressEvent && STAGES.includes(progressEvent.stage)) return progressEvent.stage

  const runningTask = snapshot.tasks.find((task) => task.status === 'running')
  if (runningTask) return runningTask.stage

  const firstIncomplete = STAGES.find((stage) => {
    const tasks = snapshot.tasks.filter((task) => task.stage === stage)
    return tasks.length === 0 || tasks.some((task) => task.status !== 'completed')
  })
  return firstIncomplete ?? 'composition'
}

export function isStageCompleted(
  stage: Stage,
  snapshot: RunSnapshot,
  progressEvent: ProgressEvent | null,
): boolean {
  if (snapshot.status === 'completed') return true
  const tasks = snapshot.tasks.filter((task) => task.stage === stage)
  if (tasks.length > 0 && tasks.every((task) => task.status === 'completed')) return true

  if (progressEvent) {
    const currentIndex = STAGES.indexOf(progressEvent.stage)
    return STAGES.indexOf(stage) < currentIndex
  }
  return false
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value))
}

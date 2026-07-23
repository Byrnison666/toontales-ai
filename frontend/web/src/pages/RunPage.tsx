import { AnimatePresence, motion } from 'framer-motion'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  api,
  ApiError,
  getRunWebSocketUrl,
  type ProgressEvent,
  type RunSnapshot,
  type Stage,
} from '../api'
import { Celebration } from '../components/Celebration'
import { ErrorState } from '../components/ErrorState'
import { MagicButton } from '../components/MagicButton'
import { MagicLoader } from '../components/MagicLoader'
import { PageTransition } from '../components/PageTransition'
import { StageProgress } from '../components/StageProgress'
import { Toast } from '../components/Toast'
import { STAGES } from '../lib/progress'

function isProgressEvent(value: unknown, runId: string): value is ProgressEvent {
  if (typeof value !== 'object' || value === null) return false
  const event = value as Partial<ProgressEvent>
  return (
    event.run_id === runId &&
    typeof event.event_id === 'number' &&
    typeof event.stage === 'string' &&
    STAGES.includes(event.stage as Stage) &&
    typeof event.progress === 'number' &&
    typeof event.stage_index === 'number' &&
    typeof event.total_stages === 'number'
  )
}

function getRunError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) return 'Мы не нашли эту историю. Возможно, она была удалена или ссылка устарела.'
    if (error.status >= 500) return 'Мастерская временно недоступна. Попробуй обновить страницу.'
    if (error.message) return error.message
  }
  return 'Не удалось загрузить историю. Проверь соединение и попробуй ещё раз.'
}

function getFailureDetails(snapshot: RunSnapshot): string {
  const failedTask = snapshot.tasks.find((task) => task.status === 'failed' && task.error)
  if (!failedTask) return 'На одном из этапов магия не сложилась. Историю можно запустить ещё раз.'
  if (typeof failedTask.error === 'string') return failedTask.error
  if (typeof failedTask.error === 'object' && failedTask.error !== null) {
    const error = failedTask.error as Record<string, unknown>
    if (typeof error.message === 'string') return error.message
    if (typeof error.detail === 'string') return error.detail
  }
  return 'На одном из этапов магия не сложилась. Историю можно запустить ещё раз.'
}

export function RunPage(): JSX.Element {
  const { runId } = useParams<{ runId: string }>()
  const navigate = useNavigate()
  const [snapshot, setSnapshot] = useState<RunSnapshot | null>(null)
  const [progressEvent, setProgressEvent] = useState<ProgressEvent | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [realtimeConnected, setRealtimeConnected] = useState(false)
  const [connectionNotice, setConnectionNotice] = useState<string | null>(null)
  const socketRef = useRef<WebSocket | null>(null)
  const terminalRef = useRef(false)
  const mountedRef = useRef(true)
  const currentRunIdRef = useRef(runId)

  const refreshSnapshot = useCallback(async (): Promise<void> => {
    if (!runId) return
    const requestedRunId = runId
    try {
      const nextSnapshot = await api.getRun(runId)
      if (mountedRef.current && currentRunIdRef.current === requestedRunId) {
        setSnapshot(nextSnapshot)
        setError(null)
      }
    } catch (requestError) {
      if (mountedRef.current && currentRunIdRef.current === requestedRunId) {
        setError(getRunError(requestError))
      }
    } finally {
      if (mountedRef.current && currentRunIdRef.current === requestedRunId) setLoading(false)
    }
  }, [runId])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  useEffect(() => {
    currentRunIdRef.current = runId
  }, [runId])

  useEffect(() => {
    void refreshSnapshot()
  }, [refreshSnapshot])

  const finalRender = snapshot?.assets.find((asset) => asset.kind === 'final_render') ?? null
  const isTerminal =
    snapshot?.status === 'failed' ||
    snapshot?.status === 'canceled' ||
    (snapshot?.status === 'completed' && finalRender !== null)

  useEffect(() => {
    terminalRef.current = isTerminal
    if (isTerminal && socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.close(1000, 'Run finished')
    }
  }, [isTerminal])

  useEffect(() => {
    if (!runId || isTerminal) return undefined

    let stopped = false
    let reconnectTimeout: number | null = null
    let reconnectAttempts = 0

    const scheduleReconnect = (): void => {
      if (stopped || terminalRef.current) return
      reconnectAttempts += 1
      const delay = Math.min(10_000, 1_000 * 2 ** Math.min(reconnectAttempts - 1, 4))
      reconnectTimeout = window.setTimeout(() => void connect(), delay)
    }

    const connect = async (): Promise<void> => {
      try {
        const { ticket } = await api.createWsTicket(runId)
        if (stopped || terminalRef.current) return

        const socket = new WebSocket(getRunWebSocketUrl(runId, ticket))
        socketRef.current = socket
        socket.onopen = () => {
          if (stopped) return
          reconnectAttempts = 0
          setRealtimeConnected(true)
          setConnectionNotice(null)
        }
        socket.onmessage = (message) => {
          if (stopped) return
          try {
            const parsed: unknown = JSON.parse(String(message.data))
            if (!isProgressEvent(parsed, runId)) return
            setProgressEvent(parsed)

            const isLastStageUpdate =
              parsed.progress >= 100 &&
              (parsed.stage === 'composition' || parsed.stage_index >= parsed.total_stages - 1)
            if (isLastStageUpdate || parsed.status === 'failed') void refreshSnapshot()
          } catch {
            setConnectionNotice('Получено необычное обновление. Проверяем прогресс через API.')
          }
        }
        socket.onerror = () => socket.close()
        socket.onclose = (closeEvent) => {
          if (socketRef.current === socket) socketRef.current = null
          if (stopped) return
          setRealtimeConnected(false)
          if (terminalRef.current || closeEvent.code === 1000) return

          if (closeEvent.code === 4404) {
            setError('История для онлайн-обновлений не найдена.')
            return
          }
          if (closeEvent.code === 4429) {
            setConnectionNotice('Онлайн-обновлений слишком много — продолжаем следить в фоновом режиме.')
            return
          }
          setConnectionNotice('Связь со звёздами прервалась — переподключаемся, а пока обновляем прогресс в фоне.')
          scheduleReconnect()
        }
      } catch (ticketError) {
        if (stopped || terminalRef.current) return
        if (!(ticketError instanceof ApiError && ticketError.status === 401)) {
          setConnectionNotice('Онлайн-канал пока недоступен — обновляем прогресс в фоновом режиме.')
          scheduleReconnect()
        }
      }
    }

    void connect()
    return () => {
      stopped = true
      if (reconnectTimeout !== null) window.clearTimeout(reconnectTimeout)
      const socket = socketRef.current
      socketRef.current = null
      if (socket && socket.readyState < WebSocket.CLOSING) socket.close(1000, 'Page closed')
    }
  }, [runId, isTerminal, refreshSnapshot])

  useEffect(() => {
    if (!runId || realtimeConnected || isTerminal) return undefined
    const pollingId = window.setInterval(() => void refreshSnapshot(), 4_000)
    return () => window.clearInterval(pollingId)
  }, [runId, realtimeConnected, isTerminal, refreshSnapshot])

  const retryLoading = (): void => {
    setLoading(true)
    setError(null)
    void refreshSnapshot()
  }

  const downloadVideo = (): void => {
    if (!finalRender) return
    const anchor = document.createElement('a')
    anchor.href = finalRender.presigned_url
    anchor.download = `toontales-${runId ?? 'story'}.mp4`
    anchor.rel = 'noopener noreferrer'
    anchor.target = '_blank'
    anchor.click()
  }

  if (!runId) {
    return (
      <PageTransition className="mx-auto grid min-h-[70vh] max-w-7xl place-items-center px-4 py-12">
        <ErrorState message="В ссылке не хватает номера истории." actionLabel="К моим мультфильмам" onAction={() => navigate('/gallery')} />
      </PageTransition>
    )
  }

  if (loading && !snapshot) {
    return (
      <PageTransition className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <MagicLoader label="Ищем твою историю среди звёзд…" />
      </PageTransition>
    )
  }

  if (error && !snapshot) {
    return (
      <PageTransition className="mx-auto grid min-h-[70vh] max-w-7xl place-items-center px-4 py-12 sm:px-6 lg:px-8">
        <ErrorState message={error} actionLabel="Попробовать снова" onAction={retryLoading} />
      </PageTransition>
    )
  }

  if (!snapshot) {
    return (
      <PageTransition className="mx-auto grid min-h-[70vh] max-w-7xl place-items-center px-4 py-12">
        <ErrorState message="История пока не появилась. Попробуй открыть её ещё раз." actionLabel="Обновить" onAction={retryLoading} />
      </PageTransition>
    )
  }

  if (snapshot.status === 'failed' || snapshot.status === 'canceled') {
    return (
      <PageTransition className="mx-auto grid min-h-[75vh] max-w-7xl place-items-center px-4 py-12 sm:px-6 lg:px-8">
        <ErrorState
          title={snapshot.status === 'canceled' ? 'Создание истории остановлено' : 'Эта сказка просит второй дубль'}
          message={snapshot.status === 'canceled' ? 'Запуск был отменён. Историю можно отправить в мастерскую ещё раз.' : getFailureDetails(snapshot)}
          actionLabel="Попробовать снова"
          onAction={() => navigate('/create')}
        />
      </PageTransition>
    )
  }

  if (snapshot.status === 'completed' && finalRender) {
    return (
      <PageTransition className="relative mx-auto max-w-6xl px-4 py-12 sm:px-6 lg:px-8 lg:py-16">
        <Celebration />
        <motion.div
          initial={{ opacity: 0, y: 24, scale: 0.94 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ type: 'spring', stiffness: 100, damping: 18 }}
          className="relative text-center"
        >
          <motion.div
            initial={{ scale: 0, rotate: -30 }}
            animate={{ scale: 1, rotate: 0 }}
            transition={{ delay: 0.2, type: 'spring', stiffness: 180, damping: 12 }}
            className="mx-auto grid h-16 w-16 place-items-center rounded-full border border-amber-200/35 bg-amber-200/15 text-3xl shadow-[0_0_45px_rgba(251,191,36,0.28)]"
            aria-hidden="true"
          >
            ✓
          </motion.div>
          <h1 className="font-display mt-5 text-4xl font-bold text-white sm:text-6xl">
            Твой мультфильм <span className="text-gradient">готов!</span>
          </h1>
          <p className="mx-auto mt-4 max-w-2xl text-lg text-violet-200">Свет гаснет, занавес открывается — приятного просмотра.</p>
          <p className="mt-3 text-sm text-violet-300">
            Списано <span className="font-bold text-amber-100">{snapshot.total_price.toLocaleString('ru-RU')} ✦</span>
            {' '}— остаток резерва уже вернулся на баланс.
          </p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 30, scale: 0.96 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ delay: 0.35, type: 'spring', stiffness: 100, damping: 18 }}
          className="glass-card mt-10 overflow-hidden p-2 sm:p-3"
        >
          <video
            controls
            playsInline
            preload="metadata"
            src={finalRender.presigned_url}
            className="aspect-video w-full rounded-[1.25rem] bg-black object-contain shadow-2xl"
          >
            Твой браузер не поддерживает воспроизведение видео.
          </video>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5 }}
          className="mt-7 flex flex-col justify-center gap-3 sm:flex-row"
        >
          <MagicButton variant="secondary" onClick={downloadVideo}>
            Скачать мультфильм ↓
          </MagicButton>
          <MagicButton className="group" onClick={() => navigate('/create')}>
            Создать ещё одну сказку ✨
          </MagicButton>
        </motion.div>
      </PageTransition>
    )
  }

  return (
    <PageTransition className="mx-auto max-w-7xl px-4 py-10 sm:px-6 lg:px-8 lg:py-14">
      <div className="mb-8 text-center">
        <motion.p
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-sm font-extrabold uppercase tracking-[0.24em] text-cyan-200"
        >
          Волшебная мастерская работает
        </motion.p>
        <h1 className="font-display mt-2 text-3xl font-bold text-white sm:text-4xl">Твоя история оживает</h1>
      </div>
      <StageProgress snapshot={snapshot} progressEvent={progressEvent} realtimeConnected={realtimeConnected} />
      <AnimatePresence>
        {connectionNotice ? (
          <motion.p
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="mx-auto mt-4 max-w-2xl rounded-2xl border border-amber-300/15 bg-amber-300/[0.06] px-4 py-3 text-center text-sm text-amber-100"
            role="status"
          >
            {connectionNotice}
          </motion.p>
        ) : null}
      </AnimatePresence>
      <Toast message={error} tone="error" onClose={() => setError(null)} />
    </PageTransition>
  )
}

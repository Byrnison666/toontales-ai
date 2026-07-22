import { describe, expect, test } from 'bun:test'
import type { ProgressEvent, RunSnapshot } from '../src/api'
import { calculateOverallProgress, getCurrentStage } from '../src/lib/progress'

const snapshot: RunSnapshot = {
  run_id: 'run-1',
  project_id: 'project-1',
  status: 'running',
  trigger: 'user',
  created_at: '2026-01-01T00:00:00Z',
  total_real_cost_usd: null,
  scenes: [],
  tasks: [],
  assets: [],
}

const event: ProgressEvent = {
  event_id: 1,
  project_id: 'project-1',
  run_id: 'run-1',
  task_id: 'task-1',
  stage: 'image_generation',
  stage_index: 1,
  total_stages: 6,
  status: 'running',
  progress: 50,
  message: 'Drawing',
  artifact_ids: [],
  error: null,
  timestamp: '2026-01-01T00:00:01Z',
}

describe('generation progress', () => {
  test('combines zero-based stage position with stage progress', () => {
    expect(calculateOverallProgress(snapshot, event)).toBe(25)
    expect(getCurrentStage(snapshot, event)).toBe('image_generation')
  })

  test('clamps malformed progress and reserves 100% for completed runs', () => {
    expect(calculateOverallProgress(snapshot, { ...event, stage_index: 99, progress: 500 })).toBe(99)
    expect(calculateOverallProgress({ ...snapshot, status: 'completed' }, null)).toBe(100)
  })
})

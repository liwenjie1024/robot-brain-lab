import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { trialSeries } from '@shared/test/fixtures'
import { FileTrialStore, NO_TRIAL_STORE } from './trialStore'

let root: string | null = null

afterEach(async () => {
  if (root) {
    await rm(root, { recursive: true, force: true })
    root = null
  }
})

describe('FileTrialStore', () => {
  it('시험 한 묶음을 시작한 때·장면 이름의 JSON 파일로 남기고, 저장소 기준 경로를 돌려준다', async () => {
    root = await mkdtemp(join(tmpdir(), 'trials-'))
    const store = new FileTrialStore(join(root, 'results', 'trials'), root)
    const series = trialSeries({ startedAt: '2026-11-06T12:00:00.123Z' })

    const path = await store.save(series)

    expect(path).toBe('results/trials/2026-11-06T12-00-00-123Z-skirmish.json')
    expect(JSON.parse(await readFile(join(root, path), 'utf8'))).toEqual(series)
  })

  it('남기지 않는 저장소는 경로 없이 끝난다', async () => {
    expect(await NO_TRIAL_STORE.save(trialSeries())).toBeNull()
  })
})

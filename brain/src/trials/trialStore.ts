import { mkdir, writeFile } from 'node:fs/promises'
import { join, relative } from 'node:path'
import type { TrialSeries } from '@shared/brain/generated/status'

/** 끝난 시험을 남기는 곳. 남긴 곳(사람이 읽는 경로)을 돌려준다 (남기지 않으면 null). */
export interface TrialStore {
  save(series: TrialSeries): Promise<string | null>
}

/** 남기지 않는다 (시험·두뇌만 따로 쓸 때) */
export const NO_TRIAL_STORE: TrialStore = { save: async () => null }

/** 시험 한 묶음을 JSON 파일 하나로 남긴다. 이름은 시작한 때와 장면이라 같은 시험을 여러 번 해도 겹치지 않는다. */
export class FileTrialStore implements TrialStore {
  constructor(
    private readonly directory: string,
    /** 돌려줄 경로의 기준 (저장소 맨 위) */
    private readonly displayRoot: string,
  ) {}

  async save(series: TrialSeries): Promise<string> {
    await mkdir(this.directory, { recursive: true })
    const path = join(this.directory, `${series.startedAt.replace(/[:.]/g, '-')}-${series.scenario}.json`)
    await writeFile(path, `${JSON.stringify(series, null, 2)}\n`)
    return relative(this.displayRoot, path).split('\\').join('/')
  }
}

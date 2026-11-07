import { fileURLToPath } from 'node:url'

/** 두뇌를 띄울 때 고를 수 있는 값 (환경 변수). */

/** 몸(시뮬레이터) 주소. 몸은 Docker에서 돈다 (compose.yaml). */
export const SIM_BASE_URL = process.env.SIM_URL ?? 'http://localhost:8765'

export const BODY_LINKS = ['ws', 'ros'] as const
export type BodyLinkKind = (typeof BODY_LINKS)[number]

/**
 * 몸에 붙는 길: ws는 몸의 WebSocket에 바로, ros는 ROS 2(rosbridge → BL-01 드라이버 노드)를 거쳐.
 * 잘못 쓴 값은 모르는 척 넘기지 않고 띄울 때 멈춘다 (다른 길로 잰 줄 모르게).
 */
export function bodyLinkKind(value: string | undefined): BodyLinkKind {
  const kind = value ?? 'ws'
  if (!(BODY_LINKS as readonly string[]).includes(kind)) {
    throw new Error(`BODY_LINK는 ${BODY_LINKS.join(' 또는 ')}만 쓸 수 있습니다 (받은 값: ${kind})`)
  }
  return kind as BodyLinkKind
}

export const BODY_LINK = bodyLinkKind(process.env.BODY_LINK)
/** ROS 2로 붙을 때 rosbridge 주소 (compose.yaml의 ros 서비스) */
export const ROSBRIDGE_URL = process.env.ROSBRIDGE_URL ?? 'ws://localhost:9090'
/** 화면이 두뇌에 붙는 WebSocket 포트 */
export const BRAIN_PORT = Number(process.env.BRAIN_PORT ?? 8766)
/** 화면에 상태를 보내는 간격 (판단 기록은 생길 때마다 바로) */
export const STATUS_INTERVAL_MS = 200
/** 몸에 처음 붙지 못했을 때 다시 해 보는 간격 */
export const SIM_RETRY_MS = 2000
/** 느린 뇌가 쓰는 언어 모델 서버(Ollama)와 모델 */
export const OLLAMA_URL = process.env.OLLAMA_URL ?? 'http://localhost:11434'
export const PLANNER_MODEL = process.env.BRAIN_MODEL ?? 'qwen2.5:7b'
/** 언어 모델을 쓸 수 있는지 다시 보는 간격 (Ollama를 나중에 띄워도 붙게) */
export const PLANNER_CHECK_MS = 15_000
/** 저장소 맨 위 (brain/src에서 두 단계 위) */
export const REPO_ROOT = fileURLToPath(new URL('../../', import.meta.url))
/** 끝난 시험을 JSON으로 남기는 곳 (git에 넣지 않는다) */
export const TRIAL_RESULTS_DIR = process.env.TRIAL_RESULTS_DIR ?? fileURLToPath(new URL('../../results/trials', import.meta.url))

/** 두뇌를 띄울 때 고를 수 있는 값 (환경 변수). */

/** 몸(시뮬레이터) 주소. 몸은 Docker에서 돈다 (compose.yaml). */
export const SIM_BASE_URL = process.env.SIM_URL ?? 'http://localhost:8765'
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

/** 두뇌를 띄울 때 고를 수 있는 값 (환경 변수). */

/** 몸(시뮬레이터) 주소. 몸은 Docker에서 돈다 (compose.yaml). */
export const SIM_BASE_URL = process.env.SIM_URL ?? 'http://localhost:8765'
/** 화면이 두뇌에 붙는 WebSocket 포트 */
export const BRAIN_PORT = Number(process.env.BRAIN_PORT ?? 8766)
/** 화면에 상태를 보내는 간격 (판단 기록은 생길 때마다 바로) */
export const STATUS_INTERVAL_MS = 200
/** 몸에 처음 붙지 못했을 때 다시 해 보는 간격 */
export const SIM_RETRY_MS = 2000

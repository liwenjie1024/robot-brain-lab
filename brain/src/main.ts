import { RosBodyClient } from '@shared/ros/rosBodyClient'
import type { BodyLink } from '@shared/sim/bodyLink'
import { SimClient } from '@shared/sim/simClient'
import { Brain } from './brain'
import {
  BODY_LINK,
  BRAIN_PORT,
  OLLAMA_URL,
  PLANNER_CHECK_MS,
  PLANNER_MODEL,
  REPO_ROOT,
  ROSBRIDGE_URL,
  SIM_BASE_URL,
  SIM_RETRY_MS,
  TRIAL_RESULTS_DIR,
} from './config'
import { BrainServer } from './server'
import { OllamaModel } from './system2/model'
import { FileTrialStore } from './trials/trialStore'

/**
 * 두뇌를 띄운다: 몸(시뮬레이터)에 붙어 상태를 받고, 느린 뇌의 언어 모델(Ollama)을 찾고, 화면이 붙을 서버를 연다.
 *   npm run brain   (저장소 맨 위)
 *   BODY_LINK=ros npm run brain   (몸에 ROS 2로: docker compose up -d ros)
 */
const client: BodyLink = BODY_LINK === 'ros' ? new RosBodyClient({ url: ROSBRIDGE_URL }) : new SimClient({ baseUrl: SIM_BASE_URL })
const bodyAddress = BODY_LINK === 'ros' ? `ROS 2 ${ROSBRIDGE_URL}` : SIM_BASE_URL
const brain = new Brain(client, new OllamaModel(PLANNER_MODEL, OLLAMA_URL), undefined, new FileTrialStore(TRIAL_RESULTS_DIR, REPO_ROOT))
let targets = new Set<string>()

client.on('scene', (scene) => {
  brain.setScene(scene)
  targets = new Set(scene.units.filter((unit) => unit.kind === 'drone').map((unit) => unit.id))
})
client.on('state', (state) => brain.onState(state))
client.on('combat', (event) => brain.onCombat(event))
client.on('phase', (phase, detail) => {
  brain.setSimConnected(phase === 'open')
  if (phase === 'failed') {
    console.warn(`[두뇌] ${detail ?? '몸에 붙지 못했습니다'} ${SIM_RETRY_MS / 1000}초 뒤 다시 해 봅니다.`)
    setTimeout(() => client.retry(), SIM_RETRY_MS)
  } else {
    console.info(`[두뇌] 몸 연결: ${phase}${detail ? ` (${detail})` : ''}`)
  }
})
client.on('invalidMessage', (reason) => console.warn(`[두뇌] 몸이 규약과 다른 메시지를 보냄: ${reason}`))

const server = new BrainServer(brain, () => targets)
const port = await server.start(BRAIN_PORT)
console.info(`[두뇌] 화면이 붙을 곳: ws://localhost:${port} (몸: ${bodyAddress})`)
void client.connect()

const checkPlanner = () =>
  void brain.system2.refreshPlanner().then((available) => {
    console.info(`[두뇌] 언어 모델 ${PLANNER_MODEL} (${OLLAMA_URL}): ${available ? '쓸 수 있음' : '쓸 수 없음 (짧은 명령만)'}`)
  })
checkPlanner()
const plannerTimer = setInterval(() => void brain.system2.refreshPlanner(), PLANNER_CHECK_MS)

for (const signal of ['SIGINT', 'SIGTERM'] as const) {
  process.on(signal, () => {
    clearInterval(plannerTimer)
    brain.stopTrials()
    brain.cancelPlan()
    client.close()
    void server.close().then(() => process.exit(0))
  })
}

import { SimClient } from '@shared/sim/simClient'
import { BRAIN_PORT, SIM_BASE_URL, SIM_RETRY_MS } from './config'
import { BrainServer } from './server'
import { System1 } from './system1'

/**
 * 두뇌를 띄운다: 몸(시뮬레이터)에 붙어 상태를 받고, 화면이 붙을 서버를 연다.
 *   npm run brain   (저장소 맨 위)
 */
const client = new SimClient({ baseUrl: SIM_BASE_URL })
const system1 = new System1(client)
let targets = new Set<string>()

client.on('scene', (scene) => {
  system1.setScene(scene)
  targets = new Set(scene.units.filter((unit) => unit.kind === 'drone').map((unit) => unit.id))
})
client.on('state', (state) => system1.onState(state))
client.on('combat', (event) => system1.onCombat(event))
client.on('phase', (phase, detail) => {
  system1.setSimConnected(phase === 'open')
  if (phase === 'failed') {
    console.warn(`[두뇌] ${detail ?? '몸에 붙지 못했습니다'} ${SIM_RETRY_MS / 1000}초 뒤 다시 해 봅니다.`)
    setTimeout(() => client.retry(), SIM_RETRY_MS)
  } else {
    console.info(`[두뇌] 몸 연결: ${phase}`)
  }
})
client.on('invalidMessage', (reason) => console.warn(`[두뇌] 몸이 규약과 다른 메시지를 보냄: ${reason}`))

const server = new BrainServer(system1, () => targets)
const port = await server.start(BRAIN_PORT)
console.info(`[두뇌] 화면이 붙을 곳: ws://localhost:${port} (몸: ${SIM_BASE_URL})`)
void client.connect()

for (const signal of ['SIGINT', 'SIGTERM'] as const) {
  process.on(signal, () => {
    client.close()
    void server.close().then(() => process.exit(0))
  })
}

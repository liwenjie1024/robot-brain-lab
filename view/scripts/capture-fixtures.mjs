// 从正在跑的仿真里抓几份真实的消息，给网页的测试当样本（src/test/fixtures）。
// 改了规约、改了身体以后重新抓：先 docker compose up -d sim，再 npm run fixtures。
// 抓的时候会换身体、重新开始；有人正在网页上看的话，他那边也会跟着变。
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const SIM = process.env.NOVA_SIM ?? 'http://127.0.0.1:8870'
const target = join(dirname(fileURLToPath(import.meta.url)), '..', 'src', 'test', 'fixtures')
// 站稳以后再抓：这时候的数是有意义的（地面托着体重，关节出着顶住重力的力矩）。
const SETTLE_S = 1.5
const TIMEOUT_MS = 15000

/** 连上仿真。返回发命令、等消息的两个函数。 */
async function connect() {
  const socket = new WebSocket(SIM.replace(/^http/, 'ws') + '/ws')
  const waiting = []
  socket.addEventListener('message', (event) => {
    const message = JSON.parse(event.data)
    for (const waiter of [...waiting]) {
      if (waiter.matches(message)) {
        waiting.splice(waiting.indexOf(waiter), 1)
        waiter.done(message)
      }
    }
  })
  await new Promise((done, fail) => {
    socket.addEventListener('open', done)
    socket.addEventListener('error', () => fail(new Error(`连不上仿真（${SIM}）。先运行 docker compose up -d sim`)))
  })
  const next = (matches) =>
    new Promise((done, fail) => {
      waiting.push({ matches, done })
      setTimeout(() => fail(new Error('等仿真的消息等得太久了')), TIMEOUT_MS)
    })
  let id = 0
  const send = async (command) => {
    id += 1
    socket.send(JSON.stringify({ ...command, id }))
    const answer = await next((message) => message.type === 'ack' && message.id === id)
    if (!answer.ok) throw new Error(`仿真没有照做：${answer.reason}`)
  }
  return { socket, next, send }
}

const { socket, next, send } = await connect()
await mkdir(target, { recursive: true })
for (const body of ['nova', 'g1']) {
  await send({ type: 'body', body })
  const scene = await (await fetch(`${SIM}/scene`)).json()
  if (scene.body !== body) throw new Error(`要的是 ${body}，仿真给的是 ${scene.body}`)
  const state = await next((message) => message.type === 'state' && message.body === body && message.time_s >= SETTLE_S)
  await writeFile(join(target, `${body}.scene.json`), JSON.stringify(scene) + '\n')
  await writeFile(join(target, `${body}.state.json`), JSON.stringify(state) + '\n')
  console.log(`${scene.name}：样子和 ${state.time_s} 秒时的状态抓好了`)
}
await send({ type: 'body', body: 'nova' })
socket.close()

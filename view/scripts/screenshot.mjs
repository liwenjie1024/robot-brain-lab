// 给网页拍一张清楚的截图（开发时检查画面用）。用这台电脑上的 Edge，不显示窗口，用一份临时的配置。
// 网页和仿真要先开着（.\scripts\view.ps1 -NoBrowser）。
// 用法：node scripts/screenshot.mjs <输出.png> [--body nova|g1] [--width 1440] [--height 900] [--wait 4000] [--url 网址]
import { spawn } from 'node:child_process'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { parseArgs } from 'node:util'

const BROWSER = process.env.NOVA_BROWSER ?? 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const SIM = process.env.NOVA_SIM ?? 'http://127.0.0.1:8870'
const DEBUG_PORT = 9333
const START_TIMEOUT_MS = 15000
const sleep = (ms) => new Promise((done) => setTimeout(done, ms))

const { values, positionals } = parseArgs({
  allowPositionals: true,
  options: {
    body: { type: 'string' },
    width: { type: 'string', default: '1440' },
    height: { type: 'string', default: '900' },
    wait: { type: 'string', default: '4000' },
    url: { type: 'string', default: 'http://127.0.0.1:5280/' },
  },
})
const output = positionals[0]
if (!output) throw new Error('要给出截图存到哪里：node scripts/screenshot.mjs <输出.png>')

/** 让仿真换一个身体放上测试台。 */
async function selectBody(body) {
  const socket = new WebSocket(SIM.replace(/^http/, 'ws') + '/ws')
  await new Promise((done, fail) => {
    socket.addEventListener('open', done)
    socket.addEventListener('error', () => fail(new Error(`连不上仿真（${SIM}）`)))
  })
  const answer = new Promise((done) => {
    socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data)
      if (message.type === 'ack') done(message)
    })
  })
  socket.send(JSON.stringify({ type: 'body', id: 1, body }))
  const ack = await answer
  socket.close()
  if (!ack.ok) throw new Error(`仿真没有换身体：${ack.reason}`)
}

/** 给浏览器发一条调试命令，等它答复。 */
function command(socket, id, method, params = {}) {
  return new Promise((done, fail) => {
    const listen = (event) => {
      const message = JSON.parse(event.data)
      if (message.id !== id) return
      socket.removeEventListener('message', listen)
      if (message.error) fail(new Error(`${method}：${message.error.message}`))
      else done(message.result)
    }
    socket.addEventListener('message', listen)
    socket.send(JSON.stringify({ id, method, params }))
  })
}

async function waitForBrowser() {
  const deadline = Date.now() + START_TIMEOUT_MS
  while (Date.now() < deadline) {
    try {
      return await (await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/version`)).json()
    } catch {
      await sleep(200)
    }
  }
  throw new Error('浏览器没有启动起来')
}

if (values.body) await selectBody(values.body)
const profile = await mkdtemp(join(tmpdir(), 'nova-screenshot-'))
const browser = spawn(
  BROWSER,
  [
    '--headless=new',
    `--remote-debugging-port=${DEBUG_PORT}`,
    `--user-data-dir=${profile}`,
    '--no-first-run',
    '--hide-scrollbars',
    `--window-size=${values.width},${values.height}`,
    'about:blank',
  ],
  { stdio: 'ignore' },
)
try {
  const version = await waitForBrowser()
  const page = await (await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/new?${values.url}`, { method: 'PUT' })).json()
  const socket = new WebSocket(page.webSocketDebuggerUrl)
  await new Promise((done) => socket.addEventListener('open', done))
  await command(socket, 1, 'Emulation.setDeviceMetricsOverride', {
    width: Number(values.width),
    height: Number(values.height),
    deviceScaleFactor: 1,
    mobile: false,
  })
  // 等网页连上仿真、拿到身体的样子、站稳，再拍。
  await sleep(Number(values.wait))
  const shot = await command(socket, 2, 'Page.captureScreenshot', { format: 'png' })
  await writeFile(output, Buffer.from(shot.data, 'base64'))
  socket.close()
  const whole = new WebSocket(version.webSocketDebuggerUrl)
  await new Promise((done) => whole.addEventListener('open', done))
  await command(whole, 3, 'Browser.close').catch(() => undefined)
  console.log(`截图存到了 ${output}`)
} finally {
  browser.kill()
  await sleep(500)
  await rm(profile, { recursive: true, force: true }).catch(() => undefined)
}

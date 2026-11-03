import { afterEach, describe, expect, it } from 'vitest'
import { WebSocket } from 'ws'
import type { BrainMessage } from '@shared/brain/generated/status'
import { BrainServer } from './server'
import { System1 } from './system1'
import { RecordingSender } from './testing'

let server: BrainServer | null = null

async function start() {
  const system1 = new System1(new RecordingSender())
  server = new BrainServer(system1, () => new Set(['drone-1']))
  const port = await server.start(0)
  const socket = new WebSocket(`ws://127.0.0.1:${port}`)
  const received: BrainMessage[] = []
  socket.on('message', (data) => received.push(JSON.parse(data.toString())))
  await new Promise((resolve) => socket.once('open', resolve))
  return { socket, received, system1 }
}

async function until(condition: () => boolean): Promise<void> {
  for (let tries = 0; tries < 100 && !condition(); tries++) {
    await new Promise((resolve) => setTimeout(resolve, 10))
  }
  expect(condition()).toBe(true)
}

afterEach(async () => {
  await server?.close()
  server = null
})

describe('BrainServer', () => {
  it('붙으면 지금 상태를 바로 보낸다', async () => {
    const { received, socket } = await start()

    await until(() => received.some((message) => message.type === 'brainStatus'))

    expect(received[0]).toMatchObject({ type: 'brainStatus', autonomy: false, skill: { name: 'idle' } })
    socket.close()
  })

  it('지시를 받아 답하고, 바뀐 상태와 판단 기록을 모든 화면에 보낸다', async () => {
    const { received, socket } = await start()

    socket.send(JSON.stringify({ type: 'setSkill', id: 'k1', skill: 'engage', evasion: 'both' }))
    await until(() => received.some((message) => message.type === 'controlResult'))
    await until(() => received.some((message) => message.type === 'decision'))

    expect(received.find((message) => message.type === 'controlResult')).toEqual({ type: 'controlResult', id: 'k1', accepted: true })
    expect(received.filter((message) => message.type === 'brainStatus').at(-1)).toMatchObject({ skill: { name: 'engage', evasion: 'both' } })
    socket.close()
  })

  it('실패: 글자가 아닌 메시지와 규약에 맞지 않는 지시는 까닭을 붙여 거절한다', async () => {
    const { received, socket } = await start()

    socket.send(Buffer.from([1, 2, 3]))
    socket.send(JSON.stringify({ type: 'setAutonomy' }))
    await until(() => received.filter((message) => message.type === 'controlResult').length === 2)

    const results = received.filter((message) => message.type === 'controlResult')
    expect(results.map((result) => result.accepted)).toEqual([false, false])
    expect(results[0]?.reason).toContain('글자(JSON)')
    socket.close()
  })
})

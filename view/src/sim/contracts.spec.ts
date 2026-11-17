import { describe, expect, it } from 'vitest'
import g1SceneJson from '@/test/fixtures/g1.scene.json'
import novaSceneJson from '@/test/fixtures/nova.scene.json'
import novaStateJson from '@/test/fixtures/nova.state.json'
import { ContractError, readMessage, readScene, readSceneText } from '@/sim/contracts'

describe('身体的样子', () => {
  it('真的仿真给的两个身体的样子都读得懂', () => {
    expect(readScene(novaSceneJson).name).toBe('Nova（核心版）')
    expect(readScene(g1SceneJson).name).toBe('Unitree G1')
  })

  it.each([
    ['少了一项', (scene: Record<string, unknown>) => delete scene.joints],
    ['多了一项规约里没有的', (scene: Record<string, unknown>) => (scene.extra = 1)],
    ['质量不是正数', (scene: Record<string, unknown>) => (scene.mass_kg = 0)],
    ['只有一只脚', (scene: Record<string, unknown>) => (scene.feet = (scene.feet as unknown[]).slice(0, 1))],
    ['形状的种类不认识', (scene: Record<string, unknown>) => ((scene.shapes as { kind: string }[])[0]!.kind = 'cone')],
    ['颜色超出 0~1', (scene: Record<string, unknown>) => ((scene.shapes as { color: number[] }[])[0]!.color[0] = 2)],
  ])('%s：不合规约，拒绝', (_name, breakIt) => {
    const scene = structuredClone(novaSceneJson) as Record<string, unknown>
    breakIt(scene)
    expect(() => readScene(scene)).toThrow(ContractError)
    expect(() => readScene(scene)).toThrow('身体的样子读不懂')
  })

  it('不是对象的东西：拒绝', () => {
    for (const value of [null, 'nova', 3, []]) expect(() => readScene(value)).toThrow(ContractError)
  })

  it('从原文读：读得懂真的样子；不是 JSON、不合规约都拒绝，说清楚', () => {
    expect(readSceneText(JSON.stringify(novaSceneJson)).name).toBe('Nova（核心版）')
    expect(() => readSceneText('{"body":')).toThrow('身体的样子不是 JSON')
    expect(() => readSceneText('')).toThrow(ContractError)
    expect(() => readSceneText('{"body":"nova"}')).toThrow('身体的样子读不懂')
  })
})

describe('仿真发来的消息', () => {
  it('招呼、状态、答复都读得懂', () => {
    expect(readMessage('{"type":"hello","body":"nova","episode":0}')).toEqual({ type: 'hello', body: 'nova', episode: 0 })
    expect(readMessage(JSON.stringify(novaStateJson)).type).toBe('state')
    expect(readMessage('{"type":"ack","id":3,"ok":false,"reason":"上一下还没推完"}')).toMatchObject({ id: 3, ok: false })
    expect(readMessage('{"type":"ack","id":null,"ok":false,"reason":"命令读不出来"}')).toMatchObject({ id: null })
  })

  it('不是 JSON：拒绝，说清楚', () => {
    expect(() => readMessage('{ not json')).toThrow('仿真发来的消息不是 JSON')
  })

  it.each([
    ['不认识的种类', '{"type":"dance"}'],
    ['招呼里少了第几回', '{"type":"hello","body":"nova"}'],
    ['答复里编号是文字', '{"type":"ack","id":"3","ok":true,"reason":""}'],
    ['是一张表', '[1,2]'],
    ['是 null', 'null'],
  ])('%s：不合规约，拒绝', (_name, text) => {
    expect(() => readMessage(text)).toThrow(ContractError)
    expect(() => readMessage(text)).toThrow('仿真发来的消息读不懂')
  })

  it.each([
    ['少了一项', (state: Record<string, unknown>) => delete state.fallen],
    ['时间是负的', (state: Record<string, unknown>) => (state.time_s = -1)],
    ['重心只有两个数', (state: Record<string, unknown>) => (state.center_of_mass = [0, 0])],
    ['只有一只脚的力', (state: Record<string, unknown>) => (state.feet = (state.feet as unknown[]).slice(0, 1))],
    ['关节的角度里混进了文字', (state: Record<string, unknown>) => ((state.joints as { angles_rad: unknown[] }).angles_rad[0] = 'a')],
  ])('状态%s：拒绝', (_name, breakIt) => {
    const state = structuredClone(novaStateJson) as Record<string, unknown>
    breakIt(state)
    expect(() => readMessage(JSON.stringify(state))).toThrow(ContractError)
  })

  it('压力中心和推的那一下可以是空的（没有踩在地上、没有在推）', () => {
    const state = structuredClone(novaStateJson) as Record<string, unknown>
    state.pressure_center = null
    state.push = null
    expect(readMessage(JSON.stringify(state)).type).toBe('state')
  })
})

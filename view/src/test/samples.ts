// 测试用的样本：从真的仿真里抓下来的"样子"和"状态"（scripts/capture-fixtures.mjs），两个身体各一份。
import g1SceneJson from './fixtures/g1.scene.json'
import g1StateJson from './fixtures/g1.state.json'
import novaSceneJson from './fixtures/nova.scene.json'
import novaStateJson from './fixtures/nova.state.json'
import { readMessage, readScene } from '@/sim/contracts'
import type { State } from '@/generated/message'
import type { Scene } from '@/generated/scene'

function asState(value: unknown): State {
  const message = readMessage(JSON.stringify(value))
  if (message.type !== 'state') throw new Error('样本不是一条状态')
  return message
}

/** 每次拿到的都是新的一份，测试里改它不会影响别的测试。 */
export const novaScene = (): Scene => readScene(structuredClone(novaSceneJson))
export const g1Scene = (): Scene => readScene(structuredClone(g1SceneJson))
export const novaState = (): State => asState(novaStateJson)
export const g1State = (): State => asState(g1StateJson)

/** 一个最小的网格：一个三角形。 */
export function triangleMeshBytes(): ArrayBuffer {
  const buffer = new ArrayBuffer(8 + 9 * 4 + 3 * 4)
  const view = new DataView(buffer)
  view.setUint32(0, 3, true)
  view.setUint32(4, 1, true)
  const points = [0, 0, 0, 1, 0, 0, 0, 1, 0]
  points.forEach((value, index) => view.setFloat32(8 + 4 * index, value, true))
  const corners = [0, 1, 2]
  corners.forEach((value, index) => view.setUint32(8 + 36 + 4 * index, value, true))
  return buffer
}

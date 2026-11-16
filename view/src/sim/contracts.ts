// 仿真发来的东西是外面来的输入：在这里照规约检查，里面的代码只用检查过的。
// 规约只写在 contracts/sim/*.schema.json 这一处，仿真那边也用同一份文件检查。
import Ajv2020 from 'ajv/dist/2020'
import type { ValidateFunction } from 'ajv'
import messageSchema from '../../../contracts/sim/message.schema.json'
import sceneSchema from '../../../contracts/sim/scene.schema.json'
import type { Message } from '@/generated/message'
import type { Scene } from '@/generated/scene'

/** 收到的东西不合规约。多半是网页和仿真不是同一个版本。 */
export class ContractError extends Error {}

const ajv = new Ajv2020()
const checkScene = ajv.compile<Scene>(sceneSchema)
const checkMessage = ajv.compile<Message>(messageSchema)

function firstProblem(check: ValidateFunction): string {
  const error = check.errors?.[0]
  if (!error) return '不合规约'
  return `${error.instancePath || '最外面'}：${error.message ?? '不合规约'}`
}

/** 检查仿真给的"身体的样子"。不合规约就报错。 */
export function readScene(value: unknown): Scene {
  if (!checkScene(value)) throw new ContractError(`身体的样子读不懂（${firstProblem(checkScene)}）`)
  return value
}

/** 把仿真发来的一条消息读出来、检查一遍。不是 JSON、不合规约都报错。 */
export function readMessage(text: string): Message {
  let value: unknown
  try {
    value = JSON.parse(text)
  } catch {
    throw new ContractError('仿真发来的消息不是 JSON')
  }
  if (!checkMessage(value)) throw new ContractError(`仿真发来的消息读不懂（${firstProblem(checkMessage)}）`)
  return value
}

// 这个文件是照 contracts/sim/command.schema.json 生成的。不要手改：改规约，再运行 npm run contracts。

/**
 * 网页发给仿真的命令。每条都带一个编号，仿真做完以后按编号答复。范围以外的值不改成范围里的，直接拒绝。
 */
export type Command = Reset | Pause | Resume | SetControl | PushBody | SelectBody
/**
 * 命令的编号，网页自己编
 */
export type Id = number

/**
 * 重新开始：回到站姿，时间归零
 */
export interface Reset {
  type: 'reset'
  id: Id
}
/**
 * 暂停
 */
export interface Pause {
  type: 'pause'
  id: Id
}
/**
 * 继续
 */
export interface Resume {
  type: 'resume'
  id: Id
}
/**
 * 让驱动器出力（顶住站姿），或者松开
 */
export interface SetControl {
  type: 'control'
  id: Id
  on: boolean
}
/**
 * 在胸上推一下，推 0.5 秒
 */
export interface PushBody {
  type: 'push'
  id: Id
  /**
   * 往哪边推
   */
  direction: 'forward' | 'backward' | 'left' | 'right'
  /**
   * 力是体重的多少倍。最多一半
   */
  share: number
}
/**
 * 换一个身体放上测试台
 */
export interface SelectBody {
  type: 'body'
  id: Id
  /**
   * Scene 的 choices 里的记号
   */
  body: string
}

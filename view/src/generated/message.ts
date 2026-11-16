// 这个文件是照 contracts/sim/message.schema.json 生成的。不要手改：改规约，再运行 npm run contracts。

/**
 * 仿真发给网页的消息：刚连上时的招呼、不停发来的状态、对命令的答复。
 */
export type Message = Hello | State | Ack
/**
 * 三个数：x 朝前、y 朝左、z 朝上
 *
 * @minItems 3
 * @maxItems 3
 */
export type Vector = [number, number, number]

/**
 * 刚连上时发一次：现在测试台上是哪个身体
 */
export interface Hello {
  type: 'hello'
  body: string
  episode: number
}
/**
 * 这一刻的状态。位置、力都是世界坐标（地面是 z = 0）
 */
export interface State {
  type: 'state'
  /**
   * 哪个身体。和网页手里的 Scene 不一样时，网页要重新拿 Scene
   */
  body: string
  /**
   * 第几回。每次重新开始、换身体都加 1，网页靠它认出"这是新的一回"
   */
  episode: number
  /**
   * 这一回里仿真过了多久
   */
  time_s: number
  /**
   * 仿真在走，还是暂停着
   */
  running: boolean
  /**
   * 驱动器在出力，还是松开了
   */
  controlled: boolean
  /**
   * 这一回里倒过没有
   */
  fallen: boolean
  /**
   * 仿真是实时的多少倍。1 就是和钟一样快
   */
  speed: number
  /**
   * 仿真出了问题时说是什么；没有问题是 null
   */
  problem: string | null
  /**
   * 每一段的位置，连着排：x、y、z、x、y、z……顺序和 Scene 的 links 一样
   */
  link_positions: number[]
  /**
   * 每一段的姿态，连着排：w、x、y、z……顺序和 Scene 的 links 一样
   */
  link_orientations: number[]
  joints: JointReadings
  imus: ImuReading[]
  forces: ForceReading[]
  /**
   * 每一处受到的接触力（牛顿）
   */
  touches: Vector[]
  /**
   * 地面托着每只脚的力。这是从仿真里直接量的，不是身体的传感器读的
   *
   * @minItems 2
   * @maxItems 2
   */
  feet: [FootSupport, FootSupport]
  /**
   * 地面一共托着多大的力
   */
  support_n: number
  /**
   * 压力中心。没有东西碰着地面时是 null
   */
  pressure_center: Vector | null
  center_of_mass: Vector
  /**
   * 骨盆歪了多少度
   */
  tilt_deg: number
  pelvis_height_m: number
  /**
   * 正在推的那一下。没有在推是 null
   */
  push: Push | null
}
/**
 * 每个关节的读数，顺序和 Scene 的 joints 一样
 */
export interface JointReadings {
  angles_rad: number[]
  speeds_rad_s: number[]
  /**
   * 驱动器给关节的力矩
   */
  torques_nm: number[]
}
/**
 * acceleration：m/s²。站着不动时是朝上的 9.81；angular_velocity：rad/s
 */
export interface ImuReading {
  acceleration: Vector
  angular_velocity: Vector
}
/**
 * force：牛顿，传感器自己的坐标；moment：牛·米
 */
export interface ForceReading {
  force: Vector
  moment: Vector
}
export interface FootSupport {
  support_n: number
  /**
   * 这只脚没有踩在地上时是 null
   */
  pressure_center: Vector | null
}
export interface Push {
  force_n: Vector
  /**
   * 还要推多久
   */
  remaining_s: number
}
/**
 * 对一条命令的答复。先做完命令再答复，所以答复以后的状态已经是做完以后的
 */
export interface Ack {
  type: 'ack'
  /**
   * 命令的编号。命令坏到读不出编号时是 null
   */
  id: number | null
  ok: boolean
  /**
   * 没有照做的时候说为什么；照做了是空的
   */
  reason: string
}

// 这个文件是照 contracts/sim/scene.schema.json 生成的。不要手改：改规约，再运行 npm run contracts。

/**
 * 三个数：x 朝前、y 朝左、z 朝上（米，或者牛顿、牛·米）
 *
 * @minItems 3
 * @maxItems 3
 *
 * This interface was referenced by `Scene`'s JSON-Schema
 * via the `definition` "Vector".
 */
export type Vector = [number, number, number]
/**
 * 姿态，四个数：w、x、y、z
 *
 * @minItems 4
 * @maxItems 4
 *
 * This interface was referenced by `Scene`'s JSON-Schema
 * via the `definition` "Quaternion".
 */
export type Quaternion = [number, number, number, number]
/**
 * 颜色，四个数：红、绿、蓝、不透明的程度，都在 0~1
 *
 * @minItems 4
 * @maxItems 4
 *
 * This interface was referenced by `Scene`'s JSON-Schema
 * via the `definition` "Color".
 */
export type Color = [number, number, number, number]

/**
 * 一个身体放在测试台上的样子。网页按它画 3D 的身体、列出关节和每种感觉；网页不认身体是哪一个。
 */
export interface Scene {
  /**
   * 这个身体的记号。选身体的命令里用它
   */
  body: string
  /**
   * 这个身体的名字，给人看的
   */
  name: string
  /**
   * 能放上测试台的身体
   */
  choices: Choice[]
  mass_kg: number
  /**
   * 站直时的身高
   */
  height_m: number
  /**
   * 仿真的步长
   */
  timestep_s: number
  /**
   * 身体的每一段在模型里的名字。状态里每一段的位置和姿态按这个顺序
   *
   * @minItems 1
   */
  links: [string, ...string[]]
  /**
   * 骨盆是 links 里的第几个
   */
  root: number
  push_point: PushPoint
  /**
   * 要画的每一个形状，长在哪一段上
   */
  shapes: Shape[]
  /**
   * 用到的网格。点和面从 /mesh/{body}/{id} 拿（body 是这个身体的记号）
   */
  meshes: Mesh[]
  /**
   * 有驱动器的关节。状态里关节的角度、速度、力矩按这个顺序
   */
  joints: Joint[]
  /**
   * IMU。状态里的 imus 按这个顺序
   */
  imus: Labelled[]
  /**
   * 六轴力传感器。状态里的 forces 按这个顺序
   */
  force_sensors: Labelled[]
  /**
   * 量接触力的地方。状态里的 touches 按这个顺序
   */
  touch_sensors: Labelled[]
  /**
   * 两只脚。状态里的 feet 按这个顺序
   *
   * @minItems 2
   * @maxItems 2
   */
  feet: [Foot, Foot]
  /**
   * 身体上的相机：从它那里看出去是什么样
   */
  cameras: Camera[]
}
/**
 * This interface was referenced by `Scene`'s JSON-Schema
 * via the `definition` "Choice".
 */
export interface Choice {
  body: string
  name: string
  /**
   * 现在能不能选
   */
  available: boolean
  /**
   * 不能选的时候说为什么；能选的时候是空的
   */
  reason: string
}
/**
 * 推一下的时候，力加在哪：胸这一段的重心。position 是它在这一段里的位置
 *
 * This interface was referenced by `Scene`'s JSON-Schema
 * via the `definition` "PushPoint".
 */
export interface PushPoint {
  /**
   * 胸是 links 里的第几段
   */
  link: number
  position: Vector
}
/**
 * size：盒子：三条半边。球：半径、0、0。胶囊：半径、半长、0。椭球：三个半径。网格：不用；position：在这一段里的位置；orientation：在这一段里的姿态
 *
 * This interface was referenced by `Scene`'s JSON-Schema
 * via the `definition` "Shape".
 */
export interface Shape {
  /**
   * 长在 links 里的第几段上
   */
  link: number
  kind: 'box' | 'sphere' | 'capsule' | 'ellipsoid' | 'mesh'
  size: Vector
  position: Vector
  orientation: Quaternion
  color: Color
  /**
   * 网格的编号；不是网格就是 null
   */
  mesh: number | null
}
/**
 * This interface was referenced by `Scene`'s JSON-Schema
 * via the `definition` "Mesh".
 */
export interface Mesh {
  id: number
  /**
   * 有多少个点
   */
  vertices: number
  /**
   * 有多少个三角形
   */
  faces: number
}
/**
 * This interface was referenced by `Scene`'s JSON-Schema
 * via the `definition` "Joint".
 */
export interface Joint {
  /**
   * 在模型里的名字
   */
  name: string
  /**
   * 给人看的名字，比如 左 膝
   */
  label: string
  /**
   * 在身体的哪一部分
   */
  region: '腿' | '腰' | '颈' | '手臂' | '手'
  lower_rad: number
  upper_rad: number
  /**
   * 驱动器最多出多大的力矩
   */
  peak_torque_nm: number
}
/**
 * This interface was referenced by `Scene`'s JSON-Schema
 * via the `definition` "Labelled".
 */
export interface Labelled {
  /**
   * 给人看的名字：装在哪
   */
  label: string
}
/**
 * sole：脚底的正中间在这一段里的位置
 *
 * This interface was referenced by `Scene`'s JSON-Schema
 * via the `definition` "Foot".
 */
export interface Foot {
  label: string
  /**
   * 脚是 links 里的第几段
   */
  link: number
  sole: Vector
  /**
   * 脚底着地的那一块有多长
   */
  length_m: number
  /**
   * 脚底着地的那一块有多宽
   */
  width_m: number
}
/**
 * orientation：相机朝自己的 -z 看，y 是画面的上方
 *
 * This interface was referenced by `Scene`'s JSON-Schema
 * via the `definition` "Camera".
 */
export interface Camera {
  label: string
  /**
   * 装在 links 里的第几段上
   */
  link: number
  position: Vector
  orientation: Quaternion
  /**
   * 竖直方向的视角
   */
  fovy_deg: number
}

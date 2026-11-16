// 3D 的身体：照仿真给的"样子"搭出来，再照每一条状态把每一段摆到位。
// 这里不认身体是哪一个；也不碰显卡（只搭东西），所以能在测试里跑。
// 坐标和仿真一样：x 朝前、y 朝左、z 朝上。
import {
  BoxGeometry,
  BufferAttribute,
  BufferGeometry,
  CapsuleGeometry,
  Group,
  Mesh,
  MeshStandardMaterial,
  Quaternion,
  SphereGeometry,
  Vector3,
} from 'three'
import type { State } from '@/generated/message'
import type { Scene, Shape } from '@/generated/scene'
import type { MeshData } from '@/sim/meshes'

const ROUND_SEGMENTS = 24
const ROUND_RINGS = 16
const CAP_SEGMENTS = 8
const NUMBERS_PER_POSITION = 3
const NUMBERS_PER_ORIENTATION = 4
const OPAQUE = 1
const ROUGHNESS = 0.75
const METALNESS = 0.05

export interface Pose {
  position: Vector3
  orientation: Quaternion
}

/** 仿真的姿态是 w、x、y、z；three.js 的是 x、y、z、w。 */
export function toQuaternion(values: readonly number[], offset = 0): Quaternion {
  return new Quaternion(values[offset + 1], values[offset + 2], values[offset + 3], values[offset])
}

/** 一个形状的几何体。原点和朝向跟仿真里的一样（胶囊沿着自己的 z）。 */
export function geometryFor(shape: Shape, meshes: ReadonlyMap<number, MeshData>): BufferGeometry {
  const [first, second, third] = shape.size
  switch (shape.kind) {
    case 'box':
      return new BoxGeometry(2 * first, 2 * second, 2 * third)
    case 'sphere':
      return new SphereGeometry(first, ROUND_SEGMENTS, ROUND_RINGS)
    case 'capsule':
      // three.js 的胶囊沿着 y，仿真的沿着 z：转过来。second 是中间那一段的半长。
      return new CapsuleGeometry(first, 2 * second, CAP_SEGMENTS, ROUND_SEGMENTS).rotateX(Math.PI / 2)
    case 'ellipsoid':
      return new SphereGeometry(1, ROUND_SEGMENTS, ROUND_RINGS).scale(first, second, third)
    case 'mesh': {
      const mesh = shape.mesh === null ? undefined : meshes.get(shape.mesh)
      if (!mesh) throw new Error(`第 ${shape.mesh} 个网格还没有拿到`)
      const geometry = new BufferGeometry()
      geometry.setAttribute('position', new BufferAttribute(mesh.vertices, NUMBERS_PER_POSITION))
      geometry.setIndex(new BufferAttribute(mesh.triangles, 1))
      geometry.computeVertexNormals()
      return geometry
    }
  }
}

export class BodyFigure {
  /** 整个身体。放进 3D 的场景里就能看到。 */
  readonly root = new Group()
  private readonly links: Group[]
  private readonly materials = new Map<string, MeshStandardMaterial>()

  constructor(
    private readonly scene: Scene,
    meshes: ReadonlyMap<number, MeshData>,
  ) {
    this.links = scene.links.map((name) => {
      const link = new Group()
      link.name = name
      this.root.add(link)
      return link
    })
    for (const shape of scene.shapes) {
      const part = new Mesh(geometryFor(shape, meshes), this.materialFor(shape.color))
      part.position.fromArray(shape.position)
      part.quaternion.copy(toQuaternion(shape.orientation))
      this.linkAt(shape.link).add(part)
    }
  }

  /** 照一条状态把每一段摆到位。状态要是这个身体的（段数一样），不然报错。 */
  apply(state: State): void {
    const count = this.links.length
    if (
      state.link_positions.length !== count * NUMBERS_PER_POSITION ||
      state.link_orientations.length !== count * NUMBERS_PER_ORIENTATION
    ) {
      throw new Error('状态里的段数和这个身体对不上')
    }
    this.links.forEach((link, index) => {
      link.position.fromArray(state.link_positions, index * NUMBERS_PER_POSITION)
      link.quaternion.copy(toQuaternion(state.link_orientations, index * NUMBERS_PER_ORIENTATION))
    })
    this.root.updateMatrixWorld(true)
  }

  /** 长在某一段上的东西（相机、脚底的点），现在在世界里的位置和姿态。 */
  worldPose(link: number, position: readonly number[], orientation?: readonly number[]): Pose {
    const parent = this.linkAt(link)
    return {
      position: new Vector3().fromArray(position).applyQuaternion(parent.quaternion).add(parent.position),
      orientation: orientation ? parent.quaternion.clone().multiply(toQuaternion(orientation)) : parent.quaternion.clone(),
    }
  }

  /** 第几台相机现在在哪、朝哪。 */
  cameraPose(index: number): Pose {
    const camera = this.scene.cameras[index]
    if (!camera) throw new Error(`这个身体没有第 ${index} 台相机`)
    return this.worldPose(camera.link, camera.position, camera.orientation)
  }

  /** 用完了：把几何体和材质占的地方还回去。 */
  dispose(): void {
    this.root.traverse((object) => {
      if (object instanceof Mesh) object.geometry.dispose()
    })
    for (const material of this.materials.values()) material.dispose()
    this.materials.clear()
  }

  private linkAt(index: number): Group {
    const link = this.links[index]
    if (!link) throw new Error(`这个身体没有第 ${index} 段`)
    return link
  }

  /** 同一种颜色的形状共用一份材质。半透明的（外壳）不挡住里面的东西。 */
  private materialFor(color: Shape['color']): MeshStandardMaterial {
    const key = color.join(',')
    let material = this.materials.get(key)
    if (!material) {
      const [red, green, blue, opacity] = color
      const seeThrough = opacity < OPAQUE
      material = new MeshStandardMaterial({
        roughness: ROUGHNESS,
        metalness: METALNESS,
        transparent: seeThrough,
        opacity,
        depthWrite: !seeThrough,
      })
      material.color.setRGB(red, green, blue)
      this.materials.set(key, material)
    }
    return material
  }
}

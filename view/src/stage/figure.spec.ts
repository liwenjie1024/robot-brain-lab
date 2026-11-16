import { Box3, Mesh, Vector3 } from 'three'
import { describe, expect, it } from 'vitest'
import { BodyFigure, geometryFor, toQuaternion } from '@/stage/figure'
import { decodeMesh } from '@/sim/meshes'
import type { MeshData } from '@/sim/meshes'
import { g1Scene, g1State, novaScene, novaState, triangleMeshBytes } from '@/test/samples'
import type { Shape } from '@/generated/scene'

const NO_MESHES = new Map<number, MeshData>()

function shape(kind: Shape['kind'], size: [number, number, number], mesh: number | null = null): Shape {
  return { link: 0, kind, size, position: [0, 0, 0], orientation: [1, 0, 0, 0], color: [1, 1, 1, 1], mesh }
}

function sizeOf(kind: Shape['kind'], size: [number, number, number]): number[] {
  const geometry = geometryFor(shape(kind, size), NO_MESHES)
  geometry.computeBoundingBox()
  return geometry.boundingBox!.getSize(new Vector3()).toArray()
}

function meshesFor(scene: ReturnType<typeof g1Scene>): Map<number, MeshData> {
  return new Map(scene.meshes.map((mesh) => [mesh.id, decodeMesh(triangleMeshBytes())]))
}

describe('每种形状的几何体', () => {
  it('盒子：三条边是三条半边的两倍', () => {
    const [x, y, z] = sizeOf('box', [0.1, 0.2, 0.3])
    expect(x).toBeCloseTo(0.2)
    expect(y).toBeCloseTo(0.4)
    expect(z).toBeCloseTo(0.6)
  })

  it('球：直径是半径的两倍', () => {
    for (const side of sizeOf('sphere', [0.5, 0, 0])) expect(side).toBeCloseTo(1)
  })

  it('胶囊：沿着自己的 z，长是中间那一段加两个半径', () => {
    const [x, y, z] = sizeOf('capsule', [0.1, 0.3, 0])
    expect(x).toBeCloseTo(0.2)
    expect(y).toBeCloseTo(0.2)
    expect(z).toBeCloseTo(0.8)
  })

  it('椭球：三个方向各是半径的两倍', () => {
    const [x, y, z] = sizeOf('ellipsoid', [0.1, 0.2, 0.3])
    expect(x).toBeCloseTo(0.2)
    expect(y).toBeCloseTo(0.4)
    expect(z).toBeCloseTo(0.6)
  })

  it('网格：用拿到的点和三角形，算好朝向（给光照用）', () => {
    const meshes = new Map([[4, decodeMesh(triangleMeshBytes())]])
    const geometry = geometryFor(shape('mesh', [0, 0, 0], 4), meshes)
    expect(geometry.getAttribute('position').count).toBe(3)
    expect(geometry.getIndex()!.count).toBe(3)
    expect(geometry.getAttribute('normal').getZ(0)).toBeCloseTo(1)
  })

  it('网格还没拿到：报错，说是第几个', () => {
    expect(() => geometryFor(shape('mesh', [0, 0, 0], 7), NO_MESHES)).toThrow('第 7 个网格还没有拿到')
  })

  it('仿真的姿态是 w、x、y、z，换成 three.js 的 x、y、z、w', () => {
    expect(toQuaternion([0.5, 0.1, 0.2, 0.3]).toArray()).toEqual([0.1, 0.2, 0.3, 0.5])
    expect(toQuaternion([9, 9, 0.5, 0.1, 0.2, 0.3], 2).toArray()).toEqual([0.1, 0.2, 0.3, 0.5])
  })
})

describe('3D 的身体', () => {
  it('每一段一个组，每个形状挂在它那一段上（Nova）', () => {
    const scene = novaScene()
    const figure = new BodyFigure(scene, NO_MESHES)
    expect(figure.root.children.map((link) => link.name)).toEqual(scene.links)
    let shapes = 0
    figure.root.traverse((object) => {
      if (object instanceof Mesh) shapes += 1
    })
    expect(shapes).toBe(scene.shapes.length)
    const first = scene.shapes[0]!
    expect(figure.root.children[first.link]!.children.length).toBeGreaterThan(0)
  })

  it('基线用网格搭出来；少一个网格就搭不出来', () => {
    const scene = g1Scene()
    const figure = new BodyFigure(scene, meshesFor(scene))
    expect(figure.root.children.length).toBe(scene.links.length)
    const missing = meshesFor(scene)
    missing.delete(scene.meshes[0]!.id)
    expect(() => new BodyFigure(scene, missing)).toThrow('还没有拿到')
  })

  it('同一种颜色共用一份材质；半透明的外壳不挡住里面的东西', () => {
    const figure = new BodyFigure(novaScene(), NO_MESHES)
    const materials = new Set()
    const seeThrough: boolean[] = []
    figure.root.traverse((object) => {
      if (object instanceof Mesh) {
        materials.add(object.material)
        if (object.material.transparent) seeThrough.push(object.material.depthWrite)
      }
    })
    expect(materials.size).toBeLessThan(10)
    expect(seeThrough.length).toBeGreaterThan(0)
    expect(seeThrough.every((writes) => writes === false)).toBe(true)
  })

  it('照状态把每一段摆到位', () => {
    const scene = novaScene()
    const state = novaState()
    const figure = new BodyFigure(scene, NO_MESHES)
    figure.apply(state)
    const pelvis = figure.root.children[scene.root]!
    expect(pelvis.position.toArray()).toEqual(state.link_positions.slice(3 * scene.root, 3 * scene.root + 3))
    expect(pelvis.position.z).toBeCloseTo(state.pelvis_height_m, 4)
    const last = scene.links.length - 1
    expect(figure.root.children[last]!.quaternion.w).toBeCloseTo(state.link_orientations[4 * last]!)
  })

  it('整个身体站在地面上：最低的地方差不多是 0，最高的地方差不多是身高', () => {
    const scene = novaScene()
    const figure = new BodyFigure(scene, NO_MESHES)
    figure.apply(novaState())
    const box = new Box3().setFromObject(figure.root)
    expect(box.min.z).toBeCloseTo(0, 2)
    expect(box.max.z).toBeGreaterThan(scene.height_m - 0.05)
    expect(box.max.z).toBeLessThan(scene.height_m + 0.01)
  })

  it('别的身体的状态（段数不一样）：拒绝', () => {
    const figure = new BodyFigure(novaScene(), NO_MESHES)
    expect(() => figure.apply(g1State())).toThrow('状态里的段数和这个身体对不上')
  })

  it('脚底的点在世界里的位置：站着的时候贴着地面', () => {
    const scene = novaScene()
    const figure = new BodyFigure(scene, NO_MESHES)
    figure.apply(novaState())
    for (const foot of scene.feet) {
      const sole = figure.worldPose(foot.link, foot.sole).position
      expect(sole.z).toBeCloseTo(0, 3)
    }
    const left = figure.worldPose(scene.feet[0]!.link, scene.feet[0]!.sole).position
    expect(left.y).toBeGreaterThan(0)
  })

  it('眼的相机：在眼的高度，朝前看；胸前的那台朝前下方看', () => {
    const scene = novaScene()
    const figure = new BodyFigure(scene, NO_MESHES)
    figure.apply(novaState())
    const labels = scene.cameras.map((camera) => camera.label)
    const eye = figure.cameraPose(labels.indexOf('左眼'))
    expect(eye.position.z).toBeGreaterThan(0.9 * scene.height_m)
    expect(eye.position.y).toBeGreaterThan(0)
    // 相机朝自己的 -z 看。
    const eyeLooks = new Vector3(0, 0, -1).applyQuaternion(eye.orientation)
    expect(eyeLooks.x).toBeCloseTo(1, 3)
    const chest = figure.cameraPose(labels.findIndex((label) => label.startsWith('胸前')))
    const chestLooks = new Vector3(0, 0, -1).applyQuaternion(chest.orientation)
    expect(chestLooks.x).toBeGreaterThan(0.3)
    expect(chestLooks.z).toBeLessThan(-0.5)
  })

  it('没有的相机、没有的段：报错', () => {
    const figure = new BodyFigure(g1Scene(), meshesFor(g1Scene()))
    expect(() => figure.cameraPose(0)).toThrow('这个身体没有第 0 台相机')
    expect(() => figure.worldPose(999, [0, 0, 0])).toThrow('这个身体没有第 999 段')
  })

  it('用完以后把几何体和材质还回去', () => {
    const figure = new BodyFigure(novaScene(), NO_MESHES)
    let disposed = 0
    figure.root.traverse((object) => {
      if (object instanceof Mesh) object.geometry.addEventListener('dispose', () => (disposed += 1))
    })
    figure.dispose()
    expect(disposed).toBe(novaScene().shapes.length)
  })
})

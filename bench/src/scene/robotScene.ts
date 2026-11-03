import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import type { MeshData } from '@/sim/meshes'
import type { StateMessage } from '@/sim/generated/message'
import type { Geom, SceneDescription } from '@/sim/generated/scene'

/**
 * 몸을 3D로 그린다. 모양은 /scene의 설명만으로 만들어 로봇이 바뀌어도 이 코드는 그대로다.
 * MuJoCo는 z가 위, three.js는 y가 위라 세계 전체를 x축으로 -90도 돌려 놓는다.
 */

export interface RobotSceneHandle {
  update(state: StateMessage): void
  setFollow(follow: boolean): void
  dispose(): void
}

export interface RobotSceneOptions {
  loadMesh: (meshId: number) => Promise<MeshData>
  reducedMotion: boolean
}

const VALUES_PER_BODY = 7
const BACKGROUND = 0x0f172a
const FLOOR_COLOR = 0x1e293b
const GRID_MAJOR = 0x475569
const GRID_MINOR = 0x334155
const GRID_SIZE_M = 40
const GRID_DIVISIONS = 40
const CAMERA_FOV = 45
const CAMERA_START = new THREE.Vector3(2.6, 1.6, 2.6)
/** 따라갈 때 한 화면마다 목표 쪽으로 옮기는 몫 (값이 크면 카메라가 흔들린다) */
const FOLLOW_SMOOTHING = 0.08
const ROBOT_EYE_HEIGHT_M = 0.6
const CURVE_SEGMENTS = 24

export async function createRobotScene(
  canvas: HTMLCanvasElement,
  description: SceneDescription,
  options: RobotSceneOptions,
): Promise<RobotSceneHandle> {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.shadowMap.enabled = true

  const scene = new THREE.Scene()
  scene.background = new THREE.Color(BACKGROUND)
  scene.add(new THREE.HemisphereLight(0xffffff, 0x334155, 1.6))
  const sun = new THREE.DirectionalLight(0xffffff, 2.2)
  sun.position.set(3, 6, 2)
  sun.castShadow = true
  scene.add(sun)

  const camera = new THREE.PerspectiveCamera(CAMERA_FOV, 1, 0.05, 200)
  camera.position.copy(CAMERA_START)
  const controls = new OrbitControls(camera, canvas)
  controls.target.set(0, ROBOT_EYE_HEIGHT_M, 0)
  controls.enableDamping = !options.reducedMotion

  const world = new THREE.Group()
  world.rotation.x = -Math.PI / 2
  scene.add(world)
  const bodies = new Map<number, THREE.Object3D>([[0, world]])
  for (const bodyId of description.movingBodies) {
    const group = new THREE.Group()
    world.add(group)
    bodies.set(bodyId, group)
  }

  const meshCache = new Map<number, Promise<THREE.BufferGeometry>>()
  const geometryFor = (meshId: number) => {
    let geometry = meshCache.get(meshId)
    if (!geometry) {
      geometry = options.loadMesh(meshId).then(meshGeometry)
      meshCache.set(meshId, geometry)
    }
    return geometry
  }
  await Promise.all(description.geoms.map(async (geom) => {
    const object = geom.shape === 'plane' ? floor() : await solid(geom, geometryFor)
    object.position.fromArray(geom.position)
    object.quaternion.copy(mujocoQuaternion(geom.quaternion))
    ;(bodies.get(geom.body) ?? world).add(object)
  }))

  let follow = true
  const followTarget = new THREE.Vector3(0, ROBOT_EYE_HEIGHT_M, 0)
  const resize = () => {
    const { clientWidth, clientHeight } = canvas
    if (clientWidth === 0 || clientHeight === 0) {
      return
    }
    renderer.setSize(clientWidth, clientHeight, false)
    camera.aspect = clientWidth / clientHeight
    camera.updateProjectionMatrix()
  }
  const observer = new ResizeObserver(resize)
  observer.observe(canvas)
  resize()

  renderer.setAnimationLoop(() => {
    if (follow) {
      const step = options.reducedMotion ? 1 : FOLLOW_SMOOTHING
      const offset = camera.position.clone().sub(controls.target)
      controls.target.lerp(followTarget, step)
      camera.position.copy(controls.target).add(offset)
    }
    controls.update()
    renderer.render(scene, camera)
  })

  return {
    update(state) {
      description.movingBodies.forEach((bodyId, index) => {
        const body = bodies.get(bodyId)
        const start = index * VALUES_PER_BODY
        if (!body || start + VALUES_PER_BODY > state.bodies.length) {
          return
        }
        const [x, y, z, qw, qx, qy, qz] = state.bodies.slice(start, start + VALUES_PER_BODY) as number[]
        body.position.set(x!, y!, z!)
        body.quaternion.set(qx!, qy!, qz!, qw!)
      })
      const [x, y] = state.robot.position
      // 세계가 돌아가 있어 MuJoCo의 (x, y)는 three.js의 (x, -z)다.
      followTarget.set(x, ROBOT_EYE_HEIGHT_M, -y)
    },
    setFollow(value) {
      follow = value
    },
    dispose() {
      renderer.setAnimationLoop(null)
      observer.disconnect()
      controls.dispose()
      scene.traverse((object) => {
        if (object instanceof THREE.Mesh) {
          object.geometry.dispose()
          ;(object.material as THREE.Material).dispose()
        }
      })
      renderer.dispose()
    },
  }
}

function mujocoQuaternion([w, x, y, z]: number[]): THREE.Quaternion {
  return new THREE.Quaternion(x, y, z, w)
}

function meshGeometry(data: MeshData): THREE.BufferGeometry {
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.BufferAttribute(data.positions, 3))
  geometry.setIndex(new THREE.BufferAttribute(data.indices, 1))
  geometry.computeVertexNormals()
  return geometry
}

async function solid(
  geom: Geom,
  geometryFor: (meshId: number) => Promise<THREE.BufferGeometry>,
): Promise<THREE.Object3D> {
  const [r = 1, g = 1, b = 1, a = 1] = geom.rgba
  const material = new THREE.MeshStandardMaterial({
    color: new THREE.Color(r, g, b),
    opacity: a,
    transparent: a < 1,
    metalness: 0.2,
    roughness: 0.6,
  })
  const mesh = new THREE.Mesh(await shapeGeometry(geom, geometryFor), material)
  mesh.castShadow = true
  return mesh
}

async function shapeGeometry(
  geom: Geom,
  geometryFor: (meshId: number) => Promise<THREE.BufferGeometry>,
): Promise<THREE.BufferGeometry> {
  const [a = 0, b = 0, c = 0] = geom.size
  switch (geom.shape) {
    case 'mesh':
      return geometryFor(geom.mesh ?? -1)
    case 'sphere':
      return new THREE.SphereGeometry(a, CURVE_SEGMENTS, CURVE_SEGMENTS / 2)
    // three.js의 원기둥·캡슐은 y축으로 서 있고 MuJoCo는 z축이라 눕힌다.
    case 'capsule':
      return new THREE.CapsuleGeometry(a, b * 2, CURVE_SEGMENTS / 2, CURVE_SEGMENTS).rotateX(Math.PI / 2)
    case 'cylinder':
      return new THREE.CylinderGeometry(a, a, b * 2, CURVE_SEGMENTS).rotateX(Math.PI / 2)
    case 'box':
      return new THREE.BoxGeometry(a * 2, b * 2, c * 2)
    default:
      throw new Error(`그릴 수 없는 모양입니다: ${geom.shape}`)
  }
}

function floor(): THREE.Object3D {
  const group = new THREE.Group()
  const plane = new THREE.Mesh(
    new THREE.PlaneGeometry(GRID_SIZE_M, GRID_SIZE_M),
    new THREE.MeshStandardMaterial({ color: FLOOR_COLOR, roughness: 0.9 }),
  )
  plane.receiveShadow = true
  group.add(plane)
  // 눈금은 three.js에서 xz 평면에 그려지므로 MuJoCo 바닥(xy)에 맞게 세운다. 1m 간격.
  const grid = new THREE.GridHelper(GRID_SIZE_M, GRID_DIVISIONS, GRID_MAJOR, GRID_MINOR)
  grid.rotation.x = Math.PI / 2
  grid.position.z = 0.001
  group.add(grid)
  return group
}

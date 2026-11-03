import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import type { MeshData } from '@/sim/meshes'
import type { ShotMessage, StateMessage } from '@shared/sim/generated/message'
import type { Geom, SceneDescription } from '@shared/sim/generated/scene'

/**
 * 시험장을 3D로 그린다. 모양은 /scene의 설명만으로 만들어 기체가 바뀌어도 이 코드는 그대로다.
 * MuJoCo는 z가 위, three.js는 y가 위라 세계 전체를 x축으로 -90도 돌려 놓고, 그 안에는 MuJoCo 좌표를 그대로 쓴다.
 */

export interface RobotSceneHandle {
  update(state: StateMessage): void
  showShot(shot: ShotMessage): void
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
/** 눈금을 그릴 넓이와 칸 (10m 칸). 바닥 전체(4km)에 그리면 너무 촘촘해 보이지 않는다. */
const GRID_SIZE_M = 800
const GRID_DIVISIONS = 80
const CAMERA_FOV = 45
const CAMERA_FAR_M = 6000
/** 기체 키 1m마다 카메라를 둘 곳 (뒤·위·옆, three.js 좌표) */
const CAMERA_OFFSET_PER_HEIGHT = new THREE.Vector3(-1.9, 0.9, 1.6)
/** 따라갈 때 한 화면마다 목표 쪽으로 옮기는 몫 (값이 크면 카메라가 흔들린다) */
const FOLLOW_SMOOTHING = 0.08
const CURVE_SEGMENTS = 24
const SHADOW_HALF_SIZE_M = 40
const SUN_OFFSET = new THREE.Vector3(40, 120, 30)
const BEAM_SECONDS = 0.35
const BEAM_RADIUS_M = 0.25
const IMPACT_RADIUS_M = 2.0
const MECHA_BEAM = 0x67e8f9
const DRONE_BEAM = 0xf87171
const DESTROYED_DIMMING = 0.3
const MECHA_ID = 'mecha'

interface Beam {
  objects: THREE.Mesh[]
  bornAt: number
}

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
  sun.castShadow = true
  Object.assign(sun.shadow.camera, {
    left: -SHADOW_HALF_SIZE_M,
    right: SHADOW_HALF_SIZE_M,
    top: SHADOW_HALF_SIZE_M,
    bottom: -SHADOW_HALF_SIZE_M,
    far: SUN_OFFSET.length() * 2,
  })
  scene.add(sun, sun.target)

  const height = description.robot.height
  const camera = new THREE.PerspectiveCamera(CAMERA_FOV, 1, 0.5, CAMERA_FAR_M)
  const controls = new OrbitControls(camera, canvas)
  controls.enableDamping = !options.reducedMotion
  controls.target.set(0, height * 0.6, 0)
  camera.position.copy(controls.target).add(CAMERA_OFFSET_PER_HEIGHT.clone().multiplyScalar(height))

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
    const object = geom.shape === 'plane' ? floor(geom) : await solid(geom, geometryFor)
    object.position.fromArray(geom.position)
    object.quaternion.copy(mujocoQuaternion(geom.quaternion))
    ;(bodies.get(geom.body) ?? world).add(object)
  }))

  const droneBodies = new Map(
    description.units.filter((unit) => unit.kind !== MECHA_ID).map((unit) => [unit.id, bodies.get(unit.body)]),
  )
  const beams: Beam[] = []
  const clock = new THREE.Timer()
  let follow = true
  const followTarget = controls.target.clone()

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
    clock.update()
    if (follow) {
      const step = options.reducedMotion ? 1 : FOLLOW_SMOOTHING
      const offset = camera.position.clone().sub(controls.target)
      controls.target.lerp(followTarget, step)
      camera.position.copy(controls.target).add(offset)
    }
    sun.position.copy(followTarget).add(SUN_OFFSET)
    sun.target.position.copy(followTarget)
    fadeBeams(beams, clock.getElapsed(), world)
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
      const active = new Map(state.units.map((unit) => [unit.id, unit.alive]))
      for (const [unitId, body] of droneBodies) {
        if (body) {
          body.visible = active.has(unitId)
          setDimmed(body, active.get(unitId) === false)
        }
      }
      const [x, y, z] = state.mecha.position
      // 세계가 돌아가 있어 MuJoCo의 (x, y, z)는 three.js의 (x, z, -y)다.
      followTarget.set(x, z, -y)
    },
    showShot(shot) {
      beams.push({ objects: beamObjects(shot, world), bornAt: clock.getElapsed() })
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
    metalness: 0.3,
    roughness: 0.55,
  })
  material.userData.baseColor = material.color.clone()
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

function floor(geom: Geom): THREE.Object3D {
  const [halfX = GRID_SIZE_M, halfY = GRID_SIZE_M] = geom.size
  const group = new THREE.Group()
  const plane = new THREE.Mesh(
    new THREE.PlaneGeometry(halfX * 2, halfY * 2),
    new THREE.MeshStandardMaterial({ color: FLOOR_COLOR, roughness: 0.9 }),
  )
  plane.receiveShadow = true
  group.add(plane)
  // 눈금은 three.js에서 xz 평면에 그려지므로 MuJoCo 바닥(xy)에 맞게 세운다.
  const grid = new THREE.GridHelper(GRID_SIZE_M, GRID_DIVISIONS, GRID_MAJOR, GRID_MINOR)
  grid.rotation.x = Math.PI / 2
  grid.position.z = 0.01
  group.add(grid)
  return group
}

function setDimmed(body: THREE.Object3D, dimmed: boolean): void {
  if (body.userData.dimmed === dimmed) {
    return
  }
  body.userData.dimmed = dimmed
  body.traverse((object) => {
    if (object instanceof THREE.Mesh && object.material instanceof THREE.MeshStandardMaterial) {
      const base = object.material.userData.baseColor as THREE.Color
      object.material.color.copy(base).multiplyScalar(dimmed ? DESTROYED_DIMMING : 1)
    }
  })
}

/** 사격 광선(가는 원기둥)과 맞은 곳의 빛. 모두 MuJoCo 좌표인 world 안에 둔다. */
function beamObjects(shot: ShotMessage, world: THREE.Group): THREE.Mesh[] {
  const from = new THREE.Vector3(...shot.from)
  const to = new THREE.Vector3(...shot.to)
  const length = from.distanceTo(to)
  const color = shot.shooter === MECHA_ID ? MECHA_BEAM : DRONE_BEAM
  const material = () => new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 1 })
  const beam = new THREE.Mesh(new THREE.CylinderGeometry(BEAM_RADIUS_M, BEAM_RADIUS_M, length, 8), material())
  beam.position.copy(from).add(to).multiplyScalar(0.5)
  beam.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), to.clone().sub(from).normalize())
  const objects: THREE.Mesh[] = [beam]
  if (shot.hit) {
    const impact = new THREE.Mesh(new THREE.SphereGeometry(IMPACT_RADIUS_M, 12, 8), material())
    impact.position.copy(to)
    objects.push(impact)
  }
  world.add(...objects)
  return objects
}

function fadeBeams(beams: Beam[], now: number, world: THREE.Group): void {
  for (let index = beams.length - 1; index >= 0; index--) {
    const beam = beams[index]!
    const age = (now - beam.bornAt) / BEAM_SECONDS
    if (age >= 1) {
      for (const object of beam.objects) {
        world.remove(object)
        object.geometry.dispose()
        ;(object.material as THREE.Material).dispose()
      }
      beams.splice(index, 1)
      continue
    }
    for (const object of beam.objects) {
      ;(object.material as THREE.MeshBasicMaterial).opacity = 1 - age
    }
  }
}

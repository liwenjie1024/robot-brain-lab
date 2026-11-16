// 3D 的舞台：地面、灯、身体、几个记号（重心、压力中心、推的那一下），和看它的相机。
// 这里碰显卡（WebGL），所以不在测试里跑；搭身体、摆姿势的部分在 figure.ts。
import {
  ArrowHelper,
  BufferGeometry,
  CircleGeometry,
  Color,
  DirectionalLight,
  GridHelper,
  Group,
  HemisphereLight,
  Line,
  LineBasicMaterial,
  Mesh,
  MeshBasicMaterial,
  PerspectiveCamera,
  RingGeometry,
  Scene as World,
  SphereGeometry,
  Vector3,
  WebGLRenderer,
} from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { GRAVITY_M_S2 } from '@/text/format'
import { BodyFigure } from '@/stage/figure'
import type { State } from '@/generated/message'
import type { Scene } from '@/generated/scene'
import type { MeshData } from '@/sim/meshes'

const BACKGROUND = '#f4f5f7'
const GRID_SIZE_M = 6
const GRID_CELLS = 12
const GRID_MAIN = '#9aa0aa'
const GRID_MINOR = '#d5d8de'
const CENTER_OF_MASS_COLOR = '#d12d2d'
const PRESSURE_CENTER_COLOR = '#1f6fd1'
const FOOT_PRESSURE_COLOR = '#2b2f36'
const PUSH_COLOR = '#e8730c'
const FREE_VIEW_FOV_DEG = 40
const NEAR_M = 0.03
const FAR_M = 60
// 记号贴着地面画，抬高一点点，不和地面叠在一起闪。
const ON_FLOOR_M = 0.003
// 推的箭头：最短这么长，力每多体重的 1 倍再长这么多，最长这么长。
const ARROW_SHORTEST_M = 0.15
const ARROW_PER_WEIGHT_M = 1.5
const ARROW_LONGEST_M = 0.6
// 记号要一直看得见，画在最上面一层。
const ON_TOP = 10

export class Stage {
  private readonly renderer: WebGLRenderer
  private readonly world = new World()
  private readonly freeCamera = new PerspectiveCamera(FREE_VIEW_FOV_DEG, 1, NEAR_M, FAR_M)
  private readonly bodyCamera = new PerspectiveCamera(FREE_VIEW_FOV_DEG, 1, NEAR_M, FAR_M)
  private readonly controls: OrbitControls
  private readonly markers = new Group()
  private readonly centerOfMass = new Mesh(new SphereGeometry(0.025), onTop(CENTER_OF_MASS_COLOR))
  private readonly plumbLine = new Line(new BufferGeometry(), new LineBasicMaterial({ color: CENTER_OF_MASS_COLOR }))
  private readonly pressureCenter = new Mesh(new RingGeometry(0.03, 0.045, 32), onTop(PRESSURE_CENTER_COLOR))
  private readonly footPressure = [0, 1].map(() => new Mesh(new CircleGeometry(0.012, 20), onTop(FOOT_PRESSURE_COLOR)))
  private readonly pushArrow = new ArrowHelper(new Vector3(1, 0, 0), new Vector3(), ARROW_SHORTEST_M, PUSH_COLOR)
  private scene: Scene | null = null
  private figure: BodyFigure | null = null
  private view: number | null = null
  private markersWanted = true

  /** 浏览器画不了 3D（没有 WebGL）的时候，这里会报错。 */
  constructor(canvas: HTMLCanvasElement) {
    this.renderer = new WebGLRenderer({ canvas, antialias: true })
    this.renderer.setPixelRatio(window.devicePixelRatio)
    this.world.background = new Color(BACKGROUND)
    // 和仿真一样，z 朝上。
    this.freeCamera.up.set(0, 0, 1)
    this.controls = new OrbitControls(this.freeCamera, canvas)
    this.controls.enableDamping = true
    this.addLightsAndFloor()
    this.markers.add(this.centerOfMass, this.plumbLine, this.pressureCenter, ...this.footPressure, this.pushArrow)
    this.world.add(this.markers)
    this.lookAtBody(1.7)
  }

  /** 换一个身体放上舞台。 */
  setFigure(scene: Scene, meshes: ReadonlyMap<number, MeshData>): void {
    this.clearFigure()
    this.scene = scene
    this.figure = new BodyFigure(scene, meshes)
    this.world.add(this.figure.root)
    this.view = null
    this.lookAtBody(scene.height_m)
  }

  /** 照一条状态摆好身体和记号。 */
  update(state: State): void {
    if (!this.figure || !this.scene) return
    this.figure.apply(state)
    const [x, y, z] = state.center_of_mass
    this.centerOfMass.position.set(x, y, z)
    this.plumbLine.geometry.setFromPoints([new Vector3(x, y, z), new Vector3(x, y, 0)])
    placeOnFloor(this.pressureCenter, state.pressure_center)
    state.feet.forEach((foot, index) => placeOnFloor(this.footPressure[index], foot.pressure_center))
    this.showPush(state)
  }

  /** 从哪看：null 是自己转着看；数字是从身体的第几台相机看出去。 */
  setView(view: number | null): void {
    this.view = view
    this.controls.enabled = view === null
    if (view !== null && this.scene) {
      const fovy = this.scene.cameras[view]?.fovy_deg
      if (fovy !== undefined) this.bodyCamera.fov = fovy
      this.bodyCamera.updateProjectionMatrix()
    }
  }

  /** 要不要画重心、压力中心这些记号。 */
  showMarkers(wanted: boolean): void {
    this.markersWanted = wanted
  }

  resize(width: number, height: number): void {
    if (width <= 0 || height <= 0) return
    this.renderer.setSize(width, height, false)
    for (const camera of [this.freeCamera, this.bodyCamera]) {
      camera.aspect = width / height
      camera.updateProjectionMatrix()
    }
  }

  /** 画一帧。 */
  render(): void {
    const fromBody = this.view !== null && this.figure !== null
    // 从身体的相机看出去时，记号不是世界里的东西，不画。
    this.markers.visible = this.markersWanted && !fromBody && this.figure !== null
    if (this.view !== null && this.figure) {
      const pose = this.figure.cameraPose(this.view)
      this.bodyCamera.position.copy(pose.position)
      this.bodyCamera.quaternion.copy(pose.orientation)
      this.renderer.render(this.world, this.bodyCamera)
      return
    }
    this.controls.update()
    this.renderer.render(this.world, this.freeCamera)
  }

  dispose(): void {
    this.clearFigure()
    this.controls.dispose()
    this.renderer.dispose()
  }

  private clearFigure(): void {
    if (!this.figure) return
    this.world.remove(this.figure.root)
    this.figure.dispose()
    this.figure = null
    this.scene = null
  }

  private addLightsAndFloor(): void {
    this.world.add(new HemisphereLight('#ffffff', '#b9bec8', 1.6))
    const sun = new DirectionalLight('#ffffff', 1.8)
    sun.position.set(2, -3, 5)
    this.world.add(sun)
    // GridHelper 默认躺在 x-z 的平面上；转过来，让它躺在地面（x-y）上。
    const grid = new GridHelper(GRID_SIZE_M, GRID_CELLS, GRID_MAIN, GRID_MINOR)
    grid.rotation.x = Math.PI / 2
    this.world.add(grid)
  }

  /** 把自己转着看的相机摆到能看全这个身体的地方：从右前方，稍微高一点。 */
  private lookAtBody(height: number): void {
    this.controls.target.set(0, 0, 0.55 * height)
    this.freeCamera.position.set(1.5 * height, -1.1 * height, 0.9 * height)
    this.controls.update()
  }

  private showPush(state: State): void {
    const push = state.push
    this.pushArrow.visible = push !== null
    if (!push || !this.figure || !this.scene) return
    const force = new Vector3().fromArray(push.force_n)
    const share = force.length() / (this.scene.mass_kg * GRAVITY_M_S2)
    const length = Math.min(ARROW_SHORTEST_M + ARROW_PER_WEIGHT_M * share, ARROW_LONGEST_M)
    const direction = force.normalize()
    const target = this.figure.worldPose(this.scene.push_point.link, this.scene.push_point.position).position
    // 箭头的尖顶在胸上：从后面推过来的样子。
    this.pushArrow.position.copy(target).addScaledVector(direction, -length)
    this.pushArrow.setDirection(direction)
    this.pushArrow.setLength(length, 0.3 * length, 0.15 * length)
  }
}

function onTop(color: string): MeshBasicMaterial {
  const material = new MeshBasicMaterial({ color, depthTest: false })
  material.transparent = true
  return material
}

function placeOnFloor(marker: Mesh | undefined, point: readonly number[] | null): void {
  if (!marker) return
  marker.visible = point !== null
  marker.renderOrder = ON_TOP
  if (point) marker.position.set(point[0] ?? 0, point[1] ?? 0, ON_FLOOR_M)
}

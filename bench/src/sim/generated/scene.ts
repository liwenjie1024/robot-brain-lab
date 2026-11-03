// contracts/sim/scene.schema.json에서 만든 파일이다. 직접 고치지 말고 npm run contracts 로 다시 만든다.

/**
 * GET /scene. 화면이 시험장을 그리고, 명령을 보내는 쪽이 범위·유닛·시험 장면을 알 수 있게 한다. 메시 모양은 GET /meshes/{id}.
 */
export interface SceneDescription {
  robot: {
    name: string
    description: string
    /**
     * 기체 키 m (화면이 카메라 거리를 정한다)
     */
    height: number
  }
  /**
   * 상태 메시지 bodies의 순서
   */
  movingBodies: number[]
  /**
   * 그릴 모양. body가 0이면 바닥처럼 움직이지 않는다.
   */
  geoms: Geom[]
  meshes: Mesh[]
  /**
   * 맞힐 수 있는 것 모두 (장면에서 쓰지 않는 드론 포함, 지금 쓰는 것은 상태 메시지의 units)
   */
  units: UnitInfo[]
  scenarios: ScenarioInfo[]
  limits: Limits
  rates: {
    physicsHz: number
    controlHz: number
    stateHz: number
  }
}
/**
 * This interface was referenced by `SceneDescription`'s JSON-Schema
 * via the `definition` "Geom".
 */
export interface Geom {
  /**
   * 붙은 몸체 번호
   */
  body: number
  shape: 'plane' | 'sphere' | 'capsule' | 'cylinder' | 'box' | 'mesh'
  /**
   * MuJoCo 크기 값 (모양마다 뜻이 다르다)
   */
  size: number[]
  /**
   * 몸체 기준 [x, y, z]
   */
  position: number[]
  /**
   * 몸체 기준 [w, x, y, z]
   */
  quaternion: number[]
  rgba: number[]
  /**
   * shape가 mesh일 때 메시 번호
   */
  mesh?: number
}
/**
 * GET /meshes/{id}: [꼭짓점 수 u32, 삼각형 수 u32, 꼭짓점 xyz f32..., 삼각형 꼭짓점 번호 u32...] (little endian)
 *
 * This interface was referenced by `SceneDescription`'s JSON-Schema
 * via the `definition` "Mesh".
 */
export interface Mesh {
  id: number
  name: string
  vertexCount: number
  faceCount: number
}
/**
 * This interface was referenced by `SceneDescription`'s JSON-Schema
 * via the `definition` "UnitInfo".
 */
export interface UnitInfo {
  id: string
  kind: 'mecha' | 'drone'
  name: string
  /**
   * 이 유닛의 몸체 번호 (화면이 감추거나 이름표를 단다)
   */
  body: number
}
/**
 * This interface was referenced by `SceneDescription`'s JSON-Schema
 * via the `definition` "ScenarioInfo".
 */
export interface ScenarioInfo {
  name: string
  label: string
  description: string
}
/**
 * 명령 값의 범위 (비행 제어가 기체를 똑바로 세운 채 따라갈 수 있는 범위). 속도 m/s, turn rad/s, pushForce는 밀기 힘의 크기 N
 *
 * This interface was referenced by `SceneDescription`'s JSON-Schema
 * via the `definition` "Limits".
 */
export interface Limits {
  forward: Range
  sideways: Range
  up: Range
  turn: Range
  pushForce: Range
  pushDurationMs: Range
}
/**
 * This interface was referenced by `SceneDescription`'s JSON-Schema
 * via the `definition` "Range".
 */
export interface Range {
  min: number
  max: number
}

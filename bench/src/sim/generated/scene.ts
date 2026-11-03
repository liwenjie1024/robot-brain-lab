// contracts/sim/scene.schema.json에서 만든 파일이다. 직접 고치지 말고 npm run contracts 로 다시 만든다.

/**
 * GET /scene. 화면이 몸을 그리고, 명령을 보내는 쪽이 범위를 알 수 있게 한다. 메시 모양은 GET /meshes/{id}.
 */
export interface SceneDescription {
  robot: {
    name: string
    description: string
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
 * 명령 값의 범위 (걷기 정책이 배운 범위 안쪽). pushForce는 밀기 힘의 크기 N
 *
 * This interface was referenced by `SceneDescription`'s JSON-Schema
 * via the `definition` "Limits".
 */
export interface Limits {
  forward: Range
  sideways: Range
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

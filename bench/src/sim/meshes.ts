/**
 * GET /meshes/{id}의 바이너리를 읽는다 (contracts/sim/scene.schema.json의 Mesh 설명):
 * [꼭짓점 수 u32, 삼각형 수 u32, 꼭짓점 xyz f32..., 삼각형 꼭짓점 번호 u32...] little endian
 */

export interface MeshData {
  positions: Float32Array
  indices: Uint32Array
}

const HEADER_BYTES = 8
const FLOATS_PER_VERTEX = 3
const INDICES_PER_FACE = 3
const BYTES_PER_VALUE = 4

export class MeshFormatError extends Error {}

export function parseMesh(buffer: ArrayBuffer): MeshData {
  if (buffer.byteLength < HEADER_BYTES) {
    throw new MeshFormatError('메시 머리말이 짧습니다')
  }
  const header = new DataView(buffer)
  const vertexCount = header.getUint32(0, true)
  const faceCount = header.getUint32(4, true)
  const positionBytes = vertexCount * FLOATS_PER_VERTEX * BYTES_PER_VALUE
  const indexBytes = faceCount * INDICES_PER_FACE * BYTES_PER_VALUE
  if (buffer.byteLength !== HEADER_BYTES + positionBytes + indexBytes) {
    throw new MeshFormatError(`메시 크기가 머리말과 다릅니다 (꼭짓점 ${vertexCount}, 삼각형 ${faceCount})`)
  }
  // 바이너리를 그대로 복사해 정렬된 배열로 쓴다 (머리말 8바이트 뒤라 4바이트 정렬이 맞는다).
  const positions = new Float32Array(buffer.slice(HEADER_BYTES, HEADER_BYTES + positionBytes))
  const indices = new Uint32Array(buffer.slice(HEADER_BYTES + positionBytes))
  const outOfRange = indices.find((index) => index >= vertexCount)
  if (outOfRange !== undefined) {
    throw new MeshFormatError(`삼각형이 없는 꼭짓점(${outOfRange})을 가리킵니다`)
  }
  return { positions, indices }
}

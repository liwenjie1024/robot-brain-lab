import { describe, expect, it } from 'vitest'
import { MeshFormatError, parseMesh } from './meshes'

function meshBuffer(vertices: number[], faces: number[], vertexCount = vertices.length / 3, faceCount = faces.length / 3) {
  const buffer = new ArrayBuffer(8 + vertices.length * 4 + faces.length * 4)
  const view = new DataView(buffer)
  view.setUint32(0, vertexCount, true)
  view.setUint32(4, faceCount, true)
  vertices.forEach((value, index) => view.setFloat32(8 + index * 4, value, true))
  faces.forEach((value, index) => view.setUint32(8 + vertices.length * 4 + index * 4, value, true))
  return buffer
}

describe('parseMesh', () => {
  it('꼭짓점과 삼각형을 읽는다', () => {
    const mesh = parseMesh(meshBuffer([0, 0, 0, 1, 0, 0, 0, 1, 0], [0, 1, 2]))

    expect([...mesh.positions]).toEqual([0, 0, 0, 1, 0, 0, 0, 1, 0])
    expect([...mesh.indices]).toEqual([0, 1, 2])
  })

  it('실패: 크기가 머리말과 다르면 거절한다', () => {
    expect(() => parseMesh(meshBuffer([0, 0, 0], [0, 0, 0], 2, 1))).toThrow(MeshFormatError)
  })

  it('실패: 없는 꼭짓점을 가리키는 삼각형은 거절한다', () => {
    expect(() => parseMesh(meshBuffer([0, 0, 0, 1, 0, 0, 0, 1, 0], [0, 1, 3]))).toThrow('없는 꼭짓점(3)')
  })

  it('경계값: 머리말보다 짧으면 거절한다', () => {
    expect(() => parseMesh(new ArrayBuffer(7))).toThrow('머리말이 짧습니다')
  })
})

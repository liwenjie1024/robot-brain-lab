import { describe, expect, it } from 'vitest'
import { decodeMesh, fetchMesh } from '@/sim/meshes'
import { triangleMeshBytes } from '@/test/samples'

describe('网格的二进制', () => {
  it('解出点和三角形', () => {
    const mesh = decodeMesh(triangleMeshBytes())
    expect([...mesh.vertices]).toEqual([0, 0, 0, 1, 0, 0, 0, 1, 0])
    expect([...mesh.triangles]).toEqual([0, 1, 2])
  })

  it('解出来的是自己的一份，不连着收到的那一块', () => {
    const bytes = triangleMeshBytes()
    const mesh = decodeMesh(bytes)
    new DataView(bytes).setFloat32(8, 99, true)
    expect(mesh.vertices[0]).toBe(0)
  })

  it('没有点也没有面的网格（只有开头）：解得出来，是空的', () => {
    const mesh = decodeMesh(new ArrayBuffer(8))
    expect(mesh.vertices.length).toBe(0)
    expect(mesh.triangles.length).toBe(0)
  })

  it.each([
    ['空的', 0],
    ['连开头都不够', 7],
  ])('%s：太短了，拒绝', (_name, length) => {
    expect(() => decodeMesh(new ArrayBuffer(length))).toThrow('网格的数据太短了')
  })

  it.each([
    ['少了一个字节', -1],
    ['多了一个字节', 1],
    ['少了一个三角形', -12],
  ])('%s：长度和它说的对不上，拒绝', (_name, change) => {
    const bytes = triangleMeshBytes()
    const wrong = new Uint8Array(bytes.byteLength + change)
    wrong.set(new Uint8Array(bytes).subarray(0, Math.min(bytes.byteLength, wrong.length)))
    expect(() => decodeMesh(wrong.buffer)).toThrow('长度和它说的点数、面数对不上')
  })

  it('三角形指到了没有的点：拒绝', () => {
    const bytes = triangleMeshBytes()
    new DataView(bytes).setUint32(8 + 36 + 8, 3, true)
    expect(() => decodeMesh(bytes)).toThrow('网格的三角形指到了没有的点')
  })
})

describe('从仿真拿网格', () => {
  it('按编号去拿，解出来', async () => {
    const asked: string[] = []
    const request = (async (url: string) => {
      asked.push(url)
      return new Response(triangleMeshBytes())
    }) as typeof fetch
    const mesh = await fetchMesh('/sim', 7, request)
    expect(asked).toEqual(['/sim/mesh/7'])
    expect(mesh.triangles.length).toBe(3)
  })

  it('仿真说没有这个网格：报错，带着编号', async () => {
    const request = (async () => new Response('没有', { status: 404 })) as typeof fetch
    await expect(fetchMesh('/sim', 9, request)).rejects.toThrow('拿不到第 9 个网格（404）')
  })
})

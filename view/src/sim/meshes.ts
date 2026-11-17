// 网格（现成模型的外形）：仿真用二进制给，这里解出来。
// 格式（都是小端）：点的个数、面的个数（各一个 32 位无符号整数），
// 然后是每个点的 x、y、z（32 位浮点数），然后是每个三角形三个点的编号（32 位无符号整数）。

export interface MeshData {
  /** 每个点的 x、y、z，连着排。 */
  vertices: Float32Array
  /** 每个三角形三个点的编号，连着排。 */
  triangles: Uint32Array
}

const HEADER_BYTES = 8
const BYTES_PER_NUMBER = 4
const NUMBERS_PER_POINT = 3
const POINTS_PER_TRIANGLE = 3

/** 把仿真给的二进制解成点和三角形。长度对不上、编号指到没有的点，都报错。 */
export function decodeMesh(buffer: ArrayBuffer): MeshData {
  if (buffer.byteLength < HEADER_BYTES) throw new Error('网格的数据太短了')
  const header = new DataView(buffer)
  const pointCount = header.getUint32(0, true)
  const triangleCount = header.getUint32(BYTES_PER_NUMBER, true)
  const vertexBytes = pointCount * NUMBERS_PER_POINT * BYTES_PER_NUMBER
  const triangleBytes = triangleCount * POINTS_PER_TRIANGLE * BYTES_PER_NUMBER
  if (buffer.byteLength !== HEADER_BYTES + vertexBytes + triangleBytes) {
    throw new Error('网格的数据长度和它说的点数、面数对不上')
  }
  // 复制一份（slice）：这样数据从 4 的倍数开始，也不再连着网络收到的那一块。
  const vertices = new Float32Array(buffer.slice(HEADER_BYTES, HEADER_BYTES + vertexBytes))
  const triangles = new Uint32Array(buffer.slice(HEADER_BYTES + vertexBytes))
  if (triangles.some((point) => point >= pointCount)) throw new Error('网格的三角形指到了没有的点')
  return { vertices, triangles }
}

/** 从仿真拿一个身体的一个网格。按身体拿：拿的中间测试台上换了身体，拿到的也还是这个身体的。 */
export async function fetchMesh(
  baseUrl: string,
  body: string,
  id: number,
  request: typeof fetch = fetch,
): Promise<MeshData> {
  const response = await request(`${baseUrl}/mesh/${encodeURIComponent(body)}/${id}`)
  if (!response.ok) throw new Error(`拿不到第 ${id} 个网格（${response.status}）`)
  return decodeMesh(await response.arrayBuffer())
}

// 网页眼里的仿真：连没连上、身体的样子、现在的状态、能发的命令。画面的各个部分都从这里拿。
import { computed, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import type { ComputedRef, Ref, ShallowRef } from 'vue'
import { readScene } from '@/sim/contracts'
import { shouldShow } from '@/sim/display'
import { SimLink } from '@/sim/link'
import type { LinkStatus, SocketLike } from '@/sim/link'
import { fetchMesh } from '@/sim/meshes'
import type { MeshData } from '@/sim/meshes'
import type { PushBody } from '@/generated/command'
import type { State } from '@/generated/message'
import type { Scene } from '@/generated/scene'

/** 仿真在哪：开发服务器把 /sim 转给仿真（vite.config.ts）。 */
export const SIM_BASE = '/sim'

export interface LoadProgress {
  done: number
  total: number
}

export interface Sim {
  /** 和仿真的连接。 */
  link: Ref<LinkStatus>
  /** 身体的样子。还没拿到是 null。 */
  scene: ShallowRef<Scene | null>
  /** 这个身体用到的网格，按编号放。 */
  meshes: ShallowRef<ReadonlyMap<number, MeshData>>
  /** 正在拿身体的样子和网格时，拿了几样、一共几样；没在拿是 null。 */
  loading: Ref<LoadProgress | null>
  /** 身体的样子没拿到时的原因。 */
  sceneError: Ref<string | null>
  /** 画面上用的状态（隔 0.1 秒换一次，重要的变化马上换）。 */
  shown: ShallowRef<State | null>
  /** 收到了读不懂的消息时，说是什么。 */
  problem: Ref<string | null>
  /** 连接断着：画面上的数是断开之前的，不是现在的。 */
  stale: ComputedRef<boolean>
  /** 最新的状态（给 3D 用，每一条都要）。和手里的样子不是同一个身体时是 null。 */
  latest(): State | null
  start(): void
  stop(): void
  retryLink(): void
  retryScene(): void
  reset(): Promise<void>
  pause(): Promise<void>
  resume(): Promise<void>
  setControl(on: boolean): Promise<void>
  /** 在胸上推一下：往哪边，力是体重的多少倍。 */
  pushBody(direction: PushBody['direction'], share: number): Promise<void>
  selectBody(body: string): Promise<void>
}

export interface SimDependencies {
  makeSocket?: (url: string) => SocketLike
  request?: typeof fetch
  now?: () => number
  socketUrl?: string
}

function defaultSocketUrl(): string {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${location.host}${SIM_BASE}/ws`
}

/** 做出一个"网页眼里的仿真"。不依赖画面，测试时把连接和网络换成假的。 */
export function createSim(dependencies: SimDependencies = {}): Sim {
  const request = dependencies.request ?? ((...args: Parameters<typeof fetch>) => fetch(...args))
  const now = dependencies.now ?? (() => performance.now())
  const link = ref<LinkStatus>('connecting')
  const scene = shallowRef<Scene | null>(null)
  const meshes = shallowRef<ReadonlyMap<number, MeshData>>(new Map())
  const loading = ref<LoadProgress | null>(null)
  const sceneError = ref<string | null>(null)
  const shown = shallowRef<State | null>(null)
  const problem = ref<string | null>(null)
  let latestState: State | null = null
  let shownAtMs = 0
  let loadingBody: string | null = null
  let loadNumber = 0

  /** 状态是不是手里这个样子的身体的。不是的话数组的长短都对不上，不能用。 */
  const matchesScene = (state: State | null): state is State => state !== null && state.body === scene.value?.body

  async function loadScene(body: string): Promise<void> {
    const number = ++loadNumber
    loadingBody = body
    sceneError.value = null
    loading.value = { done: 0, total: 1 }
    try {
      const response = await request(`${SIM_BASE}/scene`)
      if (!response.ok) throw new Error(`仿真没有给出身体的样子（${response.status}）`)
      const loaded = readScene(await response.json())
      loading.value = { done: 1, total: 1 + loaded.meshes.length }
      const loadedMeshes = new Map<number, MeshData>()
      await Promise.all(
        loaded.meshes.map(async (mesh) => {
          loadedMeshes.set(mesh.id, await fetchMesh(SIM_BASE, mesh.id, request))
          if (number === loadNumber && loading.value) loading.value = { ...loading.value, done: loading.value.done + 1 }
        }),
      )
      // 拿的中间又换了身体的话，这一次拿到的不要了。
      if (number !== loadNumber) return
      meshes.value = loadedMeshes
      scene.value = loaded
      // 画面上还留着上一个身体的状态的话，拿掉：它和新的样子对不上。
      shown.value = matchesScene(latestState) ? latestState : null
      loading.value = null
      loadingBody = null
    } catch (error) {
      if (number !== loadNumber) return
      loading.value = null
      loadingBody = null
      sceneError.value = error instanceof Error ? error.message : String(error)
    }
  }

  /** 测试台上的身体和手里的样子不一样了（刚连上，或者换了身体）：去拿新的。 */
  function followBody(body: string): void {
    if (scene.value?.body === body || loadingBody === body) return
    // 出过错的不自己反复去拿，等人点"再试一次"。
    if (sceneError.value !== null) return
    void loadScene(body)
  }

  const simLink = new SimLink(
    dependencies.socketUrl ?? defaultSocketUrl(),
    {
      onStatus: (status) => {
        link.value = status
      },
      onHello: (hello) => {
        problem.value = null
        followBody(hello.body)
      },
      onState: (state) => {
        latestState = state
        followBody(state.body)
        if (!matchesScene(state)) return
        const time = now()
        if (shouldShow(shown.value, state, shownAtMs, time)) {
          shown.value = state
          shownAtMs = time
        }
      },
      onProblem: (text) => {
        problem.value = text
      },
    },
    dependencies.makeSocket,
  )

  return {
    link,
    scene,
    meshes,
    loading,
    sceneError,
    shown,
    problem,
    stale: computed(() => link.value !== 'open'),
    latest: () => (matchesScene(latestState) ? latestState : null),
    start: () => simLink.open(),
    stop: () => simLink.close(),
    retryLink: () => simLink.retryNow(),
    retryScene: () => {
      sceneError.value = null
      void loadScene(latestState?.body ?? scene.value?.body ?? '')
    },
    reset: () => simLink.send({ type: 'reset' }),
    pause: () => simLink.send({ type: 'pause' }),
    resume: () => simLink.send({ type: 'resume' }),
    setControl: (on) => simLink.send({ type: 'control', on }),
    pushBody: (direction, share) => simLink.send({ type: 'push', direction, share }),
    selectBody: (body) => simLink.send({ type: 'body', body }),
  }
}

/** 在画面里用：画面出现时连上仿真，画面关掉时断开。 */
export function useSim(): Sim {
  const sim = createSim()
  onMounted(sim.start)
  onUnmounted(sim.stop)
  return sim
}

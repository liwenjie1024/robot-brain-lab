// 网页眼里的仿真：连没连上、身体的样子、现在的状态、能发的命令。画面的各个部分都从这里拿。
import { computed, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import type { ComputedRef, Ref, ShallowRef } from 'vue'
import { readSceneText } from '@/sim/contracts'
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

/** 一个身体的样子在哪拿。按身体拿：拿的中间测试台上换了身体，拿到的也还是要的那个。 */
export function sceneUrl(body: string): string {
  return `${SIM_BASE}/scene/${encodeURIComponent(body)}`
}

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
  /** 测试台上现在是哪个身体（招呼和状态里说的）。 */
  let benchBody: string | null = null
  let loadingBody: string | null = null
  let loadNumber = 0
  /** 手里这份样子的原文。重新连上以后再拿一次，一个字都没变就不用重新搭、不用再拿网格。 */
  let sceneText: string | null = null

  /** 状态能不能用：是手里这个样子的身体的，而且没在拿样子（再拿的时候身体可能改过，数组的长短会对不上）。 */
  const matchesScene = (state: State | null): state is State =>
    state !== null && loadingBody === null && state.body === scene.value?.body

  async function loadScene(body: string): Promise<void> {
    const number = ++loadNumber
    loadingBody = body
    sceneError.value = null
    // 再拿一次手里这个身体的样子（重新连上了）：先不挡住画面，样子真的变了才说"正在拿"。
    const again = scene.value?.body === body
    if (!again) loading.value = { done: 0, total: 1 }
    try {
      const response = await request(sceneUrl(body))
      if (!response.ok) throw new Error(`仿真没有给出身体的样子（${response.status}）`)
      const text = await response.text()
      // 拿的中间又换了身体、又重新连上了的话，这一次拿到的不要了。
      if (number !== loadNumber) return
      if (again && text === sceneText) {
        finishLoading(false)
        return
      }
      const loaded = readSceneText(text)
      loading.value = { done: 1, total: 1 + loaded.meshes.length }
      const loadedMeshes = new Map<number, MeshData>()
      await Promise.all(
        loaded.meshes.map(async (mesh) => {
          loadedMeshes.set(mesh.id, await fetchMesh(SIM_BASE, body, mesh.id, request))
          if (number === loadNumber && loading.value) loading.value = { ...loading.value, done: loading.value.done + 1 }
        }),
      )
      if (number !== loadNumber) return
      meshes.value = loadedMeshes
      scene.value = loaded
      sceneText = text
      finishLoading(true)
    } catch (error) {
      if (number !== loadNumber) return
      loading.value = null
      loadingBody = null
      sceneError.value = error instanceof Error ? error.message : String(error)
    }
  }

  /** 拿完了。有能用的新状态就用；样子变了的话，画面上留着的旧状态不能再用（和新的样子对不上）。 */
  function finishLoading(changed: boolean): void {
    loading.value = null
    loadingBody = null
    if (matchesScene(latestState)) shown.value = latestState
    else if (changed) shown.value = null
  }

  /** 测试台上的身体和手里的样子不一样了（换了身体）：去拿新的。 */
  function followBody(body: string): void {
    if (scene.value?.body === body || loadingBody === body) return
    // 出过错的不自己反复去拿（状态一秒来 30 条），等人点"再试一次"，或者等下一次连上。
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
        benchBody = hello.body
        // 每次连上都再拿一次样子：仿真可能重启过、身体可能改过；上次没拿到的，也再试一次。
        // 以前收到的状态是上一次连着时的，不再用。
        latestState = null
        void loadScene(hello.body)
      },
      onState: (state) => {
        latestState = state
        benchBody = state.body
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
      if (benchBody !== null) void loadScene(benchBody)
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

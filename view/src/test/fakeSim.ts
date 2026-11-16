// 测试画面用的假仿真：状态由测试来摆，命令只是记下来。
import { computed, defineComponent, h, ref, shallowRef } from 'vue'
import type { Component } from 'vue'
import { mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { vi } from 'vitest'
import type { Mock } from 'vitest'
import type { LinkStatus } from '@/sim/link'
import type { MeshData } from '@/sim/meshes'
import type { LoadProgress, Sim } from '@/sim/useSim'
import type { State } from '@/generated/message'
import type { Scene } from '@/generated/scene'

type Commands = 'reset' | 'pause' | 'resume' | 'setControl' | 'pushBody' | 'selectBody'
type Actions = 'start' | 'stop' | 'retryLink' | 'retryScene'
export type FakeSim = Sim & Record<Commands | Actions, Mock>

/** 一个连着的、已经拿到样子和状态的仿真。scene、state 给 null 就是还没拿到。 */
export function fakeSim(scene: Scene | null, state: State | null): FakeSim {
  const link = ref<LinkStatus>('open')
  const shown = shallowRef<State | null>(state)
  const done = () => vi.fn(async () => undefined)
  return {
    link,
    scene: shallowRef<Scene | null>(scene),
    meshes: shallowRef<ReadonlyMap<number, MeshData>>(new Map()),
    loading: ref<LoadProgress | null>(null),
    sceneError: ref<string | null>(null),
    shown,
    problem: ref<string | null>(null),
    stale: computed(() => link.value !== 'open'),
    latest: () => shown.value,
    start: vi.fn(),
    stop: vi.fn(),
    retryLink: vi.fn(),
    retryScene: vi.fn(),
    reset: done(),
    pause: done(),
    resume: done(),
    setControl: done(),
    pushBody: done(),
    selectBody: done(),
  }
}

/** 把一块画面放到页面上。外面包一层"弹出提示"的地方（有的画面出错时要弹提示）。 */
export function show(component: Component, sim: Sim): VueWrapper {
  const host = defineComponent({
    render: () => h(NMessageProvider, null, { default: () => h(component, { sim }) }),
  })
  return mount(host, { attachTo: document.body })
}

/** 找出写着这几个字的按钮。 */
export function button(wrapper: VueWrapper, text: string) {
  const found = wrapper.findAll('button').find((candidate) => candidate.text().includes(text))
  if (!found) throw new Error(`没有写着"${text}"的按钮`)
  return found
}

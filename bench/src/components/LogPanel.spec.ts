import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { Decision } from '@shared/brain/generated/status'
import { NAMES } from '@shared/test/fixtures'
import LogPanel from './LogPanel.vue'

const DECISION: Decision = { type: 'decision', seq: 2, simTime: 4.2, kind: 'reflex', text: '표적 드론 2이(가) 조준함 → 피하기' }

function panel(decisions: Decision[] = []) {
  return mount(LogPanel, { props: { decisions, combat: [], commands: [], names: NAMES } })
}

describe('LogPanel', () => {
  it('판단·전투·보낸 명령을 탭으로 나누고 탭마다 몇 줄인지 보인다', () => {
    const tabs = panel([DECISION]).findAll('.n-tabs-tab').map((tab) => tab.text())

    expect(tabs).toEqual(['판단 기록 1', '전투 기록 0', '보낸 명령 0'])
  })

  it('판단 기록을 종류와 함께 보여 주고, 없으면 빈 상태를 알린다', () => {
    expect(panel([DECISION]).get('[data-test="decisions"]').text()).toContain('반사')
    expect(panel([DECISION]).get('[data-test="decisions"]').text()).toContain('4.2초')
    expect(panel().text()).toContain('아직 판단 기록이 없습니다')
  })

  it('다른 탭의 빈 상태도 미리 그려 두어, 탭을 바꿔도 칸 크기가 흔들리지 않는다', () => {
    const text = panel().text()

    expect(text).toContain('아직 사격이 없습니다')
    expect(text).toContain('아직 보낸 명령이 없습니다')
  })
})

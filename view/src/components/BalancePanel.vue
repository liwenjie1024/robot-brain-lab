<script setup lang="ts">
// 站得怎么样：歪了多少、地面托着多少，和从上面往下看的脚底（两只脚各托多少、压力中心和重心落在哪）。
import { computed } from 'vue'
import { NCard, NEmpty } from 'naive-ui'
import HelpTip from '@/components/HelpTip.vue'
import { footprint } from '@/sim/derive'
import type { Sim } from '@/sim/useSim'
import { asKilograms, asPercent, fixed, GRAVITY_M_S2, toDegrees } from '@/text/format'

const props = defineProps<{ sim: Sim }>()

// 图上画的范围（米）：左右各 0.3，前后各 0.25。够放下两只脚，也看得出压力中心往哪边跑。
const HALF_WIDTH_M = 0.3
const HALF_HEIGHT_M = 0.25
const VIEW_BOX = `${-HALF_WIDTH_M} ${-HALF_HEIGHT_M} ${2 * HALF_WIDTH_M} ${2 * HALF_HEIGHT_M}`
// 脚托着的越多，颜色越深：最浅和最深。
const LIGHTEST = 0.12
const DARKEST = 0.6

const state = computed(() => props.sim.shown.value)
const scene = computed(() => props.sim.scene.value)
const feet = computed(() => (scene.value && state.value ? footprint(scene.value, state.value) : null))
const weightN = computed(() => (scene.value?.mass_kg ?? 0) * GRAVITY_M_S2)

/** 地面上的一点（往前、往左，米）画在图上的哪里：往前是上，往左是左。 */
function onPicture(point: readonly [number, number]): { x: number; y: number } {
  return { x: -point[1], y: -point[0] }
}

function footTransform(center: readonly [number, number], headingRad: number): string {
  const { x, y } = onPicture(center)
  // 从上面看，往左转是逆时针；SVG 里正的角度是顺时针，所以反过来。
  return `translate(${x} ${y}) rotate(${-toDegrees(headingRad)})`
}

const shade = (share: number) => LIGHTEST + (DARKEST - LIGHTEST) * Math.min(share, 1)
</script>

<template>
  <n-card title="站得怎么样" size="small">
    <n-empty v-if="!state || !feet" description="还没有收到状态" size="small" />
    <template v-else>
      <dl class="facts">
        <div>
          <dt>骨盆歪了</dt>
          <dd>{{ fixed(state.tilt_deg, 1) }}°</dd>
        </div>
        <div>
          <dt>骨盆的高度</dt>
          <dd>{{ fixed(state.pelvis_height_m, 2) }} m</dd>
        </div>
        <div>
          <dt>
            地面托着
            <help-tip text="地面往上托着身体的力，写成相当于多少公斤。站稳的时候它正好等于体重。这是从仿真里直接量的，不是身体的传感器读的。" />
          </dt>
          <dd>{{ asKilograms(state.support_n) }}（体重 {{ asKilograms(weightN) }}）</dd>
        </div>
      </dl>

      <div class="feet">
        <svg class="feet-picture" :viewBox="VIEW_BOX" role="img" aria-label="从上面往下看的脚底">
          <line x1="0" :y1="-HALF_HEIGHT_M" x2="0" :y2="HALF_HEIGHT_M" class="axis" />
          <line :x1="-HALF_WIDTH_M" y1="0" :x2="HALF_WIDTH_M" y2="0" class="axis" />
          <g v-for="foot in feet.feet" :key="foot.label">
            <rect
              :x="-foot.widthM / 2"
              :y="-foot.lengthM / 2"
              :width="foot.widthM"
              :height="foot.lengthM"
              rx="0.012"
              class="foot"
              :fill-opacity="shade(foot.share)"
              :transform="footTransform(foot.center, foot.headingRad)"
            />
            <circle
              v-if="foot.pressureCenter"
              :cx="onPicture(foot.pressureCenter).x"
              :cy="onPicture(foot.pressureCenter).y"
              r="0.007"
              class="foot-center"
            />
          </g>
          <circle
            v-if="feet.pressureCenter"
            :cx="onPicture(feet.pressureCenter).x"
            :cy="onPicture(feet.pressureCenter).y"
            r="0.018"
            class="pressure"
          />
          <g :transform="`translate(${onPicture(feet.centerOfMass).x} ${onPicture(feet.centerOfMass).y})`" class="mass">
            <line x1="-0.02" y1="0" x2="0.02" y2="0" />
            <line x1="0" y1="-0.02" x2="0" y2="0.02" />
          </g>
          <text x="0" :y="-HALF_HEIGHT_M + 0.03" class="word">前</text>
          <text :x="-HALF_WIDTH_M + 0.03" y="0.012" class="word">左</text>
          <text :x="HALF_WIDTH_M - 0.03" y="0.012" class="word">右</text>
        </svg>

        <ul class="feet-list">
          <li v-for="foot in feet.feet" :key="foot.label">
            <span class="swatch foot-swatch" :style="{ opacity: shade(foot.share) }"></span>
            {{ foot.label }}：{{ asKilograms(foot.supportN) }}（{{ asPercent(foot.share) }}）
          </li>
          <li>
            <span class="swatch pressure-swatch"></span>压力中心
            <help-tip text="地面托着身体的力，合起来作用在哪一点。它只能在脚底下面那一块里；跑到脚的边上，身体就要倒了。小黑点是每只脚自己的压力中心。" />
          </li>
          <li><span class="swatch mass-swatch">+</span>重心落在地面上的位置</li>
          <li v-if="!feet.pressureCenter" class="warn" role="status">脚没有踩在地上</li>
        </ul>
      </div>
    </template>
  </n-card>
</template>

<style scoped>
.facts {
  display: grid;
  grid-template-columns: repeat(3, auto);
  gap: 4px 16px;
  margin: 0 0 10px;
}
.facts dt {
  color: #5c6370;
  font-size: 12px;
}
.facts dd {
  margin: 0;
  font-size: 15px;
  font-variant-numeric: tabular-nums;
}
.feet {
  display: flex;
  gap: 12px;
  align-items: center;
}
.feet-picture {
  flex: 0 0 190px;
  width: 190px;
  background: #f4f5f7;
  border-radius: 6px;
}
.axis {
  stroke: #d5d8de;
  stroke-width: 0.002;
}
.foot {
  fill: #1f6fd1;
  stroke: #3a3f4a;
  stroke-width: 0.003;
}
.foot-center {
  fill: #2b2f36;
}
.pressure {
  fill: none;
  stroke: #1f6fd1;
  stroke-width: 0.006;
}
.mass line {
  stroke: #d12d2d;
  stroke-width: 0.006;
}
.word {
  fill: #8a8f98;
  font-size: 0.03px;
  text-anchor: middle;
}
.feet-list {
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: 13px;
  line-height: 1.9;
  font-variant-numeric: tabular-nums;
}
.swatch {
  display: inline-block;
  width: 12px;
  height: 12px;
  margin-right: 6px;
  vertical-align: -1px;
  text-align: center;
  line-height: 12px;
}
.foot-swatch {
  background: #1f6fd1;
  border: 1px solid #3a3f4a;
}
.pressure-swatch {
  border: 2px solid #1f6fd1;
  border-radius: 50%;
}
.mass-swatch {
  color: #d12d2d;
  font-weight: 700;
}
.warn {
  color: #d12d2d;
}
</style>

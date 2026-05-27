<script setup>
import { computed } from 'vue'

const props = defineProps({
  score: { type: Number, default: 0 },
  maxScore: { type: Number, default: 100 },
  color: { type: String, default: 'var(--color-aic)' },
  label: { type: String, default: '' },
  size: { type: Number, default: 120 },
})

const safeScore = computed(() => Math.max(0, Math.min(Number(props.score) || 0, props.maxScore)))
const percent = computed(() => {
  const max = Number(props.maxScore) || 100
  return Math.max(0, Math.min((safeScore.value / max) * 100, 100))
})
</script>

<template>
  <div
    class="donut-wrap"
    :style="{ width: size + 'px', height: size + 'px' }"
    role="img"
    :aria-label="`${label || 'Score'} ${Math.round(safeScore)}점`"
  >
    <div
      class="donut-ring"
      :style="{ '--donut-color': color, '--donut-percent': `${percent}%` }"
    ></div>
    <div class="donut-center">
      <strong :style="{ color }">{{ Math.round(safeScore) }}</strong>
      <span v-if="label">{{ label }}</span>
    </div>
  </div>
</template>

<style scoped>
.donut-wrap {
  position: relative;
  display: inline-grid;
  place-items: center;
  flex-shrink: 0;
}

.donut-ring {
  position: absolute;
  inset: 0;
  border-radius: var(--radius-full);
  background: conic-gradient(var(--donut-color) var(--donut-percent), var(--color-gray-100) 0);
  transition: background var(--transition-base);
}

.donut-ring::after {
  content: '';
  position: absolute;
  inset: 12px;
  border-radius: var(--radius-full);
  background: var(--bg-surface);
}

.donut-center {
  position: relative;
  z-index: 1;
  display: grid;
  gap: 2px;
  place-items: center;
  line-height: 1.15;
  text-align: center;
}

.donut-center strong {
  font-size: 22px;
  font-weight: 800;
}

.donut-center span {
  color: var(--text-muted);
  font-size: 10px;
  font-weight: 700;
}
</style>

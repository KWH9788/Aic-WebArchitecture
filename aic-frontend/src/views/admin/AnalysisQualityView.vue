<script setup>
import { computed, onMounted, onUnmounted, watch } from 'vue'
import { useAdminAnalysisStore } from '@/stores/adminAnalysisStore'
import AppLayout from '@/components/layout/AppLayout.vue'
import AdminKpiCard from '@/components/admin/AdminKpiCard.vue'
import RuntimeBreakdownChart from '@/components/admin/RuntimeBreakdownChart.vue'

const store = useAdminAnalysisStore()
let poller = null

onMounted(async () => {
  await store.fetchRuns()
  poller = window.setInterval(() => {
    if (store.runningRun) store.fetchRuns()
  }, 5000)
})

onUnmounted(() => {
  if (poller) window.clearInterval(poller)
})

watch(
  () => [store.baselineRunId, store.optimizedRunId],
  ([baseline, optimized]) => {
    if (baseline && optimized && baseline !== optimized) {
      store.compareSelectedRuns()
    } else {
      store.comparison = null
    }
  }
)

const selectedRun = computed(() => store.selectedRun)
const activeRun = computed(() => store.runningRun || store.runs[0] || null)
const completedRuns = computed(() => store.completedRuns)
const progress = computed(() => {
  const run = activeRun.value
  if (!run?.total) return 0
  return Math.round((run.processed / run.total) * 100)
})

const kpis = computed(() => {
  const run = selectedRun.value || activeRun.value
  return [
    {
      label: 'p50 runtime',
      value: formatSec(run?.p50_runtime_sec),
      subText: 'warmup 제외 중앙값',
      status: 'neutral',
    },
    {
      label: 'p95 runtime',
      value: formatSec(run?.p95_runtime_sec),
      subText: '느린 sample 기준',
      status: run?.p95_runtime_sec && run.p95_runtime_sec > 30 ? 'warning' : 'success',
    },
    {
      label: '평균 runtime',
      value: formatSec(run?.avg_runtime_sec),
      subText: `${run?.processed || 0}/${run?.total || 0} processed`,
      status: 'neutral',
    },
    {
      label: '실패율',
      value: formatPct(run?.failure_rate),
      subText: `fallback ${formatPct(run?.fallback_rate)}`,
      status: run?.failure_rate > 0 ? 'warning' : 'success',
    },
  ]
})

const comparisonCards = computed(() => {
  const comparison = store.comparison
  if (!comparison) return []
  return [
    ['p50', comparison.runtime?.p50],
    ['p95', comparison.runtime?.p95],
    ['평균', comparison.runtime?.avg],
    ['실패율', comparison.failure_rate],
    ['fallback', comparison.fallback_rate],
  ].map(([label, metric]) => ({
    label,
    baseline: formatMetric(metric?.baseline),
    optimized: formatMetric(metric?.optimized),
    delta: formatDelta(metric?.delta, metric?.percent_change),
    tone: metric?.delta < 0 ? 'good' : metric?.delta > 0 ? 'bad' : 'neutral',
  }))
})

const stageRows = computed(() => {
  const stageRuntime = store.comparison?.stage_runtime || {}
  return Object.entries(stageRuntime).map(([name, metric]) => ({
    name,
    baseline: formatSec(metric.baseline),
    optimized: formatSec(metric.optimized),
    delta: formatDelta(metric.delta, metric.percent_change),
  }))
})
const selectedStageSteps = computed(() => {
  const totals = selectedRun.value?.stage_runtime_totals || {}
  return Object.entries(totals).map(([name, seconds]) => ({ name, seconds, status: 'success' }))
})
const scoreDeltaRows = computed(() => {
  const metrics = store.comparison?.score_delta?.metrics || {}
  return ['aic', 'pi', 'ui', 'oi', 'topic']
    .filter((name) => metrics[name])
    .map((name) => ({
      name: name.toUpperCase(),
      count: metrics[name].count || 0,
      avgAbs: formatScoreDelta(metrics[name].avg_abs_delta),
      maxAbs: formatScoreDelta(metrics[name].max_abs_delta),
      within1: formatCount(metrics[name].within_1pt_count, metrics[name].count),
      within3: formatCount(metrics[name].within_3pt_count, metrics[name].count),
    }))
})

function selectRun(runId) {
  store.fetchRunDetail(runId)
}

function statusLabel(status) {
  return {
    pending: '대기',
    running: '실행 중',
    completed: '완료',
    failed: '실패',
    canceled: '취소',
  }[status] || status
}

function statusTone(status) {
  return status === 'completed' ? 'success' : status === 'failed' ? 'danger' : 'neutral'
}

function formatSec(value) {
  const next = Number(value)
  return Number.isFinite(next) ? `${next.toFixed(3)}s` : '-'
}

function formatPct(value) {
  const next = Number(value)
  return Number.isFinite(next) ? `${next.toFixed(1)}%` : '-'
}

function formatMetric(value) {
  const next = Number(value)
  return Number.isFinite(next) ? next.toFixed(3) : '-'
}

function formatDelta(delta, percentChange) {
  const next = Number(delta)
  if (!Number.isFinite(next)) return '-'
  const pct = Number.isFinite(Number(percentChange)) ? ` (${Number(percentChange).toFixed(1)}%)` : ''
  return `${next > 0 ? '+' : ''}${next.toFixed(3)}${pct}`
}

function formatScoreDelta(value) {
  const next = Number(value)
  return Number.isFinite(next) ? `${next.toFixed(1)}pt` : '-'
}

function formatCount(value, total) {
  const next = Number(value)
  const totalCount = Number(total)
  if (!Number.isFinite(next) || !Number.isFinite(totalCount) || totalCount <= 0) return '-'
  return `${next}/${totalCount}`
}
</script>

<template>
  <AppLayout title="AIC 분석 품질 모니터" subtitle="최근 제출 50건 benchmark 기반 성능 비교">
    <div v-if="store.error" class="error-state">{{ store.error }}</div>

    <section class="toolbar-band">
      <div>
        <h2>Benchmark Runs</h2>
        <p>운영 분석 결과를 덮어쓰지 않고 최근 제출 snapshot으로 pipeline 성능을 비교합니다.</p>
      </div>
      <button class="primary-action" :disabled="store.starting" @click="store.startBenchmark">
        {{ store.starting ? '실행 요청 중...' : '최근 제출 50건 benchmark 실행' }}
      </button>
    </section>

    <section v-if="activeRun" class="progress-band">
      <div class="progress-copy">
        <span class="status-pill" :class="statusTone(activeRun.status)">{{ statusLabel(activeRun.status) }}</span>
        <strong>{{ activeRun.run_id }}</strong>
        <span>{{ activeRun.processed }} / {{ activeRun.total }} processed</span>
        <span>{{ activeRun.failed }} failed</span>
      </div>
      <div class="progress-track" aria-label="benchmark progress">
        <div class="progress-fill" :style="{ width: `${progress}%` }"></div>
      </div>
    </section>

    <div class="kpi-grid">
      <AdminKpiCard
        v-for="kpi in kpis"
        :key="kpi.label"
        :label="kpi.label"
        :value="kpi.value"
        :sub-text="kpi.subText"
        :status="kpi.status"
      />
    </div>

    <section class="run-list-band">
      <div class="section-heading">
        <h2>완료된 benchmark 선택</h2>
        <button class="text-action" :disabled="store.loading" @click="store.fetchRuns">새로고침</button>
      </div>
      <div v-if="store.loading && !store.runs.length" class="empty-state">benchmark 목록을 불러오는 중...</div>
      <div v-else-if="!store.runs.length" class="empty-state">아직 benchmark run이 없습니다.</div>
      <div v-else class="run-table">
        <button
          v-for="run in store.runs"
          :key="run.run_id"
          class="run-row"
          :class="{ selected: selectedRun?.run_id === run.run_id }"
          @click="selectRun(run.run_id)"
        >
          <span class="run-id">{{ run.run_id }}</span>
          <span class="status-pill" :class="statusTone(run.status)">{{ statusLabel(run.status) }}</span>
          <span>{{ run.processed }}/{{ run.total }}</span>
          <span>p50 {{ formatSec(run.p50_runtime_sec) }}</span>
          <span>p95 {{ formatSec(run.p95_runtime_sec) }}</span>
          <span>fail {{ formatPct(run.failure_rate) }}</span>
        </button>
      </div>
    </section>

    <section class="compare-band">
      <div class="section-heading">
        <h2>Baseline / Optimized 비교</h2>
        <button
          class="text-action"
          :disabled="!store.baselineRunId || !store.optimizedRunId || store.baselineRunId === store.optimizedRunId || store.comparing"
          @click="store.compareSelectedRuns"
        >
          {{ store.comparing ? '비교 중...' : '비교 실행' }}
        </button>
      </div>
      <div class="selector-grid">
        <label>
          <span>Baseline run</span>
          <select v-model="store.baselineRunId">
            <option value="">선택</option>
            <option v-for="run in completedRuns" :key="run.run_id" :value="run.run_id">
              {{ run.run_id }}
            </option>
          </select>
        </label>
        <label>
          <span>Optimized run</span>
          <select v-model="store.optimizedRunId">
            <option value="">선택</option>
            <option v-for="run in completedRuns" :key="run.run_id" :value="run.run_id">
              {{ run.run_id }}
            </option>
          </select>
        </label>
      </div>

      <div v-if="store.comparison?.warnings?.length" class="warning-strip">
        <span v-for="warning in store.comparison.warnings" :key="warning">{{ warning }}</span>
      </div>

      <div v-if="comparisonCards.length" class="comparison-grid">
        <div v-for="item in comparisonCards" :key="item.label" class="comparison-cell" :class="item.tone">
          <span>{{ item.label }}</span>
          <strong>{{ item.delta }}</strong>
          <small>{{ item.baseline }} -> {{ item.optimized }}</small>
        </div>
      </div>
    </section>

    <section v-if="scoreDeltaRows.length" class="score-band">
      <div class="section-heading">
        <h2>점수 안정성</h2>
        <span class="section-note">공통 submission {{ store.comparison?.score_delta?.common_submission_count || 0 }}건 기준</span>
      </div>
      <div class="score-table">
        <div class="score-row score-head">
          <span>Metric</span>
          <span>Avg |delta|</span>
          <span>Max |delta|</span>
          <span>≤1pt</span>
          <span>≤3pt</span>
        </div>
        <div v-for="row in scoreDeltaRows" :key="row.name" class="score-row">
          <strong>{{ row.name }}</strong>
          <span>{{ row.avgAbs }}</span>
          <span>{{ row.maxAbs }}</span>
          <span>{{ row.within1 }}</span>
          <span>{{ row.within3 }}</span>
        </div>
      </div>
    </section>

    <div class="detail-grid">
      <section class="detail-band">
        <div class="section-heading">
          <h2>단계별 runtime 합계</h2>
        </div>
        <div v-if="stageRows.length" class="stage-table">
          <div v-for="row in stageRows" :key="row.name" class="stage-row">
            <span>{{ row.name }}</span>
            <span>{{ row.baseline }}</span>
            <span>{{ row.optimized }}</span>
            <strong>{{ row.delta }}</strong>
          </div>
        </div>
        <RuntimeBreakdownChart v-else-if="selectedStageSteps.length" :steps="selectedStageSteps" />
        <div v-else class="empty-state">비교할 단계별 runtime 데이터가 없습니다.</div>
      </section>

      <section class="detail-band">
        <div class="section-heading">
          <h2>Sample outliers</h2>
        </div>
        <div v-if="store.comparison?.outliers?.length" class="outlier-list">
          <div v-for="item in store.comparison.outliers" :key="item.submission_id" class="outlier-row">
            <span>#{{ item.submission_id }}</span>
            <strong>{{ formatDelta(item.delta_runtime_sec, item.percent_change) }}</strong>
            <small>{{ formatSec(item.baseline_runtime_sec) }} -> {{ formatSec(item.optimized_runtime_sec) }}</small>
          </div>
        </div>
        <div v-else class="empty-state">outlier 비교 결과가 없습니다.</div>
      </section>
    </div>
  </AppLayout>
</template>

<style scoped>
.error-state,
.empty-state {
  padding: var(--space-4);
  color: var(--text-muted);
  font-size: var(--font-size-sm);
}

.error-state {
  color: var(--color-danger);
}

.toolbar-band,
.progress-band,
.run-list-band,
.compare-band,
.score-band,
.detail-band {
  border-top: 1px solid var(--border-light);
  padding: var(--space-5) 0;
}

.toolbar-band,
.section-heading,
.progress-copy {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
}

.toolbar-band h2,
.section-heading h2 {
  margin: 0;
  font-size: var(--font-size-lg);
}

.section-note {
  color: var(--text-muted);
  font-size: var(--font-size-sm);
}

.toolbar-band p {
  margin: var(--space-1) 0 0;
  color: var(--text-muted);
  font-size: var(--font-size-sm);
}

.primary-action,
.text-action {
  min-height: 38px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  background: var(--color-aic);
  color: white;
  font-weight: 700;
  padding: 0 var(--space-4);
  cursor: pointer;
}

.text-action {
  background: var(--bg-surface);
  color: var(--text-primary);
}

.primary-action:disabled,
.text-action:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.progress-copy {
  justify-content: flex-start;
  flex-wrap: wrap;
  margin-bottom: var(--space-3);
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
}

.progress-track {
  height: 10px;
  overflow: hidden;
  background: var(--color-gray-100);
  border-radius: var(--radius-sm);
}

.progress-fill {
  height: 100%;
  background: var(--color-aic);
  transition: width 0.25s ease;
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-4);
  margin: var(--space-5) 0;
}

.run-table {
  display: grid;
  gap: var(--space-2);
}

.run-row {
  display: grid;
  grid-template-columns: minmax(180px, 1.6fr) 90px repeat(4, minmax(84px, 1fr));
  gap: var(--space-3);
  align-items: center;
  min-height: 48px;
  width: 100%;
  padding: 0 var(--space-3);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  background: var(--bg-surface);
  color: var(--text-primary);
  cursor: pointer;
  text-align: left;
}

.run-row.selected {
  border-color: var(--color-aic);
  box-shadow: 0 0 0 1px var(--color-aic);
}

.run-id {
  font-family: Consolas, monospace;
  font-size: var(--font-size-xs);
}

.status-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 24px;
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--color-gray-100);
  color: var(--text-secondary);
  font-size: var(--font-size-xs);
  font-weight: 700;
}

.status-pill.success { color: var(--color-success); }
.status-pill.danger { color: var(--color-danger); }

.selector-grid,
.comparison-grid,
.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-4);
  margin-top: var(--space-4);
}

.selector-grid label {
  display: grid;
  gap: var(--space-2);
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
}

.selector-grid select {
  width: 100%;
  min-height: 40px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  background: var(--bg-surface);
  color: var(--text-primary);
  padding: 0 var(--space-3);
}

.warning-strip {
  display: grid;
  gap: var(--space-2);
  margin-top: var(--space-4);
  color: var(--color-warning);
  font-size: var(--font-size-sm);
}

.comparison-grid {
  grid-template-columns: repeat(5, minmax(0, 1fr));
}

.comparison-cell {
  display: grid;
  gap: var(--space-1);
  min-height: 96px;
  padding: var(--space-3);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  background: var(--bg-surface);
}

.comparison-cell span,
.comparison-cell small {
  color: var(--text-muted);
  font-size: var(--font-size-xs);
}

.comparison-cell strong {
  font-size: var(--font-size-lg);
}

.comparison-cell.good strong { color: var(--color-success); }
.comparison-cell.bad strong { color: var(--color-danger); }

.stage-table,
.score-table,
.outlier-list {
  display: grid;
  gap: var(--space-2);
  margin-top: var(--space-3);
}

.stage-row,
.score-row,
.outlier-row {
  display: grid;
  grid-template-columns: 1.2fr repeat(3, minmax(78px, 1fr));
  gap: var(--space-3);
  align-items: center;
  min-height: 40px;
  border-bottom: 1px solid var(--border-light);
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
}

.score-row {
  grid-template-columns: 90px repeat(4, minmax(72px, 1fr));
}

.score-head {
  color: var(--text-muted);
  font-size: var(--font-size-xs);
  font-weight: 700;
}

.outlier-row {
  grid-template-columns: 80px 1fr 1.4fr;
}

@media (max-width: 1100px) {
  .kpi-grid,
  .comparison-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .run-row {
    grid-template-columns: 1fr 90px;
  }

  .run-row span:nth-child(n + 3) {
    display: none;
  }
}

@media (max-width: 760px) {
  .toolbar-band,
  .section-heading {
    align-items: flex-start;
    flex-direction: column;
  }

  .kpi-grid,
  .selector-grid,
  .comparison-grid,
  .detail-grid {
    grid-template-columns: 1fr;
  }
}
</style>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getStudentDashboard } from '@/api'
import AppLayout from '@/components/layout/AppLayout.vue'
import DonutChart from '@/components/common/DonutChart.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import LoadingSkeleton from '@/components/common/LoadingSkeleton.vue'
import LineChart from '@/components/charts/LineChart.vue'
import BarChart from '@/components/charts/BarChart.vue'

const router = useRouter()
const dashboard = ref(null)
const loading = ref(true)
const error = ref('')

const subMetrics = [
  { key: 'pi', label: 'PI', name: 'Prompt Insight', short: 'PI', color: 'var(--color-pi)', pale: 'var(--color-pi-pale)', icon: 'i' },
  { key: 'ui', label: 'UI', name: 'User Intervention', short: 'UI', color: 'var(--color-ui)', pale: 'var(--color-ui-pale)', icon: '✎' },
  { key: 'oi', label: 'OI', name: 'Originality Index', short: 'OI', color: 'var(--color-oi)', pale: 'var(--color-oi-pale)', icon: '!' },
  { key: 'topic', label: 'Topic', name: 'Topic Score', short: 'TS', color: 'var(--color-topic)', pale: 'var(--color-topic-pale)', icon: '⌘' },
]

onMounted(async () => {
  try {
    dashboard.value = await getStudentDashboard()
  } catch (e) {
    error.value = '대시보드 데이터를 불러오지 못했습니다.'
  } finally {
    loading.value = false
  }
})

const student = computed(() => dashboard.value?.student || {})
const latestMetrics = computed(() => dashboard.value?.latest_metrics || {})
const latestDelta = computed(() => dashboard.value?.latest_delta || {})
const classAvg = computed(() => dashboard.value?.class_avg || {})
const trend = computed(() => dashboard.value?.trend || [])
const metricsHistory = computed(() => dashboard.value?.metrics_history || [])
const recentAssignments = computed(() => dashboard.value?.recent_assignments || [])
const hasAnyMetrics = computed(() => Object.values(latestMetrics.value).some((value) => value !== null && value !== undefined))
const hasTrend = computed(() => trend.value.length > 0)
const hasMetricHistory = computed(() => metricsHistory.value.length > 0)
const hasRecentAssignments = computed(() => recentAssignments.value.length > 0)
const latestAssignment = computed(() => recentAssignments.value[0] || null)
const studentName = computed(() => student.value.name || '학생')
const classCode = computed(() => student.value.class_code || '소속 반')
const aicScore = computed(() => latestMetrics.value.aic ?? null)
const statusText = computed(() => {
  const score = Number(aicScore.value)
  if (!Number.isFinite(score)) return 'Pending'
  if (score >= 85) return 'Excellent'
  if (score >= 70) return 'Good'
  if (score >= 55) return 'Average'
  return 'Needs Work'
})
const statusClass = computed(() => {
  const score = Number(aicScore.value)
  if (!Number.isFinite(score)) return 'status-pending'
  if (score >= 85) return 'status-excellent'
  if (score >= 70) return 'status-good'
  if (score >= 55) return 'status-average'
  return 'status-risk'
})
const rankPercent = computed(() => {
  if (!dashboard.value?.rank || !dashboard.value?.total_students) return null
  return Math.max(1, Math.round((dashboard.value.rank / dashboard.value.total_students) * 100))
})
const kpiCards = computed(() => [
  {
    key: 'aic',
    value: latestMetrics.value.aic,
    delta: latestDelta.value.aic,
    label: 'AIC Score (종합)',
    color: 'var(--color-aic)',
    pale: 'var(--color-aic-pale)',
    icon: '⌁',
  },
  ...subMetrics.map((metric) => ({
    ...metric,
    value: latestMetrics.value[metric.key],
    delta: metric.key === 'topic' ? latestDelta.value.topic : latestDelta.value[metric.key],
    label: `${metric.label} · ${metric.name}`,
  })),
])
const compareItems = computed(() => [
  ...subMetrics.map((metric) => ({
    ...metric,
    value: latestMetrics.value[metric.key],
    compare: classAvg.value?.[metric.key],
  })),
  {
    key: 'aic',
    label: 'AIC',
    short: 'AIC',
    color: 'var(--color-aic)',
    value: latestMetrics.value.aic,
    compare: classAvg.value?.aic,
  },
])
const improvementNotes = computed(() => {
  const oiGap = (latestMetrics.value.oi ?? 0) - (classAvg.value?.oi ?? 0)
  const uiDelta = latestDelta.value.ui ?? 0
  return [
    {
      icon: '✦',
      tone: 'success',
      title: '강점 · OI 독창성',
      desc: oiGap > 0
        ? `독창적 관점이 반 평균 대비 +${Math.round(oiGap)}점 우수합니다`
        : '개인 관점과 사례를 조금 더 분명히 드러내보세요',
    },
    {
      icon: '⚡',
      tone: 'warning',
      title: '개선 필요 · UI 개입도',
      desc: uiDelta < 0
        ? `AI 초안 수정 비율을 높여보세요 (${uiDelta}점)`
        : 'AI 초안을 받은 뒤 구조와 예시를 직접 다듬어보세요',
    },
  ]
})

const lineConfig = computed(() => {
  if (!hasTrend.value) return null
  const labels = trend.value.map((t) => t.label)
  return {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: '나의 AIC',
          data: trend.value.map((t) => t.aic),
          borderColor: '#1E3A5F',
          backgroundColor: 'rgba(30,58,95,0.08)',
          tension: 0.3,
          fill: true,
          pointRadius: 4,
        },
        {
          label: '반 평균',
          data: trend.value.map((t) => t.class_avg),
          borderColor: '#94a3b8',
          borderDash: [5, 5],
          tension: 0.3,
          fill: false,
          pointRadius: 3,
        },
      ],
    },
    options: {
      responsive: true,
      scales: { y: { min: 0, max: 100 } },
      plugins: { legend: { position: 'bottom' } },
    },
  }
})

const barConfig = computed(() => {
  if (!hasMetricHistory.value) return null
  const labels = metricsHistory.value.map((h) => h.label)
  return {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: 'PI', data: metricsHistory.value.map((h) => h.pi), backgroundColor: '#3B82F6' },
        { label: 'UI', data: metricsHistory.value.map((h) => h.ui), backgroundColor: '#F97316' },
        { label: 'OI', data: metricsHistory.value.map((h) => h.oi), backgroundColor: '#10B981' },
      ],
    },
    options: {
      responsive: true,
      scales: { y: { min: 0, max: 100 } },
      plugins: { legend: { position: 'bottom' } },
    },
  }
})
</script>

<template>
  <AppLayout title="Dashboard" :show-page-header="false">
    <div v-if="loading" class="loading-wrap">
      <LoadingSkeleton height="160px" />
      <LoadingSkeleton height="380px" />
    </div>

    <div v-else-if="error" class="card card-body empty-state">
      <strong>{{ error }}</strong>
      <button class="btn btn-secondary btn-sm mt-4" type="button" @click="router.go(0)">다시 시도</button>
    </div>

    <div v-else-if="dashboard">
      <div class="hero-banner">
        <div class="hero-copy">
          <div class="hero-hi">👋 안녕하세요!</div>
          <div class="hero-greeting">{{ studentName }} 학생</div>
          <div class="hero-sub">
            {{ classCode }} · {{ latestAssignment?.title || '최근 과제' }} 분석 완료 · 최근 업데이트: 오늘
          </div>
          <div class="hero-badges">
            <StatusBadge :score="aicScore" />
            <span class="badge badge-pi">PI {{ latestMetrics.pi ?? '-' }}</span>
            <span class="badge badge-ui">UI {{ latestMetrics.ui ?? '-' }}</span>
            <span class="badge badge-oi">OI {{ latestMetrics.oi ?? '-' }}</span>
          </div>
        </div>
        <div class="hero-score">
          <div class="score-label">AIC Index</div>
          <div class="score-big">{{ aicScore ?? '-' }}</div>
          <div v-if="latestDelta.aic != null" class="score-rank">
            ↑ {{ latestDelta.aic >= 0 ? '+' : '' }}{{ latestDelta.aic }} from last assignment
          </div>
        </div>
      </div>

      <div class="kpi-grid">
        <div
          v-for="card in kpiCards"
          :key="card.key"
          class="dashboard-kpi"
          :style="{ '--metric-color': card.color, '--metric-pale': card.pale }"
        >
          <div class="kpi-top">
            <div class="metric-icon">{{ card.icon }}</div>
            <span
              v-if="card.delta != null"
              class="kpi-change"
              :class="card.delta > 0 ? 'up' : card.delta < 0 ? 'down' : 'neutral'"
            >
              {{ card.delta > 0 ? '↑ +' : card.delta < 0 ? '↓ ' : '→ ' }}{{ card.delta < 0 ? Math.abs(card.delta) : card.delta }}
            </span>
          </div>
          <div class="kpi-number">{{ card.value ?? '-' }}</div>
          <div class="kpi-copy">{{ card.label }}</div>
        </div>
      </div>

      <div v-if="!hasAnyMetrics && !hasTrend && !hasRecentAssignments" class="card card-body empty-state">
        아직 분석된 제출 데이터가 없습니다. 과제를 제출하면 이곳에 AIC 지표와 성장 추이가 표시됩니다.
      </div>

      <div class="dashboard-grid mb-6">
        <div class="card chart-card">
          <div class="card-header">
            <div>
              <div class="card-title">AIC Score</div>
              <div class="card-subtitle">최근 과제 기준</div>
            </div>
            <span class="status-badge" :class="statusClass">{{ statusText }}</span>
          </div>
          <div class="card-body score-card-body">
            <DonutChart
              :score="latestMetrics.aic || 0"
              color="var(--color-aic)"
              label="AIC Score"
              :size="160"
            />
            <div class="metric-chip-grid">
              <div
                v-for="m in subMetrics"
                :key="m.key"
                class="metric-chip"
                :style="{ '--metric-color': m.color, '--metric-pale': m.pale }"
              >
                <strong>{{ latestMetrics[m.key] ?? '-' }}</strong>
                <span>{{ m.short }}</span>
              </div>
            </div>
          </div>
        </div>

        <div class="card chart-card">
          <div class="card-header">
            <div>
              <div class="card-title">지표별 분석</div>
              <div class="card-subtitle">나 vs 반 평균 비교</div>
            </div>
          </div>
          <div class="card-body">
            <div class="compare-group">
              <div v-for="item in compareItems" :key="item.key" class="compare-item">
                <div class="compare-header">
                  <span class="compare-label" :style="{ color: item.color }">{{ item.short }}</span>
                  <span class="compare-values">나 {{ item.value ?? '-' }} / 평균 {{ item.compare ?? '-' }}</span>
                </div>
                <div class="compare-track">
                  <div class="compare-bar-avg" :style="{ width: `${item.compare || 0}%` }"></div>
                  <div class="compare-bar-me" :style="{ width: `${item.value || 0}%`, background: item.color }"></div>
                </div>
              </div>
            </div>
            <div class="legend-row">
              <span><i class="avg"></i>반 평균</span>
              <span><i class="mine"></i>내 점수</span>
            </div>
          </div>
        </div>

        <div class="card chart-card">
          <div class="card-header">
            <div>
              <div class="card-title">반 내 위치</div>
              <div class="card-subtitle">{{ classCode }} · {{ dashboard.total_students || '-' }}명</div>
            </div>
          </div>
          <div class="card-body rank-card-body">
            <div class="rank-display">
              <div class="rank-num">{{ dashboard.rank ?? '-' }}</div>
              <div class="rank-total">/ {{ dashboard.total_students ?? '-' }}명</div>
              <div class="rank-label">상위 {{ rankPercent ?? '-' }}%</div>
            </div>
            <div class="feedback-grid">
              <div v-for="note in improvementNotes" :key="note.title" class="feedback-item" :class="note.tone">
                <div class="feedback-icon">{{ note.icon }}</div>
                <div>
                  <div class="feedback-title">{{ note.title }}</div>
                  <div class="feedback-desc">{{ note.desc }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="lower-grid mb-6">
        <div class="card chart-card" v-if="lineConfig">
          <div class="card-header">
            <div>
              <div class="card-title">AIC 성장 추이</div>
              <div class="card-subtitle">최근 과제 기준</div>
            </div>
            <RouterLink class="card-link" to="/student/growth">전체 보기 →</RouterLink>
          </div>
          <div class="card-body chart-body">
            <LineChart :config="lineConfig" />
          </div>
        </div>
        <div v-else class="card card-body chart-card empty-state compact">성장 추이 데이터가 없습니다.</div>

        <div class="card chart-card">
          <div class="card-header">
            <div>
              <div class="card-title">최근 과제</div>
              <div class="card-subtitle">최근 {{ recentAssignments.length }}개</div>
            </div>
            <RouterLink class="card-link" to="/student/assignments">전체 →</RouterLink>
          </div>
          <div class="card-body assignment-body">
            <div v-if="hasRecentAssignments" class="assignment-list">
              <div
                v-for="(a, index) in recentAssignments.slice(0, 5)"
                :key="a.id"
                class="assignment-item"
                @click="router.push(`/student/assignments/${a.id}`)"
              >
                <div class="assign-num">{{ recentAssignments.length - index }}</div>
                <div class="assign-info">
                  <div class="assign-title">{{ a.title }}</div>
                  <div class="assign-meta">{{ a.submitted_at || '-' }}</div>
                </div>
                <div class="assign-aic">{{ a.aic ?? '-' }}</div>
              </div>
            </div>
            <div v-else class="empty-state compact">최근 과제가 없습니다.</div>
          </div>
        </div>
      </div>

      <div class="grid-2">
        <div class="card chart-card" v-if="barConfig">
          <div class="card-header">
            <div>
              <div class="card-title">과제별 지표 변화</div>
              <div class="card-subtitle">PI / UI / OI 과제별 비교</div>
            </div>
          </div>
          <div class="card-body chart-body">
            <BarChart :config="barConfig" />
          </div>
        </div>
        <div v-else class="card card-body chart-card empty-state compact">세부 지표 추이 데이터가 없습니다.</div>

        <div class="card chart-card">
          <div class="card-header">
            <div>
              <div class="card-title">핵심 개선 가이드</div>
              <div class="card-subtitle">이번 과제 분석 기반</div>
            </div>
            <RouterLink class="card-link" to="/student/feedback">전체 보기 →</RouterLink>
          </div>
          <div class="card-body guide-body">
            <div class="alert alert-warning">
              <strong>UI 개선 필요</strong>
              <span>AI 초안을 받은 후 내용을 직접 수정하고, 본인의 사례와 근거를 추가해보세요.</span>
            </div>
            <div class="alert alert-success">
              <strong>OI 강점 유지</strong>
              <span>독창적인 관점과 개인적 경험을 다음 과제에도 계속 유지하세요.</span>
            </div>
            <div class="alert alert-info">
              <strong>PI 향상 팁</strong>
              <span>프롬프트에 “왜”, “어떻게”, “비교하면” 같은 심화 질문어를 더 자주 사용해보세요.</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<style scoped>
.loading-wrap {
  display: grid;
  gap: 1rem;
}

.hero-banner {
  background: linear-gradient(135deg, #1e3a5f 0%, #2c5282 52%, #174d3c 100%);
  border-radius: var(--radius-xl);
  padding: 28px 32px;
  color: #fff;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-6);
  margin-bottom: var(--space-6);
  box-shadow: var(--shadow-md);
  min-height: 180px;
  position: relative;
  overflow: hidden;
}

.hero-banner::before,
.hero-banner::after {
  content: '';
  position: absolute;
  border-radius: var(--radius-full);
  pointer-events: none;
}

.hero-banner::before {
  width: 220px;
  height: 220px;
  right: -56px;
  top: -80px;
  background: rgba(255, 255, 255, 0.06);
}

.hero-banner::after {
  width: 120px;
  height: 120px;
  right: 66px;
  bottom: -44px;
  background: rgba(16, 185, 129, 0.12);
}

.hero-copy,
.hero-score {
  position: relative;
  z-index: 1;
}

.hero-hi {
  color: rgba(255, 255, 255, 0.56);
  font-size: var(--text-sm);
  font-weight: 600;
  margin-bottom: var(--space-1);
}

.hero-greeting {
  font-size: 23px;
  font-weight: 800;
  letter-spacing: 0;
  line-height: 1.2;
}

.hero-sub {
  margin-top: var(--space-3);
  color: rgba(255, 255, 255, 0.52);
  font-size: var(--text-sm);
  font-weight: 600;
}

.hero-badges {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-4);
}

.hero-score {
  text-align: right;
  min-width: 190px;
}

.score-big {
  font-size: 52px;
  font-weight: 800;
  line-height: 1;
  letter-spacing: 0;
  margin-top: var(--space-1);
}

.score-label,
.score-rank {
  font-size: var(--text-xs);
  color: rgba(255, 255, 255, 0.55);
  font-weight: 700;
}

.score-label {
  text-transform: uppercase;
  letter-spacing: 0.8px;
}

.score-rank {
  color: #6ee7b7;
  margin-top: var(--space-2);
}

.kpi-grid {
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: var(--space-4);
  margin-bottom: var(--space-6);
}

.dashboard-kpi {
  background: var(--bg-surface);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-sm);
  padding: var(--space-5);
  min-height: 140px;
  transition: box-shadow var(--transition-fast), transform var(--transition-fast);
}

.dashboard-kpi:hover {
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}

.kpi-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-4);
}

.metric-icon {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  display: grid;
  place-items: center;
  background: var(--metric-pale);
  color: var(--metric-color);
  font-weight: 800;
  font-size: var(--text-md);
}

.kpi-number {
  color: var(--metric-color);
  font-size: 30px;
  line-height: 1;
  font-weight: 800;
}

.dashboard-kpi:first-child .kpi-number {
  color: var(--text-primary);
}

.kpi-copy {
  color: var(--text-muted);
  font-size: var(--text-xs);
  font-weight: 700;
  margin-top: var(--space-2);
}

.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-4);
}

.score-card-body {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-5);
}

.metric-chip-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-2);
  width: 100%;
}

.metric-chip {
  background: var(--metric-pale);
  border-radius: var(--radius-md);
  padding: 8px;
  text-align: center;
}

.metric-chip strong {
  display: block;
  color: var(--metric-color);
  font-size: var(--text-xl);
  line-height: 1.1;
}

.metric-chip span {
  color: var(--text-muted);
  font-size: 10px;
  font-weight: 800;
}

.compare-group {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.compare-header {
  display: flex;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: 7px;
}

.compare-label {
  font-size: var(--text-xs);
  font-weight: 800;
}

.compare-values {
  color: var(--text-muted);
  font-size: var(--text-xs);
  font-weight: 600;
}

.compare-track {
  height: 10px;
  background: var(--color-gray-100);
  border-radius: var(--radius-full);
  overflow: hidden;
  position: relative;
}

.compare-bar-avg,
.compare-bar-me {
  position: absolute;
  left: 0;
  top: 0;
  height: 100%;
  border-radius: var(--radius-full);
}

.compare-bar-avg {
  background: var(--color-gray-300);
}

.compare-bar-me {
  opacity: 0.9;
}

.legend-row {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  color: var(--text-muted);
  font-size: var(--text-xs);
  font-weight: 600;
  margin-top: var(--space-5);
}

.legend-row span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.legend-row i {
  width: 14px;
  height: 5px;
  border-radius: var(--radius-full);
  display: inline-block;
}

.legend-row .avg {
  background: var(--color-gray-300);
}

.legend-row .mine {
  background: var(--color-pi);
}

.rank-card-body,
.guide-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.rank-display {
  min-height: 150px;
  background: var(--color-aic-pale);
  border-radius: var(--radius-lg);
  display: grid;
  place-items: center;
  align-content: center;
  text-align: center;
}

.rank-num {
  color: var(--color-aic);
  font-size: 42px;
  line-height: 1;
  font-weight: 800;
}

.rank-total {
  color: var(--text-muted);
  font-size: var(--text-sm);
  margin-top: var(--space-2);
}

.rank-label {
  color: var(--color-aic);
  font-size: var(--text-xs);
  font-weight: 800;
  margin-top: var(--space-2);
}

.feedback-grid {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.feedback-item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  background: var(--color-gray-50);
  padding: var(--space-3) var(--space-4);
}

.feedback-icon {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

.feedback-item.success .feedback-icon {
  background: var(--color-oi-pale);
}

.feedback-item.warning .feedback-icon {
  background: var(--color-ui-pale);
}

.feedback-title {
  color: var(--text-primary);
  font-size: var(--text-xs);
  font-weight: 800;
}

.feedback-desc {
  color: var(--text-muted);
  font-size: var(--text-xs);
  line-height: 1.5;
  margin-top: 2px;
}

.lower-grid {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: var(--space-4);
}

.chart-body {
  min-height: 260px;
}

.assignment-body {
  padding: var(--space-2) var(--space-3);
}

.assignment-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.assignment-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 12px 10px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.assignment-item:hover {
  background: var(--color-gray-50);
}

.assign-num {
  width: 28px;
  height: 28px;
  background: var(--color-gray-100);
  border-radius: var(--radius-sm);
  display: grid;
  place-items: center;
  color: var(--text-muted);
  font-size: var(--text-xs);
  font-weight: 800;
}

.assign-info {
  min-width: 0;
  flex: 1;
}

.assign-title {
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.assign-meta {
  color: var(--text-muted);
  font-size: var(--text-xs);
  margin-top: 1px;
}

.assign-aic {
  color: var(--color-aic);
  font-size: var(--text-xl);
  font-weight: 800;
}

.card-link {
  color: var(--color-pi);
  font-size: var(--text-xs);
  font-weight: 800;
}

.guide-body .alert {
  flex-direction: column;
  gap: var(--space-1);
}

.guide-body .alert strong {
  font-size: var(--text-xs);
}

.guide-body .alert span {
  color: var(--text-secondary);
  font-size: var(--text-xs);
  line-height: 1.5;
}

.chart-title {
  font-size: var(--text-sm);
  font-weight: 600;
  margin-bottom: 0.9rem;
}

.donut-row {
  display: flex;
  gap: 1.2rem;
  align-items: center;
}

.donut-details {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}

.metric-line {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  font-size: var(--text-sm);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.recent-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.recent-title {
  font-size: var(--text-sm);
  font-weight: 500;
}

.recent-meta {
  margin-top: 0.25rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

.compact {
  padding: var(--space-6);
}

@media (max-width: 1200px) {
  .kpi-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .dashboard-grid,
  .lower-grid {
    grid-template-columns: 1fr;
  }

  .hero-banner {
    align-items: flex-start;
    flex-direction: column;
  }

  .hero-score {
    text-align: left;
  }
}

@media (max-width: 768px) {
  .kpi-grid,
  .grid-2 {
    grid-template-columns: 1fr;
  }

  .hero-banner {
    padding: var(--space-6);
  }

  .hero-score {
    min-width: 0;
  }
}
</style>

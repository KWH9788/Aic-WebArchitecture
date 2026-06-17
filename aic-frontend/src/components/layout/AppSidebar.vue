<script setup>
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useTeacherStore } from '@/stores/teacher'

defineProps({
  open: { type: Boolean, default: false },
})

const emit = defineEmits(['close'])

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const teacherStore = useTeacherStore()

const role = computed(() => auth.user?.role)
const displayUserName = computed(() => {
  if (role.value === 'admin') return '시스템 관리자'
  return auth.user?.name || '사용자'
})
const studentNav = [
  { label: 'Dashboard', path: '/student/dashboard', icon: 'grid' },
  { label: 'Assignment Detail', path: '/student/assignments', icon: 'file' },
  { label: 'Growth Analysis', path: '/student/growth', icon: 'trendUp' },
  { label: 'Feedback Guide', path: '/student/feedback', icon: 'lightbulb' },
]
const teacherNav = [
  { label: '대시보드', path: '/teacher/dashboard', icon: 'grid' },
  { label: '학생 목록', path: '/teacher/students', icon: 'users' },
  { label: '위험군 관리', path: '/teacher/risk', icon: 'alertTriangle', badge: true },
  { label: '과제 분석', path: '/teacher/analytics/assignment', dynamicPath: true, match: '/teacher/analytics/assignment', icon: 'barChart' },
  { label: '심화 분석', path: '/teacher/advanced', icon: 'cpu' },
  { label: '통계 검증', path: '/teacher/statistics', icon: 'shield' },
]
const iconSvg = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
  trendUp: '<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>',
  lightbulb: '<path d="M9 21h6"/><path d="M12 3a6 6 0 0 1 6 6c0 2.22-1.2 4.16-3 5.2V17H9v-2.8A6 6 0 0 1 6 9a6 6 0 0 1 6-6z"/>',
  users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  alertTriangle: '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
  barChart: '<line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/>',
  cpu: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
}
const adminNav = [
  { label: '시스템 현황', path: '/admin/dashboard', icon: 'grid' },
  { label: '분석 품질', path: '/admin/analysis-quality', icon: 'shield' },
]
const navItems = computed(() => {
  if (role.value === 'admin') return adminNav
  return role.value === 'teacher' ? teacherNav : studentNav
})
const homePath = computed(() => {
  if (role.value === 'admin') return '/admin/dashboard'
  return role.value === 'teacher' ? '/teacher/dashboard' : '/student/dashboard'
})

onMounted(() => {
  if (role.value === 'teacher' && !teacherStore.assignments.length) {
    teacherStore.fetchAssignments().catch(() => {})
  }
})


function itemPath(item) {
  if (item.dynamicPath && teacherStore.firstAssignmentId) {
    return `/teacher/analytics/assignment/${teacherStore.firstAssignmentId}`
  }
  return item.path
}

function isActive(item) {
  const path = itemPath(item)
  return route.path === path || route.path.startsWith(item.match || `${path}/`)
}

function goHome() {
  router.push(homePath.value)
  emit('close')
}

async function handleLogout() {
  await auth.logout()
  emit('close')
  router.push('/login')
}
</script>

<template>
  <aside class="app-sidebar" :class="{ open }">
    <div class="sidebar-logo" @click="goHome">
      <span class="sidebar-logo-icon">AIC</span>
      <span class="sidebar-logo-text">AIC <span>Index</span></span>
    </div>
    <div class="sidebar-role-badge">{{ role === 'admin' ? 'Admin' : role === 'teacher' ? 'Teacher' : 'Student' }}</div>
    <nav class="sidebar-nav">
      <div class="nav-section-label">Navigation</div>
      <RouterLink
        v-for="item in navItems"
        :key="item.path"
        :to="itemPath(item)"
        class="nav-item"
        :class="{ active: isActive(item) }"
        @click="emit('close')"
      >
        <svg
          class="nav-item-icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          aria-hidden="true"
          v-html="iconSvg[item.icon]"
        />
        <span class="nav-label">{{ item.label }}</span>
        <span v-if="item.badge && teacherStore.riskCount > 0" class="nav-badge">
          {{ teacherStore.riskCount }}
        </span>
      </RouterLink>
    </nav>
    <div class="sidebar-user">
      <div class="user-avatar">{{ displayUserName.slice(0, 1) }}</div>
      <div class="user-info">
        <div class="user-name">{{ displayUserName }}</div>
        <div class="user-role">{{ role === 'admin' ? 'System Admin' : role === 'teacher' ? 'Teacher' : `Student · ${auth.user?.class_code || 'CS101'}` }}</div>
      </div>
      <button class="logout-btn" title="로그아웃" aria-label="로그아웃" @click.stop="handleLogout">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
          <polyline points="16,17 21,12 16,7" />
          <line x1="21" y1="12" x2="9" y2="12" />
        </svg>
      </button>
    </div>
  </aside>
</template>

<style scoped>
.nav-label {
  flex: 1;
}

.logout-btn {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.78);
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  cursor: pointer;
  flex-shrink: 0;
}

.logout-btn svg {
  width: 15px;
  height: 15px;
}

.logout-btn:hover {
  background: rgba(255, 255, 255, 0.2);
}
</style>

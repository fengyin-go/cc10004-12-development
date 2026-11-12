import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import { useSessionStore } from '@/stores/session'
const Query = () => import('@/views/query/index.vue')
const Chart = () => import('@/views/chart/index.vue')
const Source = () => import('@/views/source/index.vue')
const Aggregate = () => import('@/views/aggregate/index.vue')
const Filter = () => import('@/views/filter/index.vue')
const Reportgen = () => import('@/views/reportgen/index.vue')
const Anomaly = () => import('@/views/anomaly/index.vue')
const Drill = () => import('@/views/drill/index.vue')
const Compare = () => import('@/views/compare/index.vue')
const Pipeline = () => import('@/views/pipeline/index.vue')
const Datastore = () => import('@/views/datastore/index.vue')
const Forecast = () => import('@/views/forecast/index.vue')
const Segment = () => import('@/views/segment/index.vue')
const Scheduler = () => import('@/views/scheduler/index.vue')
const Notify = () => import('@/views/notify/index.vue')
const Cache = () => import('@/views/cache/index.vue')
const Tag = () => import('@/views/tag/index.vue')
const Share = () => import('@/views/share/index.vue')
const Login = () => import('@/views/login/index.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: Login, meta: { public: true } },
    { path: '/', name: 'overview', component: Overview },
    { path: '/query', name: 'query', component: Query },
    { path: '/chart', name: 'chart', component: Chart },
    { path: '/source', name: 'source', component: Source },
    { path: '/aggregate', name: 'aggregate', component: Aggregate },
    { path: '/filter', name: 'filter', component: Filter },
    { path: '/reportgen', name: 'reportgen', component: Reportgen },
    { path: '/anomaly', name: 'anomaly', component: Anomaly },
    { path: '/drill', name: 'drill', component: Drill },
    { path: '/compare', name: 'compare', component: Compare },
    { path: '/pipeline', name: 'pipeline', component: Pipeline },
    { path: '/datastore', name: 'datastore', component: Datastore },
    { path: '/forecast', name: 'forecast', component: Forecast },
    { path: '/segment', name: 'segment', component: Segment },
    { path: '/scheduler', name: 'scheduler', component: Scheduler },
    { path: '/notify', name: 'notify', component: Notify },
    { path: '/cache', name: 'cache', component: Cache },
    { path: '/tag', name: 'tag', component: Tag },
    { path: '/share', name: 'share', component: Share },
  ],
})

router.beforeEach((to) => {
  const session = useSessionStore()
  if (!to.meta.public && !session.isAuthenticated) {
    return { name: 'login', query: to.fullPath !== '/' ? { redirect: to.fullPath } : {} }
  }
  if (to.name === 'login' && session.isAuthenticated) {
    return { name: 'overview' }
  }
  return true
})

export default router

<template>
  <section class="page" data-module="tag">
    <header class="page-head">
      <div>
        <h2>数据标签管理 · 覆盖对象授权</h2>
        <p class="page-desc">
          按标签层级裁决分配权限与阅览归属；保密标签对未获准者连名称也不可泄露。
          重名标签以稳定身份（stable_tag_id）区分，全部越权调用由服务端拦截。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="exportRows">导出标签清单（自动脱敏）</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>按标签编号检索</span>
        <input v-model="keyword" placeholder="如 TAG-0001" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="status">
          <option value="">全部</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>保密/层级</th>
          <th>稳定身份与维护者</th>
          <th>授权操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-hidden': row.hidden }">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>
            <span v-if="row.hidden" class="badge badge-secret">保密 · 无权查看</span>
            <template v-else>
              <span class="badge" :class="row.confidential ? 'badge-secret' : 'badge-open'">
                {{ row.confidential ? '保密标签' : '普通标签' }}
              </span>
              <span class="muted">L{{ row['标签层级'] }}</span>
            </template>
          </td>
          <td>
            <template v-if="!row.hidden">
              <code>{{ row.stable_tag_id }}</code>
              <div class="muted small">维护者：{{ row.maintainer_id }}{{ row.editable ? '（可编辑）' : '' }}</div>
            </template>
            <span v-else class="muted">—</span>
          </td>
          <td class="row-actions">
            <template v-if="row.hidden">
              <span class="muted">未获准，名称与授权均不可见</span>
            </template>
            <template v-else>
              <button class="link" type="button" @click="openEditor(row)">授权编辑器</button>
              <button
                v-if="row.editable"
                v-for="action in actions"
                :key="action"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </template>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 3" class="empty-state">暂无可见标签数据</td>
        </tr>
      </tbody>
    </table>

    <h3 class="block-title">覆盖数据集与保密范围（按当前身份过滤）</h3>
    <table class="data-table">
      <thead>
        <tr><th>数据集</th><th>名称</th><th>保密范围</th><th>数据集授权</th><th>字段数</th><th>维护者</th></tr>
      </thead>
      <tbody>
        <tr v-for="ds in datasets" :key="ds.dataset_id" :class="{ 'row-hidden': !ds.authorized }">
          <td>{{ ds.dataset_id }}</td>
          <td>{{ ds.name }}</td>
          <td>{{ ds.confidential_scope }}</td>
          <td>
            <span class="badge" :class="ds.authorized ? 'badge-allow' : 'badge-deny'">
              {{ ds.authorized ? '已授权' : '未获准（已脱敏）' }}
            </span>
          </td>
          <td>{{ ds.authorized ? ds.fields.length : '—' }}</td>
          <td><code>{{ ds.maintainer_id }}</code></td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条标签记录（含 {{ hiddenCount }} 条因未获准而脱敏）</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <AccessEditor
      v-if="editorTarget"
      :tag-pk="editorTarget.id"
      :stable-tag-id="editorTarget.stable_tag_id ?? ''"
      @close="editorTarget = null"
      @changed="reload"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { readError, request } from '@/api/client'
import type { DatasetItem } from '@/types/access'
import AccessEditor from './AccessEditor.vue'

interface TagRow extends Record<string, string | number | boolean | null | undefined> {
  id: number
  hidden: boolean
  confidential?: boolean
  editable?: boolean
  stable_tag_id?: string
  maintainer_id?: string
  auth_version?: number
}

const ENDPOINT = '/api/tag'
const columns = ['标签编号', '标签名称', '计算表达式', '覆盖对象', '更新频率', '标签层级', '值域范围', '失效天数']
const actions = ['提交校验', '启用标签', '停用标签']
const statuses = ['草稿', '待校验', '已启用', '已停用']

const rows = ref<TagRow[]>([])
const datasets = ref<DatasetItem[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const status = ref('')
const editorTarget = ref<TagRow | null>(null)

const hiddenCount = computed(() => rows.value.filter((row) => row.hidden).length)
const stats = computed(() => [
  { label: '可见标签数', value: rows.value.filter((row) => !row.hidden).length },
  { label: '保密脱敏标签', value: hiddenCount.value },
  { label: '保密标签（可见口径）', value: rows.value.filter((row) => !row.hidden && row.confidential).length },
  { label: '我可编辑的标签', value: rows.value.filter((row) => row.editable).length },
])

function resetFilters() {
  keyword.value = ''
  status.value = ''
  void reload()
}

function openEditor(row: TagRow) {
  if (!row.stable_tag_id) {
    return
  }
  editorTarget.value = row
}

function exportRows() {
  // 导出同样携带令牌：改用 fetch 触发下载，避免 window.open 丢失 Authorization。
  void (async () => {
    try {
      const response = await request(`${ENDPOINT}/export`)
      if (!response.ok) {
        throw new Error(await readError(response, '导出失败'))
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = 'tag-export.json'
      anchor.click()
      URL.revokeObjectURL(url)
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '导出失败'
    }
  })()
}

async function runAction(action: string, row: TagRow) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error(await readError(response, '数据标签动作未生效'))
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据标签操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) {
    query.set('keyword', keyword.value)
  }
  if (status.value) {
    query.set('status', status.value)
  }
  try {
    const [tagResponse, datasetResponse] = await Promise.all([
      request(`${ENDPOINT}?${query.toString()}`),
      request('/api/access/datasets'),
    ])
    if (!tagResponse.ok) {
      throw new Error(await readError(tagResponse, '标签定义列表读取失败'))
    }
    const payload = (await tagResponse.json()) as { items: TagRow[]; total: number }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (datasetResponse.ok) {
      const dsPayload = (await datasetResponse.json()) as { items: DatasetItem[] }
      datasets.value = dsPayload.items ?? []
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据标签列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.row-hidden { background: #f8fafc; color: var(--muted); }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; }
.badge-secret { background: #fef3c7; color: #92400e; }
.badge-open { background: #e0f2fe; color: #075985; }
.badge-allow { background: #dcfce7; color: #166534; }
.badge-deny { background: #fee2e2; color: #991b1b; }
.muted { color: var(--muted); }
.small { font-size: 12px; }
.block-title { margin: 20px 0 8px; font-size: 15px; }
select { padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
</style>

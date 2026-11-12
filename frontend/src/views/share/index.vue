<template>
  <section class="page" data-module="share">
    <header class="page-head">
      <div>
        <h2>数据分享 · 字段说明生成</h2>
        <p class="page-desc">
          跨模块分享时，字段说明取数据集授权与标签可见性的交集；不可见标签的名称与存在性不会出现在说明中，
          未获准的保密字段直接剔除。服务端统一裁决，前端不做可信假设。
        </p>
      </div>
    </header>

    <div class="filter-bar">
      <label class="filter-item">
        <span>目标数据集</span>
        <select v-model="datasetId" @change="resetResult">
          <option value="">请选择数据集</option>
          <option v-for="ds in datasets" :key="ds.dataset_id" :value="ds.dataset_id">
            {{ ds.dataset_id }} · {{ ds.authorized ? ds.name : '未获准数据集（脱敏）' }}
          </option>
        </select>
      </label>
      <button class="btn primary" type="button" :disabled="!datasetId || loading" @click="generate">
        生成交集字段说明
      </button>
    </div>

    <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>

    <div v-if="spec" class="spec-box">
      <div class="stat-row">
        <article class="stat-card">
          <span class="stat-label">数据集</span>
          <strong class="stat-value small-strong">{{ spec.dataset_name }}（{{ spec.dataset_id }}）</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">可输出字段</span>
          <strong class="stat-value">{{ spec.fields.length }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">被交集剔除的保密字段</span>
          <strong class="stat-value">{{ spec.redacted_field_count }}</strong>
        </article>
      </div>
      <p class="page-desc">保密范围：{{ spec.confidential_scope }}</p>
      <p class="page-desc">裁决口径：{{ spec.rule }}</p>

      <h3 class="block-title">交集内可见标签（不可见标签不会出现）</h3>
      <div v-if="spec.visible_tags.length" class="tag-chips">
        <span v-for="tag in spec.visible_tags" :key="tag.stable_tag_id" class="chip">
          {{ tag.tag_name }} <code>{{ tag.stable_tag_id }}</code>
          <em class="muted">{{ sourceText(tag.decision_source) }}{{ tag.confidential ? ' · 保密' : '' }}</em>
        </span>
      </div>
      <p v-else class="muted">没有任何可见标签覆盖该数据集。</p>

      <h3 class="block-title">字段说明</h3>
      <table class="data-table">
        <thead>
          <tr><th>字段名</th><th>中文名</th><th>密级</th><th>可见依据标签</th></tr>
        </thead>
        <tbody>
          <tr v-for="field in spec.fields" :key="field.field">
            <td><code>{{ field.field }}</code></td>
            <td>{{ field.label }}</td>
            <td>
              <span class="badge" :class="field.level === '保密' ? 'badge-secret' : 'badge-open'">{{ field.level }}</span>
            </td>
            <td>{{ field.visible_via_tags.join('、') || '—' }}</td>
          </tr>
          <tr v-if="!spec.fields.length">
            <td colspan="4" class="empty-state">交集为空：当前身份没有可输出字段</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { readError, request } from '@/api/client'
import type { DatasetItem, FieldSpec } from '@/types/access'

const datasets = ref<DatasetItem[]>([])
const datasetId = ref('')
const spec = ref<FieldSpec | null>(null)
const loading = ref(false)
const errorMessage = ref('')

const sourceMap: Record<string, string> = {
  explicit_self: '本层显式授权',
  inherited_allow: '父级继承允许',
  explicit_deny: '显式拒绝',
  default_confidential: '保密默认拒绝',
  default_open: '非保密默认允许',
  implicit_maintainer: '维护者隐式可见',
  implicit_admin: '管理员隐式可见',
}

function sourceText(source: string): string {
  return sourceMap[source] ?? source
}

function resetResult() {
  spec.value = null
  errorMessage.value = ''
}

async function loadDatasets() {
  const response = await request('/api/access/datasets')
  if (response.ok) {
    const payload = (await response.json()) as { items: DatasetItem[] }
    datasets.value = payload.items
  }
}

async function generate() {
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await request(`/api/access/field-spec/${encodeURIComponent(datasetId.value)}`)
    if (!response.ok) {
      throw new Error(await readError(response, '字段说明生成失败'))
    }
    spec.value = (await response.json()) as FieldSpec
  } catch (error) {
    spec.value = null
    errorMessage.value = error instanceof Error ? error.message : '字段说明生成失败'
  } finally {
    loading.value = false
  }
}

onMounted(loadDatasets)
</script>

<style scoped>
.spec-box {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 16px;
  margin-top: 12px;
}
.small-strong { font-size: 15px; }
.block-title { margin: 16px 0 8px; font-size: 15px; }
.tag-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { background: #f1f5f9; border-radius: 14px; padding: 4px 12px; font-size: 12px; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; }
.badge-secret { background: #fef3c7; color: #92400e; }
.badge-open { background: #e0f2fe; color: #075985; }
.muted { color: var(--muted); }
select { padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; min-width: 280px; }
</style>

<template>
  <div class="modal-mask" @click.self="$emit('close')">
    <div class="modal">
      <header class="modal-head">
        <div>
          <h3>覆盖对象授权编辑器</h3>
          <p class="page-desc">
            标签 {{ stableTagId }}
            <span v-if="preview" class="badge" :class="preview.confidential ? 'badge-secret' : 'badge-open'">
              {{ preview.confidential ? '保密标签：未获准者连名称都不可见' : '非保密标签' }}
            </span>
            <span v-if="preview" class="badge">版本 v{{ preview.version }}</span>
          </p>
        </div>
        <button class="btn" type="button" @click="$emit('close')">关闭</button>
      </header>

      <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>
      <p v-if="infoMessage" class="info-text">{{ infoMessage }}</p>

      <div class="tab-bar">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          class="tab-btn"
          :class="{ active: activeTab === tab.key }"
          type="button"
          @click="switchTab(tab.key)"
        >
          {{ tab.label }}
        </button>
      </div>

      <!-- 范围预览 -->
      <div v-if="activeTab === 'preview'">
        <h4 class="block-title">可用数据集与保密范围</h4>
        <table class="data-table compact">
          <thead>
            <tr><th>数据集</th><th>名称</th><th>保密范围</th></tr>
          </thead>
          <tbody>
            <tr v-for="ds in preview?.available_datasets ?? []" :key="ds.dataset_id">
              <td>{{ ds.dataset_id }}</td>
              <td>{{ ds.name }}</td>
              <td>{{ ds.confidential_scope }}</td>
            </tr>
          </tbody>
        </table>

        <h4 class="block-title">逐身份层级裁决（现状）</h4>
        <table class="data-table compact">
          <thead>
            <tr><th>身份</th><th>裁决</th><th>裁决来源</th><th>可阅览范围</th><th>覆盖数据集交集</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in preview?.identities ?? []" :key="row.identity_id">
              <td>{{ row.name }}<br /><code>{{ row.identity_id }}</code></td>
              <td><span class="badge" :class="row.decision === 'allow' ? 'badge-allow' : 'badge-deny'">{{ row.decision === 'allow' ? '允许' : '拒绝' }}</span></td>
              <td>{{ sourceText(row.decision_source) }}</td>
              <td>{{ row.scope.length ? row.scope.join('、') : '—' }}</td>
              <td>
                <div v-for="d in row.datasets" :key="d.dataset_id" class="ds-state">
                  <span class="dot" :class="d.state"></span>{{ d.dataset_id }}：{{ stateText(d.state) }}
                  <em class="muted">（{{ d.reason }}）</em>
                </div>
              </td>
            </tr>
          </tbody>
        </table>

        <template v-if="!evidenceOnly">
          <h4 class="block-title">候选范围编辑（试算不落库）</h4>
          <table class="data-table compact">
            <thead>
              <tr><th>身份</th><th>授权效果</th><th>可阅览数据集（取交集口径）</th></tr>
            </thead>
            <tbody>
              <tr v-for="identity in identities" :key="identity.identity_id">
                <td>{{ identity.name }}<br /><code>{{ identity.identity_id }}</code></td>
                <td>
                  <select
                    :value="candidate[identity.identity_id]?.effect ?? 'none'"
                    :disabled="busy"
                    @change="onEffectChange(identity.identity_id, ($event.target as HTMLSelectElement).value)"
                  >
                    <option value="none">不设显式授权（走层级默认）</option>
                    <option value="allow">显式允许 allow</option>
                    <option value="deny">显式拒绝 deny（拒绝优先）</option>
                  </select>
                </td>
                <td>
                  <label
                    v-for="ds in preview?.coverage ?? []"
                    :key="ds"
                    class="scope-check"
                  >
                    <input
                      type="checkbox"
                      :value="ds"
                      :checked="candidate[identity.identity_id]?.scope.includes(ds) ?? false"
                      :disabled="busy || candidate[identity.identity_id]?.effect !== 'allow'"
                      @change="toggleScope(identity.identity_id, ds)"
                    />
                    {{ ds }}
                  </label>
                </td>
              </tr>
            </tbody>
          </table>
          <div class="row-actions" style="margin-top: 10px">
            <button class="btn" type="button" :disabled="busy" @click="calculate">试算候选范围</button>
            <button class="btn" type="button" :disabled="busy" @click="computeDiff">查看差异</button>
            <button class="btn ghost" type="button" :disabled="busy" @click="resetCandidate">重置为当前授权</button>
          </div>
        </template>
        <p v-else class="warn-text">您是历任维护者：授权编辑已关闭，仅可在「证据链」页签只读移交证据。</p>

        <div v-if="candidatePreview" class="candidate-box">
          <h4 class="block-title">候选试算结果（尚未生效，其他窗口看不到）</h4>
          <table class="data-table compact">
            <thead><tr><th>身份</th><th>试算裁决</th><th>来源</th><th>数据集交集</th></tr></thead>
            <tbody>
              <tr v-for="row in candidatePreview.identities" :key="row.identity_id">
                <td>{{ row.name }}</td>
                <td><span class="badge" :class="row.decision === 'allow' ? 'badge-allow' : 'badge-deny'">{{ row.decision === 'allow' ? '允许' : '拒绝' }}</span></td>
                <td>{{ sourceText(row.decision_source) }}</td>
                <td>
                  <span v-for="d in row.datasets" :key="d.dataset_id" class="ds-state">
                    <span class="dot" :class="d.state"></span>{{ d.dataset_id }}：{{ stateText(d.state) }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 差异签认 -->
      <div v-if="activeTab === 'diff'">
        <h4 class="block-title">差异签认（新增 / 移除 / 变更）</h4>
        <div v-if="!diff" class="empty-state">请先在「范围预览」中点击「查看差异」。</div>
        <template v-else>
          <div v-for="group in diffGroups" :key="group.key" class="diff-group">
            <strong :class="group.cls">{{ group.label }}（{{ group.entries.length }}）</strong>
            <table v-if="group.entries.length" class="data-table compact">
              <thead><tr><th>身份</th><th>原授权</th><th>新授权</th></tr></thead>
              <tbody>
                <tr v-for="entry in group.entries" :key="entry.identity_id">
                  <td>{{ entry.identity_id }}</td>
                  <td>{{ grantText(entry.old) }}</td>
                  <td>{{ grantText(entry.new) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="isNoDiff" class="info-text">候选范围与当前授权完全一致：重复分配不会增添关联，也不会产生新版本或证据。</p>
          <div class="row-actions" style="margin-top: 12px">
            <button class="btn primary" type="button" :disabled="busy || evidenceOnly" @click="commit">
              整份授权原子签认（基于 v{{ baseVersion }}）
            </button>
            <span class="muted">签认在服务端同一临界区内整份替换，半份新范围不会提前公开。</span>
          </div>
        </template>
      </div>

      <!-- 移交与撤回 -->
      <div v-if="activeTab === 'handover'">
        <h4 class="block-title">撤回过程</h4>
        <p class="muted">撤回该标签全部显式授权，权限回落至层级默认口径（保密标签对未获准者恢复默认拒绝），过程写入证据链。</p>
        <button class="btn" type="button" :disabled="busy || evidenceOnly" @click="withdraw">撤回全部显式授权</button>

        <h4 class="block-title">覆盖对象移交</h4>
        <p class="muted">
          当前维护者：<code>{{ currentMaintainer }}</code>。移交后旧维护者立即失去编辑权，仅保留证据只读，
          不能再借旧关联追加公开内容。
        </p>
        <div class="filter-bar">
          <label class="filter-item">
            <span>新维护者（稳定身份）</span>
            <select v-model="newMaintainer" :disabled="busy || evidenceOnly">
              <option value="">请选择身份</option>
              <option v-for="identity in maintainerCandidates" :key="identity.identity_id" :value="identity.identity_id">
                {{ identity.name }}（{{ identity.identity_id }}）
              </option>
            </select>
          </label>
          <button class="btn primary" type="button" :disabled="busy || evidenceOnly || !newMaintainer" @click="handover">
            确认移交
          </button>
        </div>
      </div>

      <!-- 证据链 -->
      <div v-if="activeTab === 'evidence'">
        <h4 class="block-title">移交 / 签认 / 撤回证据（只追加、只读）</h4>
        <table v-if="evidence.length" class="data-table compact">
          <thead><tr><th>证据编号</th><th>类型</th><th>操作人</th><th>时间</th><th>内容摘要</th></tr></thead>
          <tbody>
            <tr v-for="record in evidence" :key="record.evidence_id">
              <td>{{ record.evidence_id }}</td>
              <td>{{ record.kind }}</td>
              <td>{{ record.actor_id }}</td>
              <td>{{ record.created_at }}</td>
              <td><code class="detail-code">{{ JSON.stringify(record.detail) }}</code></td>
            </tr>
          </tbody>
        </table>
        <div v-else class="empty-state">暂无证据记录。</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { readError, request } from '@/api/client'
import type {
  CurrentGrant,
  EvidenceRecord,
  GrantDiff,
  GrantItem,
  PreviewResponse,
} from '@/types/access'

const props = defineProps<{ tagPk: number; stableTagId: string }>()
const emit = defineEmits<{ (event: 'close'): void; (event: 'changed'): void }>()

const tabs = [
  { key: 'preview', label: '范围预览' },
  { key: 'diff', label: '差异签认' },
  { key: 'handover', label: '移交与撤回' },
  { key: 'evidence', label: '证据链' },
] as const

type TabKey = (typeof tabs)[number]['key']

const activeTab = ref<TabKey>('preview')
const preview = ref<PreviewResponse | null>(null)
const candidatePreview = ref<PreviewResponse | null>(null)
const diff = ref<GrantDiff | null>(null)
const evidence = ref<EvidenceRecord[]>([])
const identities = ref<Array<{ identity_id: string; name: string; role: string }>>([])
const candidate = ref<Record<string, GrantItem>>({})
const baseVersion = ref(0)
const newMaintainer = ref('')
const busy = ref(false)
const errorMessage = ref('')
const infoMessage = ref('')
const evidenceOnly = ref(false)

const maintainerCandidates = computed(() =>
  identities.value.filter((item) => item.role === 'maintainer' || item.role === 'admin'),
)
const currentMaintainer = computed(() => {
  const id = preview.value?.maintainer_id ?? ''
  return identities.value.find((i) => i.identity_id === id)?.name ?? id
})

const diffGroups = computed(() => {
  const d = diff.value
  return [
    { key: 'added', label: '新增授权', cls: 'diff-add', entries: d?.added ?? [] },
    { key: 'removed', label: '移除授权', cls: 'diff-remove', entries: d?.removed ?? [] },
    { key: 'changed', label: '变更授权', cls: 'diff-change', entries: d?.changed ?? [] },
  ]
})
const isNoDiff = computed(() => {
  const d = diff.value
  return !!d && !d.added.length && !d.removed.length && !d.changed.length
})

function sourceText(source: string): string {
  const map: Record<string, string> = {
    explicit_self: '本层显式授权',
    inherited_allow: '父级继承允许',
    explicit_deny: '显式拒绝（拒绝优先）',
    default_confidential: '保密默认拒绝',
    default_open: '非保密默认允许',
    implicit_maintainer: '维护者隐式可见',
    implicit_admin: '管理员隐式可见',
  }
  return map[source] ?? source
}

function stateText(state: string): string {
  const map: Record<string, string> = {
    accessible: '交集放行',
    out_of_tag_scope: '标签范围外',
    blocked_by_tag: '标签裁决拦截',
    blocked_by_dataset: '数据集授权拦截',
  }
  return map[state] ?? state
}

function grantText(grant?: { effect: string; scope: string[] }): string {
  if (!grant) {
    return '—（无显式授权）'
  }
  const effect = grant.effect === 'allow' ? '允许' : '拒绝'
  return `${effect}${grant.scope.length ? ` / ${grant.scope.join('、')}` : ''}`
}

function grantsPayload(): GrantItem[] {
  return Object.values(candidate.value)
}

function initCandidate(grants: CurrentGrant[]) {
  const next: Record<string, GrantItem> = {}
  for (const grant of grants) {
    next[grant.identity_id] = {
      identity_id: grant.identity_id,
      effect: grant.effect,
      scope: [...grant.scope],
    }
  }
  candidate.value = next
}

async function loadIdentities() {
  const response = await request('/api/access/identities')
  if (response.ok) {
    const data = (await response.json()) as { items: Array<{ identity_id: string; name: string; role: string }> }
    identities.value = data.items
  }
}

async function loadPreview() {
  const response = await request(`/api/access/tags/${props.tagPk}/preview`)
  if (response.status === 403) {
    evidenceOnly.value = true
    infoMessage.value = await readError(response, '仅可只读证据')
    return
  }
  if (!response.ok) {
    throw new Error(await readError(response, '范围预览读取失败'))
  }
  const data = (await response.json()) as PreviewResponse
  preview.value = data
  baseVersion.value = data.version
  initCandidate(data.current_grants)
  candidatePreview.value = null
  diff.value = null
}

async function loadEvidence() {
  const response = await request(
    `/api/access/evidence?target_type=tag&target_id=${encodeURIComponent(props.stableTagId)}`,
  )
  if (response.ok) {
    const data = (await response.json()) as { items: EvidenceRecord[] }
    evidence.value = data.items
  }
}

function onEffectChange(identityId: string, value: string) {
  if (value === 'none') {
    delete candidate.value[identityId]
    candidate.value = { ...candidate.value }
    return
  }
  candidate.value = {
    ...candidate.value,
    [identityId]: {
      identity_id: identityId,
      effect: value as GrantItem['effect'],
      scope: candidate.value[identityId]?.scope ?? [],
    },
  }
}

function toggleScope(identityId: string, datasetId: string) {
  const item = candidate.value[identityId]
  if (!item || item.effect !== 'allow') {
    return
  }
  const scope = new Set(item.scope)
  if (scope.has(datasetId)) {
    scope.delete(datasetId)
  } else {
    scope.add(datasetId)
  }
  candidate.value = {
    ...candidate.value,
    [identityId]: { ...item, scope: [...scope] },
  }
}

function resetCandidate() {
  if (preview.value) {
    initCandidate(preview.value.current_grants)
  }
  candidatePreview.value = null
  diff.value = null
  infoMessage.value = '已重置为当前生效授权。'
}

async function calculate() {
  busy.value = true
  errorMessage.value = ''
  try {
    const response = await request(`/api/access/tags/${props.tagPk}/preview`, {
      method: 'POST',
      body: JSON.stringify({ grants: grantsPayload() }),
    })
    if (!response.ok) {
      throw new Error(await readError(response, '候选试算失败'))
    }
    candidatePreview.value = (await response.json()) as PreviewResponse
    infoMessage.value = '候选范围仅在内存试算，未写入服务端，其他窗口无法看到。'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '候选试算失败'
  } finally {
    busy.value = false
  }
}

async function computeDiff() {
  busy.value = true
  errorMessage.value = ''
  try {
    const response = await request(`/api/access/tags/${props.tagPk}/diff`, {
      method: 'POST',
      body: JSON.stringify({ grants: grantsPayload() }),
    })
    if (!response.ok) {
      throw new Error(await readError(response, '差异计算失败'))
    }
    diff.value = (await response.json()) as GrantDiff
    activeTab.value = 'diff'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '差异计算失败'
  } finally {
    busy.value = false
  }
}

async function commit() {
  busy.value = true
  errorMessage.value = ''
  infoMessage.value = ''
  try {
    const response = await request(`/api/access/tags/${props.tagPk}/commit`, {
      method: 'POST',
      body: JSON.stringify({ base_version: baseVersion.value, grants: grantsPayload() }),
    })
    if (!response.ok) {
      throw new Error(await readError(response, '授权签认失败'))
    }
    const data = (await response.json()) as {
      changed: boolean
      version: number
      evidence_id?: string
      message: string
    }
    infoMessage.value = data.changed
      ? `${data.message}（新版本 v${data.version}，证据 ${data.evidence_id}）`
      : data.message
    await reloadAll()
    emit('changed')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '授权签认失败'
  } finally {
    busy.value = false
  }
}

async function withdraw() {
  busy.value = true
  errorMessage.value = ''
  try {
    const response = await request(`/api/access/tags/${props.tagPk}/withdraw`, {
      method: 'POST',
      body: JSON.stringify({ base_version: baseVersion.value, grants: [] }),
    })
    if (!response.ok) {
      throw new Error(await readError(response, '撤回失败'))
    }
    const data = (await response.json()) as { changed: boolean; version?: number; message: string }
    infoMessage.value = data.message
    await reloadAll()
    emit('changed')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '撤回失败'
  } finally {
    busy.value = false
  }
}

async function handover() {
  busy.value = true
  errorMessage.value = ''
  try {
    const response = await request(`/api/access/tags/${props.tagPk}/handover`, {
      method: 'POST',
      body: JSON.stringify({ base_version: baseVersion.value, new_maintainer_id: newMaintainer.value }),
    })
    if (!response.ok) {
      throw new Error(await readError(response, '移交失败'))
    }
    const data = (await response.json()) as { message: string; evidence_id: string }
    infoMessage.value = `${data.message}（证据 ${data.evidence_id}）`
    await reloadAll()
    emit('changed')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '移交失败'
  } finally {
    busy.value = false
  }
}

async function reloadAll() {
  await loadPreview()
  await loadEvidence()
}

function switchTab(key: TabKey) {
  activeTab.value = key
  if (key === 'evidence') {
    void loadEvidence()
  }
}

onMounted(async () => {
  try {
    await loadIdentities()
    await loadPreview()
    await loadEvidence()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '编辑器加载失败'
  }
})
</script>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 32px 16px;
  z-index: 50;
  overflow-y: auto;
}
.modal {
  background: #fff;
  border-radius: 10px;
  width: min(1080px, 100%);
  padding: 20px 24px;
  border: 1px solid var(--border);
}
.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.tab-bar { display: flex; gap: 8px; border-bottom: 1px solid var(--border); margin: 12px 0; }
.tab-btn { border: none; background: none; padding: 8px 14px; cursor: pointer; font-size: 13px; color: var(--muted); border-bottom: 2px solid transparent; }
.tab-btn.active { color: var(--brand); border-bottom-color: var(--brand); font-weight: 600; }
.block-title { margin: 16px 0 8px; font-size: 14px; }
.compact th, .compact td { font-size: 12px; padding: 6px 8px; vertical-align: top; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; margin-left: 6px; }
.badge-secret { background: #fef3c7; color: #92400e; }
.badge-open { background: #e0f2fe; color: #075985; }
.badge-allow { background: #dcfce7; color: #166534; }
.badge-deny { background: #fee2e2; color: #991b1b; }
.scope-check { margin-right: 12px; font-size: 12px; white-space: nowrap; }
.ds-state { display: block; font-size: 12px; margin-bottom: 2px; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }
.dot.accessible { background: #16a34a; }
.dot.out_of_tag_scope { background: #94a3b8; }
.dot.blocked_by_tag, .dot.blocked_by_dataset { background: #dc2626; }
.muted { color: var(--muted); font-style: normal; }
.info-text { color: #1d4ed8; }
.warn-text { color: #b45309; }
.candidate-box { margin-top: 14px; border: 1px dashed var(--brand); border-radius: 8px; padding: 10px; background: #f8fbff; }
.diff-group { margin-bottom: 12px; }
.diff-add { color: #166534; }
.diff-remove { color: #991b1b; }
.diff-change { color: #92400e; }
.detail-code { font-size: 11px; word-break: break-all; }
select { padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
</style>

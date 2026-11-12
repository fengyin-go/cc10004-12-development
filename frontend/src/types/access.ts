/** 覆盖对象授权域的接口类型，与后端 Pydantic 模型对应。 */

export interface GrantItem {
  identity_id: string
  effect: 'allow' | 'deny'
  scope: string[]
}

export interface CurrentGrant extends GrantItem {
  granted_by: string
  updated_at: string
}

export interface DatasetPreview {
  dataset_id: string
  name: string
  confidential_scope: string
  fields?: Array<{ field: string; label: string; level: string }>
}

export interface IdentityDatasetState {
  dataset_id: string
  name: string
  confidential_scope: string
  state: 'accessible' | 'out_of_tag_scope' | 'blocked_by_tag' | 'blocked_by_dataset'
  reason: string
}

export interface IdentityPreview {
  identity_id: string
  name: string
  role: string
  decision: 'allow' | 'deny'
  decision_source: string
  source_tag: string
  scope: string[]
  datasets: IdentityDatasetState[]
}

export interface PreviewResponse {
  tag_pk: number
  stable_tag_id: string
  tag_name: string
  confidential: boolean
  version: number
  maintainer_id: string
  coverage: string[]
  available_datasets: DatasetPreview[]
  identities: IdentityPreview[]
  current_grants: CurrentGrant[]
  diff?: GrantDiff
}

export interface DiffEntry {
  identity_id: string
  old?: { effect: string; scope: string[] }
  new?: { effect: string; scope: string[] }
}

export interface GrantDiff {
  added: DiffEntry[]
  removed: DiffEntry[]
  changed: DiffEntry[]
  tag_version: number
}

export interface EvidenceRecord {
  evidence_id: string
  kind: string
  target_type: string
  target_id: string
  actor_id: string
  detail: Record<string, unknown>
  created_at: string
}

export interface DatasetItem {
  dataset_id: string
  name: string
  confidential_scope: string
  maintainer_id: string
  authorized: boolean
  fields: Array<{ field: string; label: string; level: string }>
}

export interface FieldSpec {
  dataset_id: string
  dataset_name: string
  confidential_scope: string
  fields: Array<{ field: string; label: string; level: string; visible_via_tags: string[] }>
  redacted_field_count: number
  visible_tags: Array<{ stable_tag_id: string; tag_name: string; confidential: boolean; decision_source: string }>
  rule: string
}

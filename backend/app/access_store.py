"""标签覆盖对象授权域：层级裁决、数据集授权、标签授权、移交证据。

并发与原子性约定：
- 模块级 RLock + atomic() 上下文，所有写操作在同一把锁内完成读-改-写，
  整份授权签认要么完整生效，要么完全不落地，不会出现半份新范围提前公开。
- 每条标签授权带单调递增 version，多窗口编辑时旧版本提交会被 409 拦下。
- 证据链只追加、不改写、不删除；移交后旧维护者仅保留证据只读权限。
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from threading import RLock
from typing import Any, Iterator

from app.store import store

access_lock = RLock()


@contextmanager
def atomic() -> Iterator[None]:
    """授权域事务边界：整段临界区内的变更对外同时可见。"""
    access_lock.acquire()
    try:
        yield
    finally:
        access_lock.release()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 演示用种子数据：身份见 app.bootstrap，这里只放授权域对象与初始授权关系。
# ---------------------------------------------------------------------------

# 数据集：acl 为显式数据集授权（allow/deny），缺省表示走默认口径。
DATASET_SEED: list[dict[str, Any]] = [
    {
        "dataset_id": "DS-0001",
        "name": "客户主数据",
        "confidential_scope": "含年收入区间、持仓规模等保密字段",
        "maintainer_id": "u_maint_a",
        "acl": {"u_analyst": "allow"},
        "fields": [
            {"field": "cust_no", "label": "客户编号", "level": "公开"},
            {"field": "age_band", "label": "年龄段", "level": "公开"},
            {"field": "income_band", "label": "年收入区间", "level": "保密"},
            {"field": "asset_scale", "label": "持仓规模", "level": "保密"},
        ],
    },
    {
        "dataset_id": "DS-0002",
        "name": "营销触达记录",
        "confidential_scope": "渠道转化明细，默认内部可见",
        "maintainer_id": "u_maint_b",
        "acl": {},
        "fields": [
            {"field": "batch_no", "label": "触达批次", "level": "公开"},
            {"field": "channel_code", "label": "渠道编码", "level": "公开"},
            {"field": "conv_rate", "label": "转化率", "level": "保密"},
        ],
    },
    {
        "dataset_id": "DS-0003",
        "name": "风控黑名单",
        "confidential_scope": "整库保密，未获数据集授权者不可见",
        "maintainer_id": "u_maint_a",
        "acl": {"u_guest": "deny"},
        "fields": [
            {"field": "cust_no", "label": "客户编号", "level": "公开"},
            {"field": "risk_level", "label": "风险等级", "level": "保密"},
            {"field": "hit_rule", "label": "命中规则", "level": "保密"},
        ],
    },
]

# 标签覆盖关系：标签稳定标识 -> 覆盖的数据集。
TAG_COVERAGE: dict[str, list[str]] = {
    "TAG-CORE-01": ["DS-0001", "DS-0003"],
    "TAG-CORE-02": ["DS-0001"],
    "TAG-MKT-01": ["DS-0001", "DS-0002"],
    "TAG-MKT-02": ["DS-0002"],
    "TAG-MKT-03": ["DS-0002", "DS-0003"],
}

# 初始显式授权：(标签稳定标识, 身份) -> (allow/deny, 数据集范围)。
GRANT_SEED: dict[tuple[str, str], tuple[str, list[str]]] = {
    ("TAG-CORE-01", "u_analyst"): ("allow", ["DS-0001"]),
    ("TAG-CORE-01", "u_guest"): ("deny", []),
    ("TAG-MKT-01", "u_analyst"): ("allow", ["DS-0001", "DS-0002"]),
    # 父级允许、子级显式拒绝：用于演示“继承允许与显式拒绝冲突时拒绝为准”。
    ("TAG-MKT-02", "u_analyst"): ("deny", []),
}


class AccessStore:
    """授权域内存仓储，进程内单例。"""

    def __init__(self) -> None:
        self.datasets: dict[str, dict[str, Any]] = {}
        # tag_pk 即数据标签模块行 id，稳定标识 stable_tag_id 用于区分重名标签。
        self.tags: dict[int, dict[str, Any]] = {}
        self.grants: dict[tuple[int, str], dict[str, Any]] = {}
        self.past_maintainers: dict[str, set[str]] = {}  # 目标标识 -> 历任维护人
        self.evidence: list[dict[str, Any]] = []
        self._evidence_seq = 0
        self._bootstrap()

    # ------------------------------------------------------------------ 初始化
    def _bootstrap(self) -> None:
        for dataset in DATASET_SEED:
            self.datasets[dataset["dataset_id"]] = {
                **dataset,
                "acl": dict(dataset["acl"]),
                "fields": [dict(field) for field in dataset["fields"]],
            }
            self.past_maintainers[dataset["dataset_id"]] = set()

        tag_rows = store.rows("tag")
        for row in tag_rows:
            pk = int(row["id"])
            stable = str(row["stable_tag_id"])
            tag = {
                "pk": pk,
                "stable_tag_id": stable,
                "name": row["标签名称"],
                "level": int(row["标签层级"]),
                "parent_pk": int(row["parent_pk"]) if row.get("parent_pk") else None,
                "confidential": bool(row["保密标签"]),
                "maintainer_id": row["维护人"],
                "coverage": list(TAG_COVERAGE.get(stable, [])),
                "version": 1,
            }
            self.tags[pk] = tag
            self.past_maintainers[stable] = set()

        for (stable, identity_id), (effect, scope) in GRANT_SEED.items():
            tag_pk = self._find_tag_pk(stable)
            if tag_pk is None:
                continue
            self.grants[(tag_pk, identity_id)] = {
                "effect": effect,
                "scope": list(scope),
                "granted_by": "system",
                "updated_at": _now(),
            }
            self._append_evidence(
                kind="授权初始化",
                target_type="tag",
                target_id=stable,
                actor_id="system",
                detail={"identity_id": identity_id, "effect": effect, "scope": scope},
            )

    def _find_tag_pk(self, stable_tag_id: str) -> int | None:
        for tag in self.tags.values():
            if tag["stable_tag_id"] == stable_tag_id:
                return tag["pk"]
        return None

    # ------------------------------------------------------------------ 证据链
    def _append_evidence(
        self,
        *,
        kind: str,
        target_type: str,
        target_id: str,
        actor_id: str,
        detail: dict[str, Any],
    ) -> dict[str, Any]:
        self._evidence_seq += 1
        record = {
            "evidence_id": f"EV-{self._evidence_seq:04d}",
            "kind": kind,
            "target_type": target_type,
            "target_id": target_id,
            "actor_id": actor_id,
            "detail": detail,
            "created_at": _now(),
        }
        self.evidence.append(record)
        return record

    def list_evidence(self, *, target_type: str | None = None, target_id: str | None = None) -> list[dict[str, Any]]:
        records = self.evidence
        if target_type:
            records = [r for r in records if r["target_type"] == target_type]
        if target_id:
            records = [r for r in records if r["target_id"] == target_id]
        return [dict(r) for r in records]

    # ------------------------------------------------------------------ 层级裁决
    def _path_to_root(self, tag_pk: int) -> list[dict[str, Any]]:
        """返回从根到当前标签的层级路径。"""
        chain: list[dict[str, Any]] = []
        cursor: int | None = tag_pk
        seen: set[int] = set()
        while cursor is not None and cursor not in seen:
            seen.add(cursor)
            tag = self.tags[cursor]
            chain.append(tag)
            cursor = tag["parent_pk"]
        return list(reversed(chain))

    def _identity_role(self, identity_id: str) -> str:
        from app.security import registry

        identity = registry.get(identity_id)
        return identity["role"] if identity else ""

    def _confidential_fallback(self, tag: dict[str, Any], identity_id: str) -> dict[str, Any]:
        """保密标签在无显式授权时的默认口径。

        维护者与平台管理员保有隐式可见性，否则无法履行管理职责；
        显式拒绝在调用方的层级遍历中已提前返回，拒绝优先不受此隐式口径影响。
        """
        if identity_id == tag["maintainer_id"] or self._identity_role(identity_id) == "admin":
            source = "implicit_maintainer" if identity_id == tag["maintainer_id"] else "implicit_admin"
            return {
                "decision": "allow",
                "source": source,
                "source_tag": tag["stable_tag_id"],
                "scope": list(tag["coverage"]),
            }
        return {"decision": "deny", "source": "default_confidential", "source_tag": tag["stable_tag_id"], "scope": []}

    def effective_decision(self, tag_pk: int, identity_id: str) -> dict[str, Any]:
        """按标签层级裁决单个身份的有效权限。

        规则：沿根到叶遍历；遇到显式拒绝立即判否（拒绝优先于一切继承允许）；
        显式允许按最近一层覆盖父层允许；全程无显式记录时，保密标签默认拒绝、
        非保密标签默认允许（范围为该标签全部覆盖对象）。
        """
        tag = self.tags[tag_pk]
        allow: dict[str, Any] | None = None
        for node in self._path_to_root(tag_pk):
            grant = self.grants.get((node["pk"], identity_id))
            if grant is None:
                continue
            if grant["effect"] == "deny":
                return {
                    "decision": "deny",
                    "source": "explicit_deny",
                    "source_tag": node["stable_tag_id"],
                    "scope": [],
                }
            allow = {
                "decision": "allow",
                "source": "explicit_self" if node["pk"] == tag_pk else "inherited_allow",
                "source_tag": node["stable_tag_id"],
                "scope": list(grant["scope"]),
            }
        if allow is not None:
            return allow
        if tag["confidential"]:
            return self._confidential_fallback(tag, identity_id)
        return {
            "decision": "allow",
            "source": "default_open",
            "source_tag": tag["stable_tag_id"],
            "scope": list(tag["coverage"]),
        }

    def dataset_acl_decision(self, dataset_id: str, identity_id: str) -> str:
        """数据集授权：显式 deny 拒绝；显式 allow 或无记录（默认允许）放行。"""
        dataset = self.datasets[dataset_id]
        return dataset["acl"].get(identity_id, "allow")

    def can_see_tag_name(self, tag_pk: int, identity_id: str) -> bool:
        """保密标签对未获准者连名称都不可泄露：判否即不可见。"""
        return self.effective_decision(tag_pk, identity_id)["decision"] == "allow"

    # ------------------------------------------------------------------ 范围预览
    def preview_authorization(
        self,
        tag_pk: int,
        *,
        identities: list[dict[str, Any]],
        override_grants: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """生成范围预览：逐身份裁决，并对每个覆盖数据集给出交集结论。"""
        tag = self.tags[tag_pk]
        effective_grants = self.grants
        if override_grants is not None:
            effective_grants = {
                key: value for key, value in self.grants.items() if key[0] != tag_pk
            }
            for identity_id, grant in override_grants.items():
                effective_grants[(tag_pk, identity_id)] = grant

        original_decide = self.effective_decision
        identity_results: list[dict[str, Any]] = []
        for identity in identities:
            identity_id = identity["identity_id"]
            if override_grants is None:
                decision = original_decide(tag_pk, identity_id)
            else:
                decision = self._decide_with_override(tag_pk, identity_id, override_grants)

            dataset_results: list[dict[str, Any]] = []
            for dataset_id in tag["coverage"]:
                dataset = self.datasets[dataset_id]
                item: dict[str, Any] = {
                    "dataset_id": dataset_id,
                    "name": dataset["name"],
                    "confidential_scope": dataset["confidential_scope"],
                }
                if decision["decision"] == "deny":
                    item["state"] = "blocked_by_tag"
                    item["reason"] = f"标签裁决拒绝（{decision['source_tag']}）"
                elif dataset_id not in decision["scope"]:
                    item["state"] = "out_of_tag_scope"
                    item["reason"] = "不在标签授权范围之内"
                elif self.dataset_acl_decision(dataset_id, identity_id) == "deny":
                    item["state"] = "blocked_by_dataset"
                    item["reason"] = "数据集显式拒绝，交集为空"
                else:
                    item["state"] = "accessible"
                    item["reason"] = "数据集授权与标签可见性交集放行"
                dataset_results.append(item)
            identity_results.append({
                "identity_id": identity_id,
                "name": identity["name"],
                "role": identity["role"],
                "decision": decision["decision"],
                "decision_source": decision["source"],
                "source_tag": decision["source_tag"],
                "scope": decision["scope"],
                "datasets": dataset_results,
            })

        available_datasets = [
            {
                "dataset_id": ds_id,
                "name": self.datasets[ds_id]["name"],
                "confidential_scope": self.datasets[ds_id]["confidential_scope"],
                "fields": [dict(field) for field in self.datasets[ds_id]["fields"]],
            }
            for ds_id in tag["coverage"]
        ]
        return {
            "tag_pk": tag_pk,
            "stable_tag_id": tag["stable_tag_id"],
            "tag_name": tag["name"],
            "confidential": tag["confidential"],
            "version": tag["version"],
            "maintainer_id": tag["maintainer_id"],
            "coverage": list(tag["coverage"]),
            "available_datasets": available_datasets,
            "identities": identity_results,
            "current_grants": [
                {
                    "identity_id": identity_id,
                    "effect": grant["effect"],
                    "scope": list(grant["scope"]),
                    "granted_by": grant.get("granted_by", "candidate"),
                    "updated_at": grant.get("updated_at", _now()),
                }
                for (pk, identity_id), grant in sorted(effective_grants.items(), key=lambda kv: kv[0][1])
                if pk == tag_pk
            ],
        }

    def _decide_with_override(
        self, tag_pk: int, identity_id: str, override: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        """以候选授权替代当前标签层授权后再走层级裁决（不落库）。"""
        tag = self.tags[tag_pk]
        allow: dict[str, Any] | None = None
        for node in self._path_to_root(tag_pk):
            grant = override.get(identity_id) if node["pk"] == tag_pk else self.grants.get((node["pk"], identity_id))
            if grant is None:
                continue
            if grant["effect"] == "deny":
                return {
                    "decision": "deny",
                    "source": "explicit_deny",
                    "source_tag": node["stable_tag_id"],
                    "scope": [],
                }
            allow = {
                "decision": "allow",
                "source": "explicit_self" if node["pk"] == tag_pk else "inherited_allow",
                "source_tag": node["stable_tag_id"],
                "scope": list(grant["scope"]),
            }
        if allow is not None:
            return allow
        if tag["confidential"]:
            return self._confidential_fallback(tag, identity_id)
        return {
            "decision": "allow",
            "source": "default_open",
            "source_tag": tag["stable_tag_id"],
            "scope": list(tag["coverage"]),
        }

    # ------------------------------------------------------------------ 差异签认
    def diff_grants(
        self, tag_pk: int, candidate: dict[str, dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        """对比候选授权与当前授权，输出新增/移除/变更三类差异。"""
        tag = self.tags[tag_pk]
        current = {
            identity_id: grant
            for (pk, identity_id), grant in self.grants.items()
            if pk == tag_pk
        }
        added, removed, changed = [], [], []
        for identity_id, grant in candidate.items():
            old = current.get(identity_id)
            if old is None:
                added.append({"identity_id": identity_id, "new": self._public_grant(grant)})
            elif old["effect"] != grant["effect"] or sorted(old["scope"]) != sorted(grant["scope"]):
                changed.append({
                    "identity_id": identity_id,
                    "old": self._public_grant(old),
                    "new": self._public_grant(grant),
                })
        for identity_id, grant in current.items():
            if identity_id not in candidate:
                removed.append({"identity_id": identity_id, "old": self._public_grant(grant)})
        return {"added": added, "removed": removed, "changed": changed, "tag_version": tag["version"]}

    @staticmethod
    def _public_grant(grant: dict[str, Any]) -> dict[str, Any]:
        return {"effect": grant["effect"], "scope": list(grant["scope"])}

    def commit_authorization(
        self,
        tag_pk: int,
        actor_id: str,
        *,
        base_version: int,
        candidate: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, int, str]:
        """原子签认：版本校验、差异计算、整份替换在同一临界区完成。

        返回 (结果, http_status, message)。重复分配（候选与现状完全一致）不增添关联，
        也不产生新版本或新证据。
        """
        if tag_pk not in self.tags:
            return None, 404, "标签不存在或已归档"
        tag = self.tags[tag_pk]
        with atomic():
            if tag["version"] != base_version:
                return None, 409, f"授权已被其他窗口更新（当前版本 {tag['version']}），请刷新后重新签认"
            diff = self.diff_grants(tag_pk, candidate)
            no_change = not (diff["added"] or diff["removed"] or diff["changed"])
            if no_change:
                return {
                    "changed": False,
                    "version": tag["version"],
                    "diff": diff,
                    "message": "候选范围与当前授权完全一致，重复分配未增添关联",
                }, 200, "ok"

            # 整份替换：先清后写在同一把锁内，外部永远观察不到中间态。
            for identity_id in list(identity for (pk, identity) in self.grants if pk == tag_pk):
                self.grants.pop((tag_pk, identity_id), None)
            for identity_id, grant in candidate.items():
                self.grants[(tag_pk, identity_id)] = {
                    "effect": grant["effect"],
                    "scope": list(grant["scope"]),
                    "granted_by": actor_id,
                    "updated_at": _now(),
                }
            tag["version"] += 1
            evidence = self._append_evidence(
                kind="授权签认",
                target_type="tag",
                target_id=tag["stable_tag_id"],
                actor_id=actor_id,
                detail={"base_version": base_version, "new_version": tag["version"], "diff": diff},
            )
            return {
                "changed": True,
                "version": tag["version"],
                "diff": diff,
                "evidence_id": evidence["evidence_id"],
                "message": "整份授权已原子生效",
            }, 200, "ok"

    # ------------------------------------------------------------------ 撤回
    def withdraw_authorization(
        self, tag_pk: int, actor_id: str, *, base_version: int
    ) -> tuple[dict[str, Any] | None, int, str]:
        if tag_pk not in self.tags:
            return None, 404, "标签不存在或已归档"
        tag = self.tags[tag_pk]
        with atomic():
            if tag["version"] != base_version:
                return None, 409, f"授权已被其他窗口更新（当前版本 {tag['version']}），请刷新后重试"
            removed = [
                {"identity_id": identity_id, **self._public_grant(grant)}
                for (pk, identity_id), grant in list(self.grants.items())
                if pk == tag_pk
            ]
            if not removed:
                return {"changed": False, "version": tag["version"], "message": "当前无显式授权，撤回为空操作"}, 200, "ok"
            for identity_id in [item["identity_id"] for item in removed]:
                self.grants.pop((tag_pk, identity_id), None)
            tag["version"] += 1
            evidence = self._append_evidence(
                kind="授权撤回",
                target_type="tag",
                target_id=tag["stable_tag_id"],
                actor_id=actor_id,
                detail={"base_version": base_version, "removed": removed},
            )
            return {
                "changed": True,
                "version": tag["version"],
                "removed": removed,
                "evidence_id": evidence["evidence_id"],
                "message": "全部显式授权已撤回，权限回落至层级默认口径",
            }, 200, "ok"

    # ------------------------------------------------------------------ 移交
    def handover_tag(
        self, tag_pk: int, actor_id: str, new_maintainer_id: str, *, base_version: int
    ) -> tuple[dict[str, Any] | None, int, str]:
        if tag_pk not in self.tags:
            return None, 404, "标签不存在或已归档"
        tag = self.tags[tag_pk]
        with atomic():
            if tag["version"] != base_version:
                return None, 409, f"授权已被其他窗口更新（当前版本 {tag['version']}），请刷新后重试"
            old_maintainer = tag["maintainer_id"]
            if old_maintainer == new_maintainer_id:
                return None, 400, "新维护者与当前维护者相同，无需移交"
            tag["maintainer_id"] = new_maintainer_id
            self.past_maintainers[tag["stable_tag_id"]].add(old_maintainer)
            tag["version"] += 1
            evidence = self._append_evidence(
                kind="覆盖对象移交",
                target_type="tag",
                target_id=tag["stable_tag_id"],
                actor_id=actor_id,
                detail={
                    "old_maintainer_id": old_maintainer,
                    "new_maintainer_id": new_maintainer_id,
                    "base_version": base_version,
                },
            )
            return {
                "version": tag["version"],
                "old_maintainer_id": old_maintainer,
                "new_maintainer_id": new_maintainer_id,
                "evidence_id": evidence["evidence_id"],
                "message": "维护职责已移交，旧维护者仅保留证据只读权限",
            }, 200, "ok"

    def handover_dataset(
        self, dataset_id: str, actor_id: str, new_maintainer_id: str
    ) -> tuple[dict[str, Any] | None, int, str]:
        if dataset_id not in self.datasets:
            return None, 404, "数据集不存在或已归档"
        dataset = self.datasets[dataset_id]
        with atomic():
            old_maintainer = dataset["maintainer_id"]
            if old_maintainer == new_maintainer_id:
                return None, 400, "新维护者与当前维护者相同，无需移交"
            dataset["maintainer_id"] = new_maintainer_id
            self.past_maintainers[dataset_id].add(old_maintainer)
            evidence = self._append_evidence(
                kind="覆盖对象移交",
                target_type="dataset",
                target_id=dataset_id,
                actor_id=actor_id,
                detail={"old_maintainer_id": old_maintainer, "new_maintainer_id": new_maintainer_id},
            )
            return {
                "old_maintainer_id": old_maintainer,
                "new_maintainer_id": new_maintainer_id,
                "evidence_id": evidence["evidence_id"],
                "message": "数据集维护职责已移交，旧维护者不能再借旧关联追加公开内容",
            }, 200, "ok"

    # ------------------------------------------------------------------ 跨模块字段说明
    def field_spec(self, dataset_id: str, identity_id: str) -> tuple[dict[str, Any] | None, int, str]:
        """跨模块数据分享：取数据集授权与标签可见性的交集生成字段说明。"""
        if dataset_id not in self.datasets:
            return None, 404, "数据集不存在或已归档"
        dataset = self.datasets[dataset_id]
        with atomic():
            if self.dataset_acl_decision(dataset_id, identity_id) == "deny":
                # 连可读说明都不返回，避免借分享通道探测保密资产。
                return None, 403, "数据集授权已显式拒绝，服务端拦截字段说明生成"
            visible_tags: list[dict[str, Any]] = []
            confidential_allowed = False
            for tag in self.tags.values():
                if dataset_id not in tag["coverage"]:
                    continue
                decision = self.effective_decision(tag["pk"], identity_id)
                if decision["decision"] != "allow":
                    continue  # 不可见标签：名称与存在性都不进入说明
                visible_tags.append({
                    "stable_tag_id": tag["stable_tag_id"],
                    "tag_name": tag["name"],
                    "confidential": tag["confidential"],
                    "decision_source": decision["source"],
                })
                if tag["confidential"]:
                    confidential_allowed = True

            fields: list[dict[str, Any]] = []
            redacted_count = 0
            for field in dataset["fields"]:
                if field["level"] == "保密" and not confidential_allowed:
                    redacted_count += 1
                    continue
                fields.append({
                    "field": field["field"],
                    "label": field["label"],
                    "level": field["level"],
                    "visible_via_tags": [t["stable_tag_id"] for t in visible_tags],
                })
            return {
                "dataset_id": dataset_id,
                "dataset_name": dataset["name"],
                "confidential_scope": dataset["confidential_scope"],
                "fields": fields,
                "redacted_field_count": redacted_count,
                "visible_tags": visible_tags,
                "rule": "字段说明取数据集授权与标签可见性的交集；保密字段需至少获准一条保密覆盖标签",
            }, 200, "ok"


access_store = AccessStore()

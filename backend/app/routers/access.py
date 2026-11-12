"""覆盖对象授权接口：身份验证、授权编辑器、移交撤回、证据链与跨模块字段说明。

所有接口在服务端完成身份校验与越权拦截：
- 未携带有效 Bearer 令牌 → 401；
- 身份合法但不是该标签维护者/管理员 → 403；
- 保密标签对未获准者在标签模块即被脱敏，授权接口同样不暴露其存在性（404）。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.access_store import access_store
from app.schemas import (
    CandidatePreviewPayload,
    CommitPayload,
    DatasetHandoverPayload,
    LoginPayload,
    TagHandoverPayload,
)
from app.security import current_identity, registry

router = APIRouter(prefix="/api/access", tags=["覆盖对象授权"])


# ---------------------------------------------------------------------------
# 身份验证（应用内闭环）
# ---------------------------------------------------------------------------

@router.post("/auth/login")
def login(payload: LoginPayload) -> dict[str, object]:
    """口令校验通过后签发不透明令牌；失败给出统一提示，避免账号枚举。"""
    token = registry.login(payload.identity_id, payload.password)
    if token is None:
        raise HTTPException(status_code=401, detail="身份标识或口令不正确")
    identity = registry.get(payload.identity_id)
    return {"token": token, "identity": identity}


@router.post("/auth/logout")
def logout(request: Request) -> dict[str, object]:
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    registry.logout(token)
    return {"ok": True}


@router.get("/auth/me")
def me(request: Request) -> dict[str, object]:
    identity = current_identity(request)
    return {"identity": identity}


@router.get("/identities")
def list_identities(request: Request) -> dict[str, object]:
    """可授权身份清单（稳定身份区分重名人员），仅登录用户可取。"""
    current_identity(request)
    return {"items": registry.list_identities()}


# ---------------------------------------------------------------------------
# 内部守卫
# ---------------------------------------------------------------------------

def _editable_tag(tag_pk: int, identity: dict[str, object]) -> dict[str, object]:
    """越权拦截集中点。

    判定顺序：对象不存在 → 404；历任维护者知道对象存在但只剩证据只读权 → 403；
    无关身份对不可见保密标签按不存在处理 → 404（不泄露存在性）；
    可见但非维护者 → 403；当前维护者/管理员放行。
    """
    tag = access_store.tags.get(tag_pk)
    if tag is None:
        raise HTTPException(status_code=404, detail=f"标签 {tag_pk} 不存在或无权查看")
    identity_id = str(identity["identity_id"])
    is_admin = identity.get("role") == "admin"
    is_maintainer = tag["maintainer_id"] == identity_id
    is_past = identity_id in access_store.past_maintainers.get(tag["stable_tag_id"], set())
    if is_past and not is_maintainer:
        raise HTTPException(status_code=403, detail="您是历任维护者，仅可只读移交证据，不能再变更授权")
    if not access_store.can_see_tag_name(tag_pk, identity_id):
        raise HTTPException(status_code=404, detail=f"标签 {tag_pk} 不存在或无权查看")
    if not (is_admin or is_maintainer):
        raise HTTPException(status_code=403, detail="仅当前维护者或平台管理员可编辑授权")
    return tag


def _normalize_candidate(payload: CommitPayload | CandidatePreviewPayload) -> dict[str, dict[str, object]]:
    candidate: dict[str, dict[str, object]] = {}
    for item in payload.grants:
        if item.effect not in ("allow", "deny"):
            raise HTTPException(status_code=400, detail=f"授权效果「{item.effect}」非法，仅允许 allow/deny")
        if registry.get(item.identity_id) is None:
            raise HTTPException(status_code=400, detail=f"身份「{item.identity_id}」不存在，稳定身份不可伪造")
        scope = list(dict.fromkeys(item.scope))
        candidate[item.identity_id] = {"effect": item.effect, "scope": scope}
    return candidate


# ---------------------------------------------------------------------------
# 授权编辑器：范围预览 / 差异签认 / 撤回 / 移交
# ---------------------------------------------------------------------------

@router.get("/tags/{tag_pk}/preview")
def preview(tag_pk: int, request: Request) -> dict[str, object]:
    """范围预览：可用数据集、保密范围、逐身份层级裁决与当前授权基线。"""
    identity = current_identity(request)
    _editable_tag(tag_pk, identity)
    return access_store.preview_authorization(
        tag_pk, identities=registry.list_identities()
    )


@router.post("/tags/{tag_pk}/preview")
def preview_candidate(tag_pk: int, payload: CandidatePreviewPayload, request: Request) -> dict[str, object]:
    """候选范围试算：多窗口编辑时只在内存试算，绝不把半份新范围提前公开。"""
    identity = current_identity(request)
    _editable_tag(tag_pk, identity)
    candidate = _normalize_candidate(payload)
    result = access_store.preview_authorization(
        tag_pk,
        identities=registry.list_identities(),
        override_grants=candidate,
    )
    diff = access_store.diff_grants(tag_pk, candidate)
    result["diff"] = diff
    return result


@router.post("/tags/{tag_pk}/diff")
def diff(tag_pk: int, payload: CandidatePreviewPayload, request: Request) -> dict[str, object]:
    """差异签认前置：只计算新增/移除/变更，不产生任何写入。"""
    identity = current_identity(request)
    _editable_tag(tag_pk, identity)
    candidate = _normalize_candidate(payload)
    return access_store.diff_grants(tag_pk, candidate)


@router.post("/tags/{tag_pk}/commit")
def commit(tag_pk: int, payload: CommitPayload, request: Request) -> dict[str, object]:
    """整份授权原子签认：乐观版本校验 + 临界区整份替换。"""
    identity = current_identity(request)
    _editable_tag(tag_pk, identity)
    candidate = _normalize_candidate(payload)
    result, status, message = access_store.commit_authorization(
        tag_pk, str(identity["identity_id"]),
        base_version=payload.base_version, candidate=candidate,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=message)
    return result  # type: ignore[return-value]


@router.post("/tags/{tag_pk}/withdraw")
def withdraw(tag_pk: int, payload: CommitPayload, request: Request) -> dict[str, object]:
    """撤回全部显式授权，权限回落层级默认口径，撤回过程留证。"""
    identity = current_identity(request)
    _editable_tag(tag_pk, identity)
    result, status, message = access_store.withdraw_authorization(
        tag_pk, str(identity["identity_id"]), base_version=payload.base_version
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=message)
    return result  # type: ignore[return-value]


@router.post("/tags/{tag_pk}/handover")
def handover_tag(tag_pk: int, payload: TagHandoverPayload, request: Request) -> dict[str, object]:
    """标签维护职责移交：旧维护者随即失去编辑权，仅保留证据只读。"""
    identity = current_identity(request)
    _editable_tag(tag_pk, identity)
    if registry.get(payload.new_maintainer_id) is None:
        raise HTTPException(status_code=400, detail="新维护者身份不存在")
    result, status, message = access_store.handover_tag(
        tag_pk, str(identity["identity_id"]),
        payload.new_maintainer_id, base_version=payload.base_version,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=message)
    return result  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# 数据集：清单、移交与证据
# ---------------------------------------------------------------------------

@router.get("/datasets")
def list_datasets(request: Request) -> dict[str, object]:
    """列明可用数据集与保密范围；未获数据集授权者只看到脱敏占位。"""
    identity = current_identity(request)
    identity_id = str(identity["identity_id"])
    items = []
    for dataset in access_store.datasets.values():
        allowed = access_store.dataset_acl_decision(dataset["dataset_id"], identity_id) == "allow"
        items.append({
            "dataset_id": dataset["dataset_id"],
            "name": dataset["name"] if allowed else "未获准数据集",
            "confidential_scope": dataset["confidential_scope"] if allowed else "保密范围未获准阅览",
            "maintainer_id": dataset["maintainer_id"],
            "authorized": allowed,
            "fields": [dict(field) for field in dataset["fields"]] if allowed else [],
        })
    return {"items": items}


@router.post("/datasets/{dataset_id}/handover")
def handover_dataset(dataset_id: str, payload: DatasetHandoverPayload, request: Request) -> dict[str, object]:
    """数据集维护移交：旧维护者不能再借旧关联追加公开内容。"""
    identity = current_identity(request)
    dataset = access_store.datasets.get(dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="数据集不存在或已归档")
    is_admin = identity.get("role") == "admin"
    is_maintainer = dataset["maintainer_id"] == identity["identity_id"]
    is_past = identity["identity_id"] in access_store.past_maintainers.get(dataset_id, set())
    if not (is_admin or is_maintainer):
        reason = "您是历任维护者，仅可只读移交证据" if is_past else "仅当前维护者或平台管理员可发起移交"
        raise HTTPException(status_code=403, detail=reason)
    if registry.get(payload.new_maintainer_id) is None:
        raise HTTPException(status_code=400, detail="新维护者身份不存在")
    result, status, message = access_store.handover_dataset(
        dataset_id, str(identity["identity_id"]), payload.new_maintainer_id
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=message)
    return result  # type: ignore[return-value]


@router.get("/evidence")
def evidence(request: Request, target_type: str | None = None, target_id: str | None = None) -> dict[str, object]:
    """证据链只读查询：当前/历任维护者与管理员可查对应对象的签认、撤回、移交记录。"""
    identity = current_identity(request)
    identity_id = str(identity["identity_id"])
    is_admin = identity.get("role") == "admin"
    records = access_store.list_evidence(target_type=target_type, target_id=target_id)

    def can_read(record: dict[str, object]) -> bool:
        if is_admin or record["actor_id"] == identity_id:
            return True
        t_type, t_id = str(record["target_type"]), str(record["target_id"])
        past = access_store.past_maintainers.get(t_id, set())
        current = set()
        if t_type == "tag":
            tag_pk = access_store._find_tag_pk(t_id)
            if tag_pk is not None:
                current.add(access_store.tags[tag_pk]["maintainer_id"])
        elif t_type == "dataset" and t_id in access_store.datasets:
            current.add(access_store.datasets[t_id]["maintainer_id"])
        # 现任与历任维护者：对该对象的全部签认/撤回/移交证据保持只读。
        return identity_id in current or identity_id in past

    visible = [r for r in records if can_read(r)]
    return {"items": visible, "total": len(visible)}


# ---------------------------------------------------------------------------
# 跨模块数据分享：字段说明（数据集授权 ∩ 标签可见性）
# ---------------------------------------------------------------------------

@router.get("/field-spec/{dataset_id}")
def field_spec(dataset_id: str, request: Request) -> dict[str, object]:
    """跨模块字段说明：服务端按双重授权交集过滤，未授权字段直接剔除。"""
    identity = current_identity(request)
    result, status, message = access_store.field_spec(dataset_id, str(identity["identity_id"]))
    if status >= 400:
        raise HTTPException(status_code=status, detail=message)
    return result  # type: ignore[return-value]

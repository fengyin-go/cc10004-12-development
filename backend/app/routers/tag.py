"""数据标签接口：维护标签定义，覆盖提交校验、启用标签、停用标签等动作。

安全口径：全部接口要求完成应用内身份验证；保密标签对未获准者在列表与详情中
连名称、编号都不泄露，只返回脱敏占位行（stable_tag_id 也不暴露）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.access_store import access_store
from app.schemas import ActionResult, EntryPayload, PageResult
from app.security import current_identity
from app.services.tag import TagService

router = APIRouter(prefix="/api/tag", tags=["数据标签"])

service = TagService()

LIST_FIELDS = ["标签编号", "标签名称", "计算表达式", "覆盖对象", "更新频率", "标签层级", "值域范围", "失效天数"]
STATUSES = ["草稿", "待校验", "已启用", "已停用"]

REDACTED_TAG = {
    "标签编号": "受限标签",
    "标签名称": "未获准标签（名称保密）",
    "计算表达式": "—",
    "覆盖对象": "—",
    "更新频率": "—",
    "标签层级": "—",
    "值域范围": "—",
    "失效天数": "—",
}


def _redacted_row(row: dict[str, Any]) -> dict[str, Any]:
    """未获准保密标签的脱敏行：保留分页 id 占位但不泄露稳定身份与名称。"""
    return {
        "id": row.get("id"),
        "status": "已隐藏",
        "pending": False,
        "abnormal": False,
        "hidden": True,
        "confidential": True,
        **REDACTED_TAG,
    }


def _visible_row(row: dict[str, Any], identity_id: str) -> dict[str, Any]:
    tag_pk = int(row["id"])
    visible = access_store.can_see_tag_name(tag_pk, identity_id)
    if not visible:
        return _redacted_row(row)
    out = dict(row)
    tag = access_store.tags.get(tag_pk)
    if tag is not None:
        out["stable_tag_id"] = tag["stable_tag_id"]
        out["confidential"] = tag["confidential"]
        out["maintainer_id"] = tag["maintainer_id"]
        out["auth_version"] = tag["version"]
        out["editable"] = (
            tag["maintainer_id"] == identity_id
            or current_identity_role_is_admin(identity_id)
        )
    out["hidden"] = False
    return out


def current_identity_role_is_admin(identity_id: str) -> bool:
    from app.security import registry

    identity = registry.get(identity_id)
    return bool(identity and identity.get("role") == "admin")


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按标签编号检索"),
    status: str | None = Query(default=None, description="草稿、待校验、已启用、已停用"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按标签编号与状态过滤数据标签列表；未获准的保密标签以脱敏占位出现。"""
    identity = current_identity(request)
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    items = [_visible_row(row, str(identity["identity_id"])) for row in items]
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries(request: Request) -> dict[str, Any]:
    """导出数据标签清单：未获准的保密标签在导出中同样脱敏。"""
    identity = current_identity(request)
    items, total = service.list_entries(page=1, size=10000)
    items = [_visible_row(row, str(identity["identity_id"])) for row in items]
    return {"module": "tag", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int, request: Request) -> dict:
    """读取单条标签定义明细；未获准保密标签按不存在处理，避免探测。"""
    identity = current_identity(request)
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"标签定义 {entry_id} 不存在或已归档")
    if not access_store.can_see_tag_name(entry_id, str(identity["identity_id"])):
        raise HTTPException(status_code=404, detail=f"标签定义 {entry_id} 不存在或无权查看")
    return _visible_row(entry, str(identity["identity_id"]))


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload, request: Request) -> ActionResult:
    """登记一条标签定义，缺字段时说明原因而不是静默丢弃。"""
    current_identity(request)
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="标签定义已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload, request: Request) -> ActionResult:
    """对单条标签定义执行提交校验、启用标签、停用标签；不允许的动作会被拦下并说明原因。"""
    identity = current_identity(request)
    action = str(payload.values.get("action") or "").strip()
    # 状态流转仅限该标签当前维护者或管理员，越权在服务端拦截。
    tag = access_store.tags.get(entry_id)
    if tag is not None:
        is_admin = identity.get("role") == "admin"
        if tag["maintainer_id"] != identity["identity_id"] and not is_admin:
            raise HTTPException(status_code=403, detail="仅当前维护者可流转标签状态，服务端已拦截")
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


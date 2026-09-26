"""器材管理接口：维护拍摄器材，覆盖办理领用、归还器材、送修登记、维修完成、送修失败、办理退租等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.equipment import EquipmentService, transition_map

router = APIRouter(prefix="/api/equipment", tags=["器材管理"])

service = EquipmentService()

LIST_FIELDS = ["器材编号", "器材名称", "器材类别", "品牌型号", "所属租赁商", "日租金", "领用人员", "器材状态"]
STATUSES = ["在库", "已领用", "维修中", "已退租"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按器材编号检索"),
    status: str | None = Query(default=None, description="在库、已领用、维修中、已退租"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按器材编号与状态过滤器材管理列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/transitions")
def list_transitions() -> dict[str, Any]:
    """器材状态机全表：每个状态可执行的动作与去向，排查异常时对照这一处即可。"""
    return {"module": "equipment", "statuses": STATUSES, "transitions": transition_map()}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出器材管理清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "equipment", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条拍摄器材明细（含流转记录）；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"拍摄器材 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条拍摄器材，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="拍摄器材已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条拍摄器材执行状态动作；不允许的动作会被拦下、说明原因并保持原状态。"""
    action = str(payload.values.get("action") or "").strip()
    reason = str(payload.remark or payload.values.get("reason") or "").strip()
    entry, message = service.run_action(entry_id, action, reason=reason)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)

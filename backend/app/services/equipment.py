"""器材管理业务规则：状态流转、字段校验与筛选口径都收在这里。

器材链路：在库 → 已领用 → 归还/送修 → 维修中 → 维修完成或送修失败 → 办理退租。
动作与状态的对应关系只维护 TRANSITIONS 一张表，列表、详情、动作接口共用，
排查时对照这一处即可，不用在多个入口之间来回核对。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "equipment"
REQUIRED_FIELDS = ["器材编号", "器材名称", "器材类别"]
OPTIONAL_FIELDS = ["品牌型号", "所属租赁商", "日租金", "领用人员"]
STATUS_ORDER = ["在库", "已领用", "维修中", "已退租"]
TERMINAL_STATUS = STATUS_ORDER[-1]

# 状态机：键为当前状态，值为「动作 → 目标状态」；目标为 None 表示回到送修前状态。
TRANSITIONS: dict[str, dict[str, str | None]] = {
    "在库": {"办理领用": "已领用", "送修登记": "维修中", "办理退租": "已退租"},
    "已领用": {"归还器材": "在库", "送修登记": "维修中"},
    "维修中": {"维修完成": "在库", "送修失败": None},
    "已退租": {},
}
# 必须填写原因才能执行的动作：原因会写进流转记录，事后排查能直接看到。
REASON_REQUIRED = {"送修失败"}
NEGATIVE_ACTIONS = ["送修失败"]


def available_actions(status: Any) -> list[str]:
    """某个状态当前可执行的动作；未纳入流转表的状态返回空列表，不猜。"""
    return list(TRANSITIONS.get(str(status or ""), {}))


def transition_map() -> dict[str, dict[str, str]]:
    """对外展示的流转表：把 None 目标翻译成可读说明。"""
    return {
        status: {action: (target or "送修前状态") for action, target in rules.items()}
        for status, rules in TRANSITIONS.items()
    }


class EquipmentService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("器材编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._present(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._present(entry) if entry is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in REQUIRED_FIELDS + OPTIONAL_FIELDS:
            value = values.get(field)
            if value is not None and str(value).strip():
                entry[field] = value
        entry["status"] = STATUS_ORDER[0]
        entry["器材状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["history"] = []
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str, reason: str = "") -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"拍摄器材 {entry_id} 不存在或已归档"
        known_actions = {name for rules in TRANSITIONS.values() for name in rules}
        if action not in known_actions:
            return None, f"动作「{action}」不属于器材管理可执行范围"
        current = str(entry.get("status") or STATUS_ORDER[0])
        allowed = TRANSITIONS.get(current, {})
        if action not in allowed:
            message = self._reject_message(current, action, allowed)
            self._record(entry, action, current, current, ok=False, reason=message)
            return None, message
        if action in REASON_REQUIRED and not reason:
            return None, f"「{action}」需要填写原因，说明维修方反馈或故障情况，便于事后排查"
        target = allowed[action]
        if target is None:
            # 送修失败：回到送修前状态；历史数据没有记录来源时按在库处理。
            target = str(entry.get("repair_from") or STATUS_ORDER[0])
        if action == "送修登记":
            entry["repair_from"] = current
        if current == "维修中":
            entry.pop("repair_from", None)
        entry["status"] = target
        entry["器材状态"] = target
        entry["pending"] = target != TERMINAL_STATUS
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        self._record(entry, action, current, target, ok=True, reason=reason)
        if action in NEGATIVE_ACTIONS:
            return self._present(entry), f"拍摄器材{action}，已回到「{target}」；原因：{reason}"
        return self._present(entry), f"拍摄器材已{action}，当前状态「{target}」"

    def _reject_message(self, current: str, action: str, allowed: dict[str, Any]) -> str:
        if allowed:
            allowed_text = "、".join(allowed)
        elif current == TERMINAL_STATUS:
            allowed_text = "无（器材已退租，链路结束）"
        else:
            allowed_text = "无（当前状态未纳入流转表，请核对数据）"
        if action == "办理领用" and current == "已领用":
            return f"器材当前「{current}」，不能重复办理领用；可执行：{allowed_text}"
        return f"器材当前「{current}」，不能{action}；可执行：{allowed_text}"

    def _record(
        self,
        entry: dict[str, Any],
        action: str,
        from_status: str,
        to_status: str,
        *,
        ok: bool,
        reason: str = "",
    ) -> None:
        """把每次动作（含被拦下的）追加到器材自己的流转记录里，排查只看这一条数据。"""
        history = entry.setdefault("history", [])
        history.append({
            "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "from_status": from_status,
            "to_status": to_status,
            "ok": ok,
            "reason": reason,
        })

    def _present(self, entry: dict[str, Any]) -> dict[str, Any]:
        """输出副本：附带当前状态可执行的动作，前端不用各自维护一份状态机。"""
        return {**entry, "available_actions": available_actions(entry.get("status"))}

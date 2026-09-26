"""器材管理业务规则：状态流转集中在一张状态机表里，每个状态可走的环节一目了然。

链路总览（动作 → 目标状态）：

    在库   ──办理领用──▶ 已领用 ──归还器材──▶ 在库
    在库   ──送修登记──▶ 维修中 ──维修完成──▶ 在库
    已领用 ──送修登记──▶ 维修中 ──维修失败──▶ 送修前状态（在库/已领用）
    在库   ──办理退租──▶ 已退租（链路终结，不可再操作）

所有非法流转（空记录、重复领用、已退租后再操作等）都在这里被拦下，
返回可读原因且不改写原状态；历史数据没有「送修前状态」字段时按「在库」兜底。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "equipment"
REQUIRED_FIELDS = ["器材编号", "器材名称", "器材类别"]
STATUS_ORDER = ["在库", "已领用", "维修中", "已退租"]
TERMINAL_STATUS = "已退租"
ORIGIN_FIELD = "送修前状态"
LOG_FIELD = "流转记录"

# 状态机：当前状态 → {动作: 目标状态}；目标为 None 表示「回到送修前状态」。
TRANSITIONS: dict[str, dict[str, str | None]] = {
    "在库": {"办理领用": "已领用", "送修登记": "维修中", "办理退租": "已退租"},
    "已领用": {"归还器材": "在库", "送修登记": "维修中"},
    "维修中": {"维修完成": "在库", "维修失败": None},
    "已退租": {},
}
ALL_ACTIONS = [action for rules in TRANSITIONS.values() for action in rules]


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
        return [self._with_actions(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._with_actions(entry) if entry is not None else None

    def lifecycle(self) -> dict[str, Any]:
        """输出整张状态机：每个状态可执行的动作与去向，给页面做链路说明。"""
        return {
            "statuses": STATUS_ORDER,
            "terminal": TERMINAL_STATUS,
            "transitions": {
                status: {action: (target or "送修前状态") for action, target in rules.items()}
                for status, rules in TRANSITIONS.items()
            },
        }

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry[LOG_FIELD] = []
        rows.append(entry)
        return self._with_actions(entry), []

    def run_action(
        self, entry_id: int, action: str, note: str = ""
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"拍摄器材 {entry_id} 不存在或已归档"
        if not action:
            return None, "未指定要执行的动作，请从当前状态的可执行动作中选择"
        status = str(entry.get("status") or "").strip()
        if not status:
            return None, f"拍摄器材 {entry_id} 缺少状态字段，无法判断可执行环节"
        if action not in ALL_ACTIONS:
            return None, f"动作「{action}」不属于器材管理可执行范围"
        rules = TRANSITIONS.get(status)
        if rules is None:
            return None, f"器材当前状态「{status}」不在状态机内，请核对历史数据"
        if action not in rules:
            options = "、".join(rules) if rules else "无（已退租，链路终结）"
            return None, f"器材当前处于「{status}」，不能执行「{action}」；该状态可执行：{options}"

        target = rules[action]
        if action == "送修登记":
            # 记下送修前状态，维修失败时按它回到原状态。
            entry[ORIGIN_FIELD] = status
        if target is None:
            # 维修失败：回到送修前状态；历史数据没有该字段时按在库兜底。
            target = str(entry.pop(ORIGIN_FIELD, "") or STATUS_ORDER[0])
            entry["abnormal"] = True
        elif action == "维修完成":
            entry.pop(ORIGIN_FIELD, None)
            entry["abnormal"] = False

        entry["status"] = target
        entry["pending"] = target != TERMINAL_STATUS
        log = entry.setdefault(LOG_FIELD, [])
        record = {"环节": action, "从": status, "到": target}
        if note:
            record["说明"] = note
        log.append(record)

        message = f"拍摄器材已{action}：{status} → {target}"
        if note:
            message = f"{message}（{note}）"
        return self._with_actions(entry), message

    def _with_actions(self, entry: dict[str, Any]) -> dict[str, Any]:
        """附上一份当前状态的可执行动作，不改写存储里的原始记录。"""
        view = dict(entry)
        view["available_actions"] = list(TRANSITIONS.get(str(entry.get("status", "")), {}))
        return view

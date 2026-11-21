"""人工审核结论日志。

结论只能由审核人员作出并以追加方式记录；系统不生成、不修改结论。
同一素材出现新结论时，以 reviewed_at 最新的一条为当前有效结论，
历史结论全部保留——已执行措施"当时的依据"由此可追溯。
"""
from __future__ import annotations

from datetime import date

from .model import Decision

KNOWN_REVIEW_STATES = frozenset({"restrict", "needs_review", "cleared"})


def _sort_key(decision: Decision):
    # 未提供时间的记录视为最早，保持确定性排序
    return (decision.reviewed_at or date.min, decision.decision_ref)


class DecisionLog:
    def __init__(self, decisions) -> None:
        self._decisions = tuple(decisions)
        self._by_ref = {d.decision_ref: d for d in self._decisions}
        by_asset: dict[str, list[Decision]] = {}
        for decision in self._decisions:
            by_asset.setdefault(decision.asset_ref, []).append(decision)
        self._by_asset = {
            asset_ref: tuple(sorted(items, key=_sort_key))
            for asset_ref, items in by_asset.items()
        }

    def get(self, decision_ref: str | None) -> Decision | None:
        if decision_ref is None:
            return None
        return self._by_ref.get(decision_ref)

    def history(self, asset_ref: str) -> tuple[Decision, ...]:
        """某素材的全部结论，按时间升序。"""
        return self._by_asset.get(asset_ref, ())

    def effective(self, asset_ref: str, at: date | None = None) -> Decision | None:
        """当前有效结论；给定 at 时返回该时点之前（含）的最新结论。"""
        history = self._by_asset.get(asset_ref, ())
        if at is None:
            return history[-1] if history else None
        chosen = None
        for decision in history:
            if decision.reviewed_at is None or decision.reviewed_at <= at:
                chosen = decision
            else:
                break
        return chosen

    def effective_map(self) -> dict[str, Decision]:
        return {
            asset_ref: history[-1]
            for asset_ref, history in self._by_asset.items()
            if history
        }

    def is_superseded(self, decision: Decision) -> bool:
        """该结论是否已被同一素材的后续结论取代。"""
        current = self.effective(decision.asset_ref)
        return current is not None and current.decision_ref != decision.decision_ref

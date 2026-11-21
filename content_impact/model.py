"""数据模型与装载。

将 data/ 下的合成资料读入内存结构。按照仓库 README 的约定，
空字段表示"未提供"，装载时转换为 None，不臆造取值；
无法解析或引用不完整的记录记入 issues，不中断分析链条。
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path


def _text(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = raw.strip()
    return text if text else None


def _required(row: dict, key: str) -> str:
    value = _text(row.get(key))
    if value is None:
        raise ValueError(f"缺少必填字段 {key}")
    return value


def _date(raw: str | None) -> date | None:
    text = _text(raw)
    return date.fromisoformat(text) if text else None


def _int(raw: str | None) -> int | None:
    text = _text(raw)
    return int(text) if text else None


def _decimal(raw: str | None) -> Decimal | None:
    text = _text(raw)
    return Decimal(text) if text else None


@dataclass(frozen=True)
class Asset:
    """内容素材的一个版本。"""

    asset_ref: str
    origin_ref: str | None
    version: int | None
    content_hash: str | None
    edited_at: date | None
    edit_kind: str | None


@dataclass(frozen=True)
class Placement:
    """一次投放：某账号在某直播场次使用某素材。active_to 为空表示仍在传播。"""

    placement_ref: str
    asset_ref: str
    account_ref: str | None
    session_ref: str | None
    active_from: date | None
    active_to: date | None

    @property
    def still_active(self) -> bool:
        return self.active_to is None


@dataclass(frozen=True)
class Exposure:
    """一条曝光记录。count 为空表示未提供，不按零处理。"""

    exposure_ref: str
    placement_ref: str
    seen_at: date | None
    audience_ref: str | None
    count: int | None


@dataclass(frozen=True)
class ActionRecord:
    """一条处置措施记录（限制传播/撤下等）及其依据的审核结论。"""

    action_ref: str
    placement_ref: str
    action_state: str | None
    requested_at: date | None
    completed_at: date | None
    decision_ref: str | None


@dataclass(frozen=True)
class Decision:
    """人工审核结论。结论只能由审核人员作出；系统不生成、不修改结论。"""

    decision_ref: str
    asset_ref: str
    review_state: str | None
    reviewed_at: date | None
    reviewer_ref: str | None
    reason: str | None


@dataclass(frozen=True)
class Order:
    """一笔订单。placement_ref 为空表示只能归属到场次，无法归属到具体投放。"""

    order_ref: str
    placement_ref: str | None
    session_ref: str | None
    ordered_at: date | None
    amount: Decimal | None


class Dataset:
    """全部资料的内存视图，附带引用完整性检查结果。"""

    REQUIRED_FILES = ("assets.csv", "placements.csv", "exposures.csv", "actions.csv", "decisions.csv")
    ORDERS_FILE = "orders.csv"

    def __init__(
        self,
        *,
        assets: tuple[Asset, ...],
        placements: tuple[Placement, ...],
        exposures: tuple[Exposure, ...],
        actions: tuple[ActionRecord, ...],
        decisions: tuple[Decision, ...],
        orders: tuple[Order, ...] = (),
        orders_provided: bool = False,
        issues: tuple[str, ...] = (),
    ) -> None:
        self.assets = assets
        self.placements = placements
        self.exposures = exposures
        self.actions = actions
        self.decisions = decisions
        self.orders = orders
        self.orders_provided = orders_provided
        self.issues = issues

        self.assets_by_ref = {a.asset_ref: a for a in assets}
        self.placements_by_ref = {p.placement_ref: p for p in placements}
        self.decisions_by_ref = {d.decision_ref: d for d in decisions}

    @classmethod
    def load(cls, data_dir: str | Path) -> "Dataset":
        data_dir = Path(data_dir)
        issues: list[str] = []

        def read(name: str, builder) -> tuple:
            path = data_dir / name
            rows = []
            with path.open(encoding="utf-8", newline="") as stream:
                for line_no, row in enumerate(csv.DictReader(stream), start=2):
                    try:
                        rows.append(builder(row))
                    except Exception as exc:  # 单行损坏不中断整体分析
                        issues.append(f"{name}:{line_no} 记录无法解析（{exc}），已跳过")
            return tuple(rows)

        assets = read(
            "assets.csv",
            lambda r: Asset(
                asset_ref=_required(r, "asset_ref"),
                origin_ref=_text(r.get("origin_ref")),
                version=_int(r.get("version")),
                content_hash=_text(r.get("content_hash")),
                edited_at=_date(r.get("edited_at")),
                edit_kind=_text(r.get("edit_kind")),
            ),
        )
        placements = read(
            "placements.csv",
            lambda r: Placement(
                placement_ref=_required(r, "placement_ref"),
                asset_ref=_required(r, "asset_ref"),
                account_ref=_text(r.get("account_ref")),
                session_ref=_text(r.get("session_ref")),
                active_from=_date(r.get("active_from")),
                active_to=_date(r.get("active_to")),
            ),
        )
        exposures = read(
            "exposures.csv",
            lambda r: Exposure(
                exposure_ref=_required(r, "exposure_ref"),
                placement_ref=_required(r, "placement_ref"),
                seen_at=_date(r.get("seen_at")),
                audience_ref=_text(r.get("audience_ref")),
                count=_int(r.get("count")),
            ),
        )
        actions = read(
            "actions.csv",
            lambda r: ActionRecord(
                action_ref=_required(r, "action_ref"),
                placement_ref=_required(r, "placement_ref"),
                action_state=_text(r.get("action_state")),
                requested_at=_date(r.get("requested_at")),
                completed_at=_date(r.get("completed_at")),
                decision_ref=_text(r.get("decision_ref")),
            ),
        )
        decisions = read(
            "decisions.csv",
            lambda r: Decision(
                decision_ref=_required(r, "decision_ref"),
                asset_ref=_required(r, "asset_ref"),
                review_state=_text(r.get("review_state")),
                reviewed_at=_date(r.get("reviewed_at")),
                reviewer_ref=_text(r.get("reviewer_ref")),
                reason=_text(r.get("reason")),
            ),
        )

        orders_provided = (data_dir / cls.ORDERS_FILE).exists()
        orders = (
            read(
                cls.ORDERS_FILE,
                lambda r: Order(
                    order_ref=_required(r, "order_ref"),
                    placement_ref=_text(r.get("placement_ref")),
                    session_ref=_text(r.get("session_ref")),
                    ordered_at=_date(r.get("ordered_at")),
                    amount=_decimal(r.get("amount")),
                ),
            )
            if orders_provided
            else ()
        )

        dataset = cls(
            assets=assets,
            placements=placements,
            exposures=exposures,
            actions=actions,
            decisions=decisions,
            orders=orders,
            orders_provided=orders_provided,
            issues=tuple(issues),
        )
        dataset.issues = tuple(issues) + dataset._check_references()
        return dataset

    def _check_references(self) -> tuple[str, ...]:
        """引用完整性检查：结果记入 issues，供报告披露，不中断分析。"""
        problems: list[str] = []
        for p in self.placements:
            if p.asset_ref not in self.assets_by_ref:
                problems.append(f"投放 {p.placement_ref} 引用了未知素材 {p.asset_ref}")
        for x in self.exposures:
            if x.placement_ref not in self.placements_by_ref:
                problems.append(f"曝光 {x.exposure_ref} 引用了未知投放 {x.placement_ref}")
        for a in self.actions:
            if a.placement_ref not in self.placements_by_ref:
                problems.append(f"措施 {a.action_ref} 引用了未知投放 {a.placement_ref}")
            if a.decision_ref and a.decision_ref not in self.decisions_by_ref:
                problems.append(f"措施 {a.action_ref} 引用了未知结论 {a.decision_ref}")
        for d in self.decisions:
            if d.asset_ref not in self.assets_by_ref:
                problems.append(f"结论 {d.decision_ref} 引用了未知素材 {d.asset_ref}")
        session_refs = {p.session_ref for p in self.placements if p.session_ref}
        for o in self.orders:
            if o.placement_ref and o.placement_ref not in self.placements_by_ref:
                problems.append(f"订单 {o.order_ref} 引用了未知投放 {o.placement_ref}")
            if o.session_ref and o.session_ref not in session_refs:
                problems.append(f"订单 {o.order_ref} 引用了未知场次 {o.session_ref}")
        return tuple(problems)

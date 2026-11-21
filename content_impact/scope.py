"""传播范围与措施覆盖分析。

核心语义：

处置需求（Requirement）
  REQUIRED    —— 人工限制结论直接要求的处置
  RECOMMENDED —— 由同源同承诺谱系推导出的建议处置，待人工确认；
                 这是系统给出的"建议"，不是自动违规认定
  NONE        —— 当前无需处置

覆盖状态（Coverage，仅对需要处置的投放有意义）
  COVERED     —— 已有执行完成的措施
  OUTSTANDING —— 已请求但尚未执行
  GAP         —— 未请求任何措施（覆盖缺口）

审核结论改变后，用新的结论日志重新调用 analyze() 即可重算待处理范围
与影响统计；已执行措施作为历史记录保留，其"当时的依据"通过
MeasureRecord.basis / basis_superseded 呈现。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from .classification import ClaimSegment, ContentGraph, RelationKind
from .decisions import KNOWN_REVIEW_STATES, DecisionLog
from .model import (
    ActionRecord,
    Asset,
    Dataset,
    Decision,
    Exposure,
    Order,
    Placement,
)


class Requirement(enum.Enum):
    REQUIRED = "required"
    RECOMMENDED = "recommended"
    NONE = "none"


class Coverage(enum.Enum):
    COVERED = "covered"
    OUTSTANDING = "outstanding"
    GAP = "gap"
    NOT_REQUIRED = "not_required"


_ACTION_RANK = {"completed": 3, "pending": 2, "not_requested": 1}


def _latest_action(actions) -> ActionRecord | None:
    """同一投放可能有多条措施记录，取"走得最远"的一条作为当前状态。"""
    best = None
    for action in actions:
        key = (
            _ACTION_RANK.get(action.action_state or "", 0),
            action.completed_at or action.requested_at or date.min,
            action.action_ref,
        )
        if best is None or key > best[0]:
            best = (key, action)
    return best[1] if best else None


def _sum_or_none(values):
    known = [v for v in values if v is not None]
    return sum(known) if known else None


@dataclass(frozen=True)
class PlacementAssessment:
    """一个投放的处置需求与覆盖现状。"""

    placement: Placement
    asset: Asset
    requirement: Requirement
    basis: Decision | None               # 要求/建议所依据的人工结论
    basis_relation: RelationKind | None  # 建议情形下与依据素材的内容关系
    action: ActionRecord | None          # 当前走得最远的措施记录
    coverage: Coverage
    still_active: bool
    exposures: tuple[Exposure, ...]
    exposure_total: int | None
    orders: tuple[Order, ...]
    order_total: Decimal | None


@dataclass(frozen=True)
class MeasureRecord:
    """一条措施记录及其依据、触达的传播资料（曝光与订单）。"""

    action: ActionRecord
    placement: Placement | None
    asset: Asset | None
    asset_state: str | None       # 素材当前有效结论的 review_state
    basis: Decision | None        # 措施记录所依据的审核结论（当时的依据）
    basis_superseded: bool        # 依据是否已被后续结论取代
    exposures: tuple[Exposure, ...]
    exposure_total: int | None
    orders: tuple[Order, ...]
    order_total: Decimal | None


@dataclass(frozen=True)
class FamilyReport:
    """一个承诺谱系的处置范围：依据、成员、实质改写、仅主题相近素材与投放覆盖。"""

    origin_ref: str
    segment: ClaimSegment
    decided: tuple[tuple[Asset, Decision], ...]            # 谱系内的人工限制结论
    rewrites: tuple[tuple[Asset, Decision | None], ...]    # 实质改写及各自当前结论
    topic_adjacent: tuple[tuple[Asset, Decision | None], ...]
    placements: tuple[PlacementAssessment, ...]


@dataclass(frozen=True)
class ReviewItem:
    """复核队列中的一项：仅用于安排人工复核，不构成违规认定。"""

    asset: Asset
    decision: Decision | None
    tag: str  # "needs_review" | "rewrite_of_restricted"
    exposure_total: int | None
    note: str


@dataclass(frozen=True)
class ClearedReport:
    """内容被复核为普通介绍后的处理视图：撤回未执行建议，解释已执行措施。"""

    asset: Asset
    decision: Decision
    withdrawals: tuple[MeasureRecord, ...]  # 建议撤回的未执行措施
    completed: tuple[MeasureRecord, ...]    # 已执行措施及其触达（保留存档）


@dataclass(frozen=True)
class AnalysisResult:
    families: tuple[FamilyReport, ...]
    assessments: tuple[PlacementAssessment, ...]      # 全部投放的评估
    gaps: tuple[PlacementAssessment, ...]             # 覆盖缺口（含待执行）
    withdrawals: tuple[MeasureRecord, ...]            # 建议撤回的未执行措施
    unsupported_pending: tuple[MeasureRecord, ...]    # 无限制依据的未执行请求
    review_queue: tuple[ReviewItem, ...]
    cleared_reports: tuple[ClearedReport, ...]
    audit: tuple[MeasureRecord, ...]                  # 全部已执行措施存档
    unattributed_orders: tuple[Order, ...]            # 无法归属到具体投放的订单
    issues: tuple[str, ...]
    summary: dict


def _coverage_of(requirement: Requirement, action: ActionRecord | None) -> Coverage:
    if requirement is Requirement.NONE:
        return Coverage.NOT_REQUIRED
    state = action.action_state if action else None
    if state == "completed":
        return Coverage.COVERED
    if state == "pending":
        return Coverage.OUTSTANDING
    return Coverage.GAP


def _summarize(
    dataset: Dataset,
    families: tuple[FamilyReport, ...],
    review_queue: tuple[ReviewItem, ...],
    withdrawals: tuple[MeasureRecord, ...],
    unsupported_pending: tuple[MeasureRecord, ...],
    audit: tuple[MeasureRecord, ...],
    unattributed_orders: tuple[Order, ...],
) -> dict:
    in_scope = [p for family in families for p in family.placements]
    covered = sum(1 for p in in_scope if p.coverage is Coverage.COVERED)
    outstanding = sum(1 for p in in_scope if p.coverage is Coverage.OUTSTANDING)
    gap = sum(1 for p in in_scope if p.coverage is Coverage.GAP)
    active_gaps = sum(
        1 for p in in_scope if p.still_active and p.coverage in (Coverage.OUTSTANDING, Coverage.GAP)
    )
    sessions: dict[str, list[PlacementAssessment]] = {}
    for p in in_scope:
        sessions.setdefault(p.placement.session_ref or "", []).append(p)
    fully_covered = sum(
        1 for members in sessions.values() if all(p.coverage is Coverage.COVERED for p in members)
    )
    return {
        "restrict_decisions": sum(len(f.decided) for f in families),
        "families": len(families),
        "placements_in_scope": len(in_scope),
        "covered": covered,
        "outstanding": outstanding,
        "gap": gap,
        "active_gaps": active_gaps,
        "exposure_records_in_scope": sum(len(p.exposures) for p in in_scope),
        "exposure_total_in_scope": _sum_or_none(p.exposure_total for p in in_scope),
        "orders_provided": dataset.orders_provided,
        "orders_in_scope": sum(len(p.orders) for p in in_scope),
        "order_amount_in_scope": _sum_or_none(p.order_total for p in in_scope),
        "unattributed_orders": len(unattributed_orders),
        "sessions_in_scope": len(sessions),
        "sessions_fully_covered": fully_covered,
        "review_queue": len(review_queue),
        "pending_withdrawals": len(withdrawals),
        "unsupported_pending": len(unsupported_pending),
        "completed_measures": len(audit),
    }


def analyze(dataset: Dataset, decisions=None) -> AnalysisResult:
    """从内容证据到传播影响范围的完整分析。

    decisions 可传入 DecisionLog 或 Decision 序列（例如追加了新结论的日志），
    缺省使用资料中的结论。结论变化后重新调用即可得到重算结果。
    """
    if isinstance(decisions, DecisionLog):
        log = decisions
    else:
        log = DecisionLog(dataset.decisions if decisions is None else decisions)

    graph = ContentGraph(dataset.assets)
    effective = log.effective_map()
    issues = list(dataset.issues)

    for decision in effective.values():
        if decision.review_state not in KNOWN_REVIEW_STATES:
            issues.append(
                f"结论 {decision.decision_ref} 的状态 {decision.review_state!r} 未识别，按无处置要求处理"
            )

    exposures_by_placement: dict[str, list[Exposure]] = {}
    for exposure in dataset.exposures:
        exposures_by_placement.setdefault(exposure.placement_ref, []).append(exposure)
    orders_by_placement: dict[str, list[Order]] = {}
    unattributed_orders: list[Order] = []
    for order in dataset.orders:
        if order.placement_ref:
            orders_by_placement.setdefault(order.placement_ref, []).append(order)
        else:
            unattributed_orders.append(order)
    actions_by_placement: dict[str, list[ActionRecord]] = {}
    for action in dataset.actions:
        actions_by_placement.setdefault(action.placement_ref, []).append(action)

    # ---- 每个投放的处置需求与覆盖状态 ----
    assessments: list[PlacementAssessment] = []
    for placement in sorted(dataset.placements, key=lambda p: p.placement_ref):
        asset = dataset.assets_by_ref.get(placement.asset_ref)
        if asset is None:
            issues.append(f"投放 {placement.placement_ref} 的素材 {placement.asset_ref} 未知，已跳过")
            continue

        requirement = Requirement.NONE
        basis = None
        relation = None
        own = effective.get(asset.asset_ref)
        if own is not None and own.review_state == "restrict":
            requirement = Requirement.REQUIRED
            basis = own
        else:
            segment = graph.segment_of(asset.asset_ref)
            if segment is not None:
                lineage_restricts = []
                for member in segment.members:
                    if member.asset_ref == asset.asset_ref:
                        continue
                    other = effective.get(member.asset_ref)
                    if other is not None and other.review_state == "restrict":
                        lineage_restricts.append(other)
                if lineage_restricts:
                    requirement = Requirement.RECOMMENDED
                    basis = max(
                        lineage_restricts,
                        key=lambda d: (d.reviewed_at or date.min, d.decision_ref),
                    )
                    relation = graph.classify(basis.asset_ref, asset.asset_ref)

        action = _latest_action(actions_by_placement.get(placement.placement_ref, ()))
        if action is not None and (action.action_state or "") not in _ACTION_RANK:
            issues.append(f"措施 {action.action_ref} 的状态 {action.action_state!r} 未识别，按未覆盖处理")

        exposures = tuple(
            sorted(exposures_by_placement.get(placement.placement_ref, ()), key=lambda e: e.exposure_ref)
        )
        orders = tuple(
            sorted(orders_by_placement.get(placement.placement_ref, ()), key=lambda o: o.order_ref)
        )
        assessments.append(
            PlacementAssessment(
                placement=placement,
                asset=asset,
                requirement=requirement,
                basis=basis,
                basis_relation=relation,
                action=action,
                coverage=_coverage_of(requirement, action),
                still_active=placement.still_active,
                exposures=exposures,
                exposure_total=_sum_or_none(e.count for e in exposures),
                orders=orders,
                order_total=_sum_or_none(o.amount for o in orders),
            )
        )

    assessments_by_asset: dict[str, list[PlacementAssessment]] = {}
    for assessment in assessments:
        assessments_by_asset.setdefault(assessment.asset.asset_ref, []).append(assessment)

    def measure_record(action: ActionRecord) -> MeasureRecord:
        placement = dataset.placements_by_ref.get(action.placement_ref)
        asset = dataset.assets_by_ref.get(placement.asset_ref) if placement else None
        basis_decision = log.get(action.decision_ref)
        exposures = tuple(
            sorted(exposures_by_placement.get(action.placement_ref, ()), key=lambda e: e.exposure_ref)
        )
        orders = tuple(
            sorted(orders_by_placement.get(action.placement_ref, ()), key=lambda o: o.order_ref)
        )
        return MeasureRecord(
            action=action,
            placement=placement,
            asset=asset,
            asset_state=(effective.get(asset.asset_ref).review_state if asset and effective.get(asset.asset_ref) else None),
            basis=basis_decision,
            basis_superseded=bool(basis_decision is not None and log.is_superseded(basis_decision)),
            exposures=exposures,
            exposure_total=_sum_or_none(e.count for e in exposures),
            orders=orders,
            order_total=_sum_or_none(o.amount for o in orders),
        )

    # ---- 内容家族：含有效限制结论的承诺谱系 ----
    families: list[FamilyReport] = []
    for origin in sorted(graph.groups):
        group = graph.groups[origin]
        for segment in group.segments:
            decided = tuple(
                (member, effective[member.asset_ref])
                for member in segment.members
                if effective.get(member.asset_ref) is not None
                and effective[member.asset_ref].review_state == "restrict"
            )
            if not decided:
                continue
            rewrites = tuple(
                (member, effective.get(member.asset_ref))
                for other in group.segments
                if other is not segment
                for member in other.members
            )
            adjacent = tuple(
                (member, effective.get(member.asset_ref)) for member in group.topic_adjacent
            )
            placements = tuple(
                assessment
                for member in segment.members
                for assessment in assessments_by_asset.get(member.asset_ref, ())
            )
            families.append(
                FamilyReport(origin, segment, decided, rewrites, adjacent, placements)
            )

    # ---- 覆盖缺口：需要处置但未覆盖 ----
    gaps = tuple(
        a
        for a in assessments
        if a.requirement is not Requirement.NONE
        and a.coverage in (Coverage.OUTSTANDING, Coverage.GAP)
    )

    # ---- 撤回与无依据请求 ----
    # 内容（或其所在谱系中的素材）被复核为普通介绍后，未执行的建议应当撤回；
    # 其余没有限制依据的未执行请求单独列出，交人工确认。
    def cleared_in_segment(asset_ref: str) -> bool:
        own = effective.get(asset_ref)
        if own is not None and own.review_state == "cleared":
            return True
        segment = graph.segment_of(asset_ref)
        if segment is None:
            return False
        return any(
            (d := effective.get(m.asset_ref)) is not None and d.review_state == "cleared"
            for m in segment.members
        )

    withdrawals: list[MeasureRecord] = []
    unsupported_pending: list[MeasureRecord] = []
    for assessment in assessments:
        if assessment.action is None or assessment.action.action_state != "pending":
            continue
        if assessment.requirement is not Requirement.NONE:
            continue
        if cleared_in_segment(assessment.asset.asset_ref):
            withdrawals.append(measure_record(assessment.action))
        else:
            unsupported_pending.append(measure_record(assessment.action))

    # ---- 复核队列：人工标记待复核 + 已限制谱系的实质改写且尚无结论 ----
    review_items: list[ReviewItem] = []
    for asset in sorted(dataset.assets, key=lambda a: a.asset_ref):
        decision = effective.get(asset.asset_ref)
        segment = graph.segment_of(asset.asset_ref)
        exposure_total = _sum_or_none(
            a.exposure_total for a in assessments_by_asset.get(asset.asset_ref, ())
        )
        if decision is not None and decision.review_state == "needs_review":
            notes = []
            if segment is not None:
                restricted = [
                    m.asset_ref
                    for m in segment.members
                    if m.asset_ref != asset.asset_ref
                    and (d := effective.get(m.asset_ref)) is not None
                    and d.review_state == "restrict"
                ]
                if restricted:
                    notes.append("与已限制素材 " + "、".join(restricted) + " 同源同承诺")
                if segment.created_by_rewrite:
                    notes.append(f"属于 {segment.origin_ref} 的实质改写谱系")
            review_items.append(
                ReviewItem(asset, decision, "needs_review", exposure_total, "；".join(notes))
            )
        elif decision is None and segment is not None and segment.created_by_rewrite:
            group = graph.groups.get(segment.origin_ref)
            restricted_elsewhere = False
            if group is not None:
                for other in group.segments:
                    if other is segment:
                        continue
                    for member in other.members:
                        d = effective.get(member.asset_ref)
                        if d is not None and d.review_state == "restrict":
                            restricted_elsewhere = True
            if restricted_elsewhere:
                review_items.append(
                    ReviewItem(
                        asset,
                        None,
                        "rewrite_of_restricted",
                        exposure_total,
                        "实质改写自含限制结论的谱系，尚无人工结论",
                    )
                )
    review_items.sort(key=lambda item: (-(item.exposure_total or 0), item.asset.asset_ref))

    # ---- 已解除内容：撤回未执行建议，解释已执行措施 ----
    cleared_reports: list[ClearedReport] = []
    for asset in sorted(dataset.assets, key=lambda a: a.asset_ref):
        decision = effective.get(asset.asset_ref)
        if decision is None or decision.review_state != "cleared":
            continue
        segment = graph.segment_of(asset.asset_ref)
        member_refs = (
            {m.asset_ref for m in segment.members} if segment is not None else {asset.asset_ref}
        )
        related = [a for a in assessments if a.asset.asset_ref in member_refs]
        cleared_withdrawals = tuple(
            measure_record(a.action)
            for a in related
            if a.requirement is Requirement.NONE
            and a.action is not None
            and a.action.action_state == "pending"
        )
        completed = tuple(
            measure_record(a.action)
            for a in related
            if a.action is not None and a.action.action_state == "completed"
        )
        if cleared_withdrawals or completed:
            cleared_reports.append(ClearedReport(asset, decision, cleared_withdrawals, completed))

    # ---- 已执行措施存档：历史不随结论变化而消失 ----
    audit = tuple(
        measure_record(action)
        for action in sorted(dataset.actions, key=lambda a: a.action_ref)
        if action.action_state == "completed"
    )

    unattributed = tuple(sorted(unattributed_orders, key=lambda o: o.order_ref))
    families_t = tuple(families)
    review_queue = tuple(review_items)
    withdrawals_t = tuple(withdrawals)
    unsupported_t = tuple(unsupported_pending)
    summary = _summarize(
        dataset, families_t, review_queue, withdrawals_t, unsupported_t, audit, unattributed
    )
    return AnalysisResult(
        families=families_t,
        assessments=tuple(assessments),
        gaps=gaps,
        withdrawals=withdrawals_t,
        unsupported_pending=unsupported_t,
        review_queue=review_queue,
        cleared_reports=tuple(cleared_reports),
        audit=audit,
        unattributed_orders=unattributed,
        issues=tuple(issues),
        summary=summary,
    )


def filter_by_asset(result: AnalysisResult, dataset: Dataset, asset_ref: str) -> AnalysisResult:
    """按素材过滤分析结果，用于单素材视角查看。"""
    families = tuple(
        f
        for f in result.families
        if asset_ref in {m.asset_ref for m in f.segment.members}
        or asset_ref in {a.asset_ref for a, _ in f.rewrites}
        or asset_ref in {a.asset_ref for a, _ in f.topic_adjacent}
    )
    gaps = tuple(a for a in result.gaps if a.asset.asset_ref == asset_ref)
    withdrawals = tuple(
        m for m in result.withdrawals if m.asset is not None and m.asset.asset_ref == asset_ref
    )
    unsupported = tuple(
        m for m in result.unsupported_pending if m.asset is not None and m.asset.asset_ref == asset_ref
    )
    review_queue = tuple(i for i in result.review_queue if i.asset.asset_ref == asset_ref)
    cleared_reports = tuple(
        c
        for c in result.cleared_reports
        if c.asset.asset_ref == asset_ref
        or any(m.asset is not None and m.asset.asset_ref == asset_ref for m in c.withdrawals + c.completed)
    )
    audit = tuple(
        m for m in result.audit if m.asset is not None and m.asset.asset_ref == asset_ref
    )
    summary = _summarize(
        dataset,
        families,
        review_queue,
        withdrawals,
        unsupported,
        audit,
        result.unattributed_orders,
    )
    return replace(
        result,
        families=families,
        gaps=gaps,
        withdrawals=withdrawals,
        unsupported_pending=unsupported,
        review_queue=review_queue,
        cleared_reports=cleared_reports,
        audit=audit,
        summary=summary,
    )

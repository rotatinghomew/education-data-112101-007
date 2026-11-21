"""分析报告呈现：面向运营与复核团队的中文文本报告，以及可序列化的字典。"""
from __future__ import annotations

import dataclasses
import enum
from datetime import date
from decimal import Decimal

from .classification import RelationKind
from .scope import (
    AnalysisResult,
    Coverage,
    FamilyReport,
    MeasureRecord,
    PlacementAssessment,
    Requirement,
)

REVIEW_STATE_LABELS = {
    "restrict": "限制传播",
    "needs_review": "待复核",
    "cleared": "普通介绍",
}
ACTION_STATE_LABELS = {
    "completed": "已执行",
    "pending": "已请求待执行",
    "not_requested": "未请求",
}
REQUIREMENT_LABELS = {
    Requirement.REQUIRED: "要求处置（人工限制结论）",
    Requirement.RECOMMENDED: "建议处置（同源推导·待人工确认）",
    Requirement.NONE: "无需处置",
}
COVERAGE_LABELS = {
    Coverage.COVERED: "已覆盖",
    Coverage.OUTSTANDING: "待执行",
    Coverage.GAP: "未覆盖缺口",
    Coverage.NOT_REQUIRED: "—",
}
RELATION_LABELS = {
    RelationKind.IDENTICAL_REPOST: "同源转载（内容一致）",
    RelationKind.SAME_CLAIM_VARIANT: "同源变体（关键承诺未变）",
    RelationKind.SUBSTANTIVE_REWRITE: "实质改写（关键承诺已改）",
    RelationKind.TOPIC_SIMILAR_ONLY: "仅主题相近",
    RelationKind.UNRELATED: "无关联",
}


def _state(review_state: str | None) -> str:
    return REVIEW_STATE_LABELS.get(review_state or "", review_state or "无结论")


def _num(value) -> str:
    return "无资料" if value is None else str(value)


def _money(value: Decimal | None, provided: bool = True) -> str:
    if not provided:
        return "无订单资料"
    return "未提供" if value is None else str(value)


def _day(value: date | None) -> str:
    return value.isoformat() if value else "时间未提供"


def _placement_lines(p: PlacementAssessment, orders_provided: bool) -> list[str]:
    placement = p.placement
    head = (
        f"      {placement.placement_ref}｜素材 {p.asset.asset_ref}"
        f"｜账号 {placement.account_ref or '未提供'}｜场次 {placement.session_ref or '未提供'}"
    )
    requirement = REQUIREMENT_LABELS[p.requirement]
    if p.requirement is Requirement.RECOMMENDED and p.basis is not None:
        requirement += (
            f"（依据 {p.basis.decision_ref}→{p.basis.asset_ref}，"
            f"关系：{RELATION_LABELS.get(p.basis_relation, '未知')}）"
        )
    elif p.requirement is Requirement.REQUIRED and p.basis is not None:
        requirement += f"（依据 {p.basis.decision_ref}）"

    if p.action is None:
        action_text = "无任何措施记录"
    elif p.action.action_state == "not_requested":
        action_text = f"措施 {p.action.action_ref} 未请求任何处置"
    else:
        action = p.action
        action_text = (
            f"措施 {action.action_ref} {ACTION_STATE_LABELS.get(action.action_state or '', action.action_state or '状态未知')}"
            f"（请求 {_day(action.requested_at)}／完成 {_day(action.completed_at)}"
            f"，依据 {action.decision_ref or '未提供'}）"
        )
    status = "仍在传播" if p.still_active else f"已于 {_day(placement.active_to)} 结束"
    reach = (
        f"曝光 {len(p.exposures)} 条/{_num(p.exposure_total)}"
        f"｜订单 {len(p.orders)} 笔/{_money(p.order_total, orders_provided)}"
    )
    coverage = COVERAGE_LABELS[p.coverage] if p.requirement is not Requirement.NONE else ""
    second = f"        {requirement}｜{action_text}｜{status}"
    if coverage:
        second += f"｜{coverage}"
    return [head, second, f"        {reach}"]


def _family_lines(family: FamilyReport, orders_provided: bool) -> list[str]:
    lines = [f"  家族 {family.origin_ref} · 承诺谱系 #{family.segment.index + 1}"]
    for asset, decision in family.decided:
        lines.append(
            f"    限制依据：{decision.decision_ref}（{_state(decision.review_state)}，"
            f"{_day(decision.reviewed_at)}，审核人 {decision.reviewer_ref or '未提供'}，"
            f"原因 {decision.reason or '未提供'}）→ 素材 {asset.asset_ref}"
        )
    members = "、".join(f"{m.asset_ref}（{m.edit_kind or '未标注'}）" for m in family.segment.members)
    lines.append(f"    同源同承诺素材：{members}")
    if family.rewrites:
        lines.append(
            "    实质改写（不自动并入，需单独复核）："
            + "、".join(f"{a.asset_ref}（当前结论：{_state(d.review_state if d else None)}）" for a, d in family.rewrites)
        )
    if family.topic_adjacent:
        lines.append(
            "    仅主题相近（不视为同一内容，不计入范围）："
            + "、".join(f"{a.asset_ref}（当前结论：{_state(d.review_state if d else None)}）" for a, d in family.topic_adjacent)
        )
    lines.append("    投放与措施覆盖：")
    for p in family.placements:
        lines.extend(_placement_lines(p, orders_provided))
    covered = sum(1 for p in family.placements if p.coverage is Coverage.COVERED)
    outstanding = sum(1 for p in family.placements if p.coverage is Coverage.OUTSTANDING)
    gap = sum(1 for p in family.placements if p.coverage is Coverage.GAP)
    exposure_total = sum(p.exposure_total or 0 for p in family.placements)
    order_count = sum(len(p.orders) for p in family.placements)
    order_amount = sum((p.order_total for p in family.placements if p.order_total is not None), Decimal(0))
    lines.append(
        f"    小计：投放 {len(family.placements)}（已覆盖 {covered}／待执行 {outstanding}／缺口 {gap}）"
        f"｜曝光累计 {exposure_total}｜订单 {order_count} 笔/{_money(order_amount, orders_provided)}"
    )
    return lines


def _measure_line(m: MeasureRecord, orders_provided: bool) -> str:
    placement = m.placement
    where = (
        f"{placement.placement_ref}（账号 {placement.account_ref or '未提供'}，场次 {placement.session_ref or '未提供'}）"
        if placement
        else "投放未知"
    )
    if m.basis is not None:
        basis = f"依据 {m.basis.decision_ref}（{_state(m.basis.review_state)}，{_day(m.basis.reviewed_at)}）"
        if m.basis_superseded:
            basis += f"［依据已被后续结论取代，现结论：{_state(m.asset_state)}］"
    else:
        basis = "依据未提供"
    reach = (
        f"触达曝光 {len(m.exposures)} 条/{_num(m.exposure_total)}"
        f"（{'、'.join(e.exposure_ref for e in m.exposures) or '无'}）"
        f"｜订单 {len(m.orders)} 笔/{_money(m.order_total, orders_provided)}"
        f"（{'、'.join(o.order_ref for o in m.orders) or '无'}）"
    )
    return f"{m.action.action_ref}｜{where}｜{basis}｜{reach}"


def render_text(result: AnalysisResult) -> str:
    s = result.summary
    orders_provided = bool(s.get("orders_provided"))
    lines: list[str] = []
    lines.append("内容传播影响分析报告")
    lines.append("=" * 48)
    lines.append("说明：本报告只依据人工审核结论圈定处置范围；内容相似度仅用于")
    lines.append("关联同源素材与提示复核对象，不构成违规认定。")
    lines.append("")

    lines.append("一、总览")
    lines.append(f"  有效限制结论 {s['restrict_decisions']} 项，涉及内容家族 {s['families']} 个")
    lines.append(
        f"  处置范围内投放 {s['placements_in_scope']} 个：已覆盖 {s['covered']}"
        f" · 已请求待执行 {s['outstanding']} · 未覆盖缺口 {s['gap']}"
        f"（其中仍在传播 {s['active_gaps']}）"
    )
    lines.append(
        f"  范围内曝光 {s['exposure_records_in_scope']} 条/{_num(s['exposure_total_in_scope'])}"
        f"｜订单 {s['orders_in_scope']} 笔/{_money(s['order_amount_in_scope'], orders_provided)}"
        + ("" if orders_provided else "（未提供订单资料）")
    )
    if s["unattributed_orders"]:
        lines.append(f"  另有 {s['unattributed_orders']} 笔订单无法归属到具体投放，未计入范围统计")
    lines.append(
        f"  涉及场次 {s['sessions_in_scope']} 个，措施完全覆盖 {s['sessions_fully_covered']} 个"
    )
    lines.append(
        f"  待人工复核 {s['review_queue']} 项 · 建议撤回的未执行措施 {s['pending_withdrawals']} 项"
        f" · 无限制依据的未执行请求 {s['unsupported_pending']} 项"
    )
    lines.append("")

    lines.append("二、内容家族明细（按同源承诺谱系圈定范围）")
    if not result.families:
        lines.append("  （当前没有有效的限制结论）")
    for family in result.families:
        lines.extend(_family_lines(family, orders_provided))
    lines.append("")

    lines.append("三、覆盖缺口（仍在传播的排在前面）")
    if not result.gaps:
        lines.append("  （无）")
    for p in sorted(result.gaps, key=lambda a: (not a.still_active, a.placement.placement_ref)):
        placement = p.placement
        action = p.action
        if action is None or action.action_state == "not_requested":
            measure = "未请求任何措施"
        else:
            measure = f"措施 {action.action_ref} 已请求待执行（{_day(action.requested_at)} 请求）"
        status = "仍在传播" if p.still_active else f"已于 {_day(placement.active_to)} 结束"
        lines.append(
            f"  {placement.placement_ref}｜素材 {p.asset.asset_ref}｜账号 {placement.account_ref or '未提供'}"
            f"｜场次 {placement.session_ref or '未提供'}｜{REQUIREMENT_LABELS[p.requirement].split('（')[0]}"
            f"｜{measure}｜{status}｜曝光 {_num(p.exposure_total)}"
            f"｜订单 {len(p.orders)} 笔/{_money(p.order_total, orders_provided)}"
        )
    lines.append("")

    lines.append("四、复核队列（按曝光量降序，仅用于安排人工复核）")
    if not result.review_queue:
        lines.append("  （无）")
    for item in result.review_queue:
        if item.decision is not None:
            state = f"{_state(item.decision.review_state)}（{item.decision.decision_ref}，{_day(item.decision.reviewed_at)}）"
        else:
            state = "尚无人工结论"
        note = f"｜{item.note}" if item.note else ""
        lines.append(
            f"  {item.asset.asset_ref}｜{state}｜曝光 {_num(item.exposure_total)}{note}"
        )
    lines.append("")

    lines.append("五、无限制依据的未执行请求（请人工确认是否继续）")
    if not result.unsupported_pending:
        lines.append("  （无）")
    for m in result.unsupported_pending:
        lines.append(f"  {_measure_line(m, orders_provided)}")
    lines.append("")

    lines.append("六、已解除内容的处理（撤回未执行建议，已执行措施存档可解释）")
    if not result.cleared_reports:
        lines.append("  （无）")
    for report in result.cleared_reports:
        decision = report.decision
        lines.append(
            f"  素材 {report.asset.asset_ref} 经 {decision.decision_ref} 复核为"
            f"{_state(decision.review_state)}（{_day(decision.reviewed_at)}，"
            f"审核人 {decision.reviewer_ref or '未提供'}）"
        )
        if report.withdrawals:
            lines.append("    建议撤回的未执行措施：")
            for m in report.withdrawals:
                lines.append(f"      {_measure_line(m, orders_provided)}")
        if report.completed:
            lines.append("    已执行措施及其触达（措施不撤销，存档备查）：")
            for m in report.completed:
                lines.append(f"      {_measure_line(m, orders_provided)}")
    lines.append("")

    lines.append("七、已执行措施存档（历史不随结论变化而消失）")
    if not result.audit:
        lines.append("  （无）")
    for m in result.audit:
        lines.append(f"  {_measure_line(m, orders_provided)}")
    lines.append("")

    if result.issues:
        lines.append("八、数据问题（已跳过或需核对的记录）")
        for issue in result.issues:
            lines.append(f"  - {issue}")
    return "\n".join(lines)


def to_dict(result: AnalysisResult) -> dict:
    """转换为可 JSON 序列化的字典（枚举、日期、金额转为字符串）。"""
    return dataclasses.asdict(result)


def json_default(obj):
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, (date, Decimal)):
        return str(obj)
    return str(obj)

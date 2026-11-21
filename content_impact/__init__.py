"""内容传播影响范围分析。

从内容证据（素材版本）出发，经同源承诺谱系关联投放、账号、直播场次、
曝光记录与订单，圈定人工审核结论的传播影响范围并检查措施覆盖。
"""
from .classification import (
    ClaimSegment,
    ContentGraph,
    OriginGroup,
    RelationKind,
    group_origins,
)
from .decisions import DecisionLog
from .model import (
    ActionRecord,
    Asset,
    Dataset,
    Decision,
    Exposure,
    Order,
    Placement,
)
from .scope import (
    AnalysisResult,
    ClearedReport,
    Coverage,
    FamilyReport,
    MeasureRecord,
    PlacementAssessment,
    Requirement,
    ReviewItem,
    analyze,
    filter_by_asset,
)

__all__ = [
    "ActionRecord",
    "AnalysisResult",
    "Asset",
    "ClaimSegment",
    "ClearedReport",
    "ContentGraph",
    "Coverage",
    "Dataset",
    "Decision",
    "DecisionLog",
    "Exposure",
    "FamilyReport",
    "MeasureRecord",
    "Order",
    "OriginGroup",
    "Placement",
    "PlacementAssessment",
    "RelationKind",
    "Requirement",
    "ReviewItem",
    "analyze",
    "filter_by_asset",
    "group_origins",
]

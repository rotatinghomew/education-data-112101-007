"""内容版本关系分类。

区分四类关系：同源转载（内容一致）、同源变体（仅文案级改动，关键承诺未变）、
实质改写（关键承诺被改动）、仅主题相近（不视为同一内容）。

分类只描述内容之间的关系，用于圈定传播范围和提示复核对象；
它不构成违规认定——违规结论只能来自人工审核决定。
单纯"主题相近"的素材不进入任何承诺谱系，避免把常见表达误当成同一内容。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date

from .model import Asset

# edit_kind 的两种写法在资料中都表示"仅主题相近"
TOPIC_SIMILAR_KINDS = frozenset({"similar_topic", "topic_similar"})
CLAIM_CHANGE_KINDS = frozenset({"claim_changed"})


class RelationKind(enum.Enum):
    IDENTICAL_REPOST = "identical_repost"        # 同源转载：内容一致
    SAME_CLAIM_VARIANT = "same_claim_variant"    # 同源变体：关键承诺未变
    SUBSTANTIVE_REWRITE = "substantive_rewrite"  # 实质改写：关键承诺已改
    TOPIC_SIMILAR_ONLY = "topic_similar_only"    # 仅主题相近：不视为同一内容
    UNRELATED = "unrelated"                      # 无关联


@dataclass(frozen=True)
class ClaimSegment:
    """同一来源下、关键承诺一致的一段版本序列（承诺谱系）。

    created_by_rewrite 为 True 表示该段由一次实质改写从同来源的前一段派生而来，
    与前一段不再共享关键承诺，处置范围不自动延伸。
    """

    origin_ref: str
    index: int
    members: tuple[Asset, ...]
    created_by_rewrite: bool


@dataclass(frozen=True)
class OriginGroup:
    origin_ref: str
    segments: tuple[ClaimSegment, ...]
    topic_adjacent: tuple[Asset, ...]  # 仅主题相近，不进入任何承诺谱系


def _sort_key(asset: Asset):
    return (
        asset.edited_at or date.min,
        asset.version if asset.version is not None else -1,
        asset.asset_ref,
    )


def group_origins(assets) -> dict[str, OriginGroup]:
    """按来源把素材切分为承诺谱系段，并隔离仅主题相近的素材。

    切分规则：实质改写（claim_changed）开启新的一段；文案级改动
    （caption_changed 等）并入当前段；仅主题相近的素材不进入任何段。
    """
    by_origin: dict[str, list[Asset]] = {}
    for asset in assets:
        by_origin.setdefault(asset.origin_ref or "", []).append(asset)

    groups: dict[str, OriginGroup] = {}
    for origin, members in by_origin.items():
        segments: list[list[Asset]] = []
        adjacent: list[Asset] = []
        for asset in sorted(members, key=_sort_key):
            kind = (asset.edit_kind or "").strip()
            if kind in TOPIC_SIMILAR_KINDS:
                adjacent.append(asset)
            elif kind in CLAIM_CHANGE_KINDS or not segments:
                segments.append([asset])
            else:
                segments[-1].append(asset)
        groups[origin] = OriginGroup(
            origin_ref=origin,
            segments=tuple(
                ClaimSegment(origin, index, tuple(members), created_by_rewrite=index > 0)
                for index, members in enumerate(segments)
            ),
            topic_adjacent=tuple(adjacent),
        )
    return groups


class ContentGraph:
    """内容关系图：查询素材间关系、素材所在的承诺谱系。"""

    def __init__(self, assets) -> None:
        self.assets = tuple(assets)
        self._by_ref = {a.asset_ref: a for a in self.assets}
        self.groups = group_origins(self.assets)
        self._segment_of: dict[str, ClaimSegment] = {}
        self._adjacent: set[str] = set()
        for group in self.groups.values():
            for segment in group.segments:
                for asset in segment.members:
                    self._segment_of[asset.asset_ref] = segment
            for asset in group.topic_adjacent:
                self._adjacent.add(asset.asset_ref)

    def _asset(self, asset_ref: str) -> Asset:
        try:
            return self._by_ref[asset_ref]
        except KeyError:
            raise ValueError(f"未知素材 {asset_ref}") from None

    def segment_of(self, asset_ref: str) -> ClaimSegment | None:
        """素材所在的承诺谱系；仅主题相近的素材不属于任何谱系，返回 None。"""
        return self._segment_of.get(asset_ref)

    def is_topic_adjacent(self, asset_ref: str) -> bool:
        return asset_ref in self._adjacent

    def classify(self, subject_ref: str, other_ref: str) -> RelationKind:
        """other 相对于 subject 的内容关系（对称）。"""
        if subject_ref == other_ref:
            return RelationKind.IDENTICAL_REPOST
        subject = self._asset(subject_ref)
        other = self._asset(other_ref)
        if subject_ref in self._adjacent or other_ref in self._adjacent:
            return RelationKind.TOPIC_SIMILAR_ONLY
        if (subject.origin_ref or "") != (other.origin_ref or ""):
            return RelationKind.UNRELATED
        subject_segment = self._segment_of.get(subject_ref)
        other_segment = self._segment_of.get(other_ref)
        if subject_segment is not None and subject_segment is other_segment:
            if subject.content_hash and subject.content_hash == other.content_hash:
                return RelationKind.IDENTICAL_REPOST
            return RelationKind.SAME_CLAIM_VARIANT
        return RelationKind.SUBSTANTIVE_REWRITE

"""证据汇总：达成分布、不确定性、批次计数与口径差异。

两个并列视角（缺一不可）：
- assigned 视角：试行分派版次（assigned=old/new），回答“试行分派上的效果”
- exposure 视角：实际接触材料（paper/audio 的真实组合），回答“人群真正接触到什么”

只用既领新版又成功回访的人不能发布：凡 followup != observed 的分派记录，
一律不进入达成率，而是登记为漏访/拒访证据缺口。
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .dataio import Tables
from .reconcile import Reconciled

Z_95 = 1.959963984540054


def wilson_interval(successes: int, n: int) -> tuple[float, float]:
    """Wilson 95% 置信区间；n=0 时返回 (0.0, 0.0) 并由调用方标注不可判定。"""

    if n == 0:
        return 0.0, 0.0
    phat = successes / n
    margin = (
        Z_95
        * math.sqrt(phat * (1 - phat) / n + Z_95**2 / (4 * n**2))
        / (1 + Z_95**2 / n)
    )
    center = (phat + Z_95**2 / (2 * n)) / (1 + Z_95**2 / n)
    return max(0.0, center - margin), min(1.0, center + margin)


@dataclass(frozen=True)
class RateEstimate:
    goal: str
    language: str
    view: str          # assigned / exposure
    side: str          # old / new（exposure 下为 paper 版次）
    channel: str       # old-old / new-new / new-old / old-new
    order: str | None  # None 表示合并两种顺序
    successes: int
    known: int         # 有明确达成判定的人数（达成率分母）
    unresolved: int    # 异判未定导致该目标无判定的人数
    observed: int      # 成功回访人数（含未定）
    rate: float
    ci_low: float
    ci_high: float
    conservative_rate: float  # 未定按未达成的敏感性口径
    conservative_ci_low: float
    conservative_ci_high: float

    @property
    def estimable(self) -> bool:
        """分母为 0 时速率不可估计，必须显式标注而非当作 0% 达成。"""

        return self.known > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "language": self.language,
            "view": self.view,
            "side": self.side,
            "channel": self.channel,
            "order": self.order,
            "successes": self.successes,
            "known": self.known,
            "unresolved": self.unresolved,
            "observed": self.observed,
            "estimable": self.estimable,
            "rate": round(self.rate, 4),
            "ci_low": round(self.ci_low, 4),
            "ci_high": round(self.ci_high, 4),
            "conservative_rate": round(self.conservative_rate, 4),
            "conservative_ci_low": round(self.conservative_ci_low, 4),
            "conservative_ci_high": round(self.conservative_ci_high, 4),
        }


@dataclass
class ClusterCount:
    language: str
    side: str
    total_clusters: int
    complete_clusters: int          # 该语言侧无漏访且无错发的批次
    clusters_with_missing: list[str] = field(default_factory=list)
    clusters_with_wrong_material: list[str] = field(default_factory=list)


@dataclass
class FollowupGap:
    encounter: str
    ward: str
    language: str
    cluster: str
    assigned: str
    paper: str
    audio: str
    order: str
    followup: str
    kind: str  # missing-refused / missing-pending

    def as_dict(self) -> dict[str, Any]:
        return {
            "encounter": self.encounter,
            "ward": self.ward,
            "language": self.language,
            "cluster": self.cluster,
            "assigned": self.assigned,
            "paper": self.paper,
            "audio": self.audio,
            "order": self.order,
            "followup": self.followup,
            "kind": self.kind,
        }


@dataclass
class WrongMaterial:
    encounter: str
    ward: str
    language: str
    cluster: str
    assigned: str
    paper: str
    audio: str
    order: str
    administered_edition: str  # 实际回述任务对应的版次
    issue: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "encounter": self.encounter,
            "ward": self.ward,
            "language": self.language,
            "cluster": self.cluster,
            "assigned": self.assigned,
            "paper": self.paper,
            "audio": self.audio,
            "order": self.order,
            "administered_edition": self.administered_edition,
            "issue": self.issue,
        }


@dataclass
class EvidenceBundle:
    rates: list[RateEstimate]
    cluster_counts: list[ClusterCount]
    followup_gaps: list[FollowupGap]
    wrong_materials: list[WrongMaterial]
    unresolved_cells: tuple[Any, ...]
    # 每个 (language, goal) 在 assigned 视角下的旧/新样本键，供 decision 取用
    assigned_index: dict[tuple[str, str, str, str | None], RateEstimate]
    exposure_index: dict[tuple[str, str, str, str, str | None], RateEstimate]


def _administered_edition(tables: Tables, encounter: str) -> str:
    """按该回述实际出现的任务判定旧/新版（与 assigned 无关）。"""

    tasks = {row["task"] for row in tables.scores if row["encounter"] == encounter}
    if any("new" in task for task in tasks):
        return "new"
    if any(task.endswith("-old") for task in tasks):
        return "old"
    return "none"


def build_evidence(tables: Tables, reconciled: Reconciled) -> EvidenceBundle:
    dispatch = tables.by_encounter()
    achievement = {
        key: result.achieved for key, result in reconciled.goal_results.items()
    }
    languages = sorted({row["language"] for row in tables.dispatch})
    goals = sorted({row["goal"] for row in tables.targets})

    followup_gaps = [
        FollowupGap(
            encounter=row["encounter"],
            ward=row["ward"],
            language=row["language"],
            cluster=row["cluster"],
            assigned=row["assigned"],
            paper=row["paper"],
            audio=row["audio"],
            order=row["order"],
            followup=row["followup"],
            kind="missing-pending" if row["followup"] == "pending" else "missing-refused",
        )
        for row in tables.dispatch
        if row["followup"] != "observed"
    ]

    wrong_materials: list[WrongMaterial] = []
    for row in tables.dispatch:
        if row["assigned"] == row["paper"] == row["audio"]:
            continue
        administered = _administered_edition(tables, row["encounter"])
        if row["paper"] != row["audio"]:
            issue = "纸件与口译版次不一致（成组错发候选）"
        else:
            issue = "实际接触版次与分派版次不一致"
        wrong_materials.append(
            WrongMaterial(
                encounter=row["encounter"],
                ward=row["ward"],
                language=row["language"],
                cluster=row["cluster"],
                assigned=row["assigned"],
                paper=row["paper"],
                audio=row["audio"],
                order=row["order"],
                administered_edition=administered,
                issue=issue,
            )
        )

    rates: list[RateEstimate] = []

    def add_rate(
        language: str,
        goal: str,
        view: str,
        side: str,
        channel: str,
        order: str | None,
        members: list[str],
    ) -> None:
        successes = known = unresolved = observed = 0
        for encounter in members:
            if dispatch[encounter]["followup"] != "observed":
                continue
            observed += 1
            value = achievement.get((encounter, goal))
            if value is None:
                unresolved += 1
            else:
                known += 1
                if value:
                    successes += 1
        if known == 0:
            low = high = 0.0
        else:
            low, high = wilson_interval(successes, known)
        conservative_n = known + unresolved
        c_low, c_high = (
            wilson_interval(successes, conservative_n) if conservative_n else (0.0, 0.0)
        )
        rates.append(
            RateEstimate(
                goal=goal,
                language=language,
                view=view,
                side=side,
                channel=channel,
                order=order,
                successes=successes,
                known=known,
                unresolved=unresolved,
                observed=observed,
                rate=(successes / known if known else 0.0),
                ci_low=low,
                ci_high=high,
                conservative_rate=(successes / conservative_n if conservative_n else 0.0),
                conservative_ci_low=c_low,
                conservative_ci_high=c_high,
            )
        )

    # assigned 视角：按分派版次；exposure 视角：按实际 paper/audio 组合。
    # exposure 的 side 直接用完整组合键，避免旧纸新口被纸件版次错误归并。
    assigned_members: dict[tuple[str, str, str | None], list[str]] = defaultdict(list)
    exposure_members: dict[tuple[str, str, str, str | None], list[str]] = defaultdict(list)
    for row in tables.dispatch:
        language = row["language"]
        channel = f"{row['paper']}-{row['audio']}"
        assigned_members[(language, row["assigned"], None)].append(row["encounter"])
        assigned_members[(language, row["assigned"], row["order"])].append(row["encounter"])
        exposure_members[(language, channel, channel, None)].append(row["encounter"])
        exposure_members[(language, channel, channel, row["order"])].append(
            row["encounter"]
        )

    for language in languages:
        for goal in goals:
            for (lang, side, order), members in sorted(
                assigned_members.items(),
                key=lambda item: tuple(str(part) for part in item[0]),
            ):
                if lang != language:
                    continue
                channel = side  # assigned 视角渠道直接记 old/new，与 exposure 的纸/口组合区分
                add_rate(language, goal, "assigned", side, channel, order, members)
            for (lang, side, channel, order), members in sorted(
                exposure_members.items(),
                key=lambda item: tuple(str(part) for part in item[0]),
            ):
                if lang != language:
                    continue
                add_rate(language, goal, "exposure", side, channel, order, members)

    assigned_index = {
        (r.language, r.goal, r.side, r.order): r for r in rates if r.view == "assigned"
    }
    exposure_index = {
        (r.language, r.goal, r.side, r.channel, r.order): r
        for r in rates
        if r.view == "exposure"
    }

    cluster_counts = _cluster_counts(tables, languages, wrong_materials, followup_gaps)
    return EvidenceBundle(
        rates=rates,
        cluster_counts=cluster_counts,
        followup_gaps=followup_gaps,
        wrong_materials=wrong_materials,
        unresolved_cells=reconciled.unresolved_disagreements,
        assigned_index=assigned_index,
        exposure_index=exposure_index,
    )


def _cluster_counts(
    tables: Tables,
    languages: list[str],
    wrong_materials: list[WrongMaterial],
    followup_gaps: list[FollowupGap],
) -> list[ClusterCount]:
    clusters = sorted({row["cluster"] for row in tables.dispatch})
    wrong_set = {(item.encounter) for item in wrong_materials}
    gap_set = {item.encounter for item in followup_gaps}
    counts: list[ClusterCount] = []
    for language in languages:
        for side in ("old", "new"):
            total = 0
            complete = 0
            missing_clusters: set[str] = set()
            wrong_clusters: set[str] = set()
            for cluster in clusters:
                cell = [
                    row
                    for row in tables.dispatch
                    if row["cluster"] == cluster
                    and row["language"] == language
                    and row["assigned"] == side
                ]
                if not cell:
                    continue
                total += 1
                encounters = {row["encounter"] for row in cell}
                if encounters & gap_set:
                    missing_clusters.add(cluster)
                if encounters & wrong_set:
                    wrong_clusters.add(cluster)
                if not (encounters & gap_set) and not (encounters & wrong_set):
                    complete += 1
            counts.append(
                ClusterCount(
                    language=language,
                    side=side,
                    total_clusters=total,
                    complete_clusters=complete,
                    clusters_with_missing=sorted(missing_clusters),
                    clusters_with_wrong_material=sorted(wrong_clusters),
                )
            )
    return counts


def order_effect(
    bundle: EvidenceBundle, language: str, goal: str, side: str
) -> dict[str, Any]:
    """同一分派版次内，纸件优先 vs 口译优先的达成率差异。"""

    paper_first = bundle.assigned_index.get((language, goal, side, "paper-first"))
    audio_first = bundle.assigned_index.get((language, goal, side, "audio-first"))
    pooled = bundle.assigned_index.get((language, goal, side, None))
    if paper_first is None or audio_first is None or pooled is None:
        return {}
    if not (paper_first.estimable and audio_first.estimable):
        return {
            "language": language,
            "goal": goal,
            "side": side,
            "paper_first": paper_first.as_dict(),
            "audio_first": audio_first.as_dict(),
            "rate_difference": None,
            "ci_overlap": None,
            "note": "至少一个顺序组分母为 0，顺序效应不可估计",
            "pooled": pooled.as_dict(),
        }
    return {
        "language": language,
        "goal": goal,
        "side": side,
        "paper_first": paper_first.as_dict(),
        "audio_first": audio_first.as_dict(),
        "rate_difference": round(
            paper_first.rate - audio_first.rate, 4
        ),
        "ci_overlap": not (
            paper_first.ci_high < audio_first.ci_low
            or audio_first.ci_high < paper_first.ci_low
        ),
        "pooled": pooled.as_dict(),
    }

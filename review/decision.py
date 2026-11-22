"""换版判定：公示下限、可比性门槛与发布组合裁决。

判定原则：
1. 每个关键理解目标独立核对，不能用另一目标的高分抵消关键信息的理解下降。
2. 只有同时满足 (a) 共同锚点可比、(b) 新版达成率不低于 minimum_acceptance、
   (c) 较旧版下降不超过 max_decrease、(d) 每侧完整批次数不少于 minimum_cluster，
   才允许该语言 x 渠道的新组合。
3. 共同案例（bridge）只支持定性核对；bridge-only / incomparable 的目标不具备定量换版资格。
4. 异判未定、错发、漏访造成的样本缺口单独登记，区分“可调整口径”与“需补充证据”。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .comparability import (
    ANCHOR_COMPARABLE,
    BRIDGE_ONLY,
    INCOMPARABLE,
    GoalComparability,
)
from .dataio import Tables
from .evidence import EvidenceBundle

ALLOW_NEW = "allow-new"
CONTINUE_OLD = "continue-old"
MANUAL_HARMONIZE = "manual-harmonize"
HOLD_EVIDENCE = "hold-evidence"


@dataclass
class GoalCheck:
    language: str
    goal: str
    channel: str
    comparability_level: str
    old_rate: float | None
    new_rate: float | None
    new_ci_low: float | None
    new_ci_high: float | None
    decrease: float | None
    min_acceptance: float
    max_decrease: float
    min_cluster: int
    old_complete_clusters: int
    new_complete_clusters: int
    passed: bool
    blockers: list[str] = field(default_factory=list)
    evidence_gaps: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "goal": self.goal,
            "channel": self.channel,
            "comparability_level": self.comparability_level,
            "old_rate": None if self.old_rate is None else round(self.old_rate, 4),
            "new_rate": None if self.new_rate is None else round(self.new_rate, 4),
            "new_ci_low": None if self.new_ci_low is None else round(self.new_ci_low, 4),
            "new_ci_high": None if self.new_ci_high is None else round(self.new_ci_high, 4),
            "decrease": None if self.decrease is None else round(self.decrease, 4),
            "minimum_acceptance": self.min_acceptance,
            "max_decrease": self.max_decrease,
            "minimum_cluster": self.min_cluster,
            "old_complete_clusters": self.old_complete_clusters,
            "new_complete_clusters": self.new_complete_clusters,
            "passed": self.passed,
            "blockers": self.blockers,
            "evidence_gaps": self.evidence_gaps,
        }


@dataclass
class ChannelDecision:
    language: str
    channel: str              # 拟投放纸/口译组合，如 new-new
    paper: str
    audio: str
    requires_pair: bool
    banned_for_new: bool
    status: str
    goal_checks: list[GoalCheck]
    rationale: list[str] = field(default_factory=list)
    followup_actions: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "channel": self.channel,
            "paper": self.paper,
            "audio": self.audio,
            "requires_pair": self.requires_pair,
            "banned_for_new": self.banned_for_new,
            "status": self.status,
            "goal_checks": [check.as_dict() for check in self.goal_checks],
            "rationale": self.rationale,
            "followup_actions": self.followup_actions,
        }


def _floor_map(tables: Tables) -> dict[str, dict[str, Any]]:
    return {row["goal"]: row for row in tables.review_floors}


def _cluster_map(bundle: EvidenceBundle) -> dict[tuple[str, str], Any]:
    return {(item.language, item.side): item for item in bundle.cluster_counts}


def evaluate_goals(
    tables: Tables,
    bundle: EvidenceBundle,
    comparability: dict[tuple[str, str], GoalComparability],
    language: str,
) -> list[GoalCheck]:
    floors = _floor_map(tables)
    clusters = _cluster_map(bundle)
    checks: list[GoalCheck] = []
    for goal in sorted(floors):
        rule = floors[goal]
        comp = comparability[(language, goal)]
        old = bundle.assigned_index.get((language, goal, "old", None))
        new = bundle.assigned_index.get((language, goal, "new", None))
        old_clusters = clusters[(language, "old")]
        new_clusters = clusters[(language, "new")]

        blockers: list[str] = []
        gaps: list[str] = []
        decrease = None

        if comp.level != ANCHOR_COMPARABLE:
            if comp.level == INCOMPARABLE:
                blockers.append(
                    f"目标 {goal} 的共同锚点已撤回且共同案例存在分歧，跨版不可比：{comp.rationale}"
                )
            elif comp.level == BRIDGE_ONLY:
                blockers.append(
                    f"目标 {goal} 的共同锚点已撤回，仅有定性共同案例，不能做定量换版：{comp.rationale}"
                )
            else:
                blockers.append(f"目标 {goal} 无共同锚点：{comp.rationale}")

        if new is None or new.known == 0:
            blockers.append("新版侧没有可判定样本")
        else:
            if new.rate < rule["minimum_acceptance"]:
                blockers.append(
                    f"新版达成率 {new.rate:.3f} 低于公示下限 {rule['minimum_acceptance']}"
                )
            if new.unresolved:
                gaps.append(
                    f"新版侧 {new.unresolved} 人因评分异判未定未计入，需复核决议（未定按失败的保守值 "
                    f"{new.conservative_rate:.3f}）"
                )
            if old is not None and old.known:
                decrease = old.rate - new.rate
                if decrease > rule["max_decrease"]:
                    blockers.append(
                        f"较旧版下降 {decrease:.3f} 超过可接受上限 {rule['max_decrease']}"
                    )
                if old.unresolved:
                    gaps.append(
                        f"旧版侧 {old.unresolved} 人异判未定，下降量存在口径不确定性"
                    )

        if old_clusters.complete_clusters < rule["minimum_cluster"]:
            blockers.append(
                f"旧版侧完整批次 {old_clusters.complete_clusters} < 最低 {rule['minimum_cluster']}"
            )
        if new_clusters.complete_clusters < rule["minimum_cluster"]:
            blockers.append(
                f"新版侧完整批次 {new_clusters.complete_clusters} < 最低 {rule['minimum_cluster']}"
            )
        gaps.extend(
            f"旧版侧漏访批次：{', '.join(old_clusters.clusters_with_missing)}"
            for _ in [0] if old_clusters.clusters_with_missing
        )
        gaps.extend(
            f"新版侧漏访批次：{', '.join(new_clusters.clusters_with_missing)}"
            for _ in [0] if new_clusters.clusters_with_missing
        )
        gaps.extend(
            f"旧版侧错发批次：{', '.join(old_clusters.clusters_with_wrong_material)}"
            for _ in [0] if old_clusters.clusters_with_wrong_material
        )
        gaps.extend(
            f"新版侧错发批次：{', '.join(new_clusters.clusters_with_wrong_material)}"
            for _ in [0] if new_clusters.clusters_with_wrong_material
        )

        checks.append(
            GoalCheck(
                language=language,
                goal=goal,
                channel="new",
                comparability_level=comp.level,
                old_rate=old.rate if old and old.known else None,
                new_rate=new.rate if new and new.known else None,
                new_ci_low=new.ci_low if new and new.known else None,
                new_ci_high=new.ci_high if new and new.known else None,
                decrease=decrease,
                min_acceptance=rule["minimum_acceptance"],
                max_decrease=rule["max_decrease"],
                min_cluster=rule["minimum_cluster"],
                old_complete_clusters=old_clusters.complete_clusters,
                new_complete_clusters=new_clusters.complete_clusters,
                passed=not blockers,
                blockers=blockers,
                evidence_gaps=gaps,
            )
        )
    return checks


def decide_channels(
    tables: Tables,
    bundle: EvidenceBundle,
    comparability: dict[tuple[str, str], GoalComparability],
    review_date: str,
) -> list[ChannelDecision]:
    """按 release_options 中每个候选组合给出处置。"""

    decisions: list[ChannelDecision] = []
    languages = sorted({row["language"] for row in tables.release_options})
    for language in languages:
        goal_checks = evaluate_goals(tables, bundle, comparability, language)
        cluster_items = _cluster_map(bundle)
        for option in sorted(
            (row for row in tables.release_options if row["language"] == language),
            key=lambda row: row["edition"],
        ):
            channel = f"{option['paper']}-{option['audio']}"
            banned = (
                option["banned_for_new_on"] is not None
                and option["banned_for_new_on"] <= review_date
            )
            rationale: list[str] = []
            actions: list[dict[str, Any]] = []

            if channel == "old-old":
                status = CONTINUE_OLD
                if banned:
                    status = MANUAL_HARMONIZE
                    rationale.append(
                        f"{option['edition']} 自 {option['banned_for_new_on']} 起禁止用于新批次，"
                        "已发现关键歧义的旧稿不得继续发给新批次；在院旧纸件批次仍按匹配口译稿完成交接"
                    )
                else:
                    rationale.append("旧组合继续用于在院批次与补访，作为对照侧保留")
            else:
                failed = [check for check in goal_checks if not check.passed]
                unsupported_mix = channel != "new-new" and not _mix_supported(
                    tables, language, option
                )
                if banned:
                    status = MANUAL_HARMONIZE
                    rationale.append(
                        f"{option['edition']} 已在 {option['banned_for_new_on']} 起禁止新批次投放"
                    )
                elif unsupported_mix:
                    status = HOLD_EVIDENCE
                    rationale.append(
                        f"{language} 的 {channel} 纸/口组合不在兼容发行清单，新旧组合互不兼容，"
                        "相关观察只能按实际接触口径单列，不能作为新组合证据"
                    )
                elif failed:
                    status = HOLD_EVIDENCE
                    rationale.append(
                        "存在未通过的关键理解目标，禁止以其他目标高分抵消："
                        + "；".join(
                            blocker
                            for check in failed
                            for blocker in check.blockers
                        )
                    )
                else:
                    status = ALLOW_NEW
                    rationale.append(
                        "三个理解目标均通过可比性、公示下限、下降上限与完整批次门槛"
                    )
                actions = _followup_actions(
                    tables, bundle, language, channel, goal_checks, cluster_items
                )

            decisions.append(
                ChannelDecision(
                    language=language,
                    channel=channel,
                    paper=option["paper"],
                    audio=option["audio"],
                    requires_pair=bool(option["requires_pair"]),
                    banned_for_new=banned,
                    status=status,
                    goal_checks=goal_checks if channel != "old-old" else [],
                    rationale=rationale,
                    followup_actions=actions,
                )
            )
    return decisions


def _mix_supported(
    tables: Tables, language: str, option: dict[str, Any]
) -> bool:
    return any(
        row["language"] == language
        and row["paper"] == option["paper"]
        and row["audio"] == option["audio"]
        for row in tables.release_options
    )


def _followup_actions(
    tables: Tables,
    bundle: EvidenceBundle,
    language: str,
    channel: str,
    goal_checks: list[GoalCheck],
    cluster_items: dict[tuple[str, str], Any],
) -> list[dict[str, Any]]:
    """给出下轮补问清单：补谁、核查什么。"""

    actions: list[dict[str, Any]] = []
    dispatch = tables.by_encounter()

    # 1. 漏访/拒访：按语言与拟投放侧列出
    relevant_gaps = [
        gap
        for gap in bundle.followup_gaps
        if gap.language == language and gap.assigned == "new"
    ]
    for gap in relevant_gaps:
        actions.append(
            {
                "type": "re-contact",
                "encounter": gap.encounter,
                "reason": gap.kind,
                "check": f"补做 {gap.language} 新版三个理解目标回述（批次 {gap.cluster}，顺序 {gap.order}）",
            }
        )

    # 2. 异判未定：该语言所有侧别的未定单元都需补复核，旧侧口径同样影响下降量判断
    unresolved_encounters = sorted(
        {
            cell.encounter
            for cell in bundle.unresolved_cells
            if dispatch[cell.encounter]["language"] == language
        }
    )
    for encounter in unresolved_encounters:
        side = dispatch[encounter]["assigned"]
        actions.append(
            {
                "type": "adjudicate",
                "encounter": encounter,
                "reason": f"scorer-disagreement-{side}",
                "check": (
                    f"按 scorer_reviews 流程补复核决议（{side} 侧），决议只适用该次回述任务；"
                    "未定前该目标不进入达成率，保守口径按未达成处理"
                ),
            }
        )

    # 3. 错发：核查实际接触并决定剔除或改按 exposure 口径
    for wrong in bundle.wrong_materials:
        if wrong.language != language:
            continue
        actions.append(
            {
                "type": "verify-material",
                "encounter": wrong.encounter,
                "reason": "wrong-material",
                "check": (
                    f"核查 {wrong.cluster} 实际纸件/口译（分派 {wrong.assigned}，"
                    f"接触 {wrong.paper}/{wrong.audio}，回述任务为 {wrong.administered_edition} 版），"
                    "确认后从对应渠道口径剔除或改列实际接触组"
                ),
            }
        )

    # 4. 可比性缺口
    for check in goal_checks:
        if check.comparability_level in (BRIDGE_ONLY, INCOMPARABLE):
            actions.append(
                {
                    "type": "comparability",
                    "encounter": None,
                    "reason": check.comparability_level,
                    "check": (
                        f"{language}/{check.goal} 锚点已撤回：补审该语言新版题面与共同案例，"
                        "确认含义前不得用回访达成率做换版比较"
                    ),
                }
            )
    return actions

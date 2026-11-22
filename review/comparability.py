"""跨版可比性：共同锚点撤回与共同案例（bridge）复核。

约定：
- targets.anchor_label 标记跨版含义可比较的题；null 表示该任务没有共同锚点。
- anchor_changes（kind=withdraw）表示复审确认某语言某题的共同意义不再成立，
  自 applied_on 起适用于本轮审订；撤回前发出的依据仍可回查。
- bridge_cases 是审订组的合成共同案例，不属于回访试验样本，只能用于核对含义，
  不能并入达成率，也不能替代试验侧的样本量与下限判断。

可比性分级（每个 语言 x 理解目标）：
- anchor            共同锚点仍成立，可在回访试验内做旧/新定量比较
- bridge-only       锚点已撤回，但共同案例两版判定完全一致：可做定性核对，
                     不能单独支撑换版定量结论
- incomparable      锚点撤回且共同案例出现两版分歧：该目标在该语言不可跨版比较
- no-anchor         没有共同锚点且无可用共同案例（资料中未出现，保留兜底）
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from .dataio import Tables

ANCHOR_COMPARABLE = "anchor"
BRIDGE_ONLY = "bridge-only"
INCOMPARABLE = "incomparable"
NO_ANCHOR = "no-anchor"

QUANTITATIVE_LEVELS = frozenset({ANCHOR_COMPARABLE})


@dataclass(frozen=True)
class AnchorWithdrawal:
    notice: str
    language: str
    task: str
    applied_on: str
    kind: str


@dataclass(frozen=True)
class GoalComparability:
    language: str
    goal: str
    level: str
    anchor_label: str | None
    withdrawals: tuple[AnchorWithdrawal, ...]
    bridge_total: int
    bridge_divergent: int
    bridge_confirmed: int
    comparable_tasks: tuple[str, ...]
    rationale: str


def withdrawals_for_round(tables: Tables) -> set[tuple[str, str]]:
    """本轮适用的 (language, task) 撤回集合。

    资料中所有 anchor_changes 的 applied_on 均不晚于本轮审订日，
    因此全部适用；函数仍保留日期参数以便后续轮次复用。
    """

    return {(row["language"], row["task"]) for row in tables.anchor_changes}


def _anchor_labels_by_goal(tables: Tables) -> dict[tuple[str, str], set[str | None]]:
    labels: dict[tuple[str, str], set[str | None]] = defaultdict(set)
    for row in tables.targets:
        labels[(row["language"], row["goal"])].add(row["anchor_label"])
    return labels


def evaluate_comparability(tables: Tables) -> dict[tuple[str, str], GoalComparability]:
    withdrawn = withdrawals_for_round(tables)
    withdrawal_rows = {
        (row["language"], row["task"]): AnchorWithdrawal(
            notice=row["notice"],
            language=row["language"],
            task=row["task"],
            applied_on=row["applied_on"],
            kind=row["kind"],
        )
        for row in tables.anchor_changes
    }
    labels = _anchor_labels_by_goal(tables)

    bridge_total: dict[tuple[str, str], int] = defaultdict(int)
    bridge_divergent: dict[tuple[str, str], int] = defaultdict(int)
    bridge_confirmed: dict[tuple[str, str], int] = defaultdict(int)
    for row in tables.bridge_cases:
        key = (row["language"], row["goal"])
        if row["state"] != "confirmed":
            continue
        bridge_confirmed[key] += 1
        bridge_total[key] += 1
        if row["old_understood"] != row["new_understood"]:
            bridge_divergent[key] += 1

    result: dict[tuple[str, str], GoalComparability] = {}
    languages = sorted({row["language"] for row in tables.targets})
    goals = sorted({row["goal"] for row in tables.targets})
    for language in languages:
        for goal in goals:
            key = (language, goal)
            goal_rows = [
                row for row in tables.targets
                if row["language"] == language and row["goal"] == goal
            ]
            goal_withdrawals = tuple(
                sorted(
                    (
                        withdrawal_rows[(language, row["task"])]
                        for row in goal_rows
                        if (language, row["task"]) in withdrawn
                    ),
                    key=lambda item: item.applied_on,
                )
            )
            goal_labels = sorted(label for label in labels[key] if label is not None)
            anchor_label = goal_labels[0] if goal_labels else None
            total = bridge_total[key]
            divergent = bridge_divergent[key]
            confirmed = bridge_confirmed[key]
            tasks = tuple(sorted(row["task"] for row in goal_rows))

            if not goal_withdrawals and anchor_label is not None:
                level = ANCHOR_COMPARABLE
                rationale = (
                    f"共同锚点 {anchor_label} 未被撤回，回访试验内可做旧/新定量比较"
                )
            elif not goal_withdrawals:
                # 无锚点：退回共同案例
                level, rationale = _level_from_bridge(total, divergent, anchor_label)
            else:
                notice_ids = ",".join(item.notice for item in goal_withdrawals)
                if divergent:
                    level = INCOMPARABLE
                    rationale = (
                        f"锚点经 {notice_ids} 撤回，且 {divergent}/{total} 个共同案例两版判定分歧，"
                        "该目标在该语言不可跨版比较"
                    )
                elif confirmed:
                    level = BRIDGE_ONLY
                    rationale = (
                        f"锚点经 {notice_ids} 撤回；{total} 个共同案例两版判定一致，"
                        "仅支持定性核对，不能替代试验样本做定量换版结论"
                    )
                else:
                    level = NO_ANCHOR
                    rationale = f"锚点经 {notice_ids} 撤回，且无已确认共同案例，无法比较"

            result[key] = GoalComparability(
                language=language,
                goal=goal,
                level=level,
                anchor_label=anchor_label,
                withdrawals=goal_withdrawals,
                bridge_total=total,
                bridge_divergent=divergent,
                bridge_confirmed=confirmed,
                comparable_tasks=tasks,
                rationale=rationale,
            )
    return result


def _level_from_bridge(
    total: int, divergent: int, anchor_label: str | None
) -> tuple[str, str]:
    if not total:
        return NO_ANCHOR, "无共同锚点且无已确认共同案例，无法比较"
    if divergent:
        return INCOMPARABLE, f"{divergent}/{total} 个共同案例两版判定分歧，不可比较"
    return (
        BRIDGE_ONLY,
        "无共同锚点，但共同案例两版判定一致，仅支持定性核对",
    )


def remaining_comparison_scope(
    tables: Tables,
) -> dict[str, list[dict[str, Any]]]:
    """锚点撤回后，重新列出仍可借共同案例比较的语言/目标/渠道。

    返回结构按可比性分级组织，供审订组核对撤回后还剩哪些比较路径。
    """

    comparability = evaluate_comparability(tables)
    scope: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (language, goal), item in sorted(comparability.items()):
        scope[item.level].append(
            {
                "language": language,
                "goal": goal,
                "anchor_label": item.anchor_label,
                "bridge_total": item.bridge_total,
                "bridge_divergent": item.bridge_divergent,
                "withdrawn_tasks": [item.task for item in item.withdrawals],
                "rationale": item.rationale,
            }
        )
    return dict(scope)

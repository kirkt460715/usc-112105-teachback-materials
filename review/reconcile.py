"""评分异议合并与理解目标归并。

业务约定（见 docs/materials.md 与 targets 表）：
- place、return：任一有效项正确即视为目标达成（资料中每侧各只有一个任务）。
- call：旧版单一任务 call-old；新版拆成 call-new-a、call-new-b，拆题后须两部分都正确。
- 同一人同一目标只计一次；一次回述可覆盖多个目标。
- 同人同任务出现异判且未经 scorer_reviews 复核的，保留为未定，不进入达成率分子分母，
  但要登记为需要补充证据的数据问题；另给保守口径（未定按未达成）供敏感性核对。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .dataio import Tables

GOAL_TASKS = {
    "call-old": "call",
    "call-new-a": "call",
    "call-new-b": "call",
    "return-old": "return",
    "return-new": "return",
    "place-old": "place",
    "place-new": "place",
}

# call 拆题时必须全部正确的新版部件
CALL_PARTS_NEW = ("call-new-a", "call-new-b")


@dataclass(frozen=True)
class TaskCell:
    """同一回述任务在合并评分员记录后的状态。"""

    encounter: str
    task: str
    status: str  # agreed（单一或一致）/ reviewed（复核决议）/ unresolved（异判未定）
    understood: bool | None
    score_ids: tuple[str, ...]
    assessors: tuple[str, ...]
    review_id: str | None


@dataclass(frozen=True)
class GoalResult:
    """一次回述在一个理解目标上的归并结果，每人每目标只出现一次。"""

    encounter: str
    language: str
    goal: str
    achieved: bool | None  # None 表示证据未定，不进入达成率口径
    components: tuple[str, ...]
    component_values: tuple[bool | None, ...]
    rule: str  # single / all-parts / unknown-parts
    unresolved_components: tuple[str, ...]


@dataclass(frozen=True)
class Reconciled:
    task_cells: dict[tuple[str, str], TaskCell]
    goal_results: dict[tuple[str, str], GoalResult]
    unresolved_disagreements: tuple[TaskCell, ...]
    reviewed_cells: tuple[TaskCell, ...]


def _task_goal_map(tables: Tables) -> dict[tuple[str, str], dict[str, Any]]:
    return {(row["language"], row["task"]): row for row in tables.targets}


def resolve_task_cells(tables: Tables) -> Reconciled:
    """把评分记录按 (encounter, task) 合并，并套用复核决议。"""

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in tables.scores:
        grouped[(row["encounter"], row["task"])].append(row)

    review_index = {
        (row["encounter"], row["task"]): row for row in tables.scorer_reviews
    }

    cells: dict[tuple[str, str], TaskCell] = {}
    unresolved: list[TaskCell] = []
    reviewed: list[TaskCell] = []
    for key, rows in sorted(grouped.items()):
        values = {row["understood"] for row in rows}
        score_ids = tuple(sorted(row["score"] for row in rows))
        assessors = tuple(sorted(row["assessor"] for row in rows))
        review = review_index.get(key)
        if len(values) == 1:
            cell = TaskCell(key[0], key[1], "agreed", next(iter(values)), score_ids, assessors, None)
        elif review is not None:
            cell = TaskCell(
                key[0], key[1], "reviewed", review["decided"], score_ids, assessors, review["review"]
            )
            reviewed.append(cell)
        else:
            cell = TaskCell(key[0], key[1], "unresolved", None, score_ids, assessors, None)
            unresolved.append(cell)
        cells[key] = cell

    goal_results = _aggregate_goals(tables, cells)
    return Reconciled(
        task_cells=cells,
        goal_results=goal_results,
        unresolved_disagreements=tuple(unresolved),
        reviewed_cells=tuple(reviewed),
    )


def _aggregate_goals(
    tables: Tables, cells: dict[tuple[str, str], TaskCell]
) -> dict[tuple[str, str], GoalResult]:
    dispatch = tables.by_encounter()
    per_encounter_goal: dict[tuple[str, str], list[TaskCell]] = defaultdict(list)
    for (encounter, task), cell in cells.items():
        goal = GOAL_TASKS[task]
        per_encounter_goal[(encounter, goal)].append(cell)

    results: dict[tuple[str, str], GoalResult] = {}
    for (encounter, goal), component_cells in sorted(per_encounter_goal.items()):
        language = dispatch[encounter]["language"]
        components = tuple(sorted(cell.task for cell in component_cells))
        value_by_task = {cell.task: cell.understood for cell in component_cells}
        values = tuple(value_by_task[task] for task in components)
        unresolved_parts = tuple(
            task for task in components if value_by_task[task] is None
        )

        if goal == "call" and set(CALL_PARTS_NEW).issubset(set(components)):
            # 新版拆题：两部分都正确才算达成；任一部件未定则整体未定
            rule = "all-parts"
            if unresolved_parts:
                achieved: bool | None = None
            else:
                achieved = all(value_by_task[task] for task in CALL_PARTS_NEW)
        else:
            # 单一有效项任务（旧版各目标、新版 return/place）
            rule = "single"
            if unresolved_parts:
                achieved = None
            else:
                achieved = next(iter(value_by_task.values()))

        if unresolved_parts:
            rule = "unknown-parts" if rule == "single" else f"{rule}+unknown"

        results[(encounter, goal)] = GoalResult(
            encounter=encounter,
            language=language,
            goal=goal,
            achieved=achieved,
            components=components,
            component_values=values,
            rule=rule,
            unresolved_components=unresolved_parts,
        )
    return results


def goal_achievement(reconciled: Reconciled) -> dict[tuple[str, str], bool | None]:
    """(encounter, goal) -> 达成状态；同一人每目标至多一条。"""

    return {
        key: result.achieved
        for key, result in reconciled.goal_results.items()
    }

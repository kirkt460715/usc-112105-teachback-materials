"""读取与校验审订资料。

所有资料均为 UTF-8 JSON Lines，字段以 data/manifest.json 为准。
读取时同时校验：字段集合一致、主键无重复、外键可关联、取值在约定集合内。
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EDITIONS = ("old", "new")
ORDERS = ("paper-first", "audio-first")
FOLLOWUPS = ("observed", "pending", "refused")
GOALS = ("call", "return", "place")
LANGUAGES = ("cmn", "yue", "en")


class DataError(ValueError):
    """资料结构或关联不满足审订约定。"""


@dataclass(frozen=True)
class Tables:
    """一次审订轮次使用的全部来源表。"""

    dispatch: tuple[dict[str, Any], ...]
    scores: tuple[dict[str, Any], ...]
    targets: tuple[dict[str, Any], ...]
    anchor_changes: tuple[dict[str, Any], ...]
    review_floors: tuple[dict[str, Any], ...]
    release_options: tuple[dict[str, Any], ...]
    active_wards: tuple[dict[str, Any], ...]
    bridge_cases: tuple[dict[str, Any], ...]
    scorer_reviews: tuple[dict[str, Any], ...]

    def by_encounter(self) -> dict[str, dict[str, Any]]:
        return {row["encounter"]: row for row in self.dispatch}


def _read_jsonl(path: Path, columns: list[str], table: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if not isinstance(record, dict) or set(record) != set(columns):
                raise DataError(f"{table} 第 {number} 行的字段与登记格式不符")
            rows.append(record)
    if not rows:
        raise DataError(f"{table} 为空，无法支撑审订")
    return rows


def _require_unique(rows: list[dict[str, Any]], key: str, table: str) -> None:
    counts = Counter(row[key] for row in rows)
    duplicated = sorted(value for value, n in counts.items() if n > 1)
    if duplicated:
        raise DataError(f"{table} 的 {key} 存在重复：{duplicated}")


def _check_values(rows: list[dict[str, Any]], column: str, allowed: tuple[str, ...], table: str) -> None:
    bad = sorted({str(row[column]) for row in rows if row[column] not in allowed})
    if bad:
        raise DataError(f"{table}.{column} 出现约定外取值：{bad}")


def load_tables(directory: str | Path) -> Tables:
    """按 manifest 读取整个资料目录并做跨表校验。"""

    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    raw: dict[str, list[dict[str, Any]]] = {}
    for name, columns in manifest.items():
        raw[name] = _read_jsonl(directory / f"{name}.jsonl", columns, name)

    dispatch = raw["dispatch"]
    scores = raw["scores"]
    targets = raw["targets"]
    anchor_changes = raw["anchor_changes"]
    review_floors = raw["review_floors"]
    release_options = raw["release_options"]
    active_wards = raw["active_wards"]
    bridge_cases = raw["bridge_cases"]
    scorer_reviews = raw["scorer_reviews"]

    # 主键与取值校验
    _require_unique(dispatch, "encounter", "dispatch")
    _require_unique(review_floors, "rule", "review_floors")
    _require_unique(release_options, "edition", "release_options")
    _require_unique(active_wards, "handoff", "active_wards")
    _require_unique(anchor_changes, "notice", "anchor_changes")
    _check_values(dispatch, "language", LANGUAGES, "dispatch")
    _check_values(dispatch, "assigned", EDITIONS, "dispatch")
    _check_values(dispatch, "paper", EDITIONS, "dispatch")
    _check_values(dispatch, "audio", EDITIONS, "dispatch")
    _check_values(dispatch, "order", ORDERS, "dispatch")
    _check_values(dispatch, "followup", FOLLOWUPS, "dispatch")
    _check_values(targets, "language", LANGUAGES, "targets")
    _check_values(targets, "goal", GOALS, "targets")
    _check_values(anchor_changes, "language", LANGUAGES, "anchor_changes")
    _check_values(anchor_changes, "kind", ("withdraw",), "anchor_changes")
    _check_values(review_floors, "goal", GOALS, "review_floors")
    _check_values(release_options, "language", LANGUAGES, "release_options")
    _check_values(release_options, "paper", EDITIONS, "release_options")
    _check_values(release_options, "audio", EDITIONS, "release_options")
    _check_values(active_wards, "language", LANGUAGES, "active_wards")
    _check_values(active_wards, "paper", EDITIONS, "active_wards")
    _check_values(bridge_cases, "language", LANGUAGES, "bridge_cases")
    _check_values(bridge_cases, "goal", GOALS, "bridge_cases")
    _check_values(bridge_cases, "state", ("confirmed", "superseded"), "bridge_cases")

    encounters = {row["encounter"] for row in dispatch}
    target_keys = {(row["language"], row["task"]) for row in targets}
    languages = {row["language"] for row in dispatch}

    # 评分外键与布尔取值
    for row in scores:
        if row["encounter"] not in encounters:
            raise DataError(f"scores 引用了不存在的 encounter：{row['encounter']}")
        if not isinstance(row["understood"], bool):
            raise DataError(f"scores.{row['score']} 的 understood 必须为布尔值")
        dispatch_row = next(item for item in dispatch if item["encounter"] == row["encounter"])
        key = (dispatch_row["language"], row["task"])
        if key not in target_keys:
            raise DataError(f"scores.{row['score']} 的任务未在 targets 登记：{key}")
    _require_unique(scores, "score", "scores")

    # 复核记录外键
    for row in scorer_reviews:
        if row["encounter"] not in encounters:
            raise DataError(f"scorer_reviews.{row['review']} 引用了不存在的 encounter")
        if not isinstance(row["decided"], bool):
            raise DataError(f"scorer_reviews.{row['review']} 的 decided 必须为布尔值")

    # 下限规则每个理解目标恰好一条
    floor_goals = Counter(row["goal"] for row in review_floors)
    if set(floor_goals) != set(GOALS) or any(n != 1 for n in floor_goals.values()):
        raise DataError(f"review_floors 需为每个理解目标各给一条规则，实际：{dict(floor_goals)}")

    # 病区交接外键
    for row in active_wards:
        if row["encounter"] not in encounters:
            raise DataError(f"active_wards.{row['handoff']} 引用了不存在的 encounter")

    # bridge 覆盖：每个语言 x 目标至少要有共同案例，且任务必须在 targets 中
    bridge_keys = {(row["language"], row["goal"]) for row in bridge_cases}
    for language in languages:
        for goal in GOALS:
            if (language, goal) not in bridge_keys:
                raise DataError(f"bridge_cases 缺少 {language}/{goal} 的共同案例")
    for row in bridge_cases:
        for task_column, task in (("old_task", row["old_task"]), ("new_task", row["new_task"])):
            if (row["language"], task) not in target_keys:
                raise DataError(f"bridge_cases.{row['bridge']} 的 {task_column} 未在 targets 登记")

    return Tables(
        dispatch=tuple(dispatch),
        scores=tuple(scores),
        targets=tuple(targets),
        anchor_changes=tuple(anchor_changes),
        review_floors=tuple(review_floors),
        release_options=tuple(release_options),
        active_wards=tuple(active_wards),
        bridge_cases=tuple(bridge_cases),
        scorer_reviews=tuple(scorer_reviews),
    )

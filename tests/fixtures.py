"""构造小型合成资料，供审订流水线单元测试使用。

刻意覆盖：异判已定/未定、call 拆题、漏访拒访、错发、锚点撤回、bridge 分歧、
禁发日期与成套切换。数据仅用于测试，不含真实出院内容。
"""

from __future__ import annotations

import json
from pathlib import Path

MANIFEST = {
    "dispatch": ["encounter", "language", "ward", "assigned", "paper", "audio", "order", "cluster", "followup"],
    "scores": ["score", "encounter", "task", "assessor", "understood", "received_on"],
    "targets": ["language", "task", "goal", "anchor_label"],
    "anchor_changes": ["notice", "language", "task", "applied_on", "kind"],
    "review_floors": ["rule", "goal", "minimum_acceptance", "max_decrease", "minimum_cluster"],
    "release_options": ["edition", "language", "paper", "audio", "requires_pair", "banned_for_new_on"],
    "active_wards": ["handoff", "ward", "language", "encounter", "paper", "audio_complete"],
    "bridge_cases": ["bridge", "language", "goal", "case", "old_task", "new_task", "old_understood", "new_understood", "state"],
    "scorer_reviews": ["review", "encounter", "task", "decided", "received_on"],
}

OLD_TASKS = ["call-old", "return-old", "place-old"]
NEW_TASKS = ["call-new-a", "call-new-b", "return-new", "place-new"]


def _write(directory: Path, name: str, rows: list[dict]) -> None:
    with (directory / f"{name}.jsonl").open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_fixture(directory: str | Path, *, withdraw_yue_call: bool = True) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_text(json.dumps(MANIFEST), encoding="utf-8")

    # 两个病区批次，每批 cmn/yue/en x old/new；另加漏访、拒访、错发各一例
    dispatch = []
    seq = 0

    def add(language, ward, cluster, assigned, paper, audio, order, followup):
        nonlocal seq
        dispatch.append(
            {
                "encounter": f"T{seq:03d}",
                "language": language,
                "ward": ward,
                "assigned": assigned,
                "paper": paper,
                "audio": audio,
                "order": order,
                "cluster": cluster,
                "followup": followup,
            }
        )
        seq += 1

    for cluster, ward, order in (("C0", "W1", "paper-first"), ("C1", "W1", "audio-first")):
        for language in ("cmn", "yue", "en"):
            add(language, ward, cluster, "old", "old", "old", order, "observed")
            add(language, ward, cluster, "new", "new", "new", order, "observed")
    # 额外漏访/拒访/错发
    add("cmn", "W1", "C2", "old", "old", "old", "paper-first", "pending")
    add("yue", "W1", "C2", "new", "new", "new", "paper-first", "refused")
    add("en", "W1", "C2", "new", "new", "old", "paper-first", "observed")  # 错发：新纸旧口
    add("cmn", "W1", "C3", "new", "old", "new", "audio-first", "observed")  # 错发：旧纸新口，做旧题

    targets = []
    for language in ("cmn", "yue", "en"):
        targets.extend(
            [
                {"language": language, "task": "call-old", "goal": "call", "anchor_label": "when"},
                {"language": language, "task": "call-new-a", "goal": "call", "anchor_label": "when"},
                {"language": language, "task": "call-new-b", "goal": "call", "anchor_label": "why"},
                {"language": language, "task": "return-old", "goal": "return", "anchor_label": "date"},
                {"language": language, "task": "return-new", "goal": "return", "anchor_label": "date"},
                {"language": language, "task": "place-old", "goal": "place", "anchor_label": "ward"},
                {"language": language, "task": "place-new", "goal": "place", "anchor_label": "ward"},
            ]
        )

    anchor_changes = (
        [
            {
                "notice": "v1",
                "language": "yue",
                "task": "call-new-a",
                "applied_on": "2026-10-23",
                "kind": "withdraw",
            }
        ]
        if withdraw_yue_call
        else []
    )

    review_floors = [
        {"rule": "r1", "goal": "call", "minimum_acceptance": 0.6, "max_decrease": 0.15, "minimum_cluster": 2},
        {"rule": "r2", "goal": "return", "minimum_acceptance": 0.55, "max_decrease": 0.2, "minimum_cluster": 2},
        {"rule": "r3", "goal": "place", "minimum_acceptance": 0.55, "max_decrease": 0.2, "minimum_cluster": 2},
    ]

    release_options = [
        {"edition": "cmn-old-old", "language": "cmn", "paper": "old", "audio": "old", "requires_pair": True, "banned_for_new_on": None},
        {"edition": "cmn-new-new", "language": "cmn", "paper": "new", "audio": "new", "requires_pair": True, "banned_for_new_on": None},
        {"edition": "yue-old-old", "language": "yue", "paper": "old", "audio": "old", "requires_pair": True, "banned_for_new_on": "2026-10-26"},
        {"edition": "yue-new-new", "language": "yue", "paper": "new", "audio": "new", "requires_pair": True, "banned_for_new_on": None},
        {"edition": "en-old-old", "language": "en", "paper": "old", "audio": "old", "requires_pair": False, "banned_for_new_on": None},
        {"edition": "en-new-new", "language": "en", "paper": "new", "audio": "new", "requires_pair": False, "banned_for_new_on": None},
        {"edition": "en-new-old", "language": "en", "paper": "new", "audio": "old", "requires_pair": False, "banned_for_new_on": None},
    ]

    active_wards = [
        {"handoff": "a1", "ward": "W1", "language": "yue", "encounter": "T001", "paper": "old", "audio_complete": False},
    ]

    bridge_cases = []
    case_no = 0
    for language in ("cmn", "yue", "en"):
        for goal, old_task, new_task in (
            ("call", "call-old", "call-new-a"),
            ("return", "return-old", "return-new"),
            ("place", "place-old", "place-new"),
        ):
            # yue/call 放一个分歧案例，其余一致
            divergent = language == "yue" and goal == "call"
            for i in range(3):
                old_v = True
                new_v = False if divergent and i == 0 else True
                bridge_cases.append(
                    {
                        "bridge": f"{language}-{goal}-{i}",
                        "language": language,
                        "goal": goal,
                        "case": f"case-{case_no}",
                        "old_task": old_task,
                        "new_task": new_task,
                        "old_understood": old_v,
                        "new_understood": new_v,
                        "state": "confirmed",
                    }
                )
                case_no += 1

    # 评分：让新版 call 普遍较差以触发下限；T001（yue old）制造异判未定；
    # T007（yue new C1）制造异判并给复核决议
    scores = []
    score_seq = 0

    def add_score(encounter, task, understood, assessor="P"):
        nonlocal score_seq
        scores.append(
            {
                "score": f"sc{score_seq:04d}",
                "encounter": encounter,
                "task": task,
                "assessor": assessor,
                "understood": understood,
                "received_on": "2026-10-17",
            }
        )
        score_seq += 1

    observed = [row for row in dispatch if row["followup"] == "observed"]
    for row in observed:
        tasks = OLD_TASKS if row["assigned"] == "old" else NEW_TASKS
        # 错发 old 纸/new 口（T 最后一例）实际做旧题
        if row["paper"] == "old" and row["audio"] == "new":
            tasks = OLD_TASKS
        for task in tasks:
            goal = "call" if task.startswith("call") else task.split("-")[0]
            if row["assigned"] == "new" and goal == "call":
                understood = task != "call-new-b"  # b 部件失败 -> call 整体失败
            else:
                understood = True
            add_score(row["encounter"], task, understood)

    # T002 yue old（C0 的 yue/old）call-old：P/Q 异判且无复核 -> 未定
    add_score("T002", "call-old", False, assessor="Q")
    # T009 yue new（C1 的 yue new）call-new-a：异判后复核判 True
    add_score("T009", "call-new-a", False, assessor="Q")
    scorer_reviews = [
        {"review": "s1", "encounter": "T009", "task": "call-new-a", "decided": True, "received_on": "2026-10-25"},
    ]

    _write(directory, "dispatch", dispatch)
    _write(directory, "scores", scores)
    _write(directory, "targets", targets)
    _write(directory, "anchor_changes", anchor_changes)
    _write(directory, "review_floors", review_floors)
    _write(directory, "release_options", release_options)
    _write(directory, "active_wards", active_wards)
    _write(directory, "bridge_cases", bridge_cases)
    _write(directory, "scorer_reviews", scorer_reviews)
    return directory

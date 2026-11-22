"""病区交接、发行组合与服务台批次视图。

三类范围：
- continue-old       继续旧组合：在院已领旧纸件的批次，仍可获得匹配的旧口译稿
- allow-new          允许新组合：通过全部门槛的语言 x 纸/口成套组合
- manual-harmonize   需人工统一说明：禁发新批次的旧稿、新旧互不兼容或证据不足的组合

服务台按 encounter 查询时，必须能看到：
1. 当时确实发了什么（assigned/paper/audio/order/cluster/followup）
2. 尚能提供什么（release_options 中未禁发的兼容组合、在院交接口径）
3. 换版判定依据的版本与证据（目标核对、可比性、数据问题回查编号）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .dataio import Tables
from .decision import (
    ALLOW_NEW,
    CONTINUE_OLD,
    HOLD_EVIDENCE,
    MANUAL_HARMONIZE,
    ChannelDecision,
)
from .evidence import EvidenceBundle
from .reconcile import Reconciled


@dataclass
class WardHandoff:
    handoff: str
    ward: str
    language: str
    encounter: str
    paper_held: str
    audio_complete: bool
    continue_combo: str | None
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "handoff": self.handoff,
            "ward": self.ward,
            "language": self.language,
            "encounter": self.encounter,
            "paper_held": self.paper_held,
            "audio_complete": self.audio_complete,
            "continue_combo": self.continue_combo,
            "note": self.note,
        }


@dataclass
class ServiceDeskRecord:
    encounter: str
    ward: str
    language: str
    cluster: str
    assigned: str
    paper: str
    audio: str
    order: str
    followup: str
    actual_channel: str
    administered_edition: str
    material_flags: list[str]
    available_now: list[dict[str, Any]]
    evidence_refs: dict[str, Any]

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
            "actual_channel": self.actual_channel,
            "administered_edition": self.administered_edition,
            "material_flags": self.material_flags,
            "available_now": self.available_now,
            "evidence_refs": self.evidence_refs,
        }


def build_handoffs(
    tables: Tables, channel_decisions: list[ChannelDecision], review_date: str
) -> list[WardHandoff]:
    decision_index = {(d.language, d.channel): d for d in channel_decisions}
    handoffs: list[WardHandoff] = []
    for row in tables.active_wards:
        held_channel = f"{row['paper']}-old" if row["paper"] == "old" else f"{row['paper']}-new"
        decision = decision_index.get((row["language"], held_channel))
        if decision is not None and decision.status == MANUAL_HARMONIZE and decision.banned_for_new:
            note = (
                "旧组合已禁用于新批次；本在院批次已领旧纸件，仍按匹配旧口译稿完成，"
                "不得向新批次发放该旧稿"
            )
            continue_combo = held_channel
        elif decision is not None and decision.status == CONTINUE_OLD:
            note = "在院批次保持旧纸件与匹配口译稿；新批次可按通过门槛的新组合投放"
            continue_combo = held_channel
        else:
            note = "按病区实际手头版次交接，缺失口译需补齐匹配稿"
            continue_combo = held_channel
        handoffs.append(
            WardHandoff(
                handoff=row["handoff"],
                ward=row["ward"],
                language=row["language"],
                encounter=row["encounter"],
                paper_held=row["paper"],
                audio_complete=bool(row["audio_complete"]),
                continue_combo=continue_combo,
                note=note,
            )
        )
    return handoffs


def _administered_edition(tables: Tables, encounter: str) -> str:
    tasks = {row["task"] for row in tables.scores if row["encounter"] == encounter}
    if any("new" in task for task in tasks):
        return "new"
    if any(task.endswith("-old") for task in tasks):
        return "old"
    return "none"


def build_service_desk(
    tables: Tables,
    reconciled: Reconciled,
    bundle: EvidenceBundle,
    channel_decisions: list[ChannelDecision],
    review_date: str,
) -> list[ServiceDeskRecord]:
    decision_index = {(d.language, d.channel): d for d in channel_decisions}
    wrong_index = {item.encounter: item for item in bundle.wrong_materials}
    gap_index = {item.encounter: item for item in bundle.followup_gaps}
    records: list[ServiceDeskRecord] = []

    for row in tables.dispatch:
        language = row["language"]
        actual_channel = f"{row['paper']}-{row['audio']}"
        flags: list[str] = []
        if row["encounter"] in wrong_index:
            flags.append("wrong-material:" + wrong_index[row["encounter"]].issue)
        if row["encounter"] in gap_index:
            flags.append("followup:" + gap_index[row["encounter"]].kind)
        if row["assigned"] != actual_channel.split("-")[0] or row["paper"] != row["audio"]:
            if "wrong-material" not in " ".join(flags):
                flags.append("contact-mismatch")

        available: list[dict[str, Any]] = []
        for option in tables.release_options:
            if option["language"] != language:
                continue
            banned = (
                option["banned_for_new_on"] is not None
                and option["banned_for_new_on"] <= review_date
            )
            decision = decision_index.get((language, f"{option['paper']}-{option['audio']}"))
            available.append(
                {
                    "edition": option["edition"],
                    "paper": option["paper"],
                    "audio": option["audio"],
                    "requires_pair": bool(option["requires_pair"]),
                    "banned_for_new": banned,
                    "decision": decision.status if decision else "not-evaluated",
                }
            )

        goal_refs: dict[str, Any] = {}
        own_cells = [
            cell
            for (encounter, _task), cell in reconciled.task_cells.items()
            if encounter == row["encounter"]
        ]
        for goal in ("call", "return", "place"):
            result = reconciled.goal_results.get((row["encounter"], goal))
            cell_disputes = sorted(
                {
                    cell.task
                    for cell in reconciled.unresolved_disagreements
                    if cell.encounter == row["encounter"]
                }
            )
            goal_refs[goal] = {
                "achieved": None if result is None else result.achieved,
                "components": [] if result is None else list(result.components),
                "unresolved_components": [] if result is None else list(result.unresolved_components),
                "open_disputes": cell_disputes,
            }

        records.append(
            ServiceDeskRecord(
                encounter=row["encounter"],
                ward=row["ward"],
                language=language,
                cluster=row["cluster"],
                assigned=row["assigned"],
                paper=row["paper"],
                audio=row["audio"],
                order=row["order"],
                followup=row["followup"],
                actual_channel=actual_channel,
                administered_edition=_administered_edition(tables, row["encounter"]),
                material_flags=flags,
                available_now=available,
                evidence_refs={
                    "goal_results": goal_refs,
                    "score_ids": sorted(
                        score_id for cell in own_cells for score_id in cell.score_ids
                    ),
                    "reviews": [
                        item.review_id
                        for item in reconciled.reviewed_cells
                        if item.encounter == row["encounter"]
                    ],
                    "channel_decision": (
                        decision_index[(language, actual_channel)].as_dict()
                        if (language, actual_channel) in decision_index
                        else None
                    ),
                },
            )
        )
    return records


def scope_summary(channel_decisions: list[ChannelDecision]) -> dict[str, list[dict[str, Any]]]:
    """三类处置范围汇总，供发行同事直接使用。"""

    summary: dict[str, list[dict[str, Any]]] = {
        CONTINUE_OLD: [],
        ALLOW_NEW: [],
        MANUAL_HARMONIZE: [],
        HOLD_EVIDENCE: [],
    }
    for decision in channel_decisions:
        summary[decision.status].append(
            {
                "language": decision.language,
                "channel": decision.channel,
                "paper": decision.paper,
                "audio": decision.audio,
                "requires_pair": decision.requires_pair,
                "banned_for_new": decision.banned_for_new,
                "rationale": decision.rationale,
            }
        )
    return summary

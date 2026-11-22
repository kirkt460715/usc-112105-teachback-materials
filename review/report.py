"""把审订证据组织成机器可读 JSON 与人工核对 Markdown。

输出文件（统一写入 outputs/）：
- review_packet.json     全量结构化换版依据
- review_report.md       审订组核对用报告
- service_desk.jsonl     服务台逐批次视图
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .comparability import GoalComparability, remaining_comparison_scope
from .dataio import Tables
from .decision import (
    ALLOW_NEW,
    CONTINUE_OLD,
    HOLD_EVIDENCE,
    MANUAL_HARMONIZE,
    ChannelDecision,
)
from .evidence import EvidenceBundle, order_effect
from .handoff import (
    ServiceDeskRecord,
    WardHandoff,
    scope_summary,
)
from .reconcile import Reconciled

STATUS_LABELS = {
    ALLOW_NEW: "允许新组合",
    CONTINUE_OLD: "继续旧组合",
    MANUAL_HARMONIZE: "需人工统一说明",
    HOLD_EVIDENCE: "证据不足暂缓",
}

LEVEL_LABELS = {
    "anchor": "共同锚点可比",
    "bridge-only": "仅共同案例定性可比",
    "incomparable": "不可比",
    "no-anchor": "无共同锚点",
}


def build_packet(
    tables: Tables,
    reconciled: Reconciled,
    bundle: EvidenceBundle,
    comparability: dict[tuple[str, str], GoalComparability],
    decisions: list[ChannelDecision],
    handoffs: list[WardHandoff],
    review_date: str,
) -> dict[str, Any]:
    languages = sorted({row["language"] for row in tables.dispatch})
    goals = sorted({row["goal"] for row in tables.targets})

    order_effects = [
        effect
        for language in languages
        for side in ("old", "new")
        for goal in goals
        if (effect := order_effect(bundle, language, goal, side))
    ]

    return {
        "review_date": review_date,
        "principles": [
            "按理解目标归并，一次回述可覆盖多目标，每人每目标只计一次",
            "call 新版拆题须两部分都正确；place/return 任一有效项正确即达成",
            "异判未定不进入达成率，另给未定按失败的保守口径",
            "锚点撤回后按共同案例重判可比性，bridge 不并入试验样本",
            "关键目标独立判定，禁止跨目标抵消",
            "仅领新版且成功回访的人群不能单独支撑发布",
        ],
        "comparability": [
            {
                "language": language,
                "goal": goal,
                "level": item.level,
                "level_label": LEVEL_LABELS[item.level],
                "anchor_label": item.anchor_label,
                "withdrawals": [
                    {
                        "notice": w.notice,
                        "task": w.task,
                        "applied_on": w.applied_on,
                    }
                    for w in item.withdrawals
                ],
                "bridge_total": item.bridge_total,
                "bridge_divergent": item.bridge_divergent,
                "rationale": item.rationale,
            }
            for (language, goal), item in sorted(comparability.items())
        ],
        "remaining_comparison_scope": remaining_comparison_scope(tables),
        "rates": [rate.as_dict() for rate in sorted(
            bundle.rates,
            key=lambda r: (r.language, r.goal, r.view, r.side, r.channel, str(r.order)),
        )],
        "order_effects": order_effects,
        "cluster_counts": [
            {
                "language": item.language,
                "side": item.side,
                "total_clusters": item.total_clusters,
                "complete_clusters": item.complete_clusters,
                "clusters_with_missing": item.clusters_with_missing,
                "clusters_with_wrong_material": item.clusters_with_wrong_material,
            }
            for item in bundle.cluster_counts
        ],
        "data_quality": {
            "unresolved_disagreements": [
                {
                    "encounter": cell.encounter,
                    "task": cell.task,
                    "score_ids": list(cell.score_ids),
                    "assessors": list(cell.assessors),
                    "kind": "needs-adjudication",
                }
                for cell in reconciled.unresolved_disagreements
            ],
            "reviewed_cells": [
                {
                    "encounter": cell.encounter,
                    "task": cell.task,
                    "review": cell.review_id,
                    "decided": cell.understood,
                    "score_ids": list(cell.score_ids),
                }
                for cell in reconciled.reviewed_cells
            ],
            "wrong_materials": [item.as_dict() for item in bundle.wrong_materials],
            "followup_gaps": [item.as_dict() for item in bundle.followup_gaps],
        },
        "channel_decisions": [decision.as_dict() for decision in decisions],
        "scope_summary": scope_summary(decisions),
        "ward_handoffs": [item.as_dict() for item in handoffs],
    }


def write_outputs(
    packet: dict[str, Any],
    service_desk: list[ServiceDeskRecord],
    output_dir: str | Path,
) -> tuple[Path, Path, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "review_packet.json"
    md_path = output_dir / "review_report.md"
    desk_path = output_dir / "service_desk.jsonl"

    json_path.write_text(
        json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_path.write_text(render_markdown(packet), encoding="utf-8")
    with desk_path.open("w", encoding="utf-8") as stream:
        for record in service_desk:
            stream.write(json.dumps(record.as_dict(), ensure_ascii=False) + "\n")
    return json_path, md_path, desk_path


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _rate_cell(rate: dict[str, Any]) -> str:
    if not rate["estimable"]:
        return "不可估计（分母 0）"
    return _pct(rate["rate"])


def render_markdown(packet: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# 出院说明换版审订依据（核对稿）")
    lines.append("")
    lines.append(f"审订轮次日期：{packet['review_date']}")
    lines.append("")
    lines.append("## 1. 口径原则")
    for principle in packet["principles"]:
        lines.append(f"- {principle}")
    lines.append("")

    lines.append("## 2. 跨版可比性（锚点撤回后的重判）")
    lines.append("")
    lines.append("| 语言 | 目标 | 分级 | 锚点 | 共同案例分歧/总数 | 依据 |")
    lines.append("|---|---|---|---|---|---|")
    for item in packet["comparability"]:
        lines.append(
            f"| {item['language']} | {item['goal']} | {item['level_label']} | "
            f"{item['anchor_label'] or '—'} | {item['bridge_divergent']}/{item['bridge_total']} | "
            f"{item['rationale']} |"
        )
    lines.append("")
    lines.append("撤回后仍可借共同案例比较的范围：")
    for level, rows in packet["remaining_comparison_scope"].items():
        lines.append(f"- {LEVEL_LABELS.get(level, level)}：{len(rows)} 个语言×目标")
        for row in rows:
            lines.append(
                f"  - {row['language']}/{row['goal']}（分歧 {row['bridge_divergent']}/"
                f"{row['bridge_total']}，撤回任务 {','.join(row['withdrawn_tasks']) or '无'}）"
            )
    lines.append("")

    lines.append("## 3. 达成分布与不确定性（分派视角，合并顺序）")
    lines.append("")
    lines.append("| 语言 | 目标 | 侧 | 达成/可判定 | 未定 | 达成率 | Wilson 95% 区间 | 保守率 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for rate in packet["rates"]:
        if rate["view"] != "assigned" or rate["order"] is not None:
            continue
        lines.append(
            f"| {rate['language']} | {rate['goal']} | {rate['side']} | "
            f"{rate['successes']}/{rate['known']} | {rate['unresolved']} | "
            f"{_rate_cell(rate)} | {_pct(rate['ci_low'])}–{_pct(rate['ci_high'])} | "
            f"{_pct(rate['conservative_rate'])} |"
        )
    lines.append("")

    lines.append("## 3b. 实际接触材料视角（exposure，合并顺序）")
    lines.append("")
    lines.append(
        "错发记录按实际纸/口组合单列；混合组合样本极小，分母为 0 或个位数时不能用于发布判定。"
    )
    lines.append("")
    lines.append("| 语言 | 目标 | 实际组合 | 成功回访 | 可判定 | 未定 | 达成率 | Wilson 95% 区间 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for rate in packet["rates"]:
        if rate["view"] != "exposure" or rate["order"] is not None:
            continue
        lines.append(
            f"| {rate['language']} | {rate['goal']} | {rate['channel']} | "
            f"{rate['observed']} | {rate['known']} | {rate['unresolved']} | "
            f"{_rate_cell(rate)} | {_pct(rate['ci_low'])}–{_pct(rate['ci_high'])} |"
        )
    lines.append("")

    lines.append("## 4. 顺序影响（paper-first 对 audio-first）")
    lines.append("")
    lines.append("| 语言 | 目标 | 侧 | 纸件优先 | 口译优先 | 差值 | 区间是否重叠 |")
    lines.append("|---|---|---|---|---|---|---|")
    for effect in packet["order_effects"]:
        pf = effect["paper_first"]
        af = effect["audio_first"]
        if effect.get("rate_difference") is None:
            diff_text = effect.get("note", "不可估计")
            overlap_text = "—"
        else:
            diff_text = f"{effect['rate_difference']:+.3f}"
            overlap_text = "重叠" if effect["ci_overlap"] else "不重叠"
        lines.append(
            f"| {effect['language']} | {effect['goal']} | {effect['side']} | "
            f"{_rate_cell(pf)} (n={pf['known']}) | {_rate_cell(af)} (n={af['known']}) | "
            f"{diff_text} | {overlap_text} |"
        )
    lines.append("")
    lines.append(
        "解读：差值为两种顺序下达成率之差；区间重叠表示当前样本不能把顺序效应与随机波动区分，"
        "错发或漏访集中在某一顺序时需结合第 6 节缺口判断。"
    )
    lines.append("")

    lines.append("## 5. 完整批次计数（每侧最少 2 个完整批次）")
    lines.append("")
    lines.append("| 语言 | 侧 | 总批次 | 完整批次 | 漏访批次 | 错发批次 |")
    lines.append("|---|---|---|---|---|---|")
    for item in packet["cluster_counts"]:
        lines.append(
            f"| {item['language']} | {item['side']} | {item['total_clusters']} | "
            f"{item['complete_clusters']} | {', '.join(item['clusters_with_missing']) or '—'} | "
            f"{', '.join(item['clusters_with_wrong_material']) or '—'} |"
        )
    lines.append("")

    lines.append("## 6. 数据问题与可回查记录")
    lines.append("")
    dq = packet["data_quality"]
    lines.append(f"### 6.1 评分异判未定（{len(dq['unresolved_disagreements'])} 条，需补充复核证据）")
    for item in dq["unresolved_disagreements"]:
        lines.append(
            f"- {item['encounter']} / {item['task']}：评分 {', '.join(item['score_ids'])}"
            f"（评分员 {', '.join(item['assessors'])}）"
        )
    lines.append("")
    lines.append(f"### 6.2 已复核决议（{len(dq['reviewed_cells'])} 条，口径已调整）")
    for item in dq["reviewed_cells"]:
        lines.append(
            f"- {item['encounter']} / {item['task']}：复核 {item['review']} 判定 {item['decided']}"
        )
    lines.append("")
    lines.append(f"### 6.3 材料错发（{len(dq['wrong_materials'])} 条，按实际接触单列）")
    for item in dq["wrong_materials"]:
        lines.append(
            f"- {item['encounter']}（{item['ward']}/{item['language']}/{item['cluster']}）："
            f"分派 {item['assigned']}，接触 {item['paper']}/{item['audio']}，"
            f"回述任务为 {item['administered_edition']} 版；{item['issue']}"
        )
    lines.append("")
    lines.append(f"### 6.4 缺回访（{len(dq['followup_gaps'])} 条，区分待回与拒访）")
    for item in dq["followup_gaps"]:
        lines.append(
            f"- {item['encounter']}（{item['ward']}/{item['language']}/{item['cluster']}）："
            f"{item['kind']}，分派 {item['assigned']}，顺序 {item['order']}"
        )
    lines.append("")

    lines.append("## 7. 换版判定（目标独立，不抵消）")
    lines.append("")
    for decision in packet["channel_decisions"]:
        lines.append(
            f"### {decision['language']} / {decision['channel']} — "
            f"{STATUS_LABELS[decision['status']]}"
        )
        lines.append(
            f"- 成套切换：{'是' if decision['requires_pair'] else '否'}；"
            f"禁发新批次：{'是' if decision['banned_for_new'] else '否'}"
        )
        for reason in decision["rationale"]:
            lines.append(f"- {reason}")
        if decision["goal_checks"]:
            lines.append("")
            lines.append("| 目标 | 可比性 | 旧版 | 新版 | 下降 | 批次(旧/新) | 结论 |")
            lines.append("|---|---|---|---|---|---|---|")
            for check in decision["goal_checks"]:
                lines.append(
                    f"| {check['goal']} | {LEVEL_LABELS[check['comparability_level']]} | "
                    f"{_pct(check['old_rate'])} | {_pct(check['new_rate'])} "
                    f"({_pct(check['new_ci_low'])}–{_pct(check['new_ci_high'])}) | "
                    f"{_pct(check['decrease'])} | {check['old_complete_clusters']}/"
                    f"{check['new_complete_clusters']} | {'通过' if check['passed'] else '不通过'} |"
                )
            for check in decision["goal_checks"]:
                for blocker in check["blockers"]:
                    lines.append(f"  - 阻断：{check['goal']} — {blocker}")
                for gap in check["evidence_gaps"]:
                    lines.append(f"  - 证据缺口：{check['goal']} — {gap}")
        if decision["followup_actions"]:
            lines.append("")
            lines.append("下轮补问/核查：")
            for action in decision["followup_actions"]:
                target = action["encounter"] or "跨批次"
                lines.append(f"- [{action['type']}] {target}：{action['check']}")
        lines.append("")

    lines.append("## 8. 病区交接与可投放组合")
    lines.append("")
    for status, rows in packet["scope_summary"].items():
        lines.append(f"### {STATUS_LABELS[status]}（{len(rows)} 个组合）")
        for row in rows:
            lines.append(
                f"- {row['language']} {row['channel']}（成套={row['requires_pair']}，"
                f"禁新发={row['banned_for_new']}）：{row['rationale'][0] if row['rationale'] else ''}"
            )
        lines.append("")
    lines.append("### 在院批次交接")
    for item in packet["ward_handoffs"]:
        lines.append(
            f"- {item['handoff']} {item['ward']}/{item['language']}（{item['encounter']}）："
            f"手持 {item['paper_held']} 纸件，口译完成={item['audio_complete']}，"
            f"继续组合={item['continue_combo']}；{item['note']}"
        )
    lines.append("")
    lines.append("---")
    lines.append(
        "服务台逐批次证据见 service_desk.jsonl；全部速率、区间与判定明细见 review_packet.json。"
    )
    return "\n".join(lines) + "\n"

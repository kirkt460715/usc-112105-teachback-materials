"""命令行入口：一轮回访资料到齐后生成完整换版依据。

用法：
    python3 run_review.py --data data --output outputs --review-date 2026-11-22
    python3 run_review.py lookup B013 --output outputs
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from review.comparability import evaluate_comparability
from review.dataio import DataError, load_tables
from review.decision import decide_channels
from review.evidence import build_evidence
from review.handoff import build_handoffs, build_service_desk
from review.reconcile import resolve_task_cells
from review.report import build_packet, write_outputs


def run(data_dir: Path, output_dir: Path, review_date: str) -> int:
    tables = load_tables(data_dir)
    reconciled = resolve_task_cells(tables)
    comparability = evaluate_comparability(tables)
    bundle = build_evidence(tables, reconciled)
    decisions = decide_channels(tables, bundle, comparability, review_date)
    handoffs = build_handoffs(tables, decisions, review_date)
    service_desk = build_service_desk(
        tables, reconciled, bundle, decisions, review_date
    )
    packet = build_packet(
        tables,
        reconciled,
        bundle,
        comparability,
        decisions,
        handoffs,
        review_date,
    )
    json_path, md_path, desk_path = write_outputs(packet, service_desk, output_dir)

    summary = {
        "review_date": review_date,
        "encounters": len(tables.dispatch),
        "observed": sum(1 for row in tables.dispatch if row["followup"] == "observed"),
        "unresolved_disagreements": len(reconciled.unresolved_disagreements),
        "wrong_materials": len(bundle.wrong_materials),
        "followup_gaps": len(bundle.followup_gaps),
        "outputs": [str(json_path), str(md_path), str(desk_path)],
        "channel_status": {
            f"{d.language}/{d.channel}": d.status for d in decisions
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def lookup(encounter: str, output_dir: Path) -> int:
    desk_path = output_dir / "service_desk.jsonl"
    if not desk_path.exists():
        print("请先运行整轮审订生成 outputs/service_desk.jsonl", file=sys.stderr)
        return 2
    for line in desk_path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record["encounter"] == encounter:
            print(json.dumps(record, ensure_ascii=False, indent=2))
            return 0
    print(f"未找到出院批次 {encounter}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="出院说明换版审订流水线")
    sub = parser.add_subparsers(dest="command")

    run_parser = sub.add_parser("run", help="运行整轮审订并生成全部输出")
    run_parser.add_argument("--data", type=Path, default=Path("data"))
    run_parser.add_argument("--output", type=Path, default=Path("outputs"))
    run_parser.add_argument("--review-date", default="2026-11-22")

    lookup_parser = sub.add_parser("lookup", help="服务台按出院批次查询")
    lookup_parser.add_argument("encounter")
    lookup_parser.add_argument("--output", type=Path, default=Path("outputs"))

    args = parser.parse_args(argv)
    if args.command == "lookup":
        return lookup(args.encounter, args.output)
    try:
        return run(args.data, args.output, args.review_date)
    except DataError as error:
        print(f"资料校验失败：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

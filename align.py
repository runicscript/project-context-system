"""对齐机器人入口。

用法：
    python3 align.py                # 单次运行：算一遍并写回飞书
    python3 align.py --dry-run      # 只算并打印，不写回、不发群提醒
    python3 align.py --loop 60      # 每 60 分钟自动跑一次（Ctrl+C 停止）
"""

from __future__ import annotations

import argparse
import sys
import time

from aligner import (DESIGN, DOC, FACT, STATUS_ALIGNED, STATUS_INVALID,
                     STATUS_PENDING, AlignResult, Record, compute_all)
import config
from config import (F_DESIGN_DEP_DOCS, F_DESIGN_DEP_FACTS, F_DESIGN_LINK,
                    F_DESIGN_NAME, F_DOC_DEP_FACTS, F_DOC_LINK, F_DOC_TITLE,
                    F_FACT_DESC, F_FACT_ID, F_FACT_SOURCE, F_FACT_SPEAKER,
                    F_FACT_STATUS)
from feishu_client import FeishuClient, FeishuError
from writeback import (F_CHECK, F_REASON, F_SNAPSHOT, F_STATUS, diff_fields,
                       flat_text, link_ids, parse_snapshot, url_text)

ICON = {STATUS_ALIGNED: "✅", STATUS_PENDING: "⚠️ ", STATUS_INVALID: "❌"}


def build_record(table: str, item: dict) -> Record:
    """把多维表格的一条原始记录归一化成算法要用的 Record。"""
    f = item.get("fields") or {}
    rid = item["record_id"]

    if table == FACT:
        fact_id = flat_text(f.get(F_FACT_ID)).strip()
        desc = flat_text(f.get(F_FACT_DESC))
        source = flat_text(f.get(F_FACT_SOURCE))
        speaker = flat_text(f.get(F_FACT_SPEAKER))
        return Record(
            table=FACT,
            record_id=rid,
            title=desc,
            display_id=fact_id,  # 亮灯原因读作「F-003《通用基布判定…》已废弃」
            extra="｜".join(x for x in (source, speaker) if x),
            status=flat_text(f.get(F_FACT_STATUS)) or None,
        )

    if table == DOC:
        return Record(
            table=DOC,
            record_id=rid,
            title=flat_text(f.get(F_DOC_TITLE)),
            link=url_text(f.get(F_DOC_LINK)),
            status=flat_text(f.get(F_STATUS)) or None,
            deps=link_ids(f.get(F_DOC_DEP_FACTS)),
            snapshot=parse_snapshot(f.get(F_SNAPSHOT)),
            confirm_checked=bool(f.get(F_CHECK)),
            stored_reason=flat_text(f.get(F_REASON)),
        )

    return Record(
        table=DESIGN,
        record_id=rid,
        title=flat_text(f.get(F_DESIGN_NAME)),
        link=url_text(f.get(F_DESIGN_LINK)),
        status=flat_text(f.get(F_STATUS)) or None,
        deps=link_ids(f.get(F_DESIGN_DEP_DOCS)) + link_ids(f.get(F_DESIGN_DEP_FACTS)),
        snapshot=parse_snapshot(f.get(F_SNAPSHOT)),
        confirm_checked=bool(f.get(F_CHECK)),
        stored_reason=flat_text(f.get(F_REASON)),
    )


def fetch_all_records(client: FeishuClient) -> list[Record]:
    table_ids = config.table_ids()
    records: list[Record] = []
    for table, tid in table_ids.items():
        items = client.list_records(tid)
        print(f"  读取 {table} 表：{len(items)} 条")
        records.extend(build_record(table, it) for it in items)
    return records


def run_once(client: FeishuClient, dry_run: bool = False) -> dict:
    """跑一轮：读 → 算 → 写回。返回统计摘要。"""
    print(f"\n== {time.strftime('%Y-%m-%d %H:%M:%S')} 开始对齐检查 ==")
    records = fetch_all_records(client)
    results = compute_all(records)

    writes: list[tuple[Record, AlignResult, dict]] = []
    for rec, res in zip((r for r in records if r.table != FACT), results):
        fields = diff_fields(rec, res)
        if fields:
            writes.append((rec, res, fields))

    # 打印报告
    counts = {STATUS_ALIGNED: 0, STATUS_PENDING: 0, STATUS_INVALID: 0}
    for res in results:
        counts[res.status] += 1
        mark = "*" if any(w[0].record_id == res.record_id for w in writes) else " "
        print(f" {mark}{ICON[res.status]} [{res.status}] {res.title}"
              + (f" —— {res.reason_text}" if res.reason_text else ""))

    facts = [r for r in records if r.table == FACT]
    if facts:
        print(" 业务事实（人工维护，机器人不改）：")
        for f in facts:
            print(f"    · [{f.status or '未设置'}] {f.title}")

    # 写回
    table_ids = config.table_ids()
    errors = 0
    if dry_run:
        print(f" --dry-run：{len(writes)} 条需要写回，已跳过")
    else:
        for rec, res, fields in writes:
            try:
                client.update_record(table_ids[rec.table], rec.record_id, fields)
                print(f"  已写回《{rec.title}》：{', '.join(fields)}")
            except FeishuError as exc:
                errors += 1
                print(f"  ⚠️ 写回《{rec.title}》失败：{exc}")

    summary = {
        "total": len(results),
        "aligned": counts[STATUS_ALIGNED],
        "pending": counts[STATUS_PENDING],
        "invalid": counts[STATUS_INVALID],
        "writes": len(writes),
        "errors": errors,
        "results": results,
    }
    print(f"== 完成：共 {summary['total']} 条 → "
          f"✅{summary['aligned']} / ⚠️{summary['pending']} / "
          f"❌{summary['invalid']}，写回 {summary['writes']} 条 ==")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="项目上下文对齐机器人")
    parser.add_argument("--loop", type=int, metavar="分钟",
                        help="定时循环模式：每 N 分钟跑一次")
    parser.add_argument("--dry-run", action="store_true",
                        help="只计算和打印，不写回飞书、不发群提醒")
    parser.add_argument("--no-notify", action="store_true",
                        help="本次不发群提醒")
    args = parser.parse_args()

    conf = config.feishu_conf()
    client = FeishuClient(conf["app_id"], conf["app_secret"], conf["base_token"])

    if args.loop:
        print(f"进入循环模式：每 {args.loop} 分钟跑一次，Ctrl+C 停止")
        while True:
            try:
                summary = run_once(client, dry_run=False)
                if not args.no_notify:
                    notify_maybe(summary)
            except FeishuError as exc:
                print(f"⚠️ 本轮失败：{exc}", file=sys.stderr)
            try:
                time.sleep(args.loop * 60)
            except KeyboardInterrupt:
                print("\n已停止")
                return
    else:
        summary = run_once(client, dry_run=args.dry_run)
        if not args.dry_run:
            notify_maybe(summary)


def notify_maybe(summary: dict) -> None:
    """有待核对或已失效时，往群 webhook 发一条摘要（失败不影响主流程）。"""
    webhook = config.webhook_url()
    if not webhook:
        return
    if summary["pending"] == 0 and summary["invalid"] == 0:
        return
    try:
        from notify import send_summary
        send_summary(webhook, summary)
    except Exception as exc:  # noqa: BLE001 提醒失败不影响主流程
        print(f"  ⚠️ 群提醒发送失败：{exc}")


if __name__ == "__main__":
    main()

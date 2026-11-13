"""群提醒：把对齐摘要发到飞书群的自定义机器人 webhook。"""

from __future__ import annotations

import requests

from aligner import STATUS_INVALID, STATUS_PENDING

TIMEOUT = 10


def build_summary_text(summary: dict) -> str:
    lines = [
        "【上下文对齐报告】",
        f"共 {summary['total']} 条：✅已对齐 {summary['aligned']}｜"
        f"⚠️待核对 {summary['pending']}｜❌已失效 {summary['invalid']}",
    ]
    pending = [r for r in summary["results"] if r.status == STATUS_PENDING]
    invalid = [r for r in summary["results"] if r.status == STATUS_INVALID]
    if invalid:
        lines.append("\n❌ 已失效（依据的事实被推翻，需重新设计）：")
        lines += [f"{i}. 《{r.title}》{r.reason_text}"
                  for i, r in enumerate(invalid, 1)]
    if pending:
        lines.append("\n⚠️ 待核对（上游有变化，请核对后勾选「已核对完毕」）：")
        lines += [f"{i}. 《{r.title}》{r.reason_text}"
                  for i, r in enumerate(pending, 1)]
    return "\n".join(lines)


def send_summary(webhook: str, summary: dict) -> None:
    """发到飞书群；失败只打印警告，绝不让主流程报错。"""
    text = build_summary_text(summary)
    try:
        resp = requests.post(
            webhook,
            json={"msg_type": "text", "content": {"text": text}},
            timeout=TIMEOUT,
        ).json()
        if resp.get("code") not in (0, None):
            print(f"  ⚠️ 群机器人返回错误：{resp.get('msg')}")
    except requests.RequestException as exc:
        print(f"  ⚠️ 群提醒发送失败：{exc}")

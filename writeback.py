"""写回与字段值解析的纯函数（不含任何网络调用、不读凭证）。

合并自两处：
- Grokbot 本地版 writeback.py（diff_fields / parse_snapshot / flat_text）
- zcode 原 feishu_client.py 的 url_text / link_ids

align.py 和 feishu_client.py 都从这里 import，保证纯函数只有一份实现。
"""

from __future__ import annotations

import json

from aligner import AlignResult, Record

# 投影表字段名（机器人写的四个字段 + 人工勾选框）
F_STATUS = "状态"            # 单选：已对齐 / 待核对 / 已失效（机器人写）
F_REASON = "对齐原因"        # 文本（机器人写）
F_CONFIRMED_AT = "上次核对时间"  # 文本（机器人写）
F_SNAPSHOT = "核对快照"      # 文本，存 JSON（机器人写）
F_CHECK = "已核对完毕"       # 复选框（人工勾选）


def flat_text(value) -> str:
    """文本类字段值 → 纯字符串。兼容 str / 段落列表 / {text:..} 等形态。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("text") or value.get("name") or "")
    if isinstance(value, list):
        return "".join(flat_text(v) for v in value)
    return str(value)


def url_text(value) -> str:
    """超链接字段值 → 链接地址。"""
    if value is None:
        return ""
    if isinstance(value, dict):
        return str(value.get("link") or value.get("text") or "")
    if isinstance(value, list) and value:
        return url_text(value[0])
    return str(value)


def link_ids(value) -> list[str]:
    """关联字段值 → record_id 列表。兼容两种返回形态：
    - 朴素形态：["recA", "recB"]
    - 分组形态（API 建的关联字段实测返回）：[{"record_ids": ["recA"], "table_id": …}]
    """
    if not value or not isinstance(value, list):
        return []
    out: list[str] = []
    for v in value:
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict):
            out.extend(x for x in v.get("record_ids") or [] if isinstance(x, str))
    return out


def parse_snapshot(value) -> dict | None:
    """核对快照字段值 → dict。"""
    if not value:
        return None
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(flat_text(value))
        return parsed if isinstance(parsed, dict) else None
    except (ValueError, TypeError):
        return None


def diff_fields(rec: Record, res: AlignResult) -> dict:
    """计算这条记录需要写回的字段；无需写回则返回空 dict。"""
    fields: dict = {}
    if res.status != rec.status:
        fields[F_STATUS] = res.status
    if res.reason_text != rec.stored_reason:
        fields[F_REASON] = res.reason_text
    if res.snapshot is not None:
        fields[F_SNAPSHOT] = json.dumps(res.snapshot, ensure_ascii=False)
        fields[F_CONFIRMED_AT] = res.snapshot["at"]
    if res.clear_checkbox:
        fields[F_CHECK] = False
    return fields

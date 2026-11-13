"""一键自检：验证 .env 凭证、表结构是否符合要求。

用法：python3 setup_check.py
全部通过后再运行 seed_demo.py / align.py。
"""

from __future__ import annotations

import sys

import config
from config import (DESIGN_FIELDS, DOC_FIELDS, FACT_FIELDS_OPTIONAL,
                    FACT_FIELDS_REQUIRED, F_DESIGN_DEP_DOCS,
                    F_DESIGN_DEP_FACTS, F_DOC_DEP_FACTS)
from feishu_client import FeishuClient, FeishuError

# 关键字段的期望类型码（飞书字段类型）
TYPE_LINK = 18      # 关联
TYPE_SELECT = 3     # 单选
TYPE_CHECKBOX = 7   # 复选框
TYPE_URL = 15       # 超链接
TYPE_ATTACHMENT = 17  # 附件

TYPE_NAMES = {1: "文本", 3: "单选", 5: "日期", 7: "复选框", 11: "人员",
              13: "电话", 15: "超链接", 17: "附件", 18: "关联", 19: "公式",
              20: "双向关联", 21: "自动编号"}

ok = True


def report(passed: bool, message: str) -> None:
    global ok
    if not passed:
        ok = False
    print(("  ✅ " if passed else "  ❌ ") + message)


def warn(message: str) -> None:
    print("  ⚠️  " + message)


def main() -> None:
    print("== 第 1 步：检查 .env 配置项 ==")
    missing = []
    for key in ["FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_BASE_TOKEN",
                "FACT_TABLE_ID", "DOC_TABLE_ID", "DESIGN_TABLE_ID"]:
        value = config.get(key)
        report(bool(value), f"{key} 已填写" if value else f"{key} 未填写")
        if not value:
            missing.append(key)
    if missing:
        print("\n请先复制 .env.example 为 .env 并填写后重试。")
        sys.exit(1)

    print("\n== 第 2 步：检查应用凭证（获取访问令牌）==")
    conf = config.feishu_conf()
    client = FeishuClient(conf["app_id"], conf["app_secret"], conf["base_token"])
    try:
        client._tenant_token()
        report(True, "凭证有效，成功获取 tenant_access_token")
    except FeishuError as exc:
        report(False, str(exc))
        sys.exit(1)

    print("\n== 第 3 步：检查三张表及其字段 ==")
    table_ids = config.table_ids()
    spec = {
        "fact": ("业务事实", FACT_FIELDS_REQUIRED, FACT_FIELDS_OPTIONAL),
        "doc": ("产品文档", DOC_FIELDS, []),
        "design": ("产品设计", DESIGN_FIELDS, []),
    }
    for table, tid in table_ids.items():
        label, required, optional = spec[table]
        print(f" 表「{label}」({tid})：")
        try:
            fields = client.list_field_names(tid)
        except FeishuError as exc:
            report(False, f"无法读取该表：{exc}")
            continue
        report(True, f"可访问，共 {len(fields)} 个字段")
        for name in required:
            if name in fields:
                report(True, f"字段「{name}」存在（类型：{TYPE_NAMES.get(fields[name], fields[name])}）")
            else:
                report(False, f"缺少必填字段「{name}」，请按 README 的字段规格补建")
        for name in optional:
            if name in fields:
                report(True, f"字段「{name}」存在（类型：{TYPE_NAMES.get(fields[name], fields[name])}）")
            else:
                warn(f"建议补建字段「{name}」（v1 可选，不影响跑通）")

        # 关键字段类型抽查
        checks = {
            F_DOC_DEP_FACTS: ("关联", TYPE_LINK),
            F_DESIGN_DEP_DOCS: ("关联", TYPE_LINK),
            F_DESIGN_DEP_FACTS: ("关联", TYPE_LINK),
        }
        for name, (want, code) in checks.items():
            if name in fields and fields[name] != code:
                report(False, f"字段「{name}」应为「{want}」类型，当前不是，请修改字段类型")

    print("\n== 结果 ==")
    if ok:
        print("全部通过 ✅  下一步：python3 seed_demo.py 灌入示例数据，然后 python3 align.py --dry-run")
    else:
        print("存在问题 ❌  请按上面 ❌ 提示修复后重新运行本脚本。")
        sys.exit(1)


if __name__ == "__main__":
    main()

"""配置加载：从项目目录的 .env 读取飞书凭证、表格 ID，并集中定义字段名。"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
ENV_PATH = PROJECT_DIR / ".env"


def _load_env() -> None:
    """极简 .env 解析器：KEY=VALUE，支持 # 注释，不覆盖已有环境变量。"""
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_env()


def get(key: str, default: str = "", required: bool = False) -> str:
    value = os.environ.get(key, default).strip()
    if required and not value:
        raise SystemExit(
            f"缺少配置项 {key}。请在项目目录下创建 .env 文件并填写"
            f"（可复制 .env.example 改名）"
        )
    return value


def feishu_conf() -> dict:
    return {
        "app_id": get("FEISHU_APP_ID", required=True),
        "app_secret": get("FEISHU_APP_SECRET", required=True),
        "base_token": get("FEISHU_BASE_TOKEN", required=True),
    }


def table_ids() -> dict:
    return {
        "fact": get("FACT_TABLE_ID", required=True),
        "doc": get("DOC_TABLE_ID", required=True),
        "design": get("DESIGN_TABLE_ID", required=True),
    }


def webhook_url() -> str:
    return get("FEISHU_WEBHOOK_URL", "")


# ---- 多维表格字段名（在飞书表格里要按这些名字建字段）----

# 业务事实表（事实卡，字段按 2026-11-09 合稿）
F_FACT_ID = "事实ID"         # 文本：F-xxx，永久递增，永不复用
F_FACT_DESC = "一句话陈述"   # 主字段（文本）
F_FACT_STATUS = "状态"       # 单选：现行 / 待核实 / 已废弃（人工维护，机器人不写）
F_FACT_SOURCE = "来源"       # 文本：一手记录位置；禁止指向 PRD
F_FACT_SPEAKER = "发言人"    # 文本：客户或内部谁说的（建议）
F_FACT_CONFIDENCE = "置信度"  # 单选：客户亲口 / 推断 / 待确认（不参与亮灯）
F_FACT_CREATED = "创建日期"  # 文本：YYYY-MM-DD
F_FACT_SUPERSEDES = "supersedes"        # 文本：被本卡取代的旧卡 ID
F_FACT_SUPERSEDED_BY = "superseded_by"  # 文本：取代本卡的新卡 ID
F_FACT_DECISION = "关联决策"  # 文本：D-xxx
F_CHANGED_BY = "变更人"      # 文本：谁执行了修改（人名或 Agent 名），仅追溯用

# 产品文档表
F_DOC_TITLE = "文档标题"     # 主字段（文本）
F_DOC_LINK = "文档链接"      # 超链接
F_DOC_DEP_FACTS = "依赖的事实"  # 关联字段 → 业务事实表

# 产品设计表
F_DESIGN_NAME = "设计名称"   # 主字段（文本）
F_DESIGN_LINK = "原型链接"   # 超链接（Figma 等）
F_DESIGN_FILE = "原型附件"   # 附件
F_DESIGN_DEP_DOCS = "依赖的文档"  # 关联字段 → 产品文档表
F_DESIGN_DEP_FACTS = "依赖的事实"  # 关联字段 → 业务事实表

# 投影表（文档/设计）共用的核对字段，统一定义在 writeback.py，这里引入供 setup_check 等使用
from writeback import F_CHECK, F_CONFIRMED_AT, F_REASON, F_SNAPSHOT, F_STATUS

FACT_FIELDS_REQUIRED = [F_FACT_ID, F_FACT_DESC, F_FACT_STATUS, F_FACT_SOURCE]
FACT_FIELDS_OPTIONAL = [F_FACT_SPEAKER, F_FACT_CONFIDENCE, F_FACT_CREATED,
                        F_FACT_SUPERSEDES, F_FACT_SUPERSEDED_BY, F_FACT_DECISION,
                        F_CHANGED_BY]
DOC_FIELDS = [F_DOC_TITLE, F_DOC_LINK, F_DOC_DEP_FACTS,
              F_STATUS, F_REASON, F_CONFIRMED_AT, F_SNAPSHOT, F_CHECK, F_CHANGED_BY]
DESIGN_FIELDS = [F_DESIGN_NAME, F_DESIGN_LINK, F_DESIGN_FILE,
                 F_DESIGN_DEP_DOCS, F_DESIGN_DEP_FACTS,
                 F_STATUS, F_REASON, F_CONFIRMED_AT, F_SNAPSHOT, F_CHECK, F_CHANGED_BY]

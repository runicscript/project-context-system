"""灌入「通用基布判定」示例（改编自一家纺织企业的真实案例，已匿名），演示完整口径变更剧本。

用法：python3 seed_demo.py
注意：重复运行会重复灌入，请在干净的表格上运行一次即可。

灌入的是阶段 C1（你刚批准 F-007、但投影还挂着旧卡 F-003）：
跑一次 align.py 就能看到 ❌已失效 跨层传播；
之后照 README 的「演示剧本」把三个阶段亲手走一遍。
"""

from __future__ import annotations

import config
from config import (F_CHECK, F_DESIGN_DEP_DOCS, F_DESIGN_NAME, F_DOC_DEP_FACTS,
                    F_DOC_TITLE, F_FACT_CONFIDENCE, F_FACT_DECISION,
                    F_FACT_DESC, F_FACT_ID, F_FACT_SOURCE, F_FACT_SPEAKER,
                    F_FACT_STATUS, F_FACT_SUPERSEDED_BY, F_FACT_SUPERSEDES)
from feishu_client import FeishuClient

F003_TEXT = ("通用基布判定：比对已启用品，客户名=通用基布、编码=XX-000，"
             "机台规格/原料粗细/坯布组织三项完全一致；判定所需数据来自工艺单")
F007_TEXT = ("通用基布判定：比对已启用品，客户名=通用基布、编码=XX-000，"
             "机台规格/原料粗细/坯布组织三项完全一致；判定所需数据引用现行检测报告")


def main() -> None:
    conf = config.feishu_conf()
    tables = config.table_ids()
    client = FeishuClient(conf["app_id"], conf["app_secret"], conf["base_token"])

    print("1/3 写入业务事实（F-003 已被 F-007 取代，对应决策 D-002）…")
    f003 = client.create_record(tables["fact"], {
        F_FACT_ID: "F-003",
        F_FACT_DESC: F003_TEXT,
        F_FACT_STATUS: "已废弃",
        F_FACT_SOURCE: "10-22 产品库讨论（早期稿，来源不合格仅作演示）",
        F_FACT_SPEAKER: "早期稿未记录",
        F_FACT_SUPERSEDED_BY: "F-007",
        F_FACT_DECISION: "D-002",
    })
    print("   已创建 F-003（已废弃）")

    f007 = client.create_record(tables["fact"], {
        F_FACT_ID: "F-007",
        F_FACT_DESC: F007_TEXT,
        F_FACT_STATUS: "现行",
        F_FACT_SOURCE: "10-23 妙记逐字稿 §4",
        F_FACT_SPEAKER: "客户负责人",
        F_FACT_CONFIDENCE: "客户亲口",
        F_FACT_SUPERSEDES: "F-003",
        F_FACT_DECISION: "D-002",
    })
    print("   已创建 F-007（现行，取代 F-003）")

    print("2/3 写入产品文档（此刻仍依赖旧卡 F-003，演示 C1 阶段）…")
    doc_ids = []
    for title in ("PRD 产品库章节", "产品库表单"):
        rid = client.create_record(tables["doc"], {
            F_DOC_TITLE: title,
            F_DOC_DEP_FACTS: [f003],
            F_CHECK: False,
        })
        doc_ids.append(rid)
        print(f"   已创建《{title}》（依赖 F-003）")

    print("3/3 写入产品设计（只依赖文档，演示跨层传播）…")
    client.create_record(tables["design"], {
        F_DESIGN_NAME: "产品库表单原型",
        F_DESIGN_DEP_DOCS: [doc_ids[1]],
        F_CHECK: False,
    })
    print("   已创建《产品库表单原型》（依赖《产品库表单》）")

    print("""
完成 ✅  当前是阶段 C1：口径已批准，投影还没改挂。

接下来照 README「演示剧本」走：
  1. python3 align.py            → 两份文档和原型全部 ❌已失效（C1）
  2. 表格里把两份文档的依赖从 F-003 改挂 F-007，再跑 → ⚠️待核对（C2）
  3. 勾选两份文档的「已核对完毕」，再跑 → 文档 ✅，原型仍 ⚠️；
     再勾原型的「已核对完毕」，再跑 → 全部 ✅（C3）
另可体验阶段 B：把 F-003 改回「待核实」、F-007 也设「待核实」，
  跑一遍 → 全部 ⚠️，且勾了「已核对完毕」也不会入账。""")


if __name__ == "__main__":
    main()

"""bootstrap_bitable.py — 在知识库「测试 Wiki 1」里一键创建测试多维表格。

做什么：
1. 找到名为「测试 Wiki 1」的知识库
2. 创建（或复用同名）多维表格「上下文系统·测试台账」
3. 建三张表和全部字段（含跨表关联字段）
4. 把 app_token / 三个 table_id 写回 .env

可重复运行：表格已存在时直接复用，不会重复创建。
用法：python3 bootstrap_bitable.py
"""

from __future__ import annotations

import requests

import config
from feishu_client import FeishuClient

API = "https://open.feishu.cn/open-apis"
WIKI_NAME = "测试 Wiki 1"
BASE_TITLE = "上下文系统·测试台账"
# 你的飞书租户域名（如 xxx.feishu.cn），填在 .env 的 FEISHU_TENANT_DOMAIN，仅用于最后打印表格地址
TENANT_DOMAIN = config.get("FEISHU_TENANT_DOMAIN", "")

# 投影表（文档/设计）共用的核对字段
from writeback import F_CHECK, F_CONFIRMED_AT, F_REASON, F_SNAPSHOT, F_STATUS


def fail_hints(code: int) -> str:
    if code == 131006:
        return (f"知识库权限不足：请打开知识库「{WIKI_NAME}」→ 右上角「···」→"
                f"「设置」→「成员设置」→ 添加成员 → 搜「应用/机器人」→ "
                f"把本应用机器人加进来并给「可编辑」或「管理员」权限，然后重跑本脚本")
    if code in (91403, 99991672):
        return ("应用未开通对应权限：请到开放平台「权限管理」开通"
                "「知识库 wiki:wiki（读写）」和「多维表格 bitable:app（读写）」，"
                "然后「版本管理与发布」发布新版本后重跑")
    if code == 99991663:
        return "应用身份不能创建知识库（预期内，本脚本只往已有知识库里建节点）"
    return ""


class Api:
    def __init__(self):
        app_id = config.get("FEISHU_APP_ID", required=True)
        app_secret = config.get("FEISHU_APP_SECRET", required=True)
        self._fc = FeishuClient(app_id, app_secret, base_token="")  # 只用它的 token 管理

    def call(self, method: str, path: str, **kw) -> dict:
        resp = requests.request(method, API + path, headers=self._fc._headers(),
                                 timeout=20, **kw).json()
        code = resp.get("code", 0)
        if code != 0:
            hint = fail_hints(code)
            raise SystemExit(f"[失败] {method} {path}\n  code={code}: {resp.get('msg')}"
                             + (f"\n  ▶ {hint}" if hint else ""))
        return resp.get("data") or {}

    def paged(self, path: str, item_key: str = "items") -> list[dict]:
        out, token = [], None
        while True:
            params = {"page_size": 50, **({"page_token": token} if token else {})}
            data = self.call("GET", path, params=params)
            out.extend(data.get(item_key) or [])
            if not data.get("has_more"):
                return out
            token = data.get("page_token")


def _norm(name: str) -> str:
    return name.replace(" ", "").replace("　", "").casefold()


def find_space(api: Api) -> str:
    spaces = api.paged("/wiki/v2/spaces")
    names = [s.get("name", "") for s in spaces]
    for s in spaces:
        if _norm(s.get("name", "")) == _norm(WIKI_NAME):
            print(f"✅ 找到知识库「{s['name']}」：{s['space_id']}")
            return s["space_id"]
    raise SystemExit(
        f"[失败] 知识库列表里没有「{WIKI_NAME}」。当前可见：{names or '（空）'}\n"
        f"  ▶ 若列表为空或不含目标：机器人还没被加进该知识库。打开知识库 → 设置 → "
        f"成员设置 → 添加机器人（本应用），或确认知识库名字一字不差")


def find_or_create_base(api: Api, space_id: str) -> tuple[str, str]:
    """返回 (app_token, node_token)。同名 bitable 节点直接复用。"""
    for node in api.paged(f"/wiki/v2/spaces/{space_id}/nodes"):
        if node.get("title", "").strip() != BASE_TITLE:
            continue
        if node.get("obj_type") != "bitable":
            raise SystemExit(f"[失败] 「{BASE_TITLE}」已存在但不是多维表格，请改名后重跑")
        obj_token = node.get("obj_token") or node.get("obj_id")
        print(f"✅ 复用已存在的多维表格「{BASE_TITLE}」")
        return obj_token, node["node_token"]

    data = api.call("POST", f"/wiki/v2/spaces/{space_id}/nodes",
                    json={"obj_type": "bitable", "node_type": "origin",
                          "node_title": BASE_TITLE})
    node = data["node"]
    obj_token = node.get("obj_token") or node.get("obj_id")
    print(f"✅ 已创建多维表格「{BASE_TITLE}」")
    return obj_token, node["node_token"]


def fact_fields() -> list[dict]:
    return [
        {"field_name": config.F_FACT_DESC, "type": 1},
        {"field_name": config.F_FACT_ID, "type": 1},
        {"field_name": config.F_FACT_STATUS, "type": 3,
         "property": {"options": [{"name": "现行"}, {"name": "待核实"},
                                  {"name": "已废弃"}]}},
        {"field_name": config.F_FACT_SOURCE, "type": 1},
        {"field_name": config.F_FACT_SPEAKER, "type": 1},
        {"field_name": config.F_FACT_CONFIDENCE, "type": 3,
         "property": {"options": [{"name": "客户亲口"}, {"name": "推断"},
                                  {"name": "待确认"}]}},
        {"field_name": config.F_FACT_CREATED, "type": 1},
        {"field_name": config.F_FACT_SUPERSEDES, "type": 1},
        {"field_name": config.F_FACT_SUPERSEDED_BY, "type": 1},
        {"field_name": config.F_FACT_DECISION, "type": 1},
    ]


def check_fields() -> list[dict]:
    return [
        {"field_name": F_STATUS, "type": 3,
         "property": {"options": [{"name": "已对齐"}, {"name": "待核对"},
                                  {"name": "已失效"}]}},
        {"field_name": F_REASON, "type": 1},
        {"field_name": F_CONFIRMED_AT, "type": 1},
        {"field_name": F_SNAPSHOT, "type": 1},
        {"field_name": F_CHECK, "type": 7},
    ]


def create_table(api: Api, app_token: str, name: str, fields: list[dict]) -> str:
    data = api.call("POST", f"/bitable/v1/apps/{app_token}/tables",
                    json={"table": {"name": name, "fields": fields}})
    tid = data["table_id"]
    print(f"  ✅ 表「{name}」：{tid}")
    return tid


def add_link_field(api: Api, app_token: str, table_id: str,
                   field_name: str, target_table_id: str) -> None:
    api.call("POST", f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
             json={"field_name": field_name, "type": 18,
                   "property": {"table_id": target_table_id}})
    print(f"  ✅ 关联字段「{field_name}」→ 目标表 {target_table_id}")


def update_env(app_token: str, tids: dict[str, str]) -> None:
    updates = {
        "FEISHU_BASE_TOKEN": app_token,
        "FACT_TABLE_ID": tids["fact"],
        "DOC_TABLE_ID": tids["doc"],
        "DESIGN_TABLE_ID": tids["design"],
    }
    lines = config.ENV_PATH.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.startswith("#") else ""
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    config.ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("✅ 已把 app_token 和三个表 ID 写回 .env")


def main() -> None:
    api = Api()
    space_id = find_space(api)
    app_token, node_token = find_or_create_base(api, space_id)

    # 已建过表就跳过（复用 .env 或查现有表）
    existing = api.paged(f"/bitable/v1/apps/{app_token}/tables")
    if len(existing) >= 3:
        print(f"ℹ️  表格已有 {len(existing)} 张表，跳过建表（如需重建请手动删除表格后重跑）")
        names = {t["name"]: t["table_id"] for t in existing}
        missing = [n for n in ("业务事实", "产品文档", "产品设计") if n not in names]
        if missing:
            raise SystemExit(f"[失败] 缺少这些表：{missing}，请删除整个多维表格后重跑本脚本")
        tids = {"fact": names["业务事实"], "doc": names["产品文档"],
                "design": names["产品设计"]}
        update_env(app_token, tids)
    else:
        print("开始建三张表…")
        fact_tid = create_table(api, app_token, "业务事实", fact_fields())
        doc_tid = create_table(api, app_token, "产品文档",
                               [{"field_name": config.F_DOC_TITLE, "type": 1},
                                {"field_name": config.F_DOC_LINK, "type": 15}]
                               + check_fields())
        design_tid = create_table(api, app_token, "产品设计",
                                  [{"field_name": config.F_DESIGN_NAME, "type": 1},
                                   {"field_name": config.F_DESIGN_LINK, "type": 15},
                                   {"field_name": config.F_DESIGN_FILE, "type": 17}]
                                  + check_fields())
        print("建关联字段…")
        add_link_field(api, app_token, doc_tid, config.F_DOC_DEP_FACTS, fact_tid)
        add_link_field(api, app_token, design_tid, config.F_DESIGN_DEP_DOCS, doc_tid)
        add_link_field(api, app_token, design_tid, config.F_DESIGN_DEP_FACTS, fact_tid)
        update_env(app_token, {"fact": fact_tid, "doc": doc_tid, "design": design_tid})

    print(f"""
全部完成 ✅
多维表格地址：https://{TENANT_DOMAIN}/wiki/{node_token}
下一步：
  1. python3 setup_check.py   自检字段
  2. python3 seed_demo.py     灌入通用基布示例（阶段 C1）
  3. python3 align.py --dry-run  看机器人怎么算（先不写回）
  4. python3 align.py         正式运行
""")


if __name__ == "__main__":
    main()

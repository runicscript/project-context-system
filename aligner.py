"""对齐算法：纯函数实现，不涉及任何网络请求。

移植自 zcode「项目上下文管理系统」/aligner.py（思路来自 Fieldstation），
按 v1 合稿改了事实状态口径：

事实卡状态（人维护，机器人不改）：
- 现行   （原 zcode：有效）
- 待核实 （原 zcode：存疑）——新卡默认；冲突时旧卡也打成待核实
- 已废弃 （原 zcode：已失效）——被新卡取代

投影（文档 / 设计）对齐状态（机器人算）：
- 已对齐：所有上游内容与上次核对时一致，且没有待核实事实
- 待核对：上游有更新 / 上游待核实 / 从未核对 / 依赖结构变化 / 成环 / 上游丢失
- 已失效：依据的事实中存在"已废弃"（跨层传播）
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field

# ---- 常量 ----
FACT = "fact"        # 业务事实卡
DOC = "doc"          # 产品文档（投影）
DESIGN = "design"    # 产品设计 / 原型（投影）

FACT_STATUS_CURRENT = "现行"
FACT_STATUS_UNVERIFIED = "待核实"
FACT_STATUS_DEPRECATED = "已废弃"
FACT_STATUSES = (FACT_STATUS_CURRENT, FACT_STATUS_UNVERIFIED, FACT_STATUS_DEPRECATED)

# 旧口径（zcode 原版 / 旧飞书表的单选值）→ 新口径，兼容读取
LEGACY_FACT_STATUS = {
    "有效": FACT_STATUS_CURRENT,
    "存疑": FACT_STATUS_UNVERIFIED,
    "已失效": FACT_STATUS_DEPRECATED,
}

STATUS_ALIGNED = "已对齐"
STATUS_PENDING = "待核对"
STATUS_INVALID = "已失效"

SNAPSHOT_VERSION = 1


def normalize_fact_status(value: str | None) -> str:
    """把事实卡状态归一到 现行 / 待核实 / 已废弃。

    与 zcode 的差异：zcode 把空值或未知值当作"有效"放行；这里一律按
    "待核实"处理——没被批准为现行的卡，不能让下游显示已对齐。
    """
    v = (value or "").strip()
    v = LEGACY_FACT_STATUS.get(v, v)
    return v if v in FACT_STATUSES else FACT_STATUS_UNVERIFIED


@dataclass
class Record:
    """从多维表格读出的一条记录（已归一化）。"""

    table: str                    # FACT / DOC / DESIGN
    record_id: str
    title: str                    # 事实：一句话陈述；文档/设计：标题
    display_id: str = ""          # 人类可读编号（事实的 F-xxx）；亮灯原因用它替代内部 record_id
    link: str = ""                # 文档链接 / 原型链接，参与内容指纹
    extra: str = ""               # 其他参与指纹的文本（如事实的"来源"）
    status: str | None = None     # 事实：现行/待核实/已废弃；文档/设计：当前存储的状态
    deps: list[str] = field(default_factory=list)  # 直接上游 record_id 列表
    snapshot: dict | None = None  # 核对快照（上次核对时所有上游的内容指纹）
    confirm_checked: bool = False  # 人工勾选的"已核对完毕"复选框
    stored_reason: str = ""       # 当前存储的"对齐原因"，用于判断是否需要写回


@dataclass
class AlignResult:
    record_id: str
    title: str
    status: str
    reasons: list[str]
    snapshot: dict | None = None   # 非 None 表示需要写回新快照（核对通过）
    clear_checkbox: bool = False   # True 表示核对已入账，需要取消勾选

    @property
    def reason_text(self) -> str:
        return "；".join(self.reasons)


def content_hash(rec: Record) -> str:
    """一条记录的"内容指纹"：内容或依赖结构变了，指纹就变。

    只包含内容性字段（table/title/link/extra/deps）。不包含：
    status、stored_reason、snapshot、confirm_checked——这些是机器人写的
    或人工勾选的，放进来会让机器人每写一次就把下游误报为"有更新"。
    事实状态变化不靠指纹，由规则 2（已废弃）和规则 6（待核实）单独处理。
    """
    raw = "|".join(
        [rec.table, rec.title, rec.link, rec.extra, ",".join(sorted(rec.deps))]
    )
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


# ---- 依赖图分析 ----

def _analyze_closure(rec: Record, m: dict[str, Record]):
    """从 rec 出发沿依赖边向上遍历。

    返回 (upstream_ids, fact_ids, cycle, missing)：
    - upstream_ids：所有传递上游的 record_id（不含 rec 自己）
    - fact_ids：其中属于业务事实的
    - cycle：成环时的环路径（如 [A, B, A]），无环为 None
    - missing：声明了但在记录集中找不到的上游 id（多半已被删除）
    """
    missing: set[str] = set()
    cycle: list[str] | None = None

    done: dict[str, tuple[set[str], set[str]]] = {}
    path: list[str] = []
    path_index: dict[str, int] = {}

    def dfs(cur: str) -> tuple[set[str], set[str]]:
        nonlocal cycle
        if cycle is not None:
            return set(), set()
        if cur in path_index:  # 走回了当前路径上的节点 → 成环
            cycle = path[path_index[cur]:] + [cur]
            return set(), set()
        if cur in done:
            return done[cur]
        node = m.get(cur)
        if node is None:
            missing.add(cur)
            return set(), set()
        if node.table == FACT:
            return {cur}, {cur}

        path_index[cur] = len(path)
        path.append(cur)
        u: set[str] = set()
        f: set[str] = set()
        for dep in node.deps:
            du, df = dfs(dep)
            u |= du
            u.add(dep)
            f |= df
        path.pop()
        del path_index[cur]
        done[cur] = (u, f)
        return u, f

    upstream, fact_ids = dfs(rec.record_id)
    for dep in rec.deps:
        upstream.add(dep)
    upstream.discard(rec.record_id)
    fact_ids.discard(rec.record_id)
    return upstream, fact_ids, cycle, missing


def _title(m: dict[str, Record], rid: str) -> str:
    node = m.get(rid)
    return node.title if node else rid


def _fact_label(m: dict[str, Record], rid: str) -> str:
    node = m.get(rid)
    if node is None:
        return rid
    prefix = (node.display_id or "").strip() or rid
    return f"{prefix}《{_title(m, rid)}》"


# ---- 状态计算 ----

def compute_all(records: list[Record]) -> list[AlignResult]:
    """对每条文档/设计计算对齐状态。业务事实的状态由人工维护，不参与计算。"""
    m = {r.record_id: r for r in records}
    return [_compute_one(r, m) for r in records if r.table != FACT]


def _compute_one(rec: Record, m: dict[str, Record]) -> AlignResult:
    upstream, fact_ids, cycle, missing = _analyze_closure(rec, m)

    def stamp() -> dict:
        """核对通过时的新快照：记住当前所有上游的内容指纹。"""
        return {
            "v": SNAPSHOT_VERSION,
            "at": time.strftime("%Y-%m-%d %H:%M"),
            "ids": sorted(upstream),
            "hashes": {
                rid: content_hash(m[rid]) for rid in upstream if rid in m
            },
        }

    fact_status = {f: normalize_fact_status(m[f].status) for f in fact_ids}

    # 1. 依赖成环：图不可信，先修复依赖
    if cycle:
        chain = " → ".join(_title(m, rid) for rid in cycle)
        return AlignResult(
            rec.record_id, rec.title, STATUS_PENDING,
            [f"依赖关系成环（{chain}），请先修复依赖结构"],
        )

    # 2. 任一传递上游事实已废弃 → 已失效（唯一的"红牌"，跨层传播）
    deprecated = [f for f in sorted(fact_ids) if fact_status[f] == FACT_STATUS_DEPRECATED]
    if deprecated:
        return AlignResult(
            rec.record_id, rec.title, STATUS_INVALID,
            [f"依据的事实{_fact_label(m, f)}已废弃" for f in deprecated],
        )

    reasons: list[str] = []

    # 3. 上游丢失
    for rid in sorted(missing):
        reasons.append(f"依赖的上游记录（{rid}）不存在或已被删除")

    unverified = [f for f in sorted(fact_ids) if fact_status[f] == FACT_STATUS_UNVERIFIED]

    # 4. 人工勾选了"已核对完毕" → 尝试核对入账
    #    前提：没有上游丢失、没有待核实事实（已废弃在上面已被拦住）
    if rec.confirm_checked and not missing:
        if not unverified:
            return AlignResult(
                rec.record_id, rec.title, STATUS_ALIGNED,
                ["已核对，与上游当前内容一致"],
                snapshot=stamp(),
                clear_checkbox=True,
            )
        # 待核实事实未决：不入账、不写快照，复选框保留，等你拍板后下一轮自动入账
        reasons.append("已勾选核对，但上游有待核实事实，暂不入账")

    # 5. 与上次核对快照比较
    if not rec.snapshot:
        reasons.append("尚未进行过首次核对")
    else:
        snap_ids = set(rec.snapshot.get("ids", []))
        snap_hashes = rec.snapshot.get("hashes", {})
        if snap_ids != upstream:
            reasons.append("依赖结构有变化（新增或移除了上游）")
        for rid in sorted(upstream & snap_ids):
            if rid in m and content_hash(m[rid]) != snap_hashes.get(rid):
                reasons.append(f"上游《{_title(m, rid)}》内容在上次核对后有更新")

    # 6. 待核实事实传播：即使旧快照完全匹配，也不能显示已对齐
    for f in unverified:
        raw = (m[f].status or "").strip()
        note = "" if LEGACY_FACT_STATUS.get(raw, raw) == FACT_STATUS_UNVERIFIED \
            else f"（状态值「{raw or '空'}」未识别，按待核实处理）"
        reasons.append(f"依据的事实{_fact_label(m, f)}当前待核实{note}")

    status = STATUS_PENDING if reasons else STATUS_ALIGNED
    return AlignResult(rec.record_id, rec.title, status, reasons)

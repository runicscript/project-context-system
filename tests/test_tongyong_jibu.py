"""「通用基布判定」口径变更演示（改编自一家纺织企业的真实案例，已匿名）：
F-003（工艺单）→ F-007（现行检测报告）。

投影：
- d-prd   PRD 产品库章节        依据 F-003（变更后改挂 F-007）
- d-form  产品库表单            依据 F-003（变更后改挂 F-007）
- g-form  产品库表单原型        依赖 d-form（只通过文档间接依赖事实）

阶段：
- A   变更前：F-003 现行，投影依赖 F-003 且已核对 → 已对齐
- B   发现冲突、候选卡写入：F-003、F-007 都待核实 → 下游待核对；勾选也不入账
- C1  你批准：F-003 已废弃、F-007 现行，投影仍挂 F-003 → 已失效（设计经文档传播）
- C2  投影改挂 F-007 但还没核对 → 待核对
- C3  改完后勾"已核对完毕" → 已对齐 + 新快照 + 清勾选
"""

from __future__ import annotations

import pytest

from aligner import (DESIGN, DOC, FACT, STATUS_ALIGNED, STATUS_INVALID,
                     STATUS_PENDING, AlignResult, Record, compute_all)
from writeback import F_CHECK, F_SNAPSHOT, F_STATUS, diff_fields

F003_TEXT = ("通用基布判定：比对已启用品，客户名=通用基布、编码=XX-000，"
             "机台规格/原料粗细/坯布组织三项完全一致；判定所需数据来自工艺单")
F007_TEXT = ("通用基布判定：比对已启用品，客户名=通用基布、编码=XX-000，"
             "机台规格/原料粗细/坯布组织三项完全一致；判定所需数据引用现行检测报告")

PROJECTIONS = ("d-prd", "d-form", "g-form")


def build(f003="现行", f007=None, doc_fact="F-003") -> dict[str, Record]:
    recs = [
        Record(FACT, "F-003", F003_TEXT, extra="10-22 产品库讨论（早期稿）", status=f003),
        Record(DOC, "d-prd", "PRD 产品库章节", link="feishu://prd#产品库", deps=[doc_fact]),
        Record(DOC, "d-form", "产品库表单", link="feishu://prd#产品库表单", deps=[doc_fact]),
        Record(DESIGN, "g-form", "产品库表单原型", link="proto://产品库表单", deps=["d-form"]),
    ]
    if f007 is not None:
        recs.insert(1, Record(FACT, "F-007", F007_TEXT,
                              extra="10-23 妙记逐字稿 §4；客户负责人；supersedes F-003",
                              status=f007))
    return {r.record_id: r for r in recs}


def run(m: dict[str, Record]) -> dict[str, AlignResult]:
    return {r.record_id: r for r in compute_all(list(m.values()))}


def apply_writeback(m: dict[str, Record], res: dict[str, AlignResult]) -> None:
    """模拟机器人写回：状态、原因、快照、清勾选。"""
    for rid, r in res.items():
        rec = m[rid]
        rec.status = r.status
        rec.stored_reason = r.reason_text
        if r.snapshot is not None:
            rec.snapshot = r.snapshot
        if r.clear_checkbox:
            rec.confirm_checked = False


def check_all(m, ids=PROJECTIONS):
    for rid in ids:
        m[rid].confirm_checked = True


def confirm_and_record(m):
    """按层次核对：先文档，再设计（设计的快照包含文档指纹）。"""
    check_all(m, ("d-prd", "d-form"))
    apply_writeback(m, run(m))
    check_all(m, ("g-form",))
    apply_writeback(m, run(m))


@pytest.fixture
def aligned_baseline():
    """阶段 A 的终态：F-003 现行，三个投影都已核对入账。"""
    m = build()
    confirm_and_record(m)
    return m


# ---- A ----

def test_A_current_fact_checked_is_aligned():
    m = build()
    check_all(m, ("d-prd", "d-form"))
    res = run(m)
    for rid in ("d-prd", "d-form"):
        assert res[rid].status == STATUS_ALIGNED
        assert res[rid].snapshot["ids"] == ["F-003"]
        assert res[rid].clear_checkbox is True
    apply_writeback(m, res)

    check_all(m, ("g-form",))
    res = run(m)
    assert res["g-form"].status == STATUS_ALIGNED
    assert res["g-form"].snapshot["ids"] == ["F-003", "d-form"]
    apply_writeback(m, res)

    # 写回之后再跑：稳定已对齐（指纹不含机器人字段）。
    # zcode 原行为：核对入账那轮原因写的是「已核对，与上游当前内容一致」，
    # 下一轮原因变空，会多写一次「对齐原因」，之后收敛为零写回。
    res = run(m)
    for rid in PROJECTIONS:
        assert res[rid].status == STATUS_ALIGNED
    apply_writeback(m, res)
    res = run(m)
    for rid in PROJECTIONS:
        assert res[rid].status == STATUS_ALIGNED
        assert diff_fields(m[rid], res[rid]) == {}


# ---- B ----

def test_B_both_unverified_downstream_pending_even_with_matching_snapshot(aligned_baseline):
    m = aligned_baseline
    m["F-003"].status = "待核实"
    m["F-007"] = Record(FACT, "F-007", F007_TEXT,
                        extra="10-23 妙记逐字稿 §4；客户负责人；supersedes F-003",
                        status="待核实")
    res = run(m)
    for rid in PROJECTIONS:
        # 旧快照与当前内容完全一致（F-003 陈述没动），但仍然不能显示已对齐
        assert res[rid].status == STATUS_PENDING, rid
        assert any("F-003" in r and "待核实" in r for r in res[rid].reasons)
        assert not any("有更新" in r for r in res[rid].reasons)


def test_B_checking_does_not_record(aligned_baseline):
    m = aligned_baseline
    m["F-003"].status = "待核实"
    m["F-007"] = Record(FACT, "F-007", F007_TEXT, status="待核实")
    old_snaps = {rid: m[rid].snapshot for rid in PROJECTIONS}
    check_all(m)
    res = run(m)
    for rid in PROJECTIONS:
        assert res[rid].status == STATUS_PENDING
        assert res[rid].snapshot is None          # 不入账
        assert res[rid].clear_checkbox is False   # 勾选保留
        fields = diff_fields(m[rid], res[rid])
        assert F_SNAPSHOT not in fields and F_CHECK not in fields
    apply_writeback(m, res)
    for rid in PROJECTIONS:
        assert m[rid].snapshot == old_snaps[rid]
        assert m[rid].confirm_checked is True

    # 投影已改挂 F-007 也一样：F-007 待核实 → 勾了也不入账
    m["d-prd"].deps = ["F-007"]
    res = run(m)
    assert res["d-prd"].status == STATUS_PENDING and res["d-prd"].snapshot is None


def test_B_rejected_restores_aligned(aligned_baseline):
    """你驳回：F-007 已废弃、F-003 恢复现行 → 未改挂的投影回到已对齐。"""
    m = aligned_baseline
    m["F-003"].status = "待核实"
    m["F-007"] = Record(FACT, "F-007", F007_TEXT, status="待核实")
    apply_writeback(m, run(m))
    m["F-003"].status = "现行"
    m["F-007"].status = "已废弃"
    res = run(m)
    for rid in PROJECTIONS:
        assert res[rid].status == STATUS_ALIGNED


# ---- C ----

def approve(m):
    m["F-003"].status = "已废弃"
    m.setdefault("F-007", Record(FACT, "F-007", F007_TEXT,
                                 extra="10-23 妙记逐字稿 §4；客户负责人；supersedes F-003"))
    m["F-007"].status = "现行"


def test_C1_deprecated_fact_invalidates_projection_and_design(aligned_baseline):
    m = aligned_baseline
    approve(m)
    res = run(m)
    for rid in PROJECTIONS:
        assert res[rid].status == STATUS_INVALID, rid
        assert any("F-003" in r and "已废弃" in r for r in res[rid].reasons)
    # 已失效时勾选也不入账
    check_all(m)
    res = run(m)
    for rid in PROJECTIONS:
        assert res[rid].status == STATUS_INVALID and res[rid].snapshot is None


def test_C2_repointed_but_unchecked_is_pending(aligned_baseline):
    m = aligned_baseline
    approve(m)
    apply_writeback(m, run(m))
    m["d-prd"].deps = ["F-007"]
    m["d-form"].deps = ["F-007"]
    res = run(m)
    for rid in PROJECTIONS:
        assert res[rid].status == STATUS_PENDING, rid
        assert res[rid].snapshot is None
    assert any("依赖结构有变化" in r for r in res["d-prd"].reasons)
    # 设计：上游 d-form 的依赖变了 → 结构变化 + d-form 指纹变化
    assert any("依赖结构有变化" in r for r in res["g-form"].reasons)
    assert any("产品库表单" in r and "有更新" in r for r in res["g-form"].reasons)


def test_C3_checked_after_repoint_is_aligned_with_new_snapshot(aligned_baseline):
    m = aligned_baseline
    old = {rid: m[rid].snapshot for rid in PROJECTIONS}
    approve(m)
    apply_writeback(m, run(m))
    m["d-prd"].deps = ["F-007"]
    m["d-form"].deps = ["F-007"]
    apply_writeback(m, run(m))

    check_all(m, ("d-prd", "d-form"))
    res = run(m)
    for rid in ("d-prd", "d-form"):
        assert res[rid].status == STATUS_ALIGNED
        assert res[rid].clear_checkbox is True
        assert res[rid].snapshot["ids"] == ["F-007"]
        assert res[rid].snapshot != old[rid]
        f = diff_fields(m[rid], res[rid])
        assert f[F_STATUS] == STATUS_ALIGNED and F_SNAPSHOT in f and f[F_CHECK] is False
    # 文档核对完，设计还没核对 → 仍待核对
    assert res["g-form"].status == STATUS_PENDING
    apply_writeback(m, res)

    check_all(m, ("g-form",))
    res = run(m)
    assert res["g-form"].status == STATUS_ALIGNED
    assert res["g-form"].snapshot["ids"] == ["F-007", "d-form"]
    apply_writeback(m, res)

    # 终态稳定：全部已对齐；补写一次空原因后零写回（同 A）
    res = run(m)
    for rid in PROJECTIONS:
        assert res[rid].status == STATUS_ALIGNED
    apply_writeback(m, res)
    res = run(m)
    for rid in PROJECTIONS:
        assert res[rid].status == STATUS_ALIGNED
        assert diff_fields(m[rid], res[rid]) == {}

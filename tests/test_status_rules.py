"""v1 新增的状态口径规则：旧值兼容、空值/未知值保守处理、指纹不含机器人字段。"""

from __future__ import annotations

import pytest

from aligner import (DOC, FACT, STATUS_ALIGNED, STATUS_INVALID, STATUS_PENDING,
                     Record, compute_all, content_hash, normalize_fact_status)
from tests.test_aligner import make_records, result_of, snapshot_for


@pytest.mark.parametrize("raw,expected", [
    ("现行", "现行"), ("待核实", "待核实"), ("已废弃", "已废弃"),
    ("有效", "现行"), ("存疑", "待核实"), ("已失效", "已废弃"),
    (None, "待核实"), ("", "待核实"), ("随便写的", "待核实"), (" 现行 ", "现行"),
])
def test_normalize_fact_status(raw, expected):
    assert normalize_fact_status(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "未知"])
def test_unset_or_unknown_fact_status_blocks_alignment(raw):
    """zcode 把空/未知状态当有效放行；v1 按待核实处理。"""
    recs = make_records(fact_status=raw)
    recs[1].snapshot = snapshot_for(recs, "d1")     # 旧快照完全匹配
    recs[1].status = STATUS_ALIGNED
    doc = result_of(compute_all(recs), "d1")
    assert doc.status == STATUS_PENDING
    assert any("待核实" in r for r in doc.reasons)

    recs[1].confirm_checked = True
    doc = result_of(compute_all(recs), "d1")
    assert doc.status == STATUS_PENDING and doc.snapshot is None
    assert doc.clear_checkbox is False


@pytest.mark.parametrize("raw,expected", [
    ("有效", STATUS_ALIGNED), ("存疑", STATUS_PENDING), ("已失效", STATUS_INVALID),
])
def test_legacy_status_values_still_work(raw, expected):
    recs = make_records(fact_status=raw)
    recs[1].snapshot = snapshot_for(recs, "d1")
    assert result_of(compute_all(recs), "d1").status == expected


def test_fingerprint_ignores_bot_written_fields():
    a = Record(table=DOC, record_id="d1", title="T", link="L", deps=["f1"])
    b = Record(table=DOC, record_id="d1", title="T", link="L", deps=["f1"],
               status=STATUS_INVALID, stored_reason="随便", snapshot={"x": 1},
               confirm_checked=True)
    assert content_hash(a) == content_hash(b)
    # 内容字段变化必须改变指纹
    for change in ({"title": "T2"}, {"link": "L2"}, {"extra": "E"}, {"deps": ["f2"]}):
        c = Record(**{**a.__dict__, **change})
        assert content_hash(c) != content_hash(a)


def test_fact_status_not_in_fingerprint():
    f1 = Record(table=FACT, record_id="F-1", title="x", status="现行")
    f2 = Record(table=FACT, record_id="F-1", title="x", status="待核实")
    assert content_hash(f1) == content_hash(f2)


def test_upstream_deleted_after_snapshot_does_not_crash():
    """zcode 原版：快照里有的上游被删后，步骤 5 取 m[rid] 抛 KeyError。"""
    recs = make_records()
    recs[1].snapshot = snapshot_for(recs, "d1")
    recs[1].status = STATUS_ALIGNED
    doc = result_of(compute_all(recs[1:]), "d1")   # 删掉事实 f1
    assert doc.status == STATUS_PENDING
    assert any("不存在或已被删除" in r for r in doc.reasons)

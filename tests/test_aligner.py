"""对齐算法的单元测试（移植自 zcode，事实状态已改为 现行/待核实/已废弃）。

运行：python3 -m pytest tests/
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aligner import (DESIGN, DOC, FACT, STATUS_ALIGNED, STATUS_INVALID,
                     STATUS_PENDING, Record, _analyze_closure, compute_all,
                     content_hash)


def make_records(**kwargs) -> list[Record]:
    """构造一个最小场景：1 条事实 + 1 条文档 + 1 条设计。可用参数覆盖。"""
    fact = Record(
        table=FACT, record_id="f1", title="储值余额不可提现",
        extra="运营纪要", status=kwargs.get("fact_status", "现行"),
    )
    doc = Record(
        table=DOC, record_id="d1", title="会员储值功能说明",
        deps=kwargs.get("doc_deps", ["f1"]),
        status=kwargs.get("doc_status"),
        snapshot=kwargs.get("doc_snapshot"),
        confirm_checked=kwargs.get("doc_confirm", False),
    )
    design = Record(
        table=DESIGN, record_id="g1", title="储值充值页原型",
        deps=kwargs.get("design_deps", ["d1"]),
        status=kwargs.get("design_status"),
        snapshot=kwargs.get("design_snapshot"),
        confirm_checked=kwargs.get("design_confirm", False),
    )
    return [fact, doc, design]


def snapshot_for(records: list[Record], record_id: str) -> dict:
    """以当前内容为准，生成 record_id 这条记录的"核对快照"（模拟它刚核对过）。"""
    m = {r.record_id: r for r in records}
    upstream, _facts, cycle, _missing = _analyze_closure(m[record_id], m)
    assert cycle is None
    return {
        "v": 1, "at": "2026-11-01 10:00",
        "ids": sorted(upstream),
        "hashes": {rid: content_hash(m[rid]) for rid in upstream if rid in m},
    }


def result_of(results, record_id):
    return {r.record_id: r for r in results}[record_id]


class TestAligner(unittest.TestCase):

    def test_never_confirmed_is_pending(self):
        results = compute_all(make_records())
        self.assertEqual(result_of(results, "d1").status, STATUS_PENDING)
        self.assertIn("尚未进行过首次核对", result_of(results, "d1").reasons)

    def test_confirm_makes_aligned_and_clears_checkbox(self):
        recs = make_records(doc_confirm=True)
        results = compute_all(recs)
        doc = result_of(results, "d1")
        self.assertEqual(doc.status, STATUS_ALIGNED)
        self.assertIsNotNone(doc.snapshot)
        self.assertTrue(doc.clear_checkbox)

        recs[1].snapshot = doc.snapshot
        recs[1].confirm_checked = False
        recs[1].status = STATUS_ALIGNED
        doc2 = result_of(compute_all(recs), "d1")
        self.assertEqual(doc2.status, STATUS_ALIGNED)
        self.assertEqual(doc2.reasons, [])

    def test_upstream_change_marks_pending(self):
        recs = make_records()
        recs[1].snapshot = snapshot_for(recs, "d1")
        recs[1].status = STATUS_ALIGNED
        recs[0].extra = "2026-11 新版纪要"
        doc = result_of(compute_all(recs), "d1")
        self.assertEqual(doc.status, STATUS_PENDING)
        self.assertTrue(any("有更新" in r for r in doc.reasons))

    def test_design_pending_when_doc_pending(self):
        recs = make_records()
        recs[1].snapshot = snapshot_for(recs, "d1")
        recs[1].status = STATUS_ALIGNED
        recs[2].snapshot = snapshot_for(recs, "g1")
        recs[2].status = STATUS_ALIGNED
        recs[0].extra = "口径变了"
        doc = result_of(compute_all(recs), "d1")
        design = result_of(compute_all(recs), "g1")
        self.assertEqual(doc.status, STATUS_PENDING)
        self.assertEqual(design.status, STATUS_PENDING)

    def test_deprecated_fact_propagates_through_layers(self):
        recs = make_records(fact_status="已废弃")
        results = compute_all(recs)
        self.assertEqual(result_of(results, "d1").status, STATUS_INVALID)
        self.assertEqual(result_of(results, "g1").status, STATUS_INVALID)
        self.assertIn("已废弃", result_of(results, "g1").reasons[0])

    def test_unverified_fact_marks_pending(self):
        recs = make_records(fact_status="待核实")
        recs[1].snapshot = snapshot_for(recs, "d1")
        doc = result_of(compute_all(recs), "d1")
        self.assertEqual(doc.status, STATUS_PENDING)
        self.assertTrue(any("待核实" in r for r in doc.reasons))

    def test_confirm_blocked_by_unverified_fact(self):
        recs = make_records(fact_status="待核实", doc_confirm=True)
        doc = result_of(compute_all(recs), "d1")
        self.assertEqual(doc.status, STATUS_PENDING)
        self.assertIsNone(doc.snapshot)
        self.assertFalse(doc.clear_checkbox)

    def test_confirm_wins_over_upstream_change(self):
        recs = make_records(doc_confirm=True)
        doc = result_of(compute_all(recs), "d1")
        self.assertEqual(doc.status, STATUS_ALIGNED)
        self.assertIsNotNone(doc.snapshot)

    def test_cycle_detected(self):
        d1 = Record(table=DOC, record_id="d1", title="A 文档", deps=["d2"])
        d2 = Record(table=DOC, record_id="d2", title="B 文档", deps=["d1"])
        results = compute_all([d1, d2])
        for rid in ("d1", "d2"):
            self.assertEqual(result_of(results, rid).status, STATUS_PENDING)
            self.assertTrue(any("成环" in r for r in result_of(results, rid).reasons))

    def test_missing_upstream_record(self):
        recs = make_records(doc_deps=["f1", "rec_gone"])
        doc = result_of(compute_all(recs), "d1")
        self.assertEqual(doc.status, STATUS_PENDING)
        self.assertTrue(any("不存在或已被删除" in r for r in doc.reasons))

    def test_dependency_structure_change_detected(self):
        recs = make_records()
        recs[1].snapshot = snapshot_for(recs, "d1")
        recs[1].status = STATUS_ALIGNED
        recs[1].deps = ["f1", "f2"]
        extra_fact = Record(table=FACT, record_id="f2", title="新事实", status="现行")
        doc = result_of(compute_all(recs + [extra_fact]), "d1")
        self.assertEqual(doc.status, STATUS_PENDING)
        self.assertTrue(any("依赖结构" in r for r in doc.reasons))

    def test_aligned_is_noop_for_writes(self):
        from writeback import diff_fields
        recs = make_records()
        recs[1].snapshot = snapshot_for(recs, "d1")
        recs[1].status = STATUS_ALIGNED
        res = result_of(compute_all(recs), "d1")
        self.assertEqual(diff_fields(recs[1], res), {})

    def test_snapshot_json_roundtrip(self):
        from writeback import parse_snapshot
        snap = snapshot_for(make_records(), "d1")
        self.assertEqual(parse_snapshot(json.dumps(snap, ensure_ascii=False)), snap)
        self.assertIsNone(parse_snapshot(None))
        self.assertIsNone(parse_snapshot("不是json"))

    def test_link_ids_both_shapes(self):
        """关联字段两种返回形态都能解析出 record_id（2026-11-14 飞书实测分组形态）。"""
        from writeback import link_ids
        self.assertEqual(link_ids(["recA", "recB"]), ["recA", "recB"])
        grouped = [{"record_ids": ["recA"], "table_id": "tblX",
                    "text": "x", "text_arr": ["x"], "type": "text"},
                   {"record_ids": ["recB", "recC"], "table_id": "tblY"}]
        self.assertEqual(link_ids(grouped), ["recA", "recB", "recC"])
        self.assertEqual(link_ids(None), [])
        self.assertEqual(link_ids([]), [])
        self.assertEqual(link_ids([{"no_ids": 1}]), [])


if __name__ == "__main__":
    unittest.main()

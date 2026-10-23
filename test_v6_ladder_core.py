#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v6 专项单元测试：固定层梯表（LayerLadder，bounds API）/ 换层跟踪（LayerSwitchTracker）/
历史幅度（HistoryRange）/ sheet3 解析（_read_history_sheet）。
只测纯逻辑，不触碰真实 API、真实数据文件与真实账本。
运行: /home/ubuntu/venv/bin/python3 test_v6_ladder_core.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import okx_autoTrade_TrytoConnectOKX1 as mod

LAT_LOW = 5.0 / 16384           # 同层最低 = 0.00030517578125
LAT_HIGH = 5.0 / 8192           # 同层最高 = 0.0006103515625


class TestLayerLadder(unittest.TestCase):
    def test_lat_levels(self):
        L = mod.LayerLadder(LAT_LOW, LAT_HIGH)
        self.assertAlmostEqual(L.low, LAT_LOW, places=12)
        self.assertAlmostEqual(L.high, LAT_HIGH, places=12)
        # 十六等分档位（与《设计单》一致）
        self.assertAlmostEqual(L.pullback2_down, 0.000553131103515625, places=12)  # 回撤下 13/16
        self.assertAlmostEqual(L.high_mid, 0.0005340576171875, places=12)          # 高位中间 12/16
        self.assertAlmostEqual(L.limit2_down, 0.000324249267578125, places=12)     # 极限下 1/16
        self.assertAlmostEqual(L.pullback_up, LAT_LOW + 15 * (LAT_HIGH - LAT_LOW) / 16, places=12)

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            mod.LayerLadder(0.0, 1.0)
        with self.assertRaises(ValueError):
            mod.LayerLadder(2.0, 1.0)

    def test_shift_up_down(self):
        L = mod.LayerLadder(LAT_LOW, LAT_HIGH)
        U = L.shifted("up")
        self.assertAlmostEqual(U.low, LAT_LOW * 2, places=12)
        self.assertAlmostEqual(U.high, LAT_HIGH * 2, places=12)
        D = L.shifted("down")
        self.assertAlmostEqual(D.low, LAT_LOW / 2, places=12)
        self.assertAlmostEqual(D.high, LAT_HIGH / 2, places=12)
        # 下一层再上一层 == 原层
        D2 = D.shifted("up")
        self.assertAlmostEqual(D2.low, L.low, places=12)
        self.assertAlmostEqual(D2.high, L.high, places=12)
        with self.assertRaises(ValueError):
            L.shifted("sideways")

    def test_contains_boundaries(self):
        L = mod.LayerLadder(LAT_LOW, LAT_HIGH)
        self.assertTrue(L.contains(0.0005652))
        self.assertTrue(L.contains(L.low))         # 边界含
        self.assertTrue(L.contains(L.high))
        self.assertFalse(L.contains(0.00029))
        self.assertFalse(L.contains(0.0007))


class TestSwitchTracker(unittest.TestCase):
    def setUp(self):
        self.tracker = mod.LayerSwitchTracker(mod.LayerLadder(LAT_LOW, LAT_HIGH))

    def test_no_switch_inside(self):
        self.assertIsNone(self.tracker.on_price(0.0004))

    def test_switch_up_single(self):
        r = self.tracker.on_price(LAT_HIGH * 1.5)
        self.assertEqual(r["direction"], "up")
        self.assertAlmostEqual(r["to"][0], LAT_LOW * 2, places=12)
        self.assertAlmostEqual(r["to"][1], LAT_HIGH * 2, places=12)

    def test_switch_down_multi(self):
        r = self.tracker.on_price(LAT_LOW / 8)
        self.assertEqual(r["direction"], "down")
        self.assertAlmostEqual(r["to"][0], LAT_LOW / 8, places=12)   # 一次下跨三层
        self.assertAlmostEqual(self.tracker.current.high, LAT_HIGH / 8, places=12)

    def test_boundary_no_switch(self):
        self.assertIsNone(self.tracker.on_price(LAT_HIGH))
        self.assertIsNone(self.tracker.on_price(LAT_LOW))


class TestHistoryRange(unittest.TestCase):
    def test_observe(self):
        h = mod.HistoryRange(0.1, 10.0)
        self.assertFalse(h.observe(5.0))
        self.assertTrue(h.observe(12.0))
        self.assertEqual(h.C, 12.0)
        self.assertTrue(h.observe(0.05))
        self.assertEqual(h.B, 0.05)
        self.assertAlmostEqual(h.levels.high, 12.0)

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            mod.HistoryRange(2.0, 1.0)


class TestReadHistorySheet(unittest.TestCase):
    def test_parse(self):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(["币对", "历史最低价格", "历史最高价格"])
        ws.append(["LAT", 0.0003474, 5.0])
        ws.append(["BAD", "x", 1.0])
        ws.append([None, 1.0, 2.0])
        ws.append(["OK", 1.0, 2.0])
        out = mod._read_history_sheet(ws)
        self.assertEqual(set(out.keys()), {"LAT", "OK"})
        self.assertAlmostEqual(out["LAT"][0], 0.0003474)
        self.assertAlmostEqual(out["LAT"][1], 5.0)


class TestRisenPersistence(unittest.TestCase):
    """v6：positions.csv 整表重写必须保留已涨幅度/买点类型字段（否则未标脏行被"洗掉"、重启重复播种）"""

    def test_roundtrip(self):
        import tempfile
        import shutil
        tmpdir = tempfile.mkdtemp()
        orig = mod.POSITIONS_FILE
        try:
            mod.POSITIONS_FILE = os.path.join(tmpdir, "positions.csv")
            mod.save_positions({"TEST-USDT": {
                "position_price": 1.0, "position_qty": 5.0, "position_amount": 5.0,
                "entry_type": "legacy", "buy_layer_low": 0.5, "buy_layer_high": 2.0,
                "risen_low": 0.9, "risen_high": 1.1, "risen_low_ts": "t1", "risen_high_ts": "t2",
                "risen_armed": "", "v6_next_buy": "low"}})
            row = mod.load_positions()["TEST-USDT"]
            self.assertEqual(row["entry_type"], "legacy")
            self.assertAlmostEqual(row["risen_low"], 0.9)
            self.assertAlmostEqual(row["risen_high"], 1.1)
            self.assertFalse(row["risen_armed"])
            self.assertEqual(row["v6_next_buy"], "low")
            # 二次整表重写（模拟 flush：load → 改无关字段 → save）不得丢字段
            pos = mod.load_positions()
            pos["TEST-USDT"]["current_price"] = 0.95
            mod.save_positions(pos)
            row2 = mod.load_positions()["TEST-USDT"]
            self.assertEqual(row2["entry_type"], "legacy")
            self.assertAlmostEqual(row2["risen_low"], 0.9)
            self.assertEqual(row2["v6_next_buy"], "low")
        finally:
            mod.POSITIONS_FILE = orig
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)

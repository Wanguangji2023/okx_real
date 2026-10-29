#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
okx_autoTrade_TrytoConnectOKX1.py v5.14 变更单元测试
（依据 okx_real问题及优化方案.md 步骤 2/3：幽灵配对复位 + 运行期轻量对账）

只测纯逻辑与本地账本读写：用假 fetch + 临时文件目录，不触碰任何真实 API 与真实账本。
运行: /home/ubuntu/venv/bin/python3 test_v514_reconcile.py -v
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import okx_autoTrade_TrytoConnectOKX1 as mod


class TempFilesMixin:
    """把所有 CSV/JSON 持久化路径指到临时目录，测试绝不落在真实数据目录"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="okx_v514_test_")

        def tmp(name):
            return os.path.join(self.tmpdir, name)

        self._orig_paths = {}
        for attr in ("POSITIONS_FILE", "COOLDOWN_FILE", "HIGH_LOW_FILE", "PAIR_STATUS_FILE",
                     "BUY_QUEUE_FILE", "FUNDS_FILE", "TRADE_FILE", "BLACKLIST_FILE",
                     "UNKNOWN_BLACKLIST_FILE", "OBSERVE_LIST_FILE", "OUT_OF_RANGE_FILE",
                     "CONFIG_SNAPSHOT_FILE"):
            if attr == "OUT_OF_RANGE_FILE":
                ext = ".xlsx"
            elif attr == "CONFIG_SNAPSHOT_FILE":
                ext = ".json"
            else:
                ext = ".csv"
            self._orig_paths[attr] = getattr(mod, attr)
            setattr(mod, attr, tmp(attr + ext))
        mod._CSV_ROW_CACHE.clear()
        mod._XLSX_SET_CACHE.clear()
        # 推送必须被拦下（不触网、不刷屏）
        self.pushes = []
        self._orig_push = mod.push_notify_throttled

        def fake_push(text, key=None, title="", msg_type="text", interval=None):
            self.pushes.append((text, key))
            return True

        mod.push_notify_throttled = fake_push
        # 平台查询一律走假实现（每个用例自设）
        self._orig_fetch = mod.fetch_platform_positions

    def tearDown(self):
        for attr, val in self._orig_paths.items():
            setattr(mod, attr, val)
        mod._CSV_ROW_CACHE.clear()
        mod.push_notify_throttled = self._orig_push
        mod.fetch_platform_positions = self._orig_fetch


def seed_position(inst_id, qty=100.0, price=1.0, amount=100.0):
    mod.save_positions({inst_id: {
        "position_price": price,
        "position_qty": qty,
        "position_amount": amount,
        "buy_time": "2026-10-01 00:00:00",
        "buy_reason": "单测持仓",
        "pair_type": "回撤",
        "pair_sell_line": "pullback_up",
        "peak_price": price,
        "stop_price": 0,
        "profit_triggered": False,
        "check_level": "T2",
        "last_check_time": "2026-10-01 00:00:00",
        "current_price": price,
        "market_value": amount,
        "unrealized_pnl": 0,
        "unrealized_pnl_pct": 0,
        "max_loss_pct": 0,
    }})
    return inst_id


def mini_state(inst_id):
    """只布置对账路径会碰到的字段（不跑 SymbolState.__init__ 的启动副作用）"""
    st = object.__new__(mod.SymbolState)
    st.inst_id = inst_id
    st.has_position = True
    st.position_price = 1.0
    st.position_qty = 100.0
    st.position_amount = 100.0
    st.profit_triggered = True
    st.stop_price = 1.05
    st.peak_price = 1.05
    st.max_loss_pct = -0.1
    st.buy_signal_activated = True
    st.is_sold = False
    st.sell_time = ""
    st.sell_reason = ""
    st._state_dirty = True
    return st


class TestGhostPairCandidates(TempFilesMixin, unittest.TestCase):
    def test_filters_pairs_without_position_and_platform(self):
        # 幽灵：平台与本地都没有持仓
        mod.save_pair_status("GHOST-USDT", {"is_paired": True, "is_sold": False})
        # 本地有持仓 → 不是幽灵
        mod.save_pair_status("LOCAL-USDT", {"is_paired": True, "is_sold": False})
        # 平台有持仓 → 不是幽灵
        mod.save_pair_status("PLAT-USDT", {"is_paired": True, "is_sold": False})
        # 已卖出 → 不是幽灵
        mod.save_pair_status("SOLD-USDT", {"is_paired": True, "is_sold": True})
        # 未配对 → 不是幽灵
        mod.save_pair_status("OPEN-USDT", {"is_paired": False, "is_sold": False})
        ghosts = mod._ghost_pair_candidates({"PLAT-USDT": {}}, {"LOCAL-USDT": {}})
        self.assertEqual(ghosts, ["GHOST-USDT"])

    def test_reset_ghost_pairs_marks_sold_and_keeps_other_fields(self):
        mod.save_pair_status("RSR-USDT", {"is_paired": True, "is_sold": False,
                                          "buy_price": 0.0015, "sell_line": "pullback_up"})
        reset = mod._reset_ghost_pairs(["RSR-USDT"], "平台无持仓（启动对账复位）")
        self.assertEqual(reset, ["RSR-USDT"])
        row = mod.load_pair_status()["RSR-USDT"]
        self.assertTrue(row["is_sold"])
        self.assertIn("启动对账复位", row["sell_reason"])
        self.assertAlmostEqual(row["buy_price"], 0.0015)
        self.assertEqual(row["sell_line"], "pullback_up")


class TestAlignGhostReset(TempFilesMixin, unittest.TestCase):
    def test_apply_platform_positions_resets_ghost_and_keeps_real(self):
        mod.save_pair_status("RSR-USDT", {"is_paired": True, "is_sold": False})    # 幽灵
        mod.save_pair_status("OP-USDT", {"is_paired": True, "is_sold": False})     # 平台仍有持仓
        ok = mod._apply_platform_positions({
            "OP-USDT": {"position_price": 0.14, "position_qty": 6885.0, "position_amount": 951.9},
        })
        self.assertTrue(ok)
        pairs = mod.load_pair_status()
        self.assertTrue(pairs["RSR-USDT"]["is_sold"])
        self.assertIn("启动对账复位", pairs["RSR-USDT"]["sell_reason"])
        self.assertFalse(pairs["OP-USDT"]["is_sold"])
        self.assertIn("OP-USDT", mod.load_positions())
        self.assertTrue(any("幽灵配对" in t for t, _ in self.pushes))

    def test_apply_platform_positions_no_ghost_no_push(self):
        ok = mod._apply_platform_positions({
            "OP-USDT": {"position_price": 0.14, "position_qty": 6885.0, "position_amount": 951.9},
        })
        self.assertTrue(ok)
        self.assertEqual(self.pushes, [])

    def test_qty_adjustment_preserves_all_in_cost(self):
        # 买入手续费已计入 position_amount（100.8 而非 1000×0.1），平台数量微调时不得抹掉
        mod.save_positions({"1INCH-USDT": {
            "position_price": 0.1, "position_qty": 1000.0, "position_amount": 100.8,
            "buy_time": "2026-10-29 15:09:11", "buy_reason": "单测持仓",
            "pair_type": "", "pair_sell_line": "", "peak_price": 0.1,
            "stop_price": 0, "profit_triggered": False, "check_level": "T3",
            "last_check_time": "", "current_price": 0.1, "market_value": 100.0,
            "unrealized_pnl": 0, "unrealized_pnl_pct": 0, "max_loss_pct": 0,
        }})
        ok = mod._apply_platform_positions({
            "1INCH-USDT": {"position_price": 0.1, "position_qty": 1000.0001,
                           "position_amount": 100.00001},
        })
        self.assertTrue(ok)
        row = mod.load_positions()["1INCH-USDT"]
        self.assertAlmostEqual(row["position_amount"], 100.8 / 1000.0 * 1000.0001, places=10)
        self.assertAlmostEqual(row["position_qty"], 1000.0001, places=10)


class TestRuntimeAudit(TempFilesMixin, unittest.TestCase):
    def _engine(self):
        eng = mod.MarketEngine(mod.Logger(os.devnull), {})
        eng._last_position_audit = 0.0   # 强制到点
        return eng

    def test_skips_before_interval(self):
        eng = self._engine()
        eng._last_position_audit = time.time()
        called = []
        mod.fetch_platform_positions = lambda min_usd=0.0: called.append(1) or {}
        self.assertFalse(eng._audit_positions_due())
        self.assertEqual(called, [])

    def test_disabled_by_zero_interval(self):
        eng = self._engine()
        called = []
        mod.fetch_platform_positions = lambda min_usd=0.0: called.append(1) or {}
        orig_sec = mod.POSITION_AUDIT_SEC
        mod.POSITION_AUDIT_SEC = 0
        try:
            self.assertFalse(eng._audit_positions_due())
        finally:
            mod.POSITION_AUDIT_SEC = orig_sec
        self.assertEqual(called, [])

    def test_fetch_failure_changes_nothing(self):
        inst = seed_position("RVN-USDT")
        mod.save_pair_status(inst, {"is_paired": True, "is_sold": False})
        eng = self._engine()
        mod.fetch_platform_positions = lambda min_usd=0.0: None
        self.assertFalse(eng._audit_positions_due())
        self.assertIn(inst, mod.load_positions())
        self.assertFalse(mod.load_pair_status()[inst]["is_sold"])
        self.assertEqual(self.pushes, [])

    def test_platform_still_has_position_no_change(self):
        inst = seed_position("OP-USDT")
        mod.save_pair_status(inst, {"is_paired": True, "is_sold": False})
        eng = self._engine()
        mod.fetch_platform_positions = lambda min_usd=0.0: {
            inst: {"position_price": 0.14, "position_qty": 6885.0, "position_amount": 951.9}}
        self.assertFalse(eng._audit_positions_due())
        self.assertIn(inst, mod.load_positions())
        self.assertFalse(mod.load_pair_status()[inst]["is_sold"])
        self.assertEqual(self.pushes, [])

    def test_clears_missing_position_resets_pair_and_state(self):
        inst = seed_position("RVN-USDT")
        mod.save_pair_status(inst, {"is_paired": True, "is_sold": False})
        eng = self._engine()
        st = mini_state(inst)
        eng.states[inst] = st
        mod.fetch_platform_positions = lambda min_usd=0.0: {}   # 平台已无任何余额
        self.assertTrue(eng._audit_positions_due())
        self.assertNotIn(inst, mod.load_positions())
        row = mod.load_pair_status()[inst]
        self.assertTrue(row["is_sold"])
        self.assertIn("运行期对账复位", row["sell_reason"])
        self.assertFalse(st.has_position)
        self.assertEqual(st.position_qty, 0.0)
        self.assertFalse(st.profit_triggered)
        self.assertTrue(st.is_sold)
        self.assertFalse(st._state_dirty)
        self.assertTrue(any("运行期对账" in t for t, _ in self.pushes))

    def test_cleared_position_not_written_back_by_flush(self):
        inst = seed_position("RVN-USDT")
        eng = self._engine()
        eng.states[inst] = mini_state(inst)
        mod.fetch_platform_positions = lambda min_usd=0.0: {}
        self.assertTrue(eng._audit_positions_due())
        # 即使内存状态残留，脏落盘也不应把刚清掉的持仓行写回
        with eng.lock:
            eng.flush_dirty_states()
        self.assertNotIn(inst, mod.load_positions())

    def test_runtime_ghost_pair_without_position_gets_reset(self):
        # RSR 场景：没有持仓行、只有幽灵配对行，也得复位并同步内存状态
        mod.save_pair_status("RSR-USDT", {"is_paired": True, "is_sold": False,
                                          "buy_price": 0.0015})
        eng = self._engine()
        st = mini_state("RSR-USDT")
        st.has_position = False    # 无持仓，只是配对状态卡住
        st.position_qty = 0.0
        st.position_amount = 0.0
        eng.states["RSR-USDT"] = st
        mod.fetch_platform_positions = lambda min_usd=0.0: {}
        self.assertTrue(eng._audit_positions_due())
        row = mod.load_pair_status()["RSR-USDT"]
        self.assertTrue(row["is_sold"])
        self.assertIn("运行期对账复位", row["sell_reason"])
        self.assertTrue(st.is_sold)
        self.assertFalse(st.has_position)
        self.assertTrue(any("RSR-USDT" in t for t, _ in self.pushes))


if __name__ == "__main__":
    unittest.main(verbosity=2)

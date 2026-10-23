#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v5.15 部分成交/重探/资金视图 回归测试（保护 P0-2/P0-3 修复成果）
只测纯逻辑与本地账本读写：内存假客户端 + 临时目录，不触碰任何真实 API 与真实账本。
运行: /home/ubuntu/venv/bin/python3 test_v515_partial_fill.py
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import okx_autoTrade_TrytoConnectOKX1 as mod
from test_okx_strategy import make_state


class TempFilesMixin:
    """把所有 CSV 持久化路径指到临时目录，测试绝不落在真实数据目录"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="okx_v515_test_")

        def tmp(name):
            return os.path.join(self.tmpdir, name)

        self._orig_paths = {}
        for attr in ("POSITIONS_FILE", "COOLDOWN_FILE", "HIGH_LOW_FILE", "PAIR_STATUS_FILE",
                     "BUY_QUEUE_FILE", "FUNDS_FILE", "TRADE_FILE", "BLACKLIST_FILE",
                     "UNKNOWN_BLACKLIST_FILE", "OBSERVE_LIST_FILE"):
            self._orig_paths[attr] = getattr(mod, attr)
            setattr(mod, attr, tmp(attr + ".csv"))
        mod._CSV_ROW_CACHE.clear()
        self._orig_push = mod.push_notify_throttled
        self._orig_push2 = mod.push_notify
        mod.push_notify_throttled = lambda *a, **k: True
        mod.push_notify = lambda *a, **k: True

    def tearDown(self):
        mod.push_notify_throttled = self._orig_push
        mod.push_notify = self._orig_push2
        for attr, val in self._orig_paths.items():
            setattr(mod, attr, val)
        mod._CSV_ROW_CACHE.clear()


class TestPartialSellLedger(TempFilesMixin, unittest.TestCase):
    """P0-2：部分成交卖出按比例结转成本，绝不清零"""

    class PartialSellClient:
        def __init__(self, fill_ratio):
            self.fill_ratio = fill_ratio

        def get_balance_detail(self, ccy):
            return (100.0, 100.0, 0.0)

        def get_instrument(self, inst_id):
            return {"minSz": "0.000001", "lotSz": "0.00000001", "baseCcy": "TEST"}

        def market_sell_base(self, inst_id, qty, px=None):
            fq = qty * self.fill_ratio
            return {"price": 1.1, "qty": fq, "proceeds": fq * 1.1,
                    "ord_id": "OS1", "fee": 0.0, "fee_ccy": "USDT", "state": "canceled"}

    def _sell(self, fill_ratio):
        st = make_state(has_position=True, position_price=1.0, position_qty=100.0,
                        position_amount=1000.0)
        st.client = self.PartialSellClient(fill_ratio)
        out = st._execute_sell(1.1, "测试部分卖出", min_profit_pct=None)
        return st, out

    def test_partial_keeps_remainder_with_proportional_cost(self):
        st, out = self._sell(0.3)
        self.assertIsNotNone(out)
        self.assertTrue(st.has_position)
        self.assertAlmostEqual(st.position_qty, 70.0)
        self.assertAlmostEqual(st.position_amount, 700.0)          # 成本按比例扣减
        self.assertAlmostEqual(st._last_profit, 33.0 - 300.0)      # 只对已卖部分计盈亏
        self.assertGreater(st._sell_blocked_until, time.time())    # 退避后再评估余量
        rows = mod._read_csv(mod.TRADE_FILE, mod.TRADE_HEADER)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["direction"], "SELL")
        self.assertAlmostEqual(float(rows[0]["qty"]), 30.0)
        self.assertAlmostEqual(float(rows[0]["amount"]), 33.0)
        self.assertIn("部分成交", rows[0]["reason"])

    def test_full_fill_still_clears(self):
        st, out = self._sell(1.0)
        self.assertIsNotNone(out)
        self.assertFalse(st.has_position)
        self.assertEqual(st.position_qty, 0.0)
        self.assertEqual(st.position_amount, 0.0)

    def test_just_below_threshold_still_clears(self):
        # ≥99.9% 视为全额：lotSz 取整残留不应留下永久余量
        st, out = self._sell(0.9995)
        self.assertIsNotNone(out)
        self.assertFalse(st.has_position)


class TestPartialBuyTopup(TempFilesMixin, unittest.TestCase):
    """P0-3：部分成交买入按差额补单并合并入账"""

    class PartialBuyClient:
        def __init__(self, first_cost):
            self.first_cost = first_cost
            self.calls = 0

        def get_balance(self, ccy="USDT"):
            return 100000.0

        def get_instrument(self, inst_id):
            return {"minSz": "0.0001", "lotSz": "0.0001", "baseCcy": "TEST"}

        def market_buy_quote(self, inst_id, amount, px=None):
            self.calls += 1
            if self.calls == 1:
                return {"price": 1.0, "qty": self.first_cost, "cost": self.first_cost,
                        "ord_id": "OB1", "fee": 0.0, "fee_ccy": "USDT", "state": "canceled"}
            return {"price": 1.0, "qty": amount, "cost": amount,
                    "ord_id": "OB2", "fee": 0.0, "fee_ccy": "USDT", "state": "filled"}

    def _buy(self, first_cost):
        client = self.PartialBuyClient(first_cost)
        st = make_state("TEST-USDT")
        st.client = client
        st.params = {"buy_ratio": 0.01, "cooldown_days": 7}
        orig = mod._okx_client
        mod._okx_client = client
        try:
            out = st._execute_buy(1.0, "测试部分买入", "pullback2_down", "pullback_up", "回撤")
        finally:
            mod._okx_client = orig
        return st, client, out

    def test_topup_merges_to_requested_amount(self):
        st, client, out = self._buy(15.04)          # 委托 1000（余额 10 万×1%），首笔仅 15.04
        self.assertIsNotNone(out)
        self.assertEqual(client.calls, 2)           # 触发了一次补单
        self.assertAlmostEqual(st.position_qty, 1000.0)
        self.assertAlmostEqual(st.position_amount, 1000.0)
        self.assertAlmostEqual(st.position_price, 1.0)
        self.assertIn("OB1", st.buy_reason)
        self.assertIn("OB2", st.buy_reason)
        rows = [r for r in mod._read_csv(mod.TRADE_FILE, mod.TRADE_HEADER)
                if r["direction"] == "BUY"]
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(float(rows[0]["amount"]), 1000.0)

    def test_small_gap_no_topup(self):
        # 成交 1098/委托 1000 → 已足额（≥95%），不再补单
        st, client, out = self._buy(1098.0)
        self.assertIsNotNone(out)
        self.assertEqual(client.calls, 1)

    def test_no_topup_when_state_filled(self):
        st, client, out = self._buy(15.04)
        # 上述 client 第二笔 state=filled；若第一笔就是 filled（非 canceled），不得补单
        client2 = self.PartialBuyClient(15.04)

        def filled_first(inst_id, amount, px=None):
            client2.calls += 1
            return {"price": 1.0, "qty": 15.04, "cost": 15.04, "ord_id": "OF",
                    "fee": 0.0, "fee_ccy": "USDT", "state": "filled"}

        client2.market_buy_quote = filled_first
        st2 = make_state("TEST2-USDT")
        st2.client = client2
        st2.params = {"buy_ratio": 0.01, "cooldown_days": 7}
        orig = mod._okx_client
        mod._okx_client = client2
        try:
            st2._execute_buy(1.0, "已成交但缩水", "pullback2_down", "pullback_up", "回撤")
        finally:
            mod._okx_client = orig
        self.assertEqual(client2.calls, 1)          # 非 canceled → 不补单（按实际入账）


class TestTransientErrorNotBlacklisted(TempFilesMixin, unittest.TestCase):
    """P1-2：瞬时网络错误只冷却，不进黑名单"""

    class ErrClient:
        def __init__(self, msg):
            self.msg = msg

        def get_balance(self, ccy="USDT"):
            return 500.0

        def get_instrument(self, inst_id):
            return {"minSz": "0.0001", "lotSz": "0.0001", "baseCcy": "TEST"}

        def market_buy_quote(self, inst_id, amount, px=None):
            return {"error": self.msg}

    def _try(self, msg):
        client = self.ErrClient(msg)
        st = make_state("TEST-USDT")
        st.client = client
        st._save_state = lambda force=False: None
        st._remove_from_buy_queue = lambda: None
        st._add_to_buy_queue = lambda s: None
        orig = mod._okx_client
        mod._okx_client = client
        try:
            st._execute_buy(1.0, "测试", "pullback2_down", "pullback_up", "回撤")
        finally:
            mod._okx_client = orig
        return st

    def test_ssl_timeout_cooldowns(self):
        # 实证：MASK "<urlopen error _ssl.c:983: The handshake operation timed out>"
        st = self._try("(<urlopen error _ssl.c:983: The handshake operation timed out>)")
        self.assertGreater(st._buy_blocked_until, time.time())
        self.assertNotIn("TEST-USDT", mod.load_unknown_blacklist())
        self.assertNotIn("TEST-USDT", mod.load_blacklist())

    def test_unknown_error_still_blacklisted(self):
        st = self._try("code=99999 msg=从来没见过的错误")
        self.assertIn("TEST-USDT", mod.load_unknown_blacklist())


class TestReprobeAndEnvMissing(TempFilesMixin, unittest.TestCase):
    """P1-1/P1-3：运行期重探（v5.19 起仅服务网络类失败；51001/地域限制直接黑名单）"""

    class ReprobeClient:
        def __init__(self):
            self.ok = False
            self.err = "code=51001 msg=Instrument ID doesn't exist"
            self.calls = 0

        def get_instrument(self, inst_id):
            self.calls += 1
            if not self.ok:
                raise Exception(self.err)
            return {"minSz": "1"}

    def test_reprobe_net_fail_backoff_then_recover(self):
        engine = mod.MarketEngine(mod.Logger(os.devnull))
        rc = self.ReprobeClient()
        rc.err = "网络类：<urlopen error timed out>"
        st = make_state("REP-USDT")
        st.client = rc
        st._okx_available = False
        st._net_failed = True
        st._env_missing = False
        st._reprobe_next_ts = 0.0
        engine.states = {"REP-USDT": st}

        self.assertTrue(engine._reprobe_due_states())
        self.assertTrue(st._net_failed)
        self.assertFalse(st._env_missing)
        self.assertNotIn("REP-USDT", mod.load_blacklist())   # 网络类不判不可交易
        self.assertEqual(st._reprobe_fails, 1)
        self.assertGreater(st._reprobe_next_ts, time.time() + 500)   # 退避 600s 起

        rc.ok = True
        st._reprobe_next_ts = 0.0
        self.assertTrue(engine._reprobe_due_states())
        self.assertTrue(st._okx_available)
        self.assertFalse(st._net_failed)
        ok, _msg = st._can_buy_light()
        self.assertTrue(ok)

    def test_reprobe_51001_blacklists_and_stops(self):
        # v5.19（用户决定）：重探确认当前环境无此产品 → 不可交易产品：常规黑名单持久化、不再重试
        engine = mod.MarketEngine(mod.Logger(os.devnull))
        rc = self.ReprobeClient()   # 缺省抛 51001
        st = make_state("EMB-USDT")
        st.client = rc
        st._okx_available = False
        st._net_failed = True
        st._reprobe_next_ts = 0.0
        engine.states = {"EMB-USDT": st}

        self.assertTrue(engine._reprobe_due_states())
        self.assertIn("EMB-USDT", mod.load_blacklist())      # 持久化落盘
        self.assertIn("EMB-USDT", st.blacklist)              # 内存集合同步
        self.assertTrue(st._env_missing)
        self.assertFalse(st._net_failed)
        self.assertEqual(st._reprobe_next_ts, 0.0)           # 不再安排重试
        self.assertFalse(engine._reprobe_due_states())       # 黑名单币不再入选

    def test_backoff_caps(self):
        engine = mod.MarketEngine(mod.Logger(os.devnull))
        rc = self.ReprobeClient()
        rc.ok = True
        st = make_state("CAP-USDT")
        st.client = rc
        st._okx_available = False
        st._net_failed = True
        st._reprobe_fails = 20
        st._reprobe_next_ts = 0.0
        engine.states = {"CAP-USDT": st}
        engine._reprobe_due_states()
        self.assertTrue(st._okx_available)   # 成功恢复不受退避状态影响


class TestFundsView(TempFilesMixin, unittest.TestCase):
    """P1-6：funds.csv 真实聚合"""

    def test_aggregates_positions_and_realized(self):
        mod.save_positions({"AAA-USDT": {"position_price": 1.0, "position_qty": 10,
                                         "position_amount": 10.0, "market_value": 12.0,
                                         "unrealized_pnl": 2.0}})
        mod.save_trade({"timestamp": "2026-10-18 00:00:00", "inst_id": "BBB-USDT",
                        "direction": "SELL", "price": "1", "qty": "1", "amount": "10",
                        "remaining_funds": "0", "position_price": "1",
                        "profit": "-3.5", "profit_pct": "-10", "reason": "t"})
        mod.save_trade({"timestamp": "2026-10-18 00:01:00", "inst_id": "CCC-USDT",
                        "direction": "BUY", "price": "1", "qty": "1", "amount": "10",
                        "remaining_funds": "0", "position_price": "1",
                        "profit": "0", "profit_pct": "0", "reason": "t"})
        mod._update_funds_for_view(100.0)
        rows = mod._read_csv(mod.FUNDS_FILE, mod.FUNDS_HEADER)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(float(rows[0]["remaining_funds"]), 100.0)
        self.assertAlmostEqual(float(rows[0]["total_position_market_value"]), 12.0)
        self.assertAlmostEqual(float(rows[0]["total_unrealized_pnl"]), 2.0)
        self.assertAlmostEqual(float(rows[0]["total_realized_pnl"]), -3.5)   # 只统计 SELL
        self.assertAlmostEqual(float(rows[0]["net_asset_value"]), 112.0)

    def test_cooldown_dedupes(self):
        mod.save_cooldown_entry("X-USDT", "2026-11-01 00:00:00")
        mod.save_cooldown_entry("X-USDT", "2026-11-02 00:00:00")
        rows = mod._read_csv(mod.COOLDOWN_FILE, mod.COOLDOWN_HEADER)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["cooldown_until"], "2026-11-02 00:00:00")


if __name__ == "__main__":
    unittest.main(verbosity=2)

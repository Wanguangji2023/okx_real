#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v5.16 批次二 回归测试（保护 C1/C4/C5/C10/C11 修复成果）
只测纯逻辑与本地账本读写：内存假客户端 + 临时目录，不触碰任何真实 API 与真实账本。
运行: /home/ubuntu/venv/bin/python3 test_v516_batch2.py
"""
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import okx_autoTrade_TrytoConnectOKX1 as mod
from test_okx_strategy import make_state


class TempFilesMixin:
    """把所有 CSV 持久化路径指到临时目录，测试绝不落在真实数据目录"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="okx_v516_test_")

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


class TestWsEnvSwitch(TempFilesMixin, unittest.TestCase):
    """C1②：demo 模式行情 WS 切模拟盘（wspap + brokerId=9999）"""

    def setUp(self):
        super().setUp()
        self._orig_mode = mod.TRADE_MODE
        self._orig_cfg = mod._WS_DEMO_CFG

    def tearDown(self):
        mod.TRADE_MODE = self._orig_mode
        mod._WS_DEMO_CFG = self._orig_cfg
        super().tearDown()

    def test_ws_use_demo_follows_trade_mode(self):
        mod._WS_DEMO_CFG = "auto"
        mod.TRADE_MODE = "demo"
        self.assertTrue(mod.ws_use_demo())
        mod.TRADE_MODE = "live"
        self.assertFalse(mod.ws_use_demo())

    def test_ws_use_demo_env_override(self):
        mod.TRADE_MODE = "demo"
        mod._WS_DEMO_CFG = "never"
        self.assertFalse(mod.ws_use_demo())
        mod.TRADE_MODE = "live"
        mod._WS_DEMO_CFG = "always"
        self.assertTrue(mod.ws_use_demo())

    def test_connect_targets_demo_host(self):
        calls = []
        orig = mod._ws_handshake

        def fake_handshake(host, port, path):
            calls.append((host, port, path))
            return (object(), b"")

        mod._ws_handshake = fake_handshake
        try:
            mod.TRADE_MODE = "demo"
            mod._WS_DEMO_CFG = "auto"
            mod.connect_okx_ws()
        finally:
            mod._ws_handshake = orig
        self.assertEqual(calls[0][0], "wspap.okx.com")
        self.assertEqual(calls[0][1], 8443)
        self.assertIn("brokerId=9999", calls[0][2])

    def test_connect_targets_live_host(self):
        calls = []
        orig = mod._ws_handshake

        def fake_handshake(host, port, path):
            calls.append((host, port, path))
            return (object(), b"")

        mod._ws_handshake = fake_handshake
        try:
            mod.TRADE_MODE = "live"
            mod._WS_DEMO_CFG = "auto"
            mod.connect_okx_ws()
        finally:
            mod._ws_handshake = orig
        self.assertEqual(calls[0][0], "ws.okx.com")
        self.assertEqual(calls[0][2], "/ws/v5/public")

    def test_subscribe_error_only_warns_once(self):
        """C1②：同一币对的订阅错误只提示一次（防非本环境币对刷屏）"""
        warns = []

        class FakeLogger:
            def warn(self, msg, *a, **k):
                warns.append(msg)

            def debug(self, *a, **k):
                pass

        class FakeEngine:
            logger = FakeLogger()

        mod._SUBSCRIBE_ERROR_SEEN.clear()
        msg = ('{"event": "error", "code": "60018", '
               '"arg": {"channel": "trades", "instId": "ZZZ-USDT"}, "msg": "no such instId"}')
        mod.handle_okx_message(msg, FakeEngine())
        mod.handle_okx_message(msg, FakeEngine())
        self.assertEqual(len(warns), 1)
        self.assertIn("ZZZ-USDT", mod._SUBSCRIBE_ERROR_SEEN)


class TestV6SignalTransitions(TempFilesMixin, unittest.TestCase):
    """v6（设计单 v1.1）§2：信号撤/作废转移/换层纪律（替代已废除的买点漂移死区）"""

    def _state(self):
        st = make_state()
        st._save_state = lambda force=False: None
        st._push_notify = lambda t: None
        return st

    def _feed(self, st, *prices):
        alerts = []
        for i, p in enumerate(prices):
            alerts = st.update_price(p, 1000.0 + i)
        return alerts

    def test_cancel_then_reactivate(self):
        st = self._state()
        self._feed(st, 1.70)
        self.assertEqual(st.v6_sig_type, "high")
        self._feed(st, 1.75)                    # 回升上破 13/16 → 撤信号
        self.assertEqual(st.v6_sig_type, "")
        self._feed(st, 1.71)                    # 再次下破 → 重新激活且参考最低刷新
        self.assertEqual(st.v6_sig_type, "high")
        self.assertAlmostEqual(st.v6_sig_ref_low, 1.71)

    def test_void_moves_next_buy_to_low(self):
        st = self._state()
        self._feed(st, 1.70, 1.60)              # 破 12/16 → 作废，下一买点=低位买点
        self.assertEqual(st.v6_sig_type, "")
        self.assertEqual(st.v6_next_buy, "low")
        self._feed(st, 1.70)                    # 转移后不得再激活高位买点
        self.assertEqual(st.v6_sig_type, "")

    def test_up_switch_ignored_without_position(self):
        st = self._state()
        self._feed(st, 2.5)                     # 上破层界 → 向上换层 [1, 4]
        self.assertAlmostEqual(st.levels.low, 1.0)
        self.assertAlmostEqual(st.levels.high, 4.0)
        self.assertEqual(st.v6_next_buy, "next_layer")   # 无持仓向上换层：忽略（不高位接盘）
        self._feed(st, 3.0)                     # 仍在上层：不激活任何买点
        self.assertEqual(st.v6_sig_type, "")
        self.assertEqual(st.v6_next_buy, "next_layer")


class TestDustCleanup(TempFilesMixin, unittest.TestCase):
    """C5：市值 <1 USDT 且平台总量 <minSz 的粉尘残仓清账"""

    class DustClient:
        def __init__(self, cash, min_sz="10"):
            self.cash = cash
            self.min_sz = min_sz
            self.balance_calls = 0

        def get_instrument(self, inst_id):
            return {"minSz": self.min_sz, "lotSz": "0.0001", "baseCcy": "TEST"}

        def get_balance_detail(self, ccy):
            self.balance_calls += 1
            return (self.cash, self.cash, 0.0)

    def _st(self, cash, price=1.0, qty=0.5):
        st = make_state(has_position=True, position_price=1.0, position_qty=qty, position_amount=qty)
        st.client = self.DustClient(cash)
        st._save_state = lambda force=False: None
        st._push_notify = lambda t: None
        return st

    def test_dust_below_min_sz_cleared(self):
        st = self._st(cash=0.5)     # 市值 0.5 USDT < 1，平台总量 0.5 < minSz 10
        out = st._dust_cleanup(1.0)
        self.assertIsNotNone(out)
        self.assertFalse(st.has_position)
        self.assertEqual(st.position_qty, 0.0)

    def test_dust_above_min_sz_kept(self):
        st = self._st(cash=50.0)    # 平台还能下市价单 → 不清理
        out = st._dust_cleanup(1.0)
        self.assertIsNone(out)
        self.assertTrue(st.has_position)

    def test_above_pos_min_usd_not_checked(self):
        st = self._st(cash=0.5, qty=10.0)     # 市值 10 USDT ≥ 1 → update_price 不触发粉尘核对
        st.update_price(1.0, 2000.0)
        self.assertTrue(st.has_position)
        self.assertEqual(st.client.balance_calls, 0)

    def test_below_pos_min_usd_triggers_check(self):
        st = self._st(cash=0.5)
        st.update_price(1.0, 2000.0)          # 市值 0.5 < 1 → 核对并清账
        self.assertFalse(st.has_position)
        self.assertEqual(st.client.balance_calls, 1)


class TestCostSource(TempFilesMixin, unittest.TestCase):
    """C10：成本来源字段（fill=真实成交 / reconcile=对账重建）"""

    def test_old_row_infers_reconcile(self):
        mod._write_csv_all(mod.POSITIONS_FILE, mod.POSITIONS_HEADER, [
            {"inst_id": "OLD-USDT", "position_price": "1", "position_qty": "10",
             "position_amount": "10", "buy_reason": "平台余额同步"},
        ])
        data = mod.load_positions()
        self.assertEqual(data["OLD-USDT"]["cost_source"], "reconcile")

    def test_old_row_infers_fill(self):
        mod._write_csv_all(mod.POSITIONS_FILE, mod.POSITIONS_HEADER, [
            {"inst_id": "NEW-USDT", "position_price": "1", "position_qty": "10",
             "position_amount": "10", "buy_reason": "反弹1%买入"},
        ])
        data = mod.load_positions()
        self.assertEqual(data["NEW-USDT"]["cost_source"], "fill")

    def test_roundtrip_keeps_cost_source(self):
        mod._write_csv_all(mod.POSITIONS_FILE, mod.POSITIONS_HEADER, [
            {"inst_id": "RT-USDT", "position_price": "1", "position_qty": "10",
             "position_amount": "10", "buy_reason": "反弹1%买入", "cost_source": "fill"},
        ])
        data = mod.load_positions()
        self.assertTrue(mod.save_positions(data))
        data2 = mod.load_positions()
        self.assertEqual(data2["RT-USDT"]["cost_source"], "fill")

    def test_reconcile_path_marks_reconcile(self):
        mod._apply_platform_positions({
            "BAL-USDT": {"position_price": 2.0, "position_qty": 5.0, "position_amount": 10.0},
        })
        data = mod.load_positions()
        self.assertEqual(data["BAL-USDT"]["cost_source"], "reconcile")
        self.assertEqual(data["BAL-USDT"]["buy_reason"], "平台余额同步")

    def test_position_row_reports_source(self):
        st = make_state(has_position=True, position_price=1.0, position_qty=10.0,
                        position_amount=10.0)
        st.cost_source = "fill"
        st._last_processed_price = 1.0
        self.assertEqual(st._position_row()["cost_source"], "fill")


class TestUnknownBlacklistRecheck(TempFilesMixin, unittest.TestCase):
    """C11：未知黑名单满 24h 自动复检（只查 instrument，不下单）"""

    class FakeClient:
        def __init__(self, available_ids):
            self.available_ids = set(available_ids)
            self.calls = []

        def get_instrument(self, inst_id):
            self.calls.append(inst_id)
            if inst_id in self.available_ids:
                return {"minSz": "1"}
            return None

    def _write_rows(self, rows):
        mod._write_csv_all(mod.UNKNOWN_BLACKLIST_FILE, mod.UNKNOWN_BLACKLIST_HEADER, rows)

    def setUp(self):
        super().setUp()
        self._orig_client = mod._okx_client
        self._orig_sec = mod.UNKNOWN_BLACKLIST_RECHECK_SEC

    def tearDown(self):
        mod._okx_client = self._orig_client
        mod.UNKNOWN_BLACKLIST_RECHECK_SEC = self._orig_sec
        super().tearDown()

    @staticmethod
    def _ts(hours_ago):
        return (datetime.now() - timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S")

    class _NullLogger:
        def info(self, *a, **k):
            pass

    def test_due_and_available_removed(self):
        self._write_rows([
            {"inst_id": "OK-USDT", "reason": "x", "add_time": self._ts(25)},
            {"inst_id": "BAD-USDT", "reason": "x", "add_time": self._ts(25)},
        ])
        mod._okx_client = self.FakeClient({"OK-USDT"})
        removed = mod.recheck_unknown_blacklist_due(self._NullLogger(), limit=5)
        self.assertEqual(removed, ["OK-USDT"])
        remaining = {r["inst_id"] for r in mod._read_csv(mod.UNKNOWN_BLACKLIST_FILE, mod.UNKNOWN_BLACKLIST_HEADER)}
        self.assertEqual(remaining, {"BAD-USDT"})

    def test_fresh_entry_not_checked(self):
        self._write_rows([
            {"inst_id": "FRESH-USDT", "reason": "x", "add_time": self._ts(1)},
        ])
        client = self.FakeClient({"FRESH-USDT"})
        mod._okx_client = client
        removed = mod.recheck_unknown_blacklist_due(self._NullLogger(), limit=5)
        self.assertEqual(removed, [])
        self.assertEqual(client.calls, [])

    def test_limit_caps_checks(self):
        self._write_rows([
            {"inst_id": "A-USDT", "reason": "x", "add_time": self._ts(25)},
            {"inst_id": "B-USDT", "reason": "x", "add_time": self._ts(25)},
        ])
        client = self.FakeClient({"A-USDT", "B-USDT"})
        mod._okx_client = client
        removed = mod.recheck_unknown_blacklist_due(self._NullLogger(), limit=1)
        self.assertEqual(removed, ["A-USDT"])
        self.assertEqual(client.calls, ["A-USDT"])   # 只查了 1 个

    def test_unparsable_add_time_treated_as_due(self):
        self._write_rows([
            {"inst_id": "NA-USDT", "reason": "x", "add_time": ""},
        ])
        mod._okx_client = self.FakeClient({"NA-USDT"})
        removed = mod.recheck_unknown_blacklist_due(self._NullLogger(), limit=5)
        self.assertEqual(removed, ["NA-USDT"])

    def test_engine_runtime_syncs_memory_sets(self):
        self._write_rows([
            {"inst_id": "MEM-USDT", "reason": "x", "add_time": self._ts(25)},
        ])
        mod._okx_client = self.FakeClient({"MEM-USDT"})
        engine = mod.MarketEngine(mod.Logger(os.devnull))
        st = make_state(inst_id="MEM-USDT")
        st.unknown_blacklist = {"MEM-USDT"}
        engine.states["MEM-USDT"] = st
        engine._next_unknown_recheck_ts = 0.0
        self.assertTrue(engine._recheck_unknown_blacklist_due())
        self.assertNotIn("MEM-USDT", st.unknown_blacklist)


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v5.17 验证期补丁回归测试（C12：REST 行情补齐）——v5.20 升级为"全市场行情补齐"后维护

背景：模拟盘 WS 成交推送稀疏，冷门币对（含持仓与买入候选）可能整程收不到 tick，
买卖计算全部停摆（实证 26 个持仓中 22 个"启动后未收到行情"）。v5.17 只兜底持仓且
逐币单查（300s 周期、每轮最多 10 个）；v5.20 起每 MARKET_GAP_INTERVAL_SEC（默认 60s）
用一次批量 REST（GET /api/v5/market/tickers?instType=SPOT）把"静默超过
MARKET_GAP_TICK_SEC（默认 45s）"的币对全部喂入同一条 update_price 路径。
本测试只测纯逻辑 + 内存假客户端，不触碰任何真实 API 与真实账本。
运行: /home/ubuntu/venv/bin/python3 test_v517_stale_fallback.py
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import okx_autoTrade_TrytoConnectOKX1 as mod
from test_okx_strategy import make_state
from test_v516_batch2 import TempFilesMixin


class TestLogWhitelist(unittest.TestCase):
    """C12 补充：trade_event INFO 必须落 run.log（兜底启用/交易事件不再只飘控制台）"""

    def test_trade_event_info_written(self):
        import tempfile
        lg = mod.Logger(os.path.join(tempfile.mkdtemp(prefix="okx_v517_log_"), "t.log"))
        self.assertTrue(lg._should_write_log("INFO", "trade_event"))
        self.assertTrue(lg._should_write_log("INFO", "startup"))
        self.assertTrue(lg._should_write_log("WARN", "任何分类"))
        self.assertTrue(lg._should_write_log("ERROR", "任何分类"))
        self.assertFalse(lg._should_write_log("DEBUG", "trade_event"))


class TestFetchTickerPrice(unittest.TestCase):
    """fetch_ticker_price：单币公开接口最新价解析与失败回退（v5.17 单币版，保留备用）"""

    class FakeClient:
        def __init__(self, payload=None, exc=None):
            self.payload = payload
            self.exc = exc
            self.calls = []

        def _request(self, method, path, body_obj=None, query=None, auth=True, timeout=10):
            self.calls.append((method, path, query, auth))
            if self.exc:
                raise self.exc
            return self.payload or {}

    def setUp(self):
        self._orig = mod._okx_client

    def tearDown(self):
        mod._okx_client = self._orig

    def test_parses_last_price(self):
        client = self.FakeClient({"data": [{"instId": "VINE-USDT", "last": "0.93459"}]})
        mod._okx_client = client
        self.assertAlmostEqual(mod.fetch_ticker_price("VINE-USDT"), 0.93459)
        # 必须是公开接口（auth=False），且带上 instId
        self.assertEqual(client.calls[0][0], "GET")
        self.assertIn("/api/v5/market/ticker", client.calls[0][1])
        self.assertEqual(client.calls[0][2], {"instId": "VINE-USDT"})
        self.assertFalse(client.calls[0][3])

    def test_none_without_client(self):
        mod._okx_client = None
        self.assertIsNone(mod.fetch_ticker_price("VINE-USDT"))

    def test_none_on_exception(self):
        mod._okx_client = self.FakeClient(exc=RuntimeError("boom"))
        self.assertIsNone(mod.fetch_ticker_price("VINE-USDT"))

    def test_none_on_empty_or_bad_price(self):
        mod._okx_client = self.FakeClient({"data": []})
        self.assertIsNone(mod.fetch_ticker_price("VINE-USDT"))
        mod._okx_client = self.FakeClient({"data": [{"last": "0"}]})
        self.assertIsNone(mod.fetch_ticker_price("VINE-USDT"))
        mod._okx_client = self.FakeClient({"data": [{"last": ""}]})
        self.assertIsNone(mod.fetch_ticker_price("VINE-USDT"))


class TestFetchAllTickerPrices(unittest.TestCase):
    """v5.20：批量最新价解析与失败回退（一次请求全部现货）"""

    class FakeClient:
        def __init__(self, payload=None, exc=None):
            self.payload = payload
            self.exc = exc
            self.calls = []

        def _request(self, method, path, body_obj=None, query=None, auth=True, timeout=10):
            self.calls.append((method, path, query, auth))
            if self.exc:
                raise self.exc
            return self.payload or {}

    def setUp(self):
        self._orig = mod._okx_client

    def tearDown(self):
        mod._okx_client = self._orig

    def test_batch_parses_and_filters_bad_rows(self):
        client = self.FakeClient({"data": [
            {"instId": "VINE-USDT", "last": "0.93459"},
            {"instId": "NOT-USDT", "last": "0.0004"},
            {"instId": "BAD-USDT", "last": "0"},      # 非正且无报价不入
            {"instId": "EMPTY-USDT", "last": ""},     # 空价格且无报价不入
            {"instId": "", "last": "1.0"},            # 空 instId 不入
        ]})
        mod._okx_client = client
        out = mod.fetch_all_ticker_prices()
        self.assertEqual(out, {"VINE-USDT": 0.93459, "NOT-USDT": 0.0004})
        # 必须是公开批量接口（auth=False），instType=SPOT
        self.assertEqual(client.calls[0][0], "GET")
        self.assertIn("/api/v5/market/tickers", client.calls[0][1])
        self.assertEqual(client.calls[0][2], {"instType": "SPOT"})
        self.assertFalse(client.calls[0][3])

    def test_quote_fallback_for_never_traded_inst(self):
        # 从未成交的新上市产品（last 空）：用买一/卖一报价兜底（实证 RE-USDT）
        client = self.FakeClient({"data": [
            {"instId": "RE-USDT", "last": "", "bidPx": "0.7455", "askPx": ""},
            {"instId": "NEW-USDT", "last": "", "bidPx": "", "askPx": "1.23"},
            {"instId": "DEAD-USDT", "last": "0", "bidPx": "0", "askPx": "0"},
        ]})
        mod._okx_client = client
        out = mod.fetch_all_ticker_prices()
        self.assertEqual(out, {"RE-USDT": 0.7455, "NEW-USDT": 1.23})

    def test_none_without_client(self):
        mod._okx_client = None
        self.assertIsNone(mod.fetch_all_ticker_prices())

    def test_none_on_exception(self):
        mod._okx_client = self.FakeClient(exc=RuntimeError("boom"))
        self.assertIsNone(mod.fetch_all_ticker_prices())

    def test_none_on_empty_or_all_bad_rows(self):
        mod._okx_client = self.FakeClient({"data": []})
        self.assertIsNone(mod.fetch_all_ticker_prices())
        mod._okx_client = self.FakeClient({"data": [{"instId": "X-USDT", "last": "0"}]})
        self.assertIsNone(mod.fetch_all_ticker_prices())


class TestMarketGapSweep(TempFilesMixin, unittest.TestCase):
    """引擎级：全市场行情补齐（批量喂 tick / 跳过规则 / 节流 / 卖出优先排序）"""

    def setUp(self):
        super().setUp()
        self._orig_bulk = mod.fetch_all_ticker_prices
        self._orig_tick = mod.MARKET_GAP_TICK_SEC
        self._orig_interval = mod.MARKET_GAP_INTERVAL_SEC
        self.prices = {}
        self.bulk_calls = 0

        def fake_bulk():
            self.bulk_calls += 1
            return dict(self.prices)

        mod.fetch_all_ticker_prices = fake_bulk

    def tearDown(self):
        mod.fetch_all_ticker_prices = self._orig_bulk
        mod.MARKET_GAP_TICK_SEC = self._orig_tick
        mod.MARKET_GAP_INTERVAL_SEC = self._orig_interval
        super().tearDown()

    def _engine(self, *states):
        engine = mod.MarketEngine(mod.Logger(os.devnull))
        for st in states:
            engine.states[st.inst_id] = st
        engine._last_stale_poll_ts = 0.0
        return engine

    def _mk(self, inst_id, stale_age=1000.0, price=1.05, **over):
        kw = dict(has_position=True, position_price=1.0,
                  position_qty=10.0, position_amount=10.0)
        kw.update(over)
        st = make_state(inst_id=inst_id, **kw)
        st._save_state = lambda force=False: None
        st._push_notify = lambda t: None
        st.last_tick_ts = time.time() - stale_age
        self.prices[inst_id] = price
        return st

    def test_stale_held_state_fed_via_batch(self):
        st = self._mk("A-USDT")
        engine = self._engine(st)
        self.assertEqual(engine._poll_market_gap(), 1)
        self.assertEqual(self.bulk_calls, 1)   # 一次批量请求喂全部候选
        # 价格已喂入 update_price 路径（止盈/卖出评估就地生效）
        self.assertAlmostEqual(st._last_processed_price, 1.05)
        self.assertGreater(st.last_tick_ts, time.time() - 5)
        self.assertGreater(st._last_stale_poll_ts, 0.0)
        self.assertEqual(engine._last_market_gap_fed, 1)

    def test_stale_buy_candidate_fed(self):
        st = self._mk("B-USDT", has_position=False)   # 无持仓的买入候选也要补齐
        engine = self._engine(st)
        self.assertEqual(engine._poll_market_gap(), 1)
        self.assertAlmostEqual(st._last_processed_price, 1.05)

    def test_recent_tick_not_fed(self):
        st = self._mk("C-USDT", stale_age=10.0)   # 10 秒前还有行情 → 不补齐
        engine = self._engine(st)
        self.assertEqual(engine._poll_market_gap(), 0)
        self.assertEqual(self.bulk_calls, 0)      # 无候选时不发批量请求

    def test_env_missing_skipped(self):
        st = self._mk("D-USDT", _env_missing=True)   # 当前环境无此产品（REST 也查不到）
        engine = self._engine(st)
        self.assertEqual(engine._poll_market_gap(), 0)
        self.assertEqual(self.bulk_calls, 0)

    def test_region_blocked_skipped(self):
        st = self._mk("E-USDT", _region_blocked=True)  # 地域/合规限制（不可交易产品）
        engine = self._engine(st)
        self.assertEqual(engine._poll_market_gap(), 0)

    def test_unavailable_and_excluded_candidates_skipped(self):
        cases = [
            self._mk("F1-USDT", has_position=False, _okx_available=False),  # 未通过启动探测
            self._mk("F2-USDT", has_position=False, blacklist={"F2-USDT"}),      # 常规黑名单
            self._mk("F3-USDT", has_position=False, unknown_blacklist={"F3-USDT"}),  # 未知异常黑名单
            self._mk("F4-USDT", has_position=False, observe_list={"F4-USDT"}),   # 观察名单
            self._mk("F5-USDT", has_position=False, out_of_range=True),          # 超范围
            self._mk("F6-USDT", has_position=False, position_only=True),         # 持仓管理币无仓不喂
        ]
        engine = self._engine(*cases)
        self.assertEqual(engine._poll_market_gap(), 0)
        self.assertEqual(self.bulk_calls, 0)

    def test_position_only_with_position_fed(self):
        st = self._mk("G-USDT", position_only=True)   # 有仓的持仓管理币照常补齐
        engine = self._engine(st)
        self.assertEqual(engine._poll_market_gap(), 1)

    def test_interval_throttle(self):
        st = self._mk("H-USDT")
        engine = self._engine(st)
        self.assertEqual(engine._poll_market_gap(), 1)
        # 同一轮节流期内再调：不再发第二个批量请求
        self.assertEqual(engine._poll_market_gap(), 0)
        self.assertEqual(self.bulk_calls, 1)

    def test_bulk_unavailable_returns_zero(self):
        def boom():
            self.bulk_calls += 1
            return None

        mod.fetch_all_ticker_prices = boom
        st = self._mk("I-USDT")
        engine = self._engine(st)
        self.assertEqual(engine._poll_market_gap(), 0)   # 批量不可用：本轮跳过不崩
        self.assertEqual(engine._last_market_gap_fed, 0)

    def test_missing_from_bulk_skipped(self):
        st = self._mk("J-USDT")
        del self.prices["J-USDT"]
        self.prices["OTHER-USDT"] = 1.0   # 批量有数据但恰缺该币对
        engine = self._engine(st)
        self.assertEqual(engine._poll_market_gap(), 0)
        self.assertEqual(self.bulk_calls, 1)

    def test_selling_position_priority_order(self):
        normal = self._mk("K1-USDT", stale_age=1000.0)
        selling = self._mk("K2-USDT", stale_age=130.0)
        selling._sell_blocked_until = time.time() + 60   # 卖出重试中 → 排最前
        engine = self._engine(normal, selling)
        order = []
        orig = engine.on_trade

        def spy(iid, px, ts):
            order.append(iid)
            return orig(iid, px, ts)

        engine.on_trade = spy
        self.assertEqual(engine._poll_market_gap(), 2)   # 全部补齐，卖出重试中先喂
        self.assertEqual(order, ["K2-USDT", "K1-USDT"])

    def test_update_price_records_tick_time(self):
        st = make_state()
        self.assertEqual(st.last_tick_ts, 0.0)
        st._save_state = lambda force=False: None
        st._push_notify = lambda t: None
        st.update_price(1.0, 5.0)
        self.assertGreater(st.last_tick_ts, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

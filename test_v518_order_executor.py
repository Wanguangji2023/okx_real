#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v5.18 C7 回归测试：订单执行线程（锁内决定 → 锁外 REST → 锁内记账）

背景：行情线程此前在 ENGINE_LOCK 内完成下单全流程（余额 REST、market_buy_quote /
market_sell_base、_wait_fill 最长数秒、补单），一次成交尝试会把行情接收/心跳/维护
整体堵住数秒。C7 后行情线程只做零网络预检并投递任务，REST 在锁外由订单线程完成。
本测试只测纯逻辑 + 内存假客户端，不触碰任何真实 API 与真实账本。
运行: /home/ubuntu/venv/bin/python3 test_v518_order_executor.py
"""
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import okx_autoTrade_TrytoConnectOKX1 as mod
from test_okx_strategy import make_state
from test_v516_batch2 import TempFilesMixin

DEADLINE = 3.0


def wait_until(cond, deadline=DEADLINE):
    end = time.time() + deadline
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


class FakeExecutor:
    """只记录任务，不执行：用于验证行情线程"只投递、零 REST" """

    def __init__(self, ok=True):
        self.jobs = []
        self.ok = ok

    def submit(self, job):
        if not self.ok:
            return False
        self.jobs.append(job)
        return True

    def pending(self):
        return len(self.jobs)


class SellClient:
    """卖出用假客户端：可配置成交/失败/异常/慢速（模拟 _wait_fill）"""

    def __init__(self, fill=None, avail=None, cash=None, frozen=0.0, min_sz="0.0001",
                 raise_balance=False, delay=0.0):
        self.fill = fill
        # 缺省可用/总量按 100 计（与 _pos_state 的持仓量一致）：只关心成交路径时无需重复指定
        self.avail = 100.0 if avail is None else avail
        self.cash = self.avail if cash is None else cash
        self.frozen = frozen
        self.min_sz = min_sz
        self.raise_balance = raise_balance
        self.delay = delay
        self.sell_calls = 0
        self.qty_used = None

    def get_balance_detail(self, ccy):
        if self.raise_balance:
            raise RuntimeError("balance REST boom")
        return (self.avail, self.cash, self.frozen)

    def get_instrument(self, inst_id):
        return {"minSz": self.min_sz, "lotSz": "0.0001", "baseCcy": "TEST"}

    def market_sell_base(self, inst_id, qty, px=None):
        self.sell_calls += 1
        self.qty_used = qty
        if self.delay:
            time.sleep(self.delay)
        if self.fill is None:
            return None
        f = dict(self.fill)
        f["qty"] = qty
        return f


class BuyClient:
    """买入用假客户端：同时充当模块级 _okx_client（get_okx_balance 用）"""

    def __init__(self, fill=None, balance=1000.0):
        self.fill = fill
        self.balance = balance
        self.buy_calls = 0

    def get_balance(self, ccy):
        return self.balance

    def market_buy_quote(self, inst_id, amount, px=None):
        self.buy_calls += 1
        if self.fill is None:
            return {"not_filled": True, "state": "canceled"}
        f = dict(self.fill)
        return f


def full_fill(price=1.1):
    return {"price": price, "proceeds": price * 100.0, "ord_id": "1",
            "fee": -0.1, "fee_ccy": "USDT", "state": "filled"}


class RequestDispatchTest(TempFilesMixin, unittest.TestCase):
    """入口分发：无执行器 → 同步旧行为；有执行器 → 只投递（零 REST）+ 门闩"""

    def _pos_state(self):
        st = make_state(has_position=True, position_price=1.0, position_qty=100.0,
                        position_amount=100.0)
        st._push_notify = lambda t: None
        st._save_state = lambda force=False: None
        return st

    def test_sell_sync_when_no_executor(self):
        st = self._pos_state()
        calls = []

        def fake(price, reason, min_profit_pct=0.05, market=False):
            calls.append((price, reason, min_profit_pct, market))
            return "SYNC"

        st._execute_sell = fake
        out = st._request_sell(1.1, "测试")
        self.assertEqual(out, "SYNC")
        self.assertEqual(calls, [(1.1, "测试", 0.05, False)])
        self.assertIsNone(st.order_in_flight)

    def test_buy_sync_when_no_executor(self):
        st = make_state()
        calls = []

        def fake(price, reason, buy_key, sell_key, pair_name, entry_type=""):
            calls.append((price, buy_key, sell_key, pair_name))
            return "SYNC"

        st._execute_buy = fake
        out = st._request_buy(1.0, "测试买入", "pullback2_down", "pullback_up", "回撤")
        self.assertEqual(out, "SYNC")
        self.assertEqual(calls, [(1.0, "pullback2_down", "pullback_up", "回撤")])

    def test_sell_submits_without_rest(self):
        st = self._pos_state()
        st.client = SellClient(fill=full_fill())   # 若被同步调用会记 sell_calls
        st.executor = FakeExecutor()
        out = st._request_sell(1.1, "测试卖出", min_profit_pct=None)
        self.assertTrue(out)
        self.assertEqual(st.order_in_flight, "sell")
        self.assertEqual(len(st.executor.jobs), 1)
        job = st.executor.jobs[0]
        self.assertEqual(job[0], "sell")
        self.assertEqual(job[1], "TEST-USDT")
        self.assertEqual(job[3], "测试卖出")
        self.assertIsNone(job[4])
        self.assertEqual(st.client.sell_calls, 0)   # 零 REST：行情线程未下单

    def test_sell_gate_blocks_second_request(self):
        st = self._pos_state()
        st.executor = FakeExecutor()
        self.assertTrue(st._request_sell(1.1, "第一次", min_profit_pct=None))
        self.assertIsNone(st._request_sell(1.1, "第二次", min_profit_pct=None))
        self.assertEqual(len(st.executor.jobs), 1)

    def test_buy_submits_without_rest(self):
        st = make_state()
        st.executor = FakeExecutor()
        out = st._request_buy(1.0, "测试买入", "pullback2_down", "pullback_up", "回撤")
        self.assertTrue(out)
        self.assertEqual(st.order_in_flight, "buy")
        self.assertEqual(st.executor.jobs[0][0], "buy")
        self.assertEqual(st.executor.jobs[0][4], "pullback2_down")

    def test_submit_failure_rolls_back_inflight(self):
        st = self._pos_state()
        st.executor = FakeExecutor(ok=False)
        self.assertIsNone(st._request_sell(1.1, "测试", min_profit_pct=None))
        self.assertIsNone(st.order_in_flight)

    def test_sell_precheck_still_local(self):
        # 无持仓 → 连任务都不投递（与旧同步行为一致：_can_sell 先拦）
        st = make_state()
        st.executor = FakeExecutor()
        self.assertIsNone(st._request_sell(1.1, "测试", min_profit_pct=None))
        self.assertEqual(len(st.executor.jobs), 0)

    def test_sell_backoff_blocks_submit(self):
        st = self._pos_state()
        st._sell_blocked_until = time.time() + 60
        st.executor = FakeExecutor()
        self.assertIsNone(st._request_sell(1.1, "测试", min_profit_pct=None))
        self.assertEqual(len(st.executor.jobs), 0)


class WorkerIntegrationTest(TempFilesMixin, unittest.TestCase):
    """引擎级：订单线程全流程（锁外 REST + 成交入账 + 在途标记清除）"""

    def setUp(self):
        super().setUp()
        self._orig_heartbeat = mod.HEARTBEAT_FILE
        mod.HEARTBEAT_FILE = os.path.join(self.tmpdir, "hb.json")
        self._orig_client = mod._okx_client
        mod._okx_client = None
        self._orig_push = mod.push_notify
        self._orig_push_throttled = mod.push_notify_throttled
        mod.push_notify = lambda *a, **k: True
        mod.push_notify_throttled = lambda *a, **k: None
        self.engines = []

    def tearDown(self):
        mod.HEARTBEAT_FILE = self._orig_heartbeat
        mod._okx_client = self._orig_client
        mod.push_notify = self._orig_push
        mod.push_notify_throttled = self._orig_push_throttled
        super().tearDown()

    def _engine(self):
        engine = mod.MarketEngine(mod.Logger(os.devnull))
        self.engines.append(engine)
        return engine

    def _sell_state(self, engine, client, inst_id="LOCK-USDT"):
        st = make_state(inst_id=inst_id, has_position=True, position_price=1.0,
                        position_qty=100.0, position_amount=100.0)
        st.client = client
        st.executor = engine.orders
        engine.states[st.inst_id] = st
        return st

    def test_on_trade_returns_fast_and_sell_fills_off_lock(self):
        engine = self._engine()
        client = SellClient(fill=full_fill(), delay=0.6)   # market_sell_base 模拟 0.6s REST
        st = self._sell_state(engine, client)

        t0 = time.time()
        engine.on_trade(st.inst_id, 1.25, 1000.0)   # 盈利 25% → 触发≥20%清仓（异步提交）
        elapsed = time.time() - t0
        self.assertLess(elapsed, 0.3, "行情线程不应在锁内等待下单 REST")
        self.assertEqual(st.order_in_flight, "sell")
        self.assertTrue(wait_until(lambda: client.sell_calls >= 1), "订单线程未开始下单")
        # 关键断言：REST/等成交期间（sleep 0.6s），引擎锁必须可被其他线程获取
        got = mod.ENGINE_LOCK.acquire(timeout=0.3)
        if got:
            mod.ENGINE_LOCK.release()
        self.assertTrue(got, "下单 REST 仍在 ENGINE_LOCK 内执行（C7 未生效）")
        # 等成交入账
        self.assertTrue(wait_until(lambda: st.order_in_flight is None), "在途标记未清除")
        self.assertFalse(st.has_position)
        self.assertEqual(st.position_qty, 0.0)
        # 落盘：positions 中该币对已移除
        self.assertNotIn(st.inst_id, mod.load_positions())

    def test_worker_sell_failure_keeps_position_with_backoff(self):
        engine = self._engine()
        client = SellClient(fill=None, avail=100.0, cash=100.0)   # 下单被拒（返回 None）
        st = self._sell_state(engine, client, inst_id="FAIL-USDT")
        out = st._request_sell(1.1, "测试卖出", min_profit_pct=None)
        self.assertTrue(out)
        self.assertTrue(wait_until(lambda: st.order_in_flight is None))
        self.assertTrue(st.has_position)                      # 持仓保留
        self.assertGreater(st._sell_blocked_until, time.time())   # 失败退避已设置

    def test_worker_sell_balance_exception_falls_back_to_local_qty(self):
        engine = self._engine()
        client = SellClient(fill=full_fill(), raise_balance=True)
        st = self._sell_state(engine, client, inst_id="RBAL-USDT")
        st._request_sell(1.1, "测试卖出", min_profit_pct=None)
        self.assertTrue(wait_until(lambda: st.order_in_flight is None))
        # 与旧同步行为一致：核对失败仍按本地数量尝试下单（不改判、不误清账本）
        self.assertEqual(client.qty_used, 100.0)
        self.assertFalse(st.has_position)

    def test_worker_buy_full_flow(self):
        engine = self._engine()
        client = BuyClient(fill={"price": 1.0, "qty": 100.0, "cost": 100.0, "ord_id": "9",
                                 "fee": -0.1, "fee_ccy": "TEST", "state": "filled"},
                           balance=1000.0)
        mod._okx_client = client
        st = make_state(inst_id="BUY-USDT")
        st.client = client
        st.executor = engine.orders
        engine.states[st.inst_id] = st

        out = st._request_buy(1.0, "测试买入", "pullback2_down", "pullback_up", "回撤")
        self.assertTrue(out)
        self.assertEqual(st.order_in_flight, "buy")
        self.assertTrue(wait_until(lambda: st.order_in_flight is None), "在途标记未清除")
        self.assertTrue(st.has_position)
        self.assertEqual(st.position_qty, 100.0)
        self.assertEqual(st.position_amount, 100.0)
        self.assertEqual(st.cost_source, "fill")
        self.assertEqual(client.buy_calls, 1)
        # 落盘：positions 中有该币对
        self.assertIn(st.inst_id, mod.load_positions())

    def test_run_order_job_clears_inflight_on_exception(self):
        engine = self._engine()
        st = make_state(inst_id="EXP-USDT")
        st.executor = engine.orders
        engine.states[st.inst_id] = st

        def boom(*a):
            raise RuntimeError("boom")

        st._order_sell_job = boom
        st.order_in_flight = "sell"
        with self.assertRaises(RuntimeError):
            engine._run_order_job(("sell", st.inst_id, 1.1, "x", None))
        self.assertIsNone(st.order_in_flight)   # finally 清除，不会卡死

    def test_heartbeat_reports_order_fields(self):
        engine = self._engine()
        payload = mod.write_heartbeat(engine)
        self.assertIn("orders_pending", payload)
        self.assertIn("orders_in_flight", payload)
        st = make_state(inst_id="HB-USDT")
        st.order_in_flight = "sell"
        engine.states[st.inst_id] = st
        payload = mod.write_heartbeat(engine)
        self.assertEqual(payload["orders_in_flight"], 1)

    def test_add_state_injects_executor(self):
        engine = self._engine()
        old = mod.ORDER_EXECUTOR_ENABLED
        try:
            mod.ORDER_EXECUTOR_ENABLED = True
            engine.add_state("INJ-USDT", 2.0, 0.5)
            self.assertIs(engine.states["INJ-USDT"].executor, engine.orders)
            mod.ORDER_EXECUTOR_ENABLED = False
            engine.add_state("NOINJ-USDT", 2.0, 0.5)
            self.assertIsNone(engine.states["NOINJ-USDT"].executor)
        finally:
            mod.ORDER_EXECUTOR_ENABLED = old


class ExecutorUnitTest(TempFilesMixin, unittest.TestCase):
    """OrderExecutor 单元：队列上限 / 停止信号 / 停止后排空标记"""

    def test_queue_full_rejects(self):
        engine = mod.MarketEngine(mod.Logger(os.devnull))
        old = mod.ORDER_QUEUE_MAX
        try:
            mod.ORDER_QUEUE_MAX = 1
            ex = mod.OrderExecutor(engine)
            ex.queue.put_nowait(("sell", "A-USDT", 1.0, "x", None))   # 占满（未启动线程）
            self.assertFalse(ex.submit(("sell", "B-USDT", 1.0, "x", None)))
        finally:
            mod.ORDER_QUEUE_MAX = old

    def test_submit_rejected_when_stopping(self):
        engine = mod.MarketEngine(mod.Logger(os.devnull))
        ex = mod.OrderExecutor(engine)
        mod.STOP_EVENT.set()
        try:
            self.assertFalse(ex.submit(("sell", "A-USDT", 1.0, "x", None)))
        finally:
            mod.STOP_EVENT.clear()

    def test_loop_drain_clears_inflight(self):
        engine = mod.MarketEngine(mod.Logger(os.devnull))
        st = make_state(inst_id="DRAIN-USDT")
        st.order_in_flight = "buy"
        engine.states[st.inst_id] = st
        ex = mod.OrderExecutor(engine)
        ex.queue.put_nowait(("buy", st.inst_id, 1.0, "x", "k", "s", "p"))

        done = threading.Event()

        def stopper():
            mod.STOP_EVENT.set()
            done.wait(2.0)

        t = threading.Thread(target=stopper, daemon=True)
        t.start()
        ex._loop()               # 直接跑循环：STOP 已置位 → 立即进入排空分支
        mod.STOP_EVENT.clear()
        done.set()
        self.assertIsNone(st.order_in_flight)

    def test_dust_cleanup_skips_while_inflight(self):
        class CountingClient:
            def __init__(self):
                self.calls = 0

            def get_instrument(self, inst_id):
                self.calls += 1
                return {"minSz": "1"}

            def get_balance_detail(self, ccy):
                self.calls += 1
                return (0.0, 0.5, 0.0)

        st = make_state(inst_id="DUST-USDT", has_position=True, position_price=1.0,
                        position_qty=0.5, position_amount=0.5)
        st.client = CountingClient()
        st.order_in_flight = "sell"
        self.assertIsNone(st._dust_cleanup(1.0))
        self.assertEqual(st.client.calls, 0)   # 在途期间不对账


if __name__ == "__main__":
    unittest.main(verbosity=2)

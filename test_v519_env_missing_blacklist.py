#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v5.19 回归测试：不可交易产品（51001/地域合规限制）直接入黑名单、持久化、不再重试、不进买入队列

用户决定：产品不存在的（code=51001）与地域/合规限制（51155 等）都是不可交易产品——
启动探测/运行期重探/下单路径一律直接写常规黑名单并持久化，不再指数退避重探；
重探机制此后仅服务启动时网络抖动类失败（_net_failed）；买入队列同步/新增路径一律排除。
本测试只测纯逻辑 + 内存假客户端，不触碰任何真实 API 与真实账本。
运行: /home/ubuntu/venv/bin/python3 test_v519_env_missing_blacklist.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import okx_autoTrade_TrytoConnectOKX1 as mod
from test_okx_strategy import make_state
from test_v516_batch2 import TempFilesMixin


class ProbeClient:
    """启动探测/重探用假客户端：按配置抛异常或返回可交易"""

    def __init__(self, err=None):
        self.err = err
        self.calls = 0

    def get_instrument(self, inst_id):
        self.calls += 1
        if self.err:
            raise Exception(self.err)
        return {"minSz": "1"}


def build_startup_state(inst_id, err):
    """走真实构造路径：SymbolState.__init__ 用模块级 _okx_client 探测"""
    client = ProbeClient(err)
    orig = mod._okx_client
    mod._okx_client = client
    try:
        st = mod.SymbolState(inst_id, 1.0, 0.5, mod.Logger(os.devnull))
    finally:
        mod._okx_client = orig
    return st, client


class TestStartupProbeBlacklist(TempFilesMixin, unittest.TestCase):
    """v5.19：启动探测把不可交易产品直接持久化进黑名单"""

    def test_51001_startup_blacklisted(self):
        st, _c = build_startup_state(
            "EMB-USDT", "code=51001 msg=Instrument ID, Instrument ID code, or Spread ID doesn't exist.")
        self.assertFalse(st._okx_available)
        self.assertTrue(st._env_missing)
        self.assertIn("EMB-USDT", mod.load_blacklist())    # 已持久化落盘
        self.assertIn("EMB-USDT", st.blacklist)            # 内存集合同步
        ok, msg = st._can_buy_light()
        self.assertFalse(ok)
        self.assertIn("无此产品", msg)

    def test_region_restriction_startup_blacklisted(self):
        st, _c = build_startup_state("GEO-USDT", "code=51155 msg=compliance restriction")
        self.assertFalse(st._okx_available)
        self.assertTrue(st._region_blocked)
        self.assertIn("GEO-USDT", mod.load_blacklist())
        ok, msg = st._can_buy_light()
        self.assertFalse(ok)
        self.assertIn("地域", msg)

    def test_network_failure_not_blacklisted(self):
        st, _c = build_startup_state("NET-USDT", "<urlopen error timed out>")
        self.assertFalse(st._okx_available)
        self.assertTrue(st._net_failed)
        self.assertNotIn("NET-USDT", mod.load_blacklist())  # 网络类不判不可交易

    def test_blacklist_reason_persisted(self):
        build_startup_state("EMB2-USDT", "code=51001 msg=no such instrument")
        rows = mod._read_csv(mod.BLACKLIST_FILE, mod.BLACKLIST_HEADER)
        reasons = [r.get("reason", "") for r in rows if r.get("inst_id") == "EMB2-USDT"]
        self.assertEqual(len(reasons), 1)
        self.assertIn("无此产品", reasons[0])

    def test_preblacklisted_skips_probe(self):
        mod.add_to_blacklist("OLD-USDT", "当前交易环境无此产品(51001)")
        st, client = build_startup_state("OLD-USDT", "code=51001 msg=whatever")
        self.assertEqual(client.calls, 0)          # 黑名单币跳过探测，不再请求平台
        self.assertFalse(st._env_missing)
        ok, _msg = st._can_buy_light()
        self.assertFalse(ok)

    def test_env_missing_not_reprobe_candidate(self):
        # v5.19：环境缺失不再参与重探（若能探测会成功，但不应被调用）
        engine = mod.MarketEngine(mod.Logger(os.devnull))
        rc = ProbeClient(None)
        st = make_state("EMB-USDT")
        st.client = rc
        st._okx_available = False
        st._env_missing = True
        st._net_failed = False
        st._reprobe_next_ts = 0.0
        engine.states = {"EMB-USDT": st}
        self.assertFalse(engine._reprobe_due_states())
        self.assertEqual(rc.calls, 0)


class TestBuyQueueExclusion(TempFilesMixin, unittest.TestCase):
    """v5.19（用户决定）：不可交易产品在买入队列同步/新增路径一律被排除"""

    @staticmethod
    def _queue_row(inst_id):
        return {"inst_id": inst_id, "status": "待买入", "ref_high": "1", "ref_low": "0.5",
                "add_time": "2026-10-01 00:00:00", "last_check_time": "2026-10-01 00:00:00"}

    def test_sync_removes_env_missing_from_queue(self):
        mod.save_buy_queue([self._queue_row("EMB-USDT"), self._queue_row("OK-USDT")])
        engine = mod.MarketEngine(mod.Logger(os.devnull))
        st = make_state("EMB-USDT")
        st.blacklist.add("EMB-USDT")        # v5.19 启动探测即入黑名单
        st._env_missing = True
        engine.states = {"EMB-USDT": st, "OK-USDT": make_state("OK-USDT")}
        self.assertTrue(engine.sync_all_buy_queue())
        left = {r["inst_id"] for r in mod.load_buy_queue()}
        self.assertNotIn("EMB-USDT", left)  # 不可交易产品从买入列表剔除
        self.assertIn("OK-USDT", left)

    def test_add_to_buy_queue_skips_blacklisted(self):
        st = make_state("EMB-USDT")
        st.blacklist.add("EMB-USDT")
        st._env_missing = True
        st._add_to_buy_queue("静默期_排除")
        self.assertEqual(mod.load_buy_queue(), [])          # 不落任何行

    def test_add_to_buy_queue_still_adds_normal(self):
        st = make_state("OK-USDT")
        st._add_to_buy_queue("静默期_排除")
        rows = mod.load_buy_queue()
        self.assertEqual([r["inst_id"] for r in rows], ["OK-USDT"])
        self.assertEqual(rows[0]["status"], "静默期_排除")


if __name__ == "__main__":
    unittest.main(verbosity=2)

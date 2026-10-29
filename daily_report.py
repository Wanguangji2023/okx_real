#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v5.16（文档 C8）：运行日报脚本 —— 每天通过飞书推送一条运行摘要。
由 crontab 每日 09:05 调用；只读数据文件，不触碰任何 API 下单接口。
v6.1：统计窗口由“当天 00:00 至运行时刻”改为滚动近 24 小时（DAILY_REPORT_WINDOW_HOURS 可调），
      避免 09:05 之后成交的买卖在次日日报中丢失。
用法: /home/ubuntu/venv/bin/python3 daily_report.py
"""
import base64
import csv
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "okx_ding_ok_data")

sys.path.insert(0, BASE)
from dotenv import load_dotenv
load_dotenv(os.path.join(BASE, ".env"))


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def fnum(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def parse_ts(value):
    """解析账本时间戳（YYYY-MM-DD HH:MM:SS）；格式异常返回 None。"""
    text = str(value or "").strip()[:19]
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def report_window_hours():
    try:
        return max(1.0, float(os.getenv("DAILY_REPORT_WINDOW_HOURS", "24")))
    except (TypeError, ValueError):
        return 24.0


def build_report(now=None):
    now = now or datetime.now()
    hours = report_window_hours()
    window_start = now - timedelta(hours=hours)
    funds = read_csv(os.path.join(DATA, "okx_ding_ok_funds.csv"))
    positions = read_csv(os.path.join(DATA, "okx_ding_ok_positions.csv"))
    trades = read_csv(os.path.join(DATA, "okx_ding_ok_tradeRecord.csv"))
    heartbeat = {}
    hb_path = os.path.join(DATA, "okx_ding_ok_heartbeat.json")
    if os.path.exists(hb_path):
        try:
            with open(hb_path, "r", encoding="utf-8") as f:
                heartbeat = json.load(f)
        except Exception:
            heartbeat = {}

    def in_window(trade):
        ts = parse_ts(trade.get("timestamp"))
        # 左开右闭：相邻两次日报不重复统计同一笔成交
        return ts is not None and window_start < ts <= now

    window_trades = [t for t in trades if in_window(t)]
    recent_sells = [t for t in window_trades if t.get("direction") == "SELL"]
    recent_buys = [t for t in window_trades if t.get("direction") == "BUY"]
    realized = sum(fnum(t.get("profit")) for t in recent_sells)
    fund_row = funds[-1] if funds else {}
    # v6.1：市值/浮盈直接按当前持仓表汇总。funds.csv 只在成交/启动时刷新，
    # 盘中会滞后；日报按持仓表计算，避免展示过期的仓位市值与浮盈。
    remaining = fnum(fund_row.get("remaining_funds"))
    total_mv = sum(fnum(p.get("market_value")) for p in positions)
    total_upnl = sum(fnum(p.get("unrealized_pnl")) for p in positions)
    net_asset = remaining + total_mv
    ups = sorted((fnum(p.get("unrealized_pnl")), p.get("inst_id")) for p in positions)
    worst = ups[0] if ups else (0, "-")

    ws = heartbeat.get("ws", {}) or {}
    lines = [
        f"📊 okx_real 日报 {now:%Y-%m-%d %H:%M}",
        f"统计窗口: {window_start:%m-%d %H:%M} ~ {now:%m-%d %H:%M}（近 {hours:g} 小时）",
        f"版本: {heartbeat.get('version', '?')}  模式: {heartbeat.get('trade_mode', '?')}",
        f"行情WS: {'已连接' if ws.get('connected') else '断开'}"
        + (f"（最近消息 {datetime.fromtimestamp(ws['last_msg_ts']).strftime('%H:%M:%S')}）" if ws.get("last_msg_ts") else ""),
        f"持仓 {len(positions)} 个（对账重建 {heartbeat.get('reconcile_symbols', '?')}，"
        f"无行情兜底 {heartbeat.get('stale_positions', '?')}）",
        f"窗口成交: 买 {len(recent_buys)} / 卖 {len(recent_sells)}，已实现盈亏 {realized:+.2f}",
        f"资金: 可用 {remaining:.2f}  仓位市值 {total_mv:.2f}  浮盈 {total_upnl:+.2f}  净值 {net_asset:.2f}",
        f"最大浮亏仓位: {worst[1]} {worst[0]:+.2f}",
        f"池子 {heartbeat.get('symbols', '?')} 个；环境缺失 {heartbeat.get('env_missing_symbols', '?')} "
        f"网络失败 {heartbeat.get('net_failed_symbols', '?')}",
    ]
    return "\n".join(lines)


def send_feishu(text):
    hook = os.getenv("FEISHU_WEBHOOK_okx", "").strip()
    if not hook:
        print("[日报] 未配置 FEISHU_WEBHOOK_okx，只打印不推送")
        return False
    payload = {"msg_type": "text", "content": {"text": text}}
    secret = os.getenv("FEISHU_SECRET_okx", "").strip()
    if secret:
        # 与主程序 push_to_feishu 一致的签名：hmac_sha256(key=f"{ts}\n{secret}", msg="")
        ts = str(int(time.time()))
        string_to_sign = f"{ts}\n{secret}"
        hmac_code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
        payload["timestamp"] = ts
        payload["sign"] = base64.b64encode(hmac_code).decode("utf-8")
    req = urllib.request.Request(hook, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "Python Feishu Bot"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = json.loads(resp.read().decode("utf-8"))
        print(f"[日报] 推送结果: {ok}")
        return ok.get("code") == 0
    except Exception as e:
        print(f"[日报] 推送失败: {e}")
        return False


if __name__ == "__main__":
    report = build_report()
    print(report)
    send_feishu(report)

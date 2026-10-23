#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v5.16（文档 C8）：运行日报脚本 —— 每天通过飞书推送一条运行摘要。
由 crontab 每日 09:05 调用；只读数据文件，不触碰任何 API 下单接口。
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
from datetime import datetime

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


def build_report():
    today = datetime.now().strftime("%Y-%m-%d")
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

    fund_row = funds[-1] if funds else {}
    today_sells = [t for t in trades if t.get("direction") == "SELL" and str(t.get("timestamp", "")).startswith(today)]
    today_buys = [t for t in trades if t.get("direction") == "BUY" and str(t.get("timestamp", "")).startswith(today)]
    realized = sum(fnum(t.get("profit")) for t in today_sells)
    ups = sorted((fnum(p.get("unrealized_pnl")), p.get("inst_id")) for p in positions)
    worst = ups[0] if ups else (0, "-")

    ws = heartbeat.get("ws", {}) or {}
    lines = [
        f"📊 okx_real 日报 {today}",
        f"版本: {heartbeat.get('version', '?')}  模式: {heartbeat.get('trade_mode', '?')}",
        f"行情WS: {'已连接' if ws.get('connected') else '断开'}"
        + (f"（最近消息 {datetime.fromtimestamp(ws['last_msg_ts']).strftime('%H:%M:%S')}）" if ws.get("last_msg_ts") else ""),
        f"持仓 {len(positions)} 个（对账重建 {heartbeat.get('reconcile_symbols', '?')}，"
        f"无行情兜底 {heartbeat.get('stale_positions', '?')}）",
        f"今日成交: 买 {len(today_buys)} / 卖 {len(today_sells)}，已实现盈亏 {realized:+.2f}",
        f"资金: 可用 {fnum(fund_row.get('remaining_funds')):.2f}  "
        f"仓位市值 {fnum(fund_row.get('total_position_market_value')):.2f}  "
        f"净值 {fnum(fund_row.get('net_asset_value')):.2f}",
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

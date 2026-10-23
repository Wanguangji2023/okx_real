#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v5.16 批次二 C6：历史数据一次性校正脚本（dry-run 默认，--apply 执行）

处理内容（仅动这四类，其余文件不碰）：
  1. pair_status.csv 4 条部分卖出错账校正（ASP/IOST/LAT/WCT）——旧代码把部分成交按整笔清零，
     盈亏按"整笔成本"误记；按 v5.15 部分成交口径（成本 × 成交量/持仓量）重算，并修正
     is_sold/is_paired（余量仍持有的 3 对不再显示"已卖出"）。
  2. cooldown.csv 同币对重复行去重（保留 sell_time 最新的一行）。
  3. run.log / console.out 归档到 okx_ding_ok_data/archive/（要求服务已停止）。
  4. 应用前自动整体备份到 okx_ding_ok_data/backup_<时间戳>/（含根目录相关 csv）。

用法：
  /home/ubuntu/venv/bin/python3 tools_v516_cleanup.py            # dry-run，只打印
  /home/ubuntu/venv/bin/python3 tools_v516_cleanup.py --apply    # 停服后执行
"""
import argparse
import csv
import os
import shutil
import subprocess
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "okx_ding_ok_data")
PAIR_STATUS = os.path.join(DATA_DIR, "okx_ding_ok_pair_status.csv")
COOLDOWN = os.path.join(DATA_DIR, "okx_ding_ok_cooldown.csv")
TRADE_RECORD = os.path.join(DATA_DIR, "okx_ding_ok_tradeRecord.csv")
RUN_LOG = os.path.join(DATA_DIR, "okx_ding_ok_run.log")
CONSOLE_OUT = os.path.join(DATA_DIR, "console.out")
ARCHIVE_DIR = os.path.join(DATA_DIR, "archive")

PAIR_STATUS_HEADER = ["inst_id", "pair_type", "is_paired", "buy_price", "buy_time", "sell_line",
                      "sell_line_price", "is_sold", "sell_time", "sell_reason", "profit", "profit_pct"]
COOLDOWN_HEADER = ["inst_id", "sell_time", "cooldown_until"]

# 4 条错账的证据（对应 tradeRecord.csv 行；脚本会用台账重新计算，只在证据缺失时报错）
CORRECTIONS = {
    "IOST": {"buy_ts": "2026-10-13 00:06:43", "sell_ts": ["2026-10-13 15:59:32"],
             "remain_held": True},
    "ASP":  {"buy_ts": "2026-10-16 01:42:05", "sell_ts": ["2026-10-17 01:00:21"],
             "remain_held": True},
    "WCT":  {"buy_ts": "2026-10-13 09:11:59", "sell_ts": ["2026-10-15 01:54:17"],
             "remain_held": True},
    "LAT":  {"buy_ts": "2026-10-13 08:08:18",
             "sell_ts": ["2026-10-14 02:54:54", "2026-10-14 15:00:00"],
             "remain_held": False},
}


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, header, rows):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def service_running():
    try:
        out = subprocess.run(["pgrep", "-f", "okx_autoTrade_TrytoConnectOKX1.py"],
                             capture_output=True, text=True)
        return bool(out.stdout.strip())
    except Exception:
        return False


def find_trade(rows, inst_id, direction, ts):
    for r in rows:
        if r.get("inst_id") == inst_id and r.get("direction") == direction \
                and r.get("timestamp") == ts:
            return r
    return None


def compute_corrections():
    """按 v5.15 口径重算 4 条错账，返回 {inst_id: {字段: 新值}}"""
    trades = read_csv(TRADE_RECORD)
    pairs = {r.get("inst_id"): r for r in read_csv(PAIR_STATUS)}
    result = {}
    for pair, ev in CORRECTIONS.items():
        buy = find_trade(trades, pair + "-USDT", "BUY", ev["buy_ts"])
        if buy is None:
            raise SystemExit(f"[C6] 证据缺失：{pair} 的买单 {ev['buy_ts']} 不在 tradeRecord")
        held_amt = float(buy["amount"])       # 该批买入成本（旧代码整笔误记的基准）
        held_qty = float(buy["qty"])
        remain_amt, remain_qty = held_amt, held_qty
        total_profit, total_proceeds, last_sell = 0.0, 0.0, None
        for ts in ev["sell_ts"]:
            sell = find_trade(trades, pair + "-USDT", "SELL", ts)
            if sell is None:
                raise SystemExit(f"[C6] 证据缺失：{pair} 的卖单 {ts} 不在 tradeRecord")
            fq, proceeds = float(sell["qty"]), float(sell["amount"])
            ratio = min(1.0, fq / remain_qty) if remain_qty > 0 else 0.0
            cost_sold = remain_amt * ratio
            total_profit += proceeds - cost_sold
            total_proceeds += proceeds
            remain_amt = max(0.0, remain_amt - cost_sold)
            remain_qty = max(0.0, remain_qty - fq)
            last_sell = sell
        cost_total = held_amt - remain_amt              # 已结转成本合计
        pct = total_profit / cost_total * 100 if cost_total > 0 else 0.0
        old = pairs.get(pair + "-USDT", {})
        old_profit = float(old.get("profit") or 0)
        note = (f" | v5.16账务校正：原按整笔误记 {old_profit:+.4f}，实际为部分成交"
                f"{'（余量持有）' if ev['remain_held'] else '（已清仓）'}，"
                f"按成交量结转成本后 {total_profit:+.4f} USDT（{pct:+.2f}%）")
        result[pair + "-USDT"] = {
            "is_paired": "True" if ev["remain_held"] else "False",
            "is_sold": "False" if ev["remain_held"] else "True",
            "sell_time": last_sell["timestamp"],
            "sell_reason": (last_sell.get("reason", "") + note)[:600],
            "profit": f"{total_profit:.12g}",
            "profit_pct": f"{pct:.6f}",
            "remain_qty": remain_qty,
        }
    return result


def plan_pair_status():
    rows = read_csv(PAIR_STATUS)
    fixes = compute_corrections()
    plan = []
    for row in rows:
        inst = row.get("inst_id")
        if inst in fixes:
            new = fixes[inst]
            plan.append((inst, {k: new[k] for k in
                                ("is_paired", "is_sold", "sell_time", "sell_reason", "profit", "profit_pct")}))
    return rows, fixes, plan


def apply_pair_status(rows, fixes):
    changed = 0
    for row in rows:
        inst = row.get("inst_id")
        if inst in fixes:
            for k, v in fixes[inst].items():
                if k == "remain_qty":
                    continue
                if row.get(k) != v:
                    row[k] = v
                    changed += 1
    write_csv(PAIR_STATUS, PAIR_STATUS_HEADER, rows)
    return changed


def plan_cooldown():
    rows = read_csv(COOLDOWN)
    best = {}
    for i, r in enumerate(rows):
        inst = r.get("inst_id", "")
        if not inst:
            continue
        cur = best.get(inst)
        if cur is None or (r.get("sell_time", "") > rows[cur].get("sell_time", "")):
            best[inst] = i
    kept = [rows[i] for i in sorted(best.values())]
    dups = [(r.get("inst_id"), r.get("sell_time")) for i, r in enumerate(rows)
            if r.get("inst_id") in best and i != best[r.get("inst_id")]]
    return rows, kept, dups


def archive_logs(apply: bool):
    actions = []
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for path in (RUN_LOG, CONSOLE_OUT):
        if os.path.exists(path):
            dst = os.path.join(ARCHIVE_DIR, f"{os.path.basename(path)}.{stamp}")
            actions.append((path, dst))
            if apply:
                shutil.move(path, dst)
    return actions


def backup_all():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(DATA_DIR, f"backup_{stamp}_pre_c6")
    os.makedirs(dst, exist_ok=True)
    count = 0
    for name in os.listdir(DATA_DIR):
        src = os.path.join(DATA_DIR, name)
        if os.path.isfile(src) and name.endswith((".csv", ".log", ".out", ".json")):
            shutil.copy2(src, os.path.join(dst, name))
            count += 1
    for name in ("okx_ding_ok_blacklist.csv", "okx_ding_ok_unknown_blacklist.csv",
                 "okx_ding_ok_observe_list.csv", "okx_ding_ok_out_of_range.xlsx"):
        src = os.path.join(BASE_DIR, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(dst, name))
            count += 1
    print(f"[C6] 已备份 {count} 个文件 -> {dst}")
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="执行修改（默认 dry-run 只打印）")
    ap.add_argument("--force", action="store_true", help="服务仍在运行时也执行（危险，仅调试）")
    args = ap.parse_args()

    if args.apply and service_running() and not args.force:
        print("[C6] 检测到主程序仍在运行，拒绝执行。请先停服：sudo systemctl stop okx_real_qoder.service")
        sys.exit(2)

    print("=" * 72)
    print(f"[C6] {'执行模式' if args.apply else 'DRY-RUN 模式（不改任何文件）'}")
    print("=" * 72)

    rows, fixes, plan = plan_pair_status()
    print("\n--- 1) pair_status.csv 错账校正 ---")
    for inst, new in plan:
        old = next(r for r in rows if r.get("inst_id") == inst)
        print(f"\n{inst}:")
        for k in ("is_paired", "is_sold", "sell_time", "profit", "profit_pct"):
            old_v = old.get(k, "")
            new_v = new[k]
            mark = "->" if old_v != new_v else "=="
            print(f"    {k:12s} {old_v!r} {mark} {new_v!r}")
        print(f"    remain_qty  {fixes[inst]['remain_qty']:.6f}")

    cd_rows, cd_kept, cd_dups = plan_cooldown()
    print(f"\n--- 2) cooldown.csv 去重：{len(cd_rows)} 行 -> {len(cd_kept)} 行 ---")
    for inst, ts in cd_dups:
        print(f"    删除旧行: {inst} @ {ts}")

    print("\n--- 3) 日志归档 ---")
    for src, dst in archive_logs(apply=False):
        print(f"    {src}\n      -> {dst}")

    if not args.apply:
        print("\n[C6] DRY-RUN 完成。确认无误后执行： python3 tools_v516_cleanup.py --apply")
        return

    backup_all()
    print("\n[C6] 开始应用 ...")
    changed = apply_pair_status(rows, fixes)
    print(f"[C6] pair_status.csv 更新 {changed} 个字段")
    write_csv(COOLDOWN, COOLDOWN_HEADER, cd_kept)
    print(f"[C6] cooldown.csv 已去重（{len(cd_rows)} -> {len(cd_kept)} 行）")
    for src, dst in archive_logs(apply=True):
        print(f"[C6] 已归档 {src} -> {dst}")
    print("[C6] 完成。可重启服务： sudo systemctl start okx_real_qoder.service")


if __name__ == "__main__":
    main()

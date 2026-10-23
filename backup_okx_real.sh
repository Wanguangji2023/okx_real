#!/bin/bash
# v5.16（文档 C8）：每日备份 okx_real 数据账本 + 代码 + 文档。
# 注意：故意不包含 .env（API 密钥），密钥请单独离线保存；恢复时手动补回。
# 用法: backup_okx_real.sh    （由 crontab 每日 03:30 调用，保留最近 14 份）
set -u
BASE=/home/ubuntu/okx_real
DEST=$BASE/backups
STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p "$DEST"
DESC="$DEST/okx_real_$STAMP.tar.gz"
tar -czf "$DESC" \
  -C "$BASE" \
  --exclude='.venv' --exclude='__pycache__' --exclude='backups' \
  --exclude='okx_ding_ok_data/backup_*' --exclude='*.tmp' --exclude='*.lock' \
  okx_autoTrade_TrytoConnectOKX1.py \
  "okx_autoTrade_TrytoConnectOKX1运行文档及优化建议.md" \
  okx_ding_ok_data \
  okx_ding_ok_blacklist.csv okx_ding_ok_unknown_blacklist.csv \
  okx_ding_ok_observe_list.csv okx_ding_ok_out_of_range.xlsx \
  test_okx_strategy.py test_v514_reconcile.py test_v515_partial_fill.py test_v516_batch2.py \
  test_v517_stale_fallback.py \
  tools_v516_cleanup.py daily_report.py 2>/dev/null
# 保留最近 14 份
ls -1t "$DEST"/okx_real_*.tar.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
echo "[backup] $STAMP -> $(du -h "$DESC" 2>/dev/null | cut -f1)"

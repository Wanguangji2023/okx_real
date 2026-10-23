# v5.14 逐项优化日志（幽灵配对复位 + 运行期轻量对账）

- 目标文件: `okx_real/okx_autoTrade_TrytoConnectOKX1.py`（v5.13 → v5.14，3767 行，LF 换行）
- 改前备份: `okx_real/okx_autoTrade_TrytoConnectOKX1.py.bak_v5.13_20261016`（md5 `10675b9d47b4b56a765d796f5a8c80f8`）
- 依据: `okx_real/okx_real问题及优化方案.md` 步骤 2/3（2026-10-16 核实：该文档行号引用与主程序逐条吻合）
- 测试:
  - 新增 `okx_real/test_v514_reconcile.py`：**11/11 通过**（临时目录 + 假 fetch，不触真实 API/账本）
  - 回归 `okx_real/test_okx_strategy.py`：**121/121 通过**
- 状态（2026-10-16 20:25）: **实施完成，代码已落盘；未重启服务**（进程 136595 仍跑 v5.13 内存副本）。
  重启时机由用户决定（须 SIGTERM/`systemctl restart`，禁用 `-9`）。

## 背景（前置核实结论）

1. `okx_real问题及优化方案.md` ↔ 本机主程序 v5.13：**完全匹配**。
   抽查行号 :1175 / :1203 / :2227 / :2247 / :2493 / :2552 / :2725 / :3275 全部命中；
   幽灵配对现场实例 `RSR-USDT`（pair_status.csv 第 6 行，`is_paired=True, is_sold=False`，2026-10-09 起）确认存在。
2. 同目录 `okx_autoTrade_TrytoConnectOKX1_运行文档与逻辑审查.md` 描述的是
   `/home/wanguangji/alibaba_agent/okx_real/...`（v5.5，2232 行，wanguangjiserver 孪生机），
   **不是**本机 v5.13/v5.14 主程序——本机优化以其"问题及优化方案"文档为准。
3. `okx_real.service`（旧副本服务）的 unit 文件已不存在（`/etc/systemd/system/` 下只剩
   `okx_real_qoder.service`），步骤 1 的"服务隔离"已无须再做；`code/` 旧副本按用户要求不动。

## 条目清单

| 编号 | 内容 | 风险 | 状态 | 完成时间 | 改动摘要 | 验证 |
|---|---|---|---|---|---|---|
| G1 | 幽灵配对复位：启动/恢复全量对账后，复位"平台与本地都无持仓"的 is_paired/is_sold 卡死行（RSR 买不进） | P1 | 完成 | 2026-10-16 20:22 | 见施工记录 G1 | 11/11 + 121/121 |
| G2 | 运行期轻量对账：`POSITION_AUDIT_SEC`（默认 300s）到点清"平台已无余额"的本地持仓、复位配对、同步内存态 | P1 | 完成 | 2026-10-16 20:22 | 见施工记录 G2 | 11/11 + 121/121 |
| — | 上线验证（待用户重启后核对） | — | 待办 | | 见文末"上线验证" | |

## 逐条施工记录

### G1 幽灵配对复位（启动/恢复全量对账后）

- 问题：平台侧手动卖出/转账后，若本地从未触发卖出规则，`pair_status` 无人复位；
  `_can_buy` 以"已配对未卖出"（`is_paired and not is_sold`，:2535）永久挡掉该币对。
  现场实例 RSR-USDT 自 2026-10-09 起买不进。
- 改法：新增 `_ghost_pair_candidates()`（挑出 is_paired=True、is_sold=False、
  平台与本地均无持仓的行）+ `_reset_ghost_pairs()`（置 is_sold=True、sell_time=now、
  sell_reason="平台无持仓（启动对账复位）"，走既有 `save_pair_status` 单行失败不回滚）；
  在 `_apply_platform_positions` 全量对齐成功落盘后、**同一 ENGINE_LOCK 临界区内**调用；命中即
  `logger.warn(..., "reconcile")` + 限流推送（key=pairghost:startup）。
- 涉及行：:1275-1317（apply 尾部调用、两个新函数）；logger 白名单新增 `reconcile`（:624）。
- 测试：`test_v514_reconcile.py` TestGhostPairCandidates（2 例）+ TestAlignGhostReset（2 例）。
- 遗留：恢复线程路径（启动期账户不可达→后台恢复成功）只复位盘上配对行，内存状态靠 G2 下一次
  运行期对账同步（≤POSITION_AUDIT_SEC）；RSR/SAHARA 等不在池中的币对无内存态，无此问题。

### G2 运行期轻量对账（MarketEngine.maintenance 到点触发）

- 问题：全量对齐此前只在启动做一次；平台侧手动成交后本地账本要等该币恰好触发卖出规则才自愈，
  期间 open_positions / unrealized_pnl / funds 视图全是虚值（RSR 故障即极端表现）。
- 改法：
  1. 新参数 `POSITION_AUDIT_SEC = env_num("POSITION_AUDIT_SEC", 300.0)`（<=0 关闭）；:1189
  2. 从 `sync_positions_from_api` 提取 `fetch_platform_positions()`（同一实现，失败返回 None），
     启动同步与运行期对账共用；:1190-1219
  3. `MarketEngine.__init__` 记录 `_last_position_audit`（首个周期从启动时刻起算）；:3234
  4. `maintenance()` 调 `_audit_positions_due()`：**锁外**做一次
     GET `/api/v5/account/balance`；**锁内**（ENGINE_LOCK）只做本地比对——平台已无余额的本地持仓
     清记录 → 落盘失败则本轮跳过；成功后再复位相应幽灵配对（sell_reason="平台无持仓（运行期对账复位）"）；
     同步内存状态（清 has_position/peak/stop/止盈激活等；幽灵行置 is_sold）——防止下一次脏落盘
     把持仓行写回；最后 logger.warn(..., "reconcile") + 限流推送（key=posaudit:runtime）。:3339-3413
  5. 请求失败/网络类异常：本轮跳过、不改判任何账本（与卖出前余额快照失败的既有原则一致）。
- 测试：`test_v514_reconcile.py` TestRuntimeAudit（7 例，含"清掉后 flush 不回写"与"无持仓的幽灵行也复位"）。
- 遗留：只修"平台已无余额"方向，不做数量覆盖（卖出前另有逐笔可用量核对，符合方案边界）。

## 上线验证（重启后核对，待办）

1. 重启（用户决定时机）: `systemctl restart okx_real_qoder.service`（SIGTERM，勿用 -9）。
2. 启动日志应出现：`幽灵配对复位 …: RSR-USDT（平台无持仓，启动对账复位）`（SAHARA 若平台也无余额则一并复位；
   平台仍有余额的不动）+ 启动推送"🧹 幽灵配对已复位"。
3. 启动日志尾部：`持仓缓存已初始化（启动全量对齐完成；运行期每 300s 轻量对账一次）`。
4. 重启后 ≤5 分钟若平台与本地一致：无对账告警（正常）；若期间有平台侧手动成交，将出现
   "⚠️ 运行期对账发现本地账本与平台不一致，已自动修复"推送。
5. 核对 RSR-USDT 恢复买入资格（超范围表/池内据实）。

# okx_autoTrade_TrytoConnectOKX1 运行文档及优化建议

| 项目 | 内容 |
|---|---|
| 审阅对象 | `okx_autoTrade_TrytoConnectOKX1.py`（审查时 v5.14，3767 行；**现 v5.20**——批次一~三 + v5.19 政策变更 + v5.20 行情补齐全部落地） |
| 审阅日期 | 2026-10-17（JST） |
| 审阅方式 | 全量静态走读 + 数据文件核对（`okx_ding_ok_data/` 全部 CSV/JSON/日志）+ `journalctl` 服务日志分析 + systemd 单元检查 + OKX 只读 API 探针（主网 / 模拟盘双向取样）+ 回归测试复跑 |
| 运行宿主 | `okx_real_qoder.service`（systemd），`/home/ubuntu/venv/bin/python3`，PID 86815，2026-10-17 21:31:44 启动 |
| 修复状态 | **批次一~三 + v5.19 + v5.20 全部落地（2026-10-18，代码 v5.14 → v5.20）**：批次一 v5.15（P0-2/P0-3 等 18 项）→ 批次二 v5.16（C1~C11，含 C6 数据修正）→ 验证期 v5.17（C12 无行情兜底）→ 批次三 v5.18（C7 锁内下单重构）→ v5.19（政策变更：不可交易产品直接入黑名单、不再重试、不入买入队列）→ v5.20（全市场行情补齐：批量 REST 每 60s 覆盖持仓+买入候选）。进度台账见 **第 6 节**。代码改动需重启进程生效 |
| 测试状态 | 全量 7 个测试文件 **219/219 通过**（122+11+13+23+22+19+9）；最新一轮 2026-10-18 v5.20 落地后复跑全过 |

> 本文档分四部分：**0 速览** → **1 运行文档**（怎么跑、怎么查、怎么修）→ **2 缺陷审查**（P0/P1/P2/P3，全部带证据）→ **3 优化建议与落地顺序**；另加 **6 修复进度台账与待确认清单**。原审查阶段（2026-10-17）未修改任何代码和数据文件，API 探针全部为只读查询；2026-10-18 起按用户指令实施批次一修复（**仅改代码，未动任何数据文件**），所有进度与待确认项记录在第 6 节，断后恢复时以第 6 节为准。

---

## 0. 速览（TL;DR）

### 0.1 当前运行快照（2026-10-17 21:46 JST）

| 指标 | 数值 |
|---|---|
| 交易模式 | `demo`（OKX 模拟盘，API 真实下单、`x-simulated-trading: 1`） |
| 股票池 | 108 个币对（2 个 xlsx 文件解析成功） |
| 行情订阅 | 54 个币对（其余 54 个在黑名单/未知黑名单/观察列表） |
| 持仓 | 24 个，持仓成本 14,149.14 USDT，市值 12,297.81，浮亏 **−1,851.33（−13.08%）** |
| 其中 VINE-USDT | 单仓浮亏 **−898.59（−99.13%）**——见 P0-1 |
| USDT 可用 | 89,634.69 |
| 总资产（可用+持仓市值） | ≈ 101,932.50 USDT |
| 心跳 | ws connected、push_pending 0、degraded false、RSS 13.1MB、可用内存 226MB |
| 黑名单 | 57 条（46 条在池内）；未知异常黑名单 7 条；观察列表 4 条 |

### 0.2 三条 P0（必须先处理）

1. **P0-1 交易环境双源割裂**：下单走**模拟盘**（demo），行情/股票池/价格区间却来自**主网**。108 个池内币对只有 53 个在模拟盘存在；两环境都有且可取的 52 个币对里 13 个价差 >2%（VINE 主网 0.007587 vs 模拟盘 0.93459，差 12,218%）。已造成真实账目事故：VINE 以 0.8735「买入」906 USDT，账本按主网价显示 −99.13%，永久性死仓。
2. **P0-2 部分成交卖出 → 本地账本整笔清零 + 假盈亏**：卖单只部分成交（如 ASP 只成交 34.3%）时，`_execute_sell` 仍然清零全部持仓、按**全额成本**计算盈亏，卖出记录里的盈亏最高错到 −184 USDT（实际 ≈ −1.7）。已有 4 笔实证（ASP / IOST / LAT / WCT）。
3. **P0-3 部分成交买入 → 数量大幅缩水、无补单无告警**：按计价金额市价买入在模拟盘经常只部分成交并被取消（CSPR 947.73 USDT 只成交 15.04，1.6%；SAHARA 916.24 只成交 62.42，6.8%），代码把「部分成交」当成功买入入账，剩余金额不再补单。

> **修复状态（2026-10-18）**：P0-1 已由 C1/C2 解决（行情切模拟盘；VINE 残量已于 06:30:49 经兜底盯盘自动清仓了结，+19.23 USDT）；P0-2、P0-3 在 v5.15 批次一落地；C7（P2-2 锁内下单）在 v5.18 落地。全部回归 200 项通过。

### 0.3 其他高价值发现（摘要）

- 启动探测失败的币对（18 个）**整个进程生命周期内不可买**且没有任何重试（P1-1）；这些全部是「模拟盘里不存在」的币对（`code=51001`，P1-3）。
- 一次 SSL 握手里超时就把币对**永久**写进未知异常黑名单（MASK，2026-10-17 00:03:45），恢复必须手工改 CSV + 重启（P1-2）。
- `run.log` 写入白名单过窄：472 行错误日志里 408 行是历史脏数据，近两天所有 WARN/运营警告**一条都没进 run.log**（P1-5）。
- 两天内 13,553 次「买入跳过: 币对在黑名单/不可交易」DEBUG 刷屏（TAO 3,416 次居首），每次还伴随一次强制余额 REST（P1-1/P2-1）。
- 采点边界抖动：两天 384 次「最佳买点漂移」重绑买入信号（KAT 在 transition2_down↔limit2_down 之间 6 分钟内来回）（P1-7）。

---

## 1. 运行文档

### 1.1 程序定位与版本

- 程序名 `okx_ding_ok`，版本 **v5.18**（2026-10-18 批次一~三修复；代码头注释含完整变更摘要，v5.14 历史变更见 `doc_txt/fixlog_v5.14.md`）。
- 功能：OKX 现货「多层价格区间 + 反弹 1% 买入 + 动态止盈」自动交易机器人，本地 CSV 账本、飞书/钉钉推送、systemd 托管。
- 交易模式三选一（`OKX_TRADE_MODE`）：
  - `local`：本地模拟，不下单（当前代码路径已按 demo/live 二分实现，`local` 描述保留在 .env 注释中）；
  - `demo`：OKX 模拟盘，**API 真实下单**（当前使用中）；
  - `live`：实盘，必须显式设置 `OKX_LIVE_CONFIRM=YES`，否则自动降级 demo（`init_okx_client`，2316-2318 行）。

### 1.2 目录与文件布局

```
/home/ubuntu/okx_real/                          # BASE_DIR（代码与运行数据分离）
├── okx_autoTrade_TrytoConnectOKX1.py           # 主程序（3767 行）
├── .env                                        # 全部运行配置（API 凭证、模式、推送）
├── okx_ding_ok.lock                            # 单实例锁（fcntl.flock + PID 内容）
├── okx_ding_ok_blacklist.csv                   # 常规黑名单（57 条）
├── okx_ding_ok_unknown_blacklist.csv           # 未知异常黑名单（7 条）
├── okx_ding_ok_observe_list.csv                # 待观察列表（4 条）
├── okx_ding_ok_out_of_range.xlsx               # 超出计算范围审计表（当前不存在=无越界币对）
├── test_okx_strategy.py / test_v514_reconcile.py   # 回归测试（132 项）
├── doc_txt/                                    # 版本变更记录
└── okx_ding_ok_data/                           # DATA_DIR（全部账本与日志）
    ├── okx_ding_ok_positions.csv               # 持仓账本（24 行）
    ├── okx_ding_ok_pair_status.csv             # 配对状态与历史盈亏
    ├── okx_ding_ok_cooldown.csv                # 静默期（卖出后 N 天禁买）
    ├── okx_ding_ok_high_low.csv                # 各币对历史高低点（驱动价格档位）
    ├── okx_ding_ok_buy_queue.csv               # 买入队列（31 个待买入）
    ├── okx_ding_ok_funds.csv                   # 资金浏览表（⚠ 恒为 0，见 P1-6）
    ├── okx_ding_ok_tradeRecord.csv             # 成交流水（39 买 / 16 卖）
    ├── okx_ding_ok_heartbeat.json              # 心跳（监控第一入口）
    ├── okx_ding_ok_config_snapshot.json        # 上次有效配置快照（108 币对）
    ├── okx_ding_ok_run.log                     # 程序内日志（写盘白名单，见 P1-5）
    └── console.out                             # 旧版本控制台输出（2026-10-12 后停更，可清理）

股票池（.env INPUT_DATA）：
/home/ubuntu/alibaba_agent/downlaods_futu_data/.../标黄/已标注/
├── demo_..._标黄_已标注.xlsx                    # 当前 108 币对来源（含"已精减/"子目录一并扫描）
└── 已精减/已精减汇总.xlsx
```

### 1.3 架构与线程模型

```
systemd (okx_real_qoder.service)
└─ python3 okx_autoTrade_TrytoConnectOKX1.py
   ├─ 主线程  main() 循环（1s 一拍）
   │    ├─ engine.maintenance()          # 负载采样 / xlsx 审计批量写 / 运行期对账(300s) / 脏账本落盘
   │    ├─ write_heartbeat()             # 每 10s 写心跳 JSON（原子替换）
   │    └─ watch_market_thread()         # 行情线程死了原样拉起（≥30s 间隔）
   ├─ okx-market-stream（daemon 线程）
   │    └─ stream_okx → 手写 WebSocket (ws.okx.com) → handle_okx_message → engine.on_trade
   │         └─ 持 ENGINE_LOCK：state.update_price() → 买入信号/卖出评估 → 投递订单任务（v5.18 起不再锁内下单）
   ├─ okx-order（daemon，懒启动：首个订单任务时创建）
   │    └─ OrderExecutor 单线程串行：锁外 REST（余额强刷/下单/等成交/补单）→ 锁内 apply 记账
   └─ okx-recover（daemon，仅启动时账户不可达且有持仓时创建）→ 每 60s 重试账户恢复
```

关键机制：

- **账本锁 `ENGINE_LOCK`**：行情线程、订单线程、主线程维护、账户恢复线程共用；「锁内不做网络请求」已于 v5.18（C7）达成——行情线程锁内只投递订单任务，订单类 REST 全部在 okx-order 线程锁外执行。
- **落盘节流**：常规 tick 只标脏，按全局闸门（默认 5s，高负载/低内存时 30s）合并整表写；买卖/止盈激活等关键事件 `force=True` 立即落盘。所有 CSV 写入采用 `.tmp` + `os.replace` 原子替换，启动时清理残留临时文件。
- **CSV 读失败保护**：读表失败会记入 `_CSV_READ_FAILED`，持仓表读取失败时禁止买入（防重复建仓）。
- **WebSocket 自愈**：25s ping；静默 ≥75s（`WS_STALL_FACTOR=3`）主动断开重连；重连等待 3s；连续失败 ≥3 次才推送告警。
- **单实例锁**：`okx_ding_ok.lock`（fcntl.flock 非阻塞），重复启动直接退出。

### 1.4 运行环境与依赖

| 项目 | 值 |
|---|---|
| Python | 3.12.3（`/home/ubuntu/venv/bin/python3`，systemd 单元指定） |
| 关键依赖 | `python-dotenv`（读 .env）、`openpyxl`（读写 xlsx 股票池/审计表）；WebSocket 为手写实现（socket+ssl，无第三方 ws 库） |
| systemd 单元 | `/etc/systemd/system/okx_real_qoder.service`：`Restart=on-failure`、`RestartSec=600`、`WorkingDirectory=/home/ubuntu/okx_real/`、`PYTHONUNBUFFERED=1` |
| 机器 | 单核（`cpu_cores=1.0`），心跳显示 load≈0.85、可用内存 ≈226MB |

⚠ 注意：`Restart=on-failure` 意味着**正常退出（SIGTERM/Ctrl+C）不会被自动拉起**；只有异常崩溃才自动重启（间隔 600s）。

### 1.5 配置体系

#### 1.5.1 `.env` 参数总表（当前生效）

| 变量 | 当前值 | 说明 |
|---|---|---|
| `OKX_API_KEY` / `OKX_API_SECRET` / `OKX_API_PASSPHRASE` | （已配置，含实盘权限凭证） | ⚠ 文件权限已收紧 `600`（2026-10-18）；**凭证轮换待办**（见 P2-8 / 6.2-C9） |
| `OKX_TRADE_MODE` | `demo` | local/demo/live；优先级高于 xlsx「系统参数」表 |
| `OKX_LIVE_CONFIRM` | 空 | 只有 `=YES` 才允许实盘，否则自动降级 demo |
| `MIN_BUY_AMOUNT` | `110` | 单笔最小买入金额 USDT |
| `COOLDOWN_DAYS` | `7` | 卖出后静默期天数（覆盖表格值，非法值有保护） |
| `INPUT_DATA` | `.../标黄/已标注` | 股票池目录（递归扫描全部 xlsx，跳过 `~$` 临时文件） |
| `FILTER_LAYER` | 空 | 倍数层过滤（`8-16`、`8-16及以上`、`8-16以下`，逗号叠加）；空=不过滤 |
| `NOTIFY_CHANNEL` | `feishu` | dingtalk / feishu / both / none |
| `FEISHU_WEBHOOK_okx` / `FEISHU_SECRET_okx` | （已配置） | 飞书机器人 |
| `BUY_RATIO` | 未设置 | 可选；覆盖表格 `buy_ratio`（当前 0.01 → 单笔≈账户余额 1%） |

**v6 参数（2026-10-19 参数外置化批次起显式写入 `.env`；每键中文注记见 `.env`；改后需重启服务生效；
调参验证：`test_okx_strategy.TestEnvTuning`）**：

| 变量 | 当前值 | 参考用途（设计单 v1.1 / 用户要求） |
|---|---|---|
| `REF_LOW_MINUTES` | `120` | 参考最低静默分钟（低位/高位买点条件）；设计单 §2「.env 可调」 |
| `RISEN_RANGE_MIN_PCT` | `0.05` | 已涨幅度有效门槛（≥5% 启用清仓1；未达 → 动态止盈兜底）；设计单 §3「.env 可调」 |
| `RISEN_PUSH_THROTTLE_SEC` | `20` | 已涨幅度推送节流（秒）；设计单 §3「节流 ≥20 秒」（E3） |
| `SELL_REPRICE_SEC` | `15` | 清仓限价单撤单重挂周期（秒）；设计单 §4（E3）⚠ 15s 重挂属「后续补强」，代码暂未读取 |
| `HARD_STOP_LOSS_PCT` | `0.125` | 铁律①：个股最大亏损 12.5% → 市价止损清仓（优先于其余清仓规则） |
| `BREAKEVEN_CLEAR_LOSS_PCT` | `0.05` | 铁律②：亏损记录超 5% 后回本即清仓 |
| `TAKE_PROFIT_ACTIVATE_PCT` | `0.065` | 动态止盈激活门槛（6.5%） |
| `TAKE_PROFIT_CLEAR_PCT` | `0.20` | 盈利 ≥20% 立即清仓（回撤容忍归零） |
| `TAKE_PROFIT_TOLERANCE_PCT` | `0.015` | 激活档回撤容忍基准（1.5%） |
| `TAKE_PROFIT_TOLERANCE_SLOPE` | `0.1` | 每多 1% 盈利，回撤容忍减少 0.1% |
| `TAKE_PROFIT_BUCKET` | `0.001` | 容忍曲线分档步长（0.1%，与原硬表逐档等价） |
| `TAKE_PROFIT_MIN_MARGIN_PCT` | `0.05` | 止盈价地板 = 成本×(1+本值)，保底 5% 盈利 |

#### 1.5.2 代码内可选调优项（未写入 .env 时使用默认值）

| 变量 | 默认 | 作用 |
|---|---|---|
| `TAKER_FEE_RATE` | 0.001 | 保本价、盈亏口径使用的手续费率 |
| `BUY_BALANCE_MARGIN` | 1.1 | 买入前余额需 ≥ MIN_BUY_AMOUNT×1.1 |
| `BUY_BALANCE_COOLDOWN_SEC` | 600 | 余额不足冷却秒数 |
| `BUY_NOTFILLED_COOLDOWN_SEC` | 300 | 买入未成交冷却秒数（不进黑名单） |
| `SELL_BLOCK_RETRY_SEC` | 120 | 挂单冻结/粉尘受阻的重试间隔 |
| `SELL_FAIL_RETRY_SEC` | 60 | 卖出失败重试间隔 |
| `STATE_SAVE_INTERVAL_SEC` | 5 | 常规落盘闸门；degraded 时 30s |
| `HEARTBEAT_INTERVAL_SEC` | 10 | 心跳写入间隔 |
| `POSITION_AUDIT_SEC` | 300 | 运行期轻量对账周期；≤0 关闭 |
| `POS_MIN_USD` | 1.0 | 平台余额折合 USD 低于此值不建持仓 |
| `OUT_OF_RANGE_HYSTERESIS_PCT` | 0.005 | 超出范围恢复滞回带 |
| `OUT_OF_RANGE_FLIP_MIN_SEC` | 300 | 范围翻转最小间隔 |
| `WS_STALL_FACTOR` | 3.0 | 静默判定=ping 间隔×3=75s |
| `CPU_MAX_LOAD_RATIO` / `MEM_MIN_AVAILABLE_MB` | 0.7 / 80 | 降频保护阈值 |
| `NOTIFY_MAX_PENDING` / `ERROR_PUSH_THROTTLE_SEC` | 50 / 300 | 推送队列上限 / 同类错误推送节流 |
| `OKX_INIT_RETRY_MAX` / `OKX_RECOVERY_INTERVAL_SEC` | 3 / 60 | 启动账户探测重试次数 / 后台恢复周期 |
| `MARKET_THREAD_RESTART_MIN_SEC` | 30 | 行情线程拉起最小间隔 |
| `BUY_PARTIAL_TOPUP_MAX` | 1 | v5.15：部分成交买入按差额补单的最大次数（0=关闭补单） |
| `BUY_PARTIAL_FILL_TOLERANCE` | 0.95 | v5.15：实际成交额 < 委托额×该值 视为"未足额" |
| `BUY_PARTIAL_MIN_TOPUP` | 55 | v5.15：补单差额低于此值（USDT）不再追 |
| `REPROBE_BASE_SEC` / `REPROBE_MAX_SEC` | 600 / 3600 | v5.15：探测失败币对的重探退避起点/上限（秒）；v5.19 起仅服务网络类失败（环境缺失/地域限制直接黑名单） |
| `FILL_WAIT_TRIES` / `FILL_WAIT_INTERVAL` | 8 / 0.5 | v5.15：下单后成交查询次数 × 间隔（秒），合计默认 4s |

#### 1.5.3 股票池 xlsx 规范（v5.13 起）

- 来源：`INPUT_DATA` 目录下**全部** xlsx（含子目录），按路径排序解析，同名币对**保留先出现**的区间。
- 每个文件至少 2 个 sheet：
  - 第 1 个 sheet「层计算」：区间列（如 `8-16`）供 `FILTER_LAYER` 过滤；
  - 第 2 个 sheet「层计算幅度」：A=币对代码，C=同层最低→`ref_low`，D=同层最高→`ref_high`。
- 兼容旧表：文件里若有「系统参数」sheet 仍会解析（键名映射见 `PARAM_KEY_ALIASES`）。
- 当前实测：解析 2/2 个文件、108 币对、11 条跨文件重复（保留先出现）、`FILTER_LAYER` 未启用。
- 容错：任何 xlsx 打开失败会整体回退到 `config_snapshot.json`（v5.12 R16）；脏行跳过并推送告警。

#### 1.5.4 system_params（表格「系统参数」/默认值合并后）

当前生效（快照）：`buy_ratio=0.01`、`cooldown_days=7`、`trade_mode=demo`，其余保持默认。
**注意**：`total_funds`、`profit_trigger`、`stop_loss`、`profit_step`、`break_alert_max`、`break_alert_interval`、`push_interval`、`data_source` 属于**已识别但代码中无实际用途**的参数（`UNUSED_PARAMS`，1342 行），改它们不改变行为。止盈参数是代码常量：`STOP_LOSS_BASE=1.5%`、`STOP_LOSS_TRIGGER_PCT=6.5%`、`STOP_LOSS_ZERO_PCT=20%`、`STOP_LOSS_SLOPE=0.1%/1%`（589-593 行）。

### 1.6 启动与停止

**启动**

```bash
sudo systemctl start okx_real_qoder.service
sudo systemctl status okx_real_qoder.service --no-pager
journalctl -u okx_real_qoder.service -f          # 实时控制台（含 DEBUG，与 run.log 不同）
```

启动自检顺序（`main()`）：
1. 获取单实例锁 → 清理残留 `.tmp`；
2. 注册 SIGTERM/SIGINT/SIGQUIT 处理（置停止位，主循环收尾落盘）；
3. 推送通道初始化；
4. 读取股票池（失败回退快照；无有效配置但有持仓 → 只做持仓管理）；
5. 初始化 OKX 账户（最多 3 次重试；全失败且本地有持仓 → 降级运行 + 后台恢复线程）；
6. **黑名单复检**：原因为「启动检测不可交易」的记录用当前环境的 `get_instrument` 复验，可交易则自动移除；
7. 逐币对建 `SymbolState`：查 `get_instrument` → 不可交易进黑名单 / 网络异常仅标记；加载账本、冷却、配对、高低点；
8. 启动全量对账（平台余额 → 本地账本）；平台有持仓但不在池内的币对自动纳入「仅持仓管理」；
9. 同步买入队列、打印队列与余额、启动行情线程（订阅 54 个币对）、写心跳。

**停止**

```bash
sudo systemctl stop okx_real_qoder.service      # SIGTERM → 收尾（脏账本落盘、超范围审计表落盘、心跳标记 shutting_down）
```

- 二次信号（如连按 Ctrl+C）会直接强杀——收尾可能卡在网络等待上时用。
- 依赖 `Restart=on-failure`：**干净停止不会自动重启**；需要恢复运行要手动 `start`。

### 1.7 交易规则（运营口径）

#### 价格体系（17 个点位，十六等分）

对每个币对维护 `high`（历史最高）与 `low`（历史最低，随行情实时刷新的极值，来自 `high_low.csv` 与运行期极值），16 等分生出 17 个点位，分为四族：

| 族 | 卖点（上） | 买点（2下） |
|---|---|---|
| 回撤族 | `pullback_up` | `pullback2_down` |
| 回调族 | `callback_up` | `callback2_down` |
| 过渡族 | `transition_up` | `transition2_down` |
| 极限族 | `limit_up` | `limit2_down` |

#### 买入规则

1. 价格低于某买点 → 激活买入信号（记录最低价）；
2. 价格自最低点**反弹 ≥1%** 且**仍低于买点** → 触发买入（同一币对尝试间隔 ≥30s）；
3. 金额 = `max(余额×buy_ratio, MIN_BUY_AMOUNT)`，不超过余额；报价深度校验后以计价币市价单买入；
4. 前置检查：非仅持仓管理、未超计算范围、非黑名单（常规/未知/待观察）、本地无持仓、不在静默期、余额充足（≥MIN×1.1）、买入冷却已过；
5. 失败分类：合规限制（51155）→ 常规黑名单；订单限制（51201）→ 待观察；余额不足（51008）→ 冷却 600s；未成交 → 冷却 300s；其他 → 未知异常黑名单。

#### 卖出规则（v5.8 口径，每个行情 tick 实时评估）

- **动态止盈**：盈利 ≥6.5% 激活；止盈价 = max(峰值×(1−回撤容忍), 成本×1.05)，回撤容忍从 1.5% 起每多 1% 盈利减小 0.1%，到 20% 归零；价格跌穿止盈价且 ≥保本价（含双边手续费 0.1%×2）→ 市价清仓；跌破保本价则保留激活继续等。
- **盈利 ≥20%**：立即清仓。
- **回本清仓**：持仓期间最大亏损 ≤−5%，价格回到保本价之上 → 无条件清仓。
- **配对卖点**：亏损史 >5% 的持仓，价格触碰配对卖点且 ≥保本价 → 清仓（回本豁免）；普通持仓到达配对卖点不直接卖，交给动态止盈处理。
- 卖出前后都会与平台可用量核对（挂单冻结 → 保留记录延后重试；粉尘不足最小下单量 → 清除记录并推送）。
- 卖出成功 → 进入静默期（`cooldown_days=7`）并从买入队列剔除。

#### 风控/状态类

- **超出计算范围**：价格越出 `[ref_low, ref_high]` → 记入 `out_of_range.xlsx`、剔出买入；回到区间（含 0.5% 滞回带，翻转间隔 ≥300s）自动恢复。
- **黑名单三类**：常规（含"启动检测不可交易"、"交易地域/合规限制"）、未知异常、待观察。
- **T0–T3**：只是账本标签（T0 止盈中/T1 盈利/T2 配对/T3 默认），不影响执行。

### 1.8 数据文件字典

| 文件 | 生产者 | 关键字段 | 说明 |
|---|---|---|---|
| positions.csv | 行情线程/对账 | position_price(qty/amount)、peak、stop、profit_triggered、max_loss_pct、market_value… | 持仓主账本；行数=在册持仓（暴露的 bug 见 P0-2） |
| pair_status.csv | 买卖/复位 | pair_type、is_paired、sell_line_price、is_sold、profit(_pct) | 每币对配对生命周期记录 |
| cooldown.csv | 卖出 | inst_id、sell_time、cooldown_until | 允许重复行（见 P2-6） |
| high_low.csv | 行情/买入 | all_time_high/low、last_update | 聚合落盘（`_HL_PENDING`，见 P2-5） |
| buy_queue.csv | 引擎 | status（待买入/静默期_排除）、ref_high/low | 当前 31 个待买入 |
| funds.csv | 买卖/退出 | remaining_funds、其余列 | ⚠ 除 remaining_funds 外恒为 0（P1-6） |
| tradeRecord.csv | 买卖 | direction、price、qty、amount、profit(_pct) | 39 买 / 16 卖；部分成交账目有误（P0-2） |
| heartbeat.json | 主线程 | ws.*、sys.*、push_pending、market_thread_alive | 原子替换写入，监控首选 |
| config_snapshot.json | 启动 | config(108)、system_params | 表格读不出来时的兜底 |
| run.log | Logger | 白名单 | ⚠ 大量运行事件不落盘（P1-5） |
| blacklist.csv / unknown_blacklist.csv / observe_list.csv | 各环节 | inst_id、reason、add_time | 手工修改需重启生效（内存集合是启动快照） |
| out_of_range.xlsx | 主线程批量 | inst_id、current_price、range、reason | 当前不存在（无越界） |

### 1.9 监控与日常巡检

**心跳（第一入口）**

```bash
cat /home/ubuntu/okx_real/okx_ding_ok_data/okx_ding_ok_heartbeat.json | python3 -m json.tool
```

重点字段：
- `ts`/`epoch`：最新心跳时间（每 10s；超过 60s 未更新 = 主循环卡死或进程亡）；
- `ws.connected` / `ws.last_msg_ts` / `ws.stall_reconnects` / `ws.thread_restarts`：行情链路；
- `open_positions` / `profit_triggered`：持仓与止盈激活数；
- `sys.degraded`：高负载/低内存降频标志；
- `push_pending`：推送队列积压；
- `market_thread_alive`。

**常用巡检命令**

```bash
# 服务与进程
systemctl status okx_real_qoder.service --no-pager
ps -p "$(cat /home/ubuntu/okx_real/okx_ding_ok.lock)" -o pid,etime,pcpu,rss,cmd

# 最近报错（控制台日志含 DEBUG/WARN，比 run.log 全）
journalctl -u okx_real_qoder.service --since "-1h" --no-pager | grep -E "\[WARN\]|\[ERROR\]"

# 买入被档原因统计（每 2 天清一次视野）
journalctl -u okx_real_qoder.service --since "-1d" --no-pager | grep -oP '(?<=\[DEBUG\] )[A-Z0-9]+-USDT 买入跳过: [^，]+' | sort | uniq -c | sort -rn | head

# 持仓与浮亏汇总
python3 - <<'PY'
import csv
rows=list(csv.DictReader(open('/home/ubuntu/okx_real/okx_ding_ok_data/okx_ding_ok_positions.csv',encoding='utf-8-sig')))
c=sum(float(r['position_amount']) for r in rows); m=sum(float(r['market_value']) for r in rows)
print(f"持仓 {len(rows)} 个 | 成本 {c:.2f} | 市值 {m:.2f} | 浮动 {m-c:.2f} ({(m-c)/c*100:.2f}%)")
PY
```

**推送事件**（飞书）：买入、卖出、止盈激活、止损触发、黑名单加入、配置快照回退、运行期对账修复、卖出受阻/失败、买入暂缓等。同类消息有节流（`push_interval` 3s / 错误 300s）。

### 1.10 故障处理手册

| 现象 | 排查 | 处置 |
|---|---|---|
| 启不来，日志「已有实例在运行」 | `cat okx_ding_ok.lock` 看 PID 是否活着 | 确认旧进程已死后重启；锁文件是 flock，进程死即自动释放，无需删 |
| 启不来，「没有可交易的币对」 | 股票池全部黑名单/池文件损坏 | 修 `INPUT_DATA` xlsx；或检查黑名单是否误杀 |
| 状态 running 但行情不动 | 心跳 `ws.connected=false` 或 `last_msg_ts` 落后 >2min | 等自动重连（3s 重试、75s 静默重连）；多次重连失败查网络/代理 |
| 某币对一直不买 | `journalctl` 搜该币对：黑名单/静默期/超范围/`_net_failed` | 确认原因后处理；**网络探测失败类当前无运行期恢复，只能重启**（P1-1） |
| 买入「未成交（冷却）」 | 正常保护（300s 冷却） | 无需干预；若持续出现见 P0-3 |
| 卖出失败/挂单占用 | 日志「卖出受阻」「API卖出失败」 | 检查 OKX 端是否有手动挂单；解冻后自动重试（120s/60s） |
| 对账告警「本地账本与平台不一致」 | 见 journal `[reconcile]` | 通常是平台手动成交/转账；程序已自动修复，人工核对盈亏记录 |
| 未知异常黑名单误伤 | `okx_ding_ok_unknown_blacklist.csv` | 删除对应行 + 重启（内存集合启动时加载） |
| 需要暂停交易 | 无全局暂停开关 | 将 `OKX_API_KEY` 置空会导致退出；建议临时改 `OKX_TRADE_MODE=local` 或 stop 服务（持仓将无人盯守，谨慎） |

### 1.11 自动化测试

```bash
cd /home/ubuntu/okx_real
/home/ubuntu/venv/bin/python3 test_okx_strategy.py       # 121 项：价位表、买卖条件、止盈阶梯、失败分类等
/home/ubuntu/venv/bin/python3 test_v514_reconcile.py     # 11 项：启动/运行期对账、幽灵配对复位等
/home/ubuntu/venv/bin/python3 test_v515_partial_fill.py  # 12 项：部分成交买/卖、瞬时错误冷却、重探、funds 聚合（v5.15 新增）
/home/ubuntu/venv/bin/python3 test_v516_batch2.py        # 23 项：批次二 C1/C4/C5/C10/C11（v5.16 新增）
/home/ubuntu/venv/bin/python3 test_v517_stale_fallback.py # 14 项：无行情持仓 REST 兜底（v5.17 新增）
/home/ubuntu/venv/bin/python3 test_v518_order_executor.py # 19 项：订单线程锁外 REST/门闩/同步回退（v5.18 新增）
```

2026-10-18 v5.18 落地后全量复跑：**200/200 全过**（121+11+12+23+14+19）。

---

## 2. 缺陷审查（Bug Review）

评级定义：**P0**=正在造成资金/账目失真（模拟盘口径为"账目/逻辑"损失）；**P1**=功能失效或长期不可用、运维盲区；**P2**=数据/边界/一致性问题；**P3**=代码质量与体验。

### 2.1 P0-1 交易环境双源割裂：demo 下单 + 主网行情/股票池 ★核心风险 ⏳ 待确认（批次二 C1/C2）

**证据（2026-10-17 实测，只读探针）**

- 池内 108 币对在模拟盘的可用性：**53 个两环境都有、55 个仅主网有、0 个仅模拟盘有**。
- 55 个主网独有币对中：
  - 18 个启动探测直接抛 `code=51001`（模拟盘无此产品）→ 被当作"网络异常"静默排除（见 P1-3）；
  - 其余 37 个返回空值 → 写进黑名单「启动检测不可交易」（文件里共 47 条此类记录）。
- 两环境都存在的 53 个币对中，有报价的 52 个里 **13 个最新价偏差 >2%**：

| 币对 | 主网价（程序看到的） | 模拟盘价（实际成交环境） | 偏差 |
|---|---|---|---|
| ANIME | 0.002781 | 56534.73 | ~200 万倍 |
| SCR | 0.02102 | 208.85 | ~99 万倍 |
| ME | 0.06211 | 8.83 | 14,117% |
| **VINE** | **0.007587** | **0.93459** | **12,218%** |
| BABYDOGE | 3.62e-10 | 1.20e-08 | 3,218% |
| MEGA | 0.04433 | 0.08654 | 95% |
| SOPH | 0.002247 | 0.00275 | 22% |
| A / STETH / BIO | 0.1083 / 2426.79 / 0.02454 | 0.0973 / 2672.31 / 0.027 | 约 10% |
| RESOLV / ASP / NOT | — | — | 5.8% / 5.7% / 2.2% |

**已发生的账目事故（VINE-USDT）**

- 2026-10-17 04:26:26 买入成交：`ordId=4015673165263015936`，`avgPx=0.8735309835294476`，数量 1,036.66，花费 **906.46 USDT**；触发原因记录为「反弹1%买入 (最低 0.007368)」——那是**主网**价格（`tradeRecord.csv` 末行、`pair_status.csv`）。
- 模拟盘 VINE 的真实价格是 0.93459（程序买入时模拟盘约 0.87 成交），即这笔交易在模拟盘口径其实约 +7%；
- 但程序用主网价 0.007587 监控，账本显示浮亏 **−898.59（−99.13%）**，且价格永远无法回到 `成本×1.05` → **永不可卖的"死仓"**，还占用了 `has_position`、静默期等仓位资源。
- 同理，凡偏差 >2% 的币对（ASP 等）一旦成交，成本与监测价错位，止盈/回本判定全部失真。

**根因**：`OKX_WS_HOST=ws.okx.com`（381 行，无模拟盘开关）+ `check_okx_available` 探测主网（1794 行）；REST 交易却带 `x-simulated-trading: 1`（1842 行）；股票池/区间来自用户侧数据管道（同为 OKX 主网口径）。三处口径未对齐。

**建议（优先级最高）**
1. **统一环境（二选一）**：① 全面转实盘（live + `OKX_LIVE_CONFIRM=YES`，小仓位起步）；或 ② 全面转模拟盘：行情源切到模拟盘 WS `wss://wspap.okx.com:8443/ws/v5/public?brokerId=9999`（已实测可连、可订阅）、股票池改用模拟盘数据生成、区间用模拟盘高低点。
2. **无论选哪边，加启动自检**：对每个池内币对验证「当前环境 `get_instrument` 成功 + 价格与区间同源」，失败必须汇总告警而不是静默排除。
3. 对两环境价差 >2% 的币对做**入池前过滤**（当前 13 个在池内属于天然风险源）。
4. VINE 残局处理：程序按主网价永远不会触发卖出，需在 OKX 模拟盘手工平仓（成本口径修正），平仓后运行期对账会自动清除本地持仓/幽灵配对记录，再手工校正 `pair_status.csv` 中该笔盈亏，避免继续污染统计。

### 2.2 P0-2 部分成交卖出 → 账本整笔清零 + 假盈亏 ✅ 已修复（批次一，v5.15）

> **修复落地（2026-10-18）**：`_execute_sell` 部分成交时按成交比例结转成本（`cost_sold = position_amount × fill_qty / qty`）、保留余量与止盈激活状态、记录部分盈亏（tradeRecord 标注「部分成交」）、推送提醒并退避 `SELL_BLOCK_RETRY_SEC` 再评估；只有成交 ≥99.9% 才走清零收尾。冒烟验证：100 持仓卖 30 → 余 70/成本 700、盈亏按 30% 成本计。**历史 4 条 pair_status 错账的校正属批次二（C6）**。

**代码路径**：`_execute_sell`（2788-2930 行）：卖出前核对平台可用量（2800-2838），但在**成交回执后没有检查部分成交**：

```python
2869  if fill["qty"] < qty * 0.999:
2870      self.logger.warn(... "卖出按 lotSz 取整/部分成交: ...", "sell_execute")   # 只打日志
2876  profit = amount - self.position_amount          # 用"全额成本"算盈亏
2886-2889  has_position=False; position_qty=0; position_amount=0   # 整笔清零
```

只警告、不清算部分，且清零全部记录 → 已实现盈亏错得离谱，**未卖出的剩余数量从此脱管**（下一次启动对账时才按当时市价重新入账，成本基准被静默重置）。

**实证（本次逐单复核，订单状态均为 `canceled` = 部分成交被取消）**

| 日期 | 币对 | 订单号 | 委托量 / 实际成交 | 实际成交比例 | tradeRecord 记录盈亏 | 真实盈亏（约） | 剩余量去向 |
|---|---|---|---|---|---|---|---|
| 10-13 | IOST | 4005472144582639616 | 239,013.52 / 215,373.86 | 90.1% | **−20.40（−10.05%）** | ≈ −0.3 | 23,639.66 于 10-13 18:14 "平台余额同步" @0.000849 |
| 10-14 | LAT | 4006791572729495552 | 203,240.97 / 99,945.71 | 49.2% | **−57.69（−51.12%）** | ≈ −0.3 | 103,295.26 于 10-14 "平台余额同步" @0.0005 |
| 10-15 | WCT | 4009568632313090048 | 2,348.37 / 2,301.18 | 98.0% | +1.64 | ≈ +3.4 | 47.18 @0.04174（粉尘，见 P1-8） |
| 10-17 | ASP | 4015258283669590016 | 24,295.12 / 8,329.38 | 34.3% | **−184.01（−66.33%）** | ≈ −1.7 | 15,965.74 于当日 21:31 对账 @0.0107 |

> 检查方法：`GET /api/v5/trade/order?instId=...&ordId=...`（带 `x-simulated-trading: 1`），对比 `sz / accFillSz / state`。

**影响**：16 笔卖出累计记录盈亏 −138.93，其中约 −260 是错记；`pair_status.csv` 里保留的 `profit/profit_pct`（如 ASP −66.33%）会污染胜率/盈亏统计；剩余仓位"新生"成本为市价，后续所有盈亏与止盈判定基于错误基准。

**建议**：按成交比例结转成本 `cost_sold = position_amount × fill_qty / qty`；`profit_sold = proceeds − cost_sold`；持仓记账 `position_qty -= fill_qty; position_amount -= cost_sold`；只有 `fill_qty ≥ qty×(1-ε)` 时才清零。剩余数量 > minSz 时下一轮继续卖（保留原成本），小于 minSz 按粉尘流程处理。修正后需要一次性校正 `pair_status.csv` 中 4 条历史记录。

### 2.3 P0-3 部分成交买入 → 数量大幅缩水、无补单无告警 ✅ 已修复（批次一，v5.15）

> **修复落地（2026-10-18）**：`_execute_buy` 检测 `state=canceled` 且成交额 < 委托×`BUY_PARTIAL_FILL_TOLERANCE`(0.95) 时按差额自动补单（`BUY_PARTIAL_TOPUP_MAX` 默认 1 次，差额 < `BUY_PARTIAL_MIN_TOPUP`(55 USDT) 放弃），多笔成交按加权均价合并入账、单号/手续费并入记录并推送提醒；最终未足额也按实际成交入账 + WARN。冒烟验证：委托 1000 首笔仅成 15.04 → 自动补 984.96，合并账 1000/均价 1.0。

**代码路径**：`market_buy_quote`（1976-1997）按计价金额下单（`tgtCcy=quote_ccy`），`_fill_result`（1944-1965）对 `accFillSz>0` 一律按成功返回；`_execute_buy`（2715）`buy_amount = fill["cost"]` 直接入账，不检查成交额与请求额的差距。

**实证**

| 日期 | 币对 | 订单号 | 委托额（USDT） | 实际成交额 | 成交比例 | 记录仓位 |
|---|---|---|---|---|---|---|
| 10-17 | CSPR | 4015159273432682496 | 947.73 | 15.04（6,351.87 枚） | **1.6%** | 15.04 USDT（微不足道） |
| 10-17 | SAHARA | 4015446914740916224 | 916.24 | 62.42（8,006.61 枚） | **6.8%** | 62.42 USDT |

两单 `state=canceled`——模拟盘"市价单"实际按 IOC/部分撮合执行。程序把零头仓位当正常买入：占用持仓行活、进入静默期计、买卖规则照跑，而且因为金额太小，后续止盈/回本金额均为"零钱"级。

**建议**：
1. 成交额低于请求额的 95%（或低于 MIN_BUY_AMOUNT）时：按实际成交额入账并**推送提醒**；剩余差额进入冷却后**补单**（或一次性补足到目标额±2%）；
2. 若补单后仍不足 MIN_BUY_AMOUNT → 视作异常仓位（可直接市价平掉或标记人工处理）；
3. 在 `market_buy_quote` 返回中附带 `requested` 字段供上层判断。

### 2.4 P1 级问题

#### P1-1 启动探测失败"粘滞"：18 个币对整程不可买、无重试 ✅ 已修复（批次一，运行期重探）

- 证据：2026-10-17 21:31 启动 18 个币对出现「交易对查询未成功（账户/网络不可达），暂不判定为不可交易，不加入黑名单」（BLUR/EDGE/KAT/PROVE/AI/AUDF/AUDM/BRL1/IRYS/NES/PAXG/PYUSD/ROBO/TAO/USAT/USD1/USDS/WET）。
- 代码：`SymbolState.__init__` 捕获异常设 `_net_failed=True; _okx_available=False`（2381-2388）；**此后没有任何运行期重试**（`_okx_available` 仅有的恢复路径是启动快照里有平台持仓，2451-2457；或首次探测成功）；`_can_buy` 直接以「币对在黑名单/不可交易」拒买（2563-2564）。
- 后果：这些币对行情照订阅、买入信号照计算、每次触发都拒绝：两天 13,553 条「买入跳过」DEBUG（TAO 3,416、BASED 1,811、KAT 1,496、AI 1,250、IRYS 1,083、ROBO 1,077、EDGE 933、NES 874、BLUR 583、WET 518、PAXG 311、PROVE 201）。它们的真实原因是模拟盘缺产品（P1-3），在 demo 下本来就买不了——但本质上是"正确结果 + 错误机制 + 错误标签"，在 live 模式会把好币对误伤。
- 建议：给 `_net_failed`/`_okx_available=False` 的币对加**指数退避重探**（如每 10 分钟一次 `get_instrument`，成功即恢复）；区分"网络失败"与"确定不存在"（P1-3），后者进环境过滤名单而非无限刷屏。

#### P1-2 瞬时网络异常 → 永久未知异常黑名单 ✅ 已修复（批次一，瞬时错误冷却化）

- 证据：`unknown_blacklist.csv` 中 MASK-USDT：`未知错误: <urlopen error _ssl.c:983: The handshake operation timed out>`，2026-10-17 00:03:45——一次 SSL 握手里超时（完全可能自愈）被永久拉黑；FLOW/TRUMP（2026-09-13「未知错误（返回None）」）同因。
- 代码：`_execute_buy` 的错误分类（2684-2711）只放行 51155/51201/51008，其余全部 `_blacklist_unknown_error`（2775-2783），黑名单文件写入后需要**手工改 CSV + 重启**才能恢复。
- 建议：把 `urllib/socket/ssl` 类异常、`_wait_fill` 超时等划入"暂时性"（与 R5 的 300s 冷却同类处理，连续 N 次才升级黑名单）；未知异常黑名单加自动过期或定期重探机制。

#### P1-3 `code=51001` 被误判为"网络类"错误 ✅ 已修复（批次一，单列 `_env_missing`）

- 证据：18 个失败探测的 DEBUG 原文：`交易对查询异常（网络类），不做黑名单判定: code=51001 msg=Instrument ID ... doesn't exist`。
- 51001 是**确定性答复**（当前环境没有该产品），却被归入"账户/网络不可达"，导致：不写黑名单（文件不能反映真实状态）、永久阻断（P1-1）、日志诊断误导。
- 建议：解析 `OkxTradeError` 的 code：`51001` → "当前环境无此产品"（按环境过滤或写专用原因）；网络类才走 `_net_failed`。

#### P1-4 运行期对账只修一个方向；"平台同步成本"其实是市价 ◐ 部分修复（批次一：文案；成本/估值字段模型待确认 C10）

- `_audit_positions_due`（3350-3413）只清「平台已无、本地仍有」的持仓，不修数量/成本差异（设计如此，卖出前另有可用量核对——可接受）；
- 但启动全量对账 `fetch_platform_positions`（1190-1219）用 `unit_px = eq_usd / eq`——**折合市价**——作为"成本"写入账本（1253-1268），控制台还打印「成本 0.0107」（3706）。任何被补进的持仓（如 ASP 残留 15,965.74）成本=当时市价，止盈/回本判定随之漂移。结合 P0-2 的残量重入账，成本基准被静默重置。
- 建议：新增字段区分「买入均价」与「对账估值价」，或明确把这类行标记 `对账重建` 并在统计中单列；控制台文案改为「估值价」。

#### P1-5 `run.log` 写入白名单过窄，运营告警大面积丢失 ✅ 代码侧已修复（批次一：WARN 全量；旧日志归档待 C6）

- 代码：`Logger._should_write_log`（约 620 行）：仅 ERROR 全写；INFO 限 8 个分类；**WARN 只允许 `insufficient_funds / connection_error / reconcile`**。
- 后果（实测文件）：`run.log` 472 行 ERROR + **仅 1 行 WARN**；而同期 journald 里满是「交易对查询未成功」「买入暂缓」「卖出受阻」「黑名单复检」「超出范围剔除」等 WARN——全部丢弃。408 行 ERROR 还是 10-12 的历史脏数据（`could not convert string to float: '2026-10-12 03:41:11'`，v5.5 年代 bug，现已被 `_to_float` 防护，但旧日志未清）。
- 建议：WARN 全量落盘（至少加 `buy_execute/sell_execute/startup/storage` 分类）；DEBUG 提供独立开关（`LOG_LEVEL`，默认关闭或单文件轮转）；清理 408 行历史 ERROR 并留头注明。

#### P1-6 `funds.csv` 除余额外恒为零值 ✅ 已修复（批次一，真实聚合）

- `_update_funds_for_view`（2040-2056）把 `total_position_market_value / total_unrealized_pnl / total_realized_pnl` 硬编码为 `"0"`；买卖、退出时都会调用，所以该表永远长这样：

```
remaining_funds,total_position_market_value,total_unrealized_pnl,total_realized_pnl,net_asset_value,last_update
89634.69,0,0,0,89634.69,2026-10-17 21:31:44
```

- 建议：要么真正聚合 `positions.csv + tradeRecord.csv`（一次读表开销极小），要么删除误导列。

#### P1-7 买点边界抖动：两天 384 次信号重绑，反弹确认被反复重置 ⏳ 待确认（批次二 C4，参数决策）

- 代码：`update_price`（3100-3108）价格跨过买点边界时重绑信号，`_reset_buy_signal` 把 `buy_signal_lowest_price` 重置为当前价（3109-3113）——"从最低点反弹 1%"的确认因此频繁从头开始。
- 证据：journal 中 384 条「最佳买点漂移」；例：KAT 21:21:08 `transition2_down→limit2_down`，5 分 39 秒后 21:26:47 又漂回 `limit2_down→transition2_down`。
- 影响：贴线行情下买入时机被系统性推迟或错过（该买不买）；配合 P1-1 还会放大刷屏。
- 建议：重绑加死区（价格需越过边界 0.3%~0.5% 或稳定 N 个 tick）；重绑时保留原最低价（取新旧更小值）而非直接重置。

#### P1-8 残留粉尘持仓永久占位 ⏳ 待确认（批次二 C5，清理策略决策）

- 证据：IOST 23,639.66 枚（成本 20.07，市值 18.02）、WCT 47.18 枚（成本 1.97，市值 1.72）——都是 P0-2 部分卖出后的残留被对账以市价补入（`buy_reason=平台余额同步`）。
- 影响：`has_position=True` 长期占位（阻止该币对再买入——尽管静默期也在挡）；如价格不回升到止盈/回本线会无限期滞留；持仓数、市值统计被少量虚增。
- 建议：新增"清理规则"：仓位市值 < `POS_MIN_USD`（1 USDT）或数量 < minSz 时，在卖出评估里直接按粉尘流程清账（现有代码已实现该分支，只是触发条件苛刻）；或提供手工清理脚本（改 positions.csv 前必须同步核对平台余额）。

### 2.5 P2/P3 级问题（打包）

| # | 级别 | 问题 | 证据/位置 | 建议 |
|---|---|---|---|---|
| P2-1 | P2 | 买入路径先做 REST 再查静态条件 | `_execute_buy` 2655 强制刷新余额 → 2667 才 `_can_buy`；13,553 次被拒前都发了余额请求 | 先判 `_okx_available/黑名单/冷却`，再碰网络 |
| P2-2 | P2 | 买卖 REST 与 `_wait_fill`（8×0.5s）在 ENGINE_LOCK 内执行 | `on_trade` 3414-3421 持锁调 `update_price`→`_execute_buy/_execute_sell` | 下单异步队列化；至少余额查询移出锁 |
| P2-3 | P2 | `_wait_fill` 总等待 4s，偏短 | 1931-1943；慢币对可能被误判未成交 | 配置化等待（如 8s），与 not_filled 冷却配合 |
| P2-4 | P2 | `check_okx_available` 在 demo 模式仍探主网 | 1794-1805 | 按 `TRADE_MODE` 加 `x-simulated-trading` |
| P2-5 | P2 | `_HL_PENDING` 弹出竞态 | `flush_high_low` 2165 取快照 → 写盘成功后按快照键 `pop`（2184）：写盘期间新写入的极值会被误删，直到下次极值刷新 | 用版本号/generation 对比后再删 |
| P2-6 | P2 | 冷却表重复行（LAT 两条） | `cooldown.csv` | 落盘前按 inst_id 去重（保留最新） |
| P2-7 | P2 | 未知黑名单 reason 截断到 100 字符，丢失 sCode | `unknown_blacklist.csv` 多条 `...sCode': '52` 截断 | 单独记录 sCode/msg 字段 |
| P2-8 | P2 | `.env` 权限 664，含实盘 API Secret 与飞书 secret | `ls -l .env` | ~~`chmod 600`~~ **已于 2026-10-18 执行（600）**；key 轮换待办（C9） |
| P2-9 | P2 | 退出时 `NOTIFY_POOL.shutdown(wait=False)` 可能丢最后几条推送 | 3763 | 给 1-2s 收尾等待 |
| P2-10 | P2 | `load_config` 单文件失败即整体 raise → 全量回退快照 | 1541-1560 | 单文件失败跳过 + 汇总告警，其余文件继续用 |
| P2-11 | P2 | 历史脏数据未清理：run.log 408 条旧 ERROR、console.out 停更、pair_status 4 条错账 | 数据文件 | 一次性清理/归档并附注 |
| P3-1 | P3 | `_get_buy_level` 连续调用两次（3088/3090） | 重复计算 | 删一行 |
| P3-2 | P3 | `_can_buy` 内 `if balance < buy_amount` 永假（上方已 clamp） | 2592-2597 | 删死分支 |
| P3-3 | P3 | 心跳缺黑名单/池子数量等运营指标 | `write_heartbeat` | 增加字段便于远程判断"池子变了没有" |
| P3-4 | P3 | 无日志轮转策略（run.log 跨重启累积，当前 477KB） | — | logrotate 或启动时归档 |
| P3-5 | P3 | systemd `Restart=on-failure` 与运维直觉不一致（干净退出不自动拉起） | 单元文件 | 若需常驻改 `Restart=always`（注意 SIGTERM 语义）或文档化（本文档已注明） |

**批次一修复对照（2026-10-18，代码 v5.15；✅=已落地，◐=部分，⏳=待确认）**

| # | 状态 | 落地内容 / 遗留 |
|---|---|---|
| P2-1 | ✅ | `_execute_buy` 拆出 `_can_buy_light()`：黑名单/持仓/冷却等静态条件先本地判定，余额 `force_refresh` REST 只留给可能下单的尝试 |
| P2-2 | ⏳ 批次二 C7 | 锁内下单/`_wait_fill` 异步化重构（大改动，需确认） |
| P2-3 | ✅ | `_wait_fill` 等待参数可配：`FILL_WAIT_TRIES`(8) × `FILL_WAIT_INTERVAL`(0.5s) |
| P2-4 | ✅ | `check_okx_available` 在 demo 模式带 `x-simulated-trading: 1`（探测与下单环境一致） |
| P2-5 | ✅ | `flush_high_low` 落盘成功后按**等值校验**再弹出（写盘期间的新极值不再被误删） |
| P2-6 | ✅ 代码侧 | `save_cooldown_entry` 改为整表更新（同币对单行）；**存量重复行清理属 C6** |
| P2-7 | ✅ | 未知异常黑名单 reason 截断 100→300 字符（保留 sCode/sMsg） |
| P2-8 | ◐ | `.env` 已 `chmod 600`（2026-10-18）；**API key / 飞书 secret 轮换需你操作（C9）** |
| P2-9 | ✅ | 退出前最多等 2s 清空推送队列（`shutdown(wait=False)` 改为先排空） |
| P2-10 | ✅ | 股票池单文件打开失败跳过 + 打印/推送告警；仅"一个文件都没成功"才回退快照 |
| P2-11 | ⏳ 批次二 C6 | 数据清理（run.log 旧 408 行 ERROR、pair_status 4 条错账、冷却重复行）：需停机窗口 |
| P3-1 | ✅ | 删除 `_get_buy_level` 重复调用 |
| P3-2 | ✅ | 删除 `_can_buy` 内永假的 `if balance < buy_amount` 死分支 |
| P3-3 | ✅ | 心跳新增 `net_failed_symbols` / `env_missing_symbols` 计数 |
| P3-4 | ⏳ 批次二 C8 | 日志轮转（logrotate / 启动归档）：运维决策 |
| P3-5 | ⏳ 批次二 C8 | systemd `Restart=` 策略：需确认 + sudo |

---

## 3. 优化建议（按主题）

### 3.1 环境一致性（A 组，最高优先）

- **A1** 决策：统一到 demo 或 live（建议先 demo 全链路）+ 修 VINE 残局。
- **A2** demo 行情源：`wss://wspap.okx.com:8443/ws/v5/public?brokerId=9999`（已实测 101 + 订阅成功）；把 host/brokerId 做成 `.env` 开关。
- **A3** 启动"环境一致性自检"：池内每个币对验证 `get_instrument`（同环境）成功，失败清单汇总推送；价差监控（抽样 10 个币对比可交易的 demo REST ticker vs WS 价，偏差 >2% 告警）。
- **A4** 股票池生成管道对齐所选环境（区间与池子必须来自同一环境的行情）。
- **A5** 若短期无法统一：把 demo-缺产品或偏差 >2% 的币对放入独立"环境排除名单"，不再让它们进入监控/买入信号路径（减少 13k+ 无谓日志与 REST）。

### 3.2 订单执行层（B 组）

- **B1** 部分成交统一处理（P0-2/P0-3 的公共修复）：新增 `apply_fill()` 语义——买入按实际成交额与数量入账并可补单；卖出按成交比例结转成本、余量保留、下一周期继续。
- **B2** 订单状态机：`filled / partially_filled / canceled / rejected` 显式落地；`_wait_fill` 超时与 canceled 区分处理。
- **B3** 下单前校验请求额与最小单：买入金额低于 `MIN_BUY_AMOUNT` 或换算后低于 minSz×价格时直接拒绝并说明，不下单。
- **B4** 成交额容差：实际成交 < 请求 95% 时按"未足额"处理（补单/告警），≥95% 才算正常。

### 3.3 账本与对账（C 组）

- **C1** 成本结转模型（见 B1），另加对账校准入口：允许人工确认后把平台均值成本回写到指定持仓。
- **C2** 运行期对账升级：除"清除型"外，记录差异审计（数量差、成本差）→ 每日汇总推送，不自动覆盖（保留现行安全原则），但给出"一键核对"输出。
- **C3** 数据修复脚本：修正 `pair_status.csv` 4 条错账、清理重复冷却行、归档旧 run.log；脚本需 dry-run 模式。
- **C4** 统计口径：`funds.csv` 真实聚合（市值、浮动、已实现），或改名为 `balance_view.csv` 并删除 0 列。

### 3.4 可靠性/错误分类（D 组）

- **D1** 错误分类器：把"确定性错误（51001/51155/51201）"与"暂时性错误（超时/SSL/DNS/5xx）"分开；暂时性走退避重试（如 300s→600s→…上限 1h），不写黑名单。
- **D2** 探测失败重试：`_net_failed` 币对每 10 分钟重探一次；成功即恢复买入资格并推送恢复通知。
- **D3** 黑名单自动复检扩展到"未知异常"类：每 24h 尝试一次下单资格预检（只查 instrument，不下单）。
- **D4** 买入前置检查顺序（P2-1）与锁外下单（P2-2）改造。

### 3.5 可观测性（E 组）

- **E1** `run.log`：WARN 全量、DEBUG 可开关；按天轮转保留 14 天。
- **E2** 心跳增补：黑名单数量、净买入次数、最近成交时间、锁等待采样。
- **E3** 运行日报：每天推一次"持仓成本/市值/浮亏、成交笔数、未成交缩水事件、对账差异"摘要（已有数据，脚本 30 行）。
- **E4** 告警分级：资金类（卖出失败/账本不一致）立即推；环境类（探测失败/价差异常）每小时聚合推。

### 3.6 运维安全（F 组）

- **F1** `.env` 权限 600；API key 轮换（当前 key 有实盘权限）；飞书 secret 轮换。
- **F2** systemd 加固：`Restart=always`（如需常驻）+ `StartLimitIntervalSec`；`MemoryMax` 可选。
- **F3** 备份策略：每日对 `okx_ding_ok_data/*.csv、黑名单、快照` 打包备份（含 `out_of_range.xlsx`）；保留 30 天。
- **F4** 变更纪律：改股票池/参数后先跑 `test_okx_strategy.py`，再看启动日志的「解析 N/N 个文件、共 X 个币对」与自检清单。

---

## 4. 建议落地顺序

| 顺序 | 事项 | 对应问题 | 预估工作量 | 风险/收益 | 状态（2026-10-18） |
|---|---|---|---|---|---|
| 1 | 决定环境（demo 或 live），修 VINE 残局 | P0-1 | 0.5 天 + 决策 | 消除系统性错价风险 | ⏳ 待确认（C1/C2） |
| 2 | 部分成交记账修复（卖/买两侧，含补单） | P0-2/P0-3 | 1-2 天（含测试） | 账目真实；需回归 132 项测试 | ✅ 代码已落地（v5.15）；历史数据校正 ⏳ C6 |
| 3 | 错误分类 + 探测重试 + 黑名单复检扩展 | P1-1/P1-2/P1-3 | 1 天 | 恢复可用性、减少误伤 | ✅ 已落地；未知黑名单定期复检（D3）⏳ C7 |
| 4 | 买入前置检查顺序、锁外下单 | P2-1/P2-2 | 1-2 天 | 单核机器响应更稳 | ◐ P2-1 ✅；P2-2（锁外下单）⏳ C7 |
| 5 | run.log/心跳/funds/日报等可观测性 | P1-5/P1-6/P3-x | 0.5-1 天 | 运维不再盲飞 | ◐ run.log/心跳/funds ✅；日报脚本 ⏳ C8 |
| 6 | 数据清理（错账、重复行、旧日志）+ 备份脚本 | P1-8/P2-6/P2-11 | 0.5 天 | 统计口径恢复 | ⏳ 待确认（C5/C6/C8） |
| 7 | 边界死区、粉尘清理、杂项 P2/P3 | P1-7/P1-8/P3 | 按需 | 细节完善 | ◐ 杂项 P2/P3 多数 ✅（见 2.5 对照表）；死区/粉尘 ⏳ C4/C5 |

---

## 5. 附录

### 5.1 证据清单（复现方法）

```bash
# 1) 环境差异（只读，公开接口）
#    主网 vs 模拟盘 同 instId 行情：GET /api/v5/market/ticker?instId=VINE-USDT（模拟盘加 header x-simulated-trading: 1）
#    产品存在性：GET /api/v5/public/instruments?instType=SPOT&instId=VINE-USDT（同上）
# 2) 订单成交细节（只读，需签名 + 模拟盘 header）
#    GET /api/v5/trade/order?instId=ASP-USDT&ordId=4015258283669590016
#    → state=canceled sz=24295.11 accFillSz=8329.38（34.3%）
# 3) 买入跳过刷屏统计
journalctl -u okx_real_qoder.service --since "2026-10-15" --no-pager | \
  grep -oP '(?<=\[DEBUG\] )[A-Z0-9]+-USDT 买入跳过: 币对在黑名单/不可交易' | awk '{print $1}' | sort | uniq -c | sort -rn | head
# 4) 启动探测失败
journalctl -u okx_real_qoder.service --since "2026-10-15" --no-pager | grep "交易对查询异常" | grep -oP "code=\d+" | sort | uniq -c
# 5) 日志白名单缺口
grep -c "ERROR" okx_ding_ok_data/okx_ding_ok_run.log   # 472
grep -c "WARN"  okx_ding_ok_data/okx_ding_ok_run.log   # 1
# 6) 回归测试
/home/ubuntu/venv/bin/python3 test_okx_strategy.py && /home/ubuntu/venv/bin/python3 test_v514_reconcile.py
```

### 5.2 关键代码位置索引

> 行号基于审查时 v5.14；v5.15 批次一改动后有偏移（约 +230 行），请按函数名搜索定位。

| 主题 | 位置（行号） |
|---|---|
| 股票池解析 / 快照回退 | 1443-1620（`load_config_with_fallback` / `load_config`）、1396-1425 |
| 黑名单/未知/待观察 | 308-311、983-1010（复检）、1188-1269（平台对账） |
| 价格档位（17 点） | `class PriceLevels` 1621 起（`update` 约 1632-1700） |
| 买入信号与执行 | 2556-2600（`_can_buy`）、2647-2762（`_execute_buy`）、3086-3149（信号） |
| 卖出与止盈 | 2615-2626（`_can_sell`）、2788-2930（`_execute_sell`）、2957-3000（`_check_take_profit`）、589-599（止损阶梯） |
| WS 与行情 | 381-394（常量）、1780-1792（连接）、3431-3533（订阅/消息/流）、3469+（stall） |
| 主循环/看门狗/信号 | 3538-3586、3588-3766 |
| 日志白名单 | `Logger._should_write_log` 约 620 |
| REST 客户端 | 1829-1920（签名/下单）、1884-1897（余额）、1921-1997（查询/成交换算/买）、1998-2023（卖） |

### 5.3 当前关键数字汇总（供修改后对照）

- 池 108 / 订阅 54 / 可买（理论）36；黑名单 46（池内）+ 未知 7 + 观察 4；
- 持仓 24（成本 14,149.14 / 市值 12,297.81 / 浮亏 −1,851.33，−13.08%；剔除 VINE 后 −952.73，−7.19%）；
- 买入队列待买入 31；静默期未到期 11 条（10 个币对）——NEO 至 10-17 22:25、QTUM 10-18 00:00、IOST/API3 10-20、LAT 10-21（重复 2 条）、BERA 10-21、WCT 10-22、GRAM 10-23、SHIB/ASP 10-24；
- 成交史：39 买 16 卖，记录已实现盈亏合计 −138.93（含约 −260 错账）。

### 5.4 术语表

- **demo**：OKX 模拟盘（下单带 `x-simulated-trading: 1`）；**live**：实盘；**local**：本地模拟。
- **买点/卖点**：从历史高低区间按十六等分推导的触发价位（回撤/回调/过渡/极限四族，各分上/中/2下）。
- **保本价**：`position_amount/position_qty/(1−taker费率)`，即含双边手续费的盈亏平衡价。
- **静默期**：卖出后 N 天（当前 7 天）内不再买入同一币对。
- **幽灵配对**：`pair_status.csv` 显示已配对但平台/本地已无持仓的记录，v5.14 起启动与运行期对账可自动复位。
- **粉尘**：市值/数量低于最小下单量而无法卖出的残仓。

---

## 6. 修复进度台账（唯一台账，2026-10-18 v5.20 定稿）

> **断后恢复须知**：本节是修复进度的唯一台账。若工作中断，先读本节判断"哪些已做、哪些没做"，
> 避免重复实施。标记：✅=已落地并验证；◐=部分完成；⏳=未完成/待你操作。
> **版本进度**：v5.15（批次一）→ v5.16（批次二 C1~C11）→ v5.17（验证期补丁 C12）→ v5.18（批次三 C7 锁内下单重构）→ v5.19（不可交易产品直接排除）→ v5.20（全市场行情补齐）。
> 六版均已重启生效（当前进程 v5.20，2026-10-18 14:17:33 重启，PID 154114）。已完成项一律不重做。

### 6.1 批次一：已落地（代码 v5.14 → v5.15；✅=已落地，◐=部分，⏳=待确认）

**改动范围**：仅 `okx_autoTrade_TrytoConnectOKX1.py`（版本号 v5.15，文件头含完整变更日志）+ 新增
`test_v515_partial_fill.py`（12 项回归）。**未改动任何数据文件、未重启服务**。

**回归验证（2026-10-18）**：
```bash
cd /home/ubuntu/okx_real
/home/ubuntu/venv/bin/python3 test_okx_strategy.py      # 121/121 OK
/home/ubuntu/venv/bin/python3 test_v514_reconcile.py    # 11/11 OK
/home/ubuntu/venv/bin/python3 test_v515_partial_fill.py # 12/12 OK
```

| 问题 | 状态 | 落地内容 | 新增/相关开关（.env 可不填） |
|---|---|---|---|
| P0-2 | ✅ | `_execute_sell` 部分成交按成交比例结转成本（`cost_sold = position_amount×fill_qty/qty`），仅成交 ≥99.9% 才清零收尾；余量保留原成本与止盈激活状态、记录部分盈亏（tradeRecord 标注「部分成交」）、推送、退避后继续盯盘 | `SELL_BLOCK_RETRY_SEC`（既有，前批） |
| P0-3 | ✅ | `_execute_buy` 检测 `state=canceled` 且未足额时按差额补单、多笔成交加权均价合并入账、单号/手续费并入记录并推送；最终未足额按实际入账 + WARN | `BUY_PARTIAL_TOPUP_MAX=1`、`BUY_PARTIAL_FILL_TOLERANCE=0.95`、`BUY_PARTIAL_MIN_TOPUP=55` |
| P1-1 | ✅ | 探测失败币对运行期重探（指数退避 600s→3600s 封顶，每轮最多 1 个），成功恢复买入资格并推送；**v5.19 收窄：仅网络类失败重探**（详见 6.6） | `REPROBE_BASE_SEC`、`REPROBE_MAX_SEC` |
| P1-2 | ✅ | 新 `is_transient_error()`：超时/SSL/握手/连接/5xx/50011 等瞬时错误 → 冷却重试（`_buy_cooldown`），不再写未知黑名单（存量 MASK/FLOW/TRUMP 仍须人工清，见 C6） | `BUY_NOTFILLED_COOLDOWN_SEC`（既有） |
| P1-3 | ✅ | `code=51001` 单列 `_env_missing`（"当前交易环境无此产品"），日志不再误标"网络类"；`_can_buy` 诊断区分三种原因；**v5.19 改版：51001 直接写常规黑名单持久化、不再重探**（详见 6.6） | — |
| P1-4 | ✅ | 启动持仓快照打印"成本"→"估值(市价，非买入成本)"；v5.16（C10）新增 `cost_source` 字段（fill/reconcile）已落地 | — |
| P1-5 | ✅ | WARN 全量落 run.log（`_should_write_log`）；旧 408 行历史 ERROR 已于 C6 归档 | — |
| P1-6 | ✅ | `_update_funds_for_view` 真实聚合：市值/浮盈取 positions.csv、累计已实现取 tradeRecord 的 SELL 行；买卖路径改为先落账本/成交记录再刷新 | — |
| P1-7 | ✅ | v5.16（C4）买点边界死区 `BUY_REBIND_DEADBAND_PCT=0.003` 落地（保留旧最低价为可选开关，默认关） | `BUY_REBIND_DEADBAND_PCT` |
| P1-8 | ✅ | v5.16（C5）粉尘清理落地：市值 <1 USDT 且数量 <minSz 清账并推送 | `DUST_CHECK_SEC=3600` |
| P2-1 | ✅ | 新增 `_can_buy_light()`（零网络静态预检），买点复查前移；余额 `force_refresh` REST 只留给可能下单的尝试 | — |
| P2-2 | ✅ | v5.18（C7）锁内下单重构落地：新增 OrderExecutor 订单线程，`_execute_buy/_execute_sell` 拆为三段（`_buy_prepare/_buy_place/_buy_apply`、`_sell_prepare/_sell_place/_sell_apply`）；行情线程锁内只做零网络预检并投递任务，余额强刷/下单/等成交/补单全部移出锁外；每币对 `order_in_flight` 门闩防重复提交；无执行器时自动回退旧同步路径（测试与兼容） | `ORDER_EXECUTOR_ENABLED=1`（=0 回退）、`ORDER_QUEUE_MAX=64` |
| P2-3 | ✅ | `_wait_fill` 等待参数可配 | `FILL_WAIT_TRIES=8`、`FILL_WAIT_INTERVAL=0.5` |
| P2-4 | ✅ | `check_okx_available` demo 模式带 `x-simulated-trading: 1` | — |
| P2-5 | ✅ | `flush_high_low` 等值校验后再弹 `_HL_PENDING`（写盘期间新极值不再误删） | — |
| P2-6 | ✅ | `save_cooldown_entry` 整表更新（同币对对单行）；存量重复行已于 C6 去重（17→14） | — |
| P2-7 | ✅ | 未知黑名单 reason 截断 100→300 字符 | — |
| P2-8 | ✅ | .env 已 `chmod 600`；key/secret 轮换（C9）经用户决定**忽略**（模拟盘，不轮换，见 6.5） | — |
| P2-9 | ✅ | 退出前最多等 2s 排空推送队列 | — |
| P2-10 | ✅ | 股票池单文件打开失败跳过 + 打印/推送告警；"一个文件都没成功"仍回退快照 | — |
| P2-11 | ✅ | 历史数据清理已于 C6 执行（2026-10-18 02:34 停机窗口，见 6.2/C6） | — |
| P3-1 | ✅ | 删除 `_get_buy_level` 重复调用 | — |
| P3-2 | ✅ | 删除 `_can_buy` 死分支 | — |
| P3-3 | ✅ | 心跳新增 `net_failed_symbols` / `env_missing_symbols`（v5.16 又增 `reconcile_symbols`，v5.17 增 `stale_positions`，v5.18 增 `orders_pending`/`orders_in_flight`） | — |
| P3-4 | ✅ | v5.16（C8）logrotate 已装：`/etc/logrotate.d/okx_real`（周/10M、保留 8 份、copytruncate） | — |
| P3-5 | ✅ | v5.16（C8）systemd drop-in：`Restart=always`、`RestartSec=30`（原 on-failure/600s） | — |

**重启生效**：已于 2026-10-18 02:34 重启，v5.15 全部生效（心跳 `version=v5.16` 起可见
`net_failed_symbols`/`env_missing_symbols` 字段；实测 18 个币对计入 `env_missing_symbols`）。
后续 v5.16/v5.17 也已生效，见 6.2、6.3 重启验证记录。

### 6.2 批次二（v5.16，C1~C11）：已落地 + 执行记录

**改动范围**：`okx_autoTrade_TrytoConnectOKX1.py`（v5.16，含文件头变更日志）+ 新增
`test_v516_batch2.py`（23 项回归）+ `tools_v516_cleanup.py`（C6 校正脚本）+ `backup_okx_real.sh`、
`daily_report.py`（C8）。**C6 数据修正已在停机窗口执行完毕**（2026-10-18 02:34）。

| # | 状态 | 落地内容（实际执行结果） |
|---|---|---|
| C1 | ✅ | ②全面转模拟盘：demo 模式行情 WS 改连 `wss://wspap.okx.com:8443/ws/v5/public?brokerId=9999`（`OKX_WS_DEMO=auto\|always\|never` 可强制）；订阅错误同一币对只提示一次。重启日志实证"OKX WebSocket 连接成功（模拟盘行情 wspap.okx.com）" |
| C2 | ✅ | VINE 随环境统一自动了结：不再需要手工平仓——切模拟盘后按模拟盘价（0.93）由"亏损超5%回本清仓"豁免路径自动市价卖出（2026-10-18 02:45:42 首单已自动成交部分，余量持续自动重试，见 6.3） |
| C3 | ✅ | 补单默认参数接受（补 1 次/差额≥55 USDT/容差 95%）；**未加**"零头平仓" |
| C4 | ✅ | 买点死区 `BUY_REBIND_DEADBAND_PCT=0.003`（0.3%）落地（贴线抖动不再反复重绑/复位反弹确认）。**与原建议唯一偏差**："重绑时保留更小最低价"默认关闭（`BUY_REBIND_KEEP_LOWEST=0`）——实施时被既有 R7 回归测试拦截：保留陈旧低点会重演"跳过反弹确认直接买入"的坏单，故改为可选开关（=1 开启），默认行为=重绑以当前价重新起算 |
| C5 | ✅ | 粉尘清理：持仓市值 <1 USDT 且平台可用与总量都 <minSz 时清本地账并推送（核对失败不动账本，每币对至多 1h 核对一次） |
| C6 | ✅ | 校正脚本 dry-run → 停机执行（02:34，停服约 40 秒）→ 重启。实际结果：**pair_status 4 条错账修正（18 个字段）**：IOST −20.40→−0.3244(−0.18%)、ASP −184.01→−1.7153(−1.80%)、WCT +1.64→+3.5029(+3.86%)、LAT +4.37→−1.6770(−1.49%)，且 IOST/ASP/WCT 的 is_sold 由"已卖"纠正为"余量持有"；**cooldown 去重 17→14 行**（ASP/LRC/LAT 保留较新一行）；**run.log/console.out 归档**至 `okx_ding_ok_data/archive/`；执行前整体备份至 `okx_ding_ok_data/backup_20261018-023409_pre_c6/`（回滚用）。**未知黑名单 7 条旧条目由 C11 启动复检自动清理**（无需手工） |
| C7 | ✅ | **v5.18 落地（2026-10-18，用户确认"立马实施"）**：新增 `OrderExecutor` 订单执行线程（单线程串行）；`_execute_buy/_execute_sell` 重构为三段——`_buy_prepare/_buy_place/_buy_apply`、`_sell_prepare/_sell_place/_sell_apply`（同步入出口与旧实现逐分支等价，保留给测试/回滚）；行情线程（`update_price` 5 处调用点）改走 `_request_buy/_request_sell`：锁内只做零网络预检（`_can_buy_light`/`_can_sell`/买点复查/退避检查）+ 投递任务，毫秒级返回；REST（余额强刷、market_buy_quote/market_sell_base、`_wait_fill` 等成交、部分成交补单、成交后余额）全部在锁外由订单线程执行，仅在"读本地决策/写本地账务"两个短暂阶段持 ENGINE_LOCK；每币对 `order_in_flight` 门闩防重复提交（tick 期间直接跳过）；`ORDER_EXECUTOR_ENABLED=0` 一键回退旧同步行为；无执行器（测试/独立运行）自动走同步路径。心跳新增 `orders_pending`/`orders_in_flight`。详情与验证见 6.4 |
| C8 | ✅ | ①备份脚本 `backup_okx_real.sh`（不含 .env）+ crontab 每日 03:30、保留 14 份（已实测出包）；②logrotate `/etc/logrotate.d/okx_real`（周/10M、保留 8、copytruncate）；③systemd drop-in `Restart=always`/30s；④`daily_report.py` 运行日报 + crontab 每日 09:05（飞书推送已实测成功 code=0） |
| C9 | ✅ 忽略 | 用户决定**不轮换** key/secret（模拟盘场景收益有限）。`.env` 权限 600 已完成 |
| C10 | ✅ | positions.csv 新增 `cost_source`（fill=真实成交/reconcile=对账重建估值，旧行按 buy_reason 自动推断）；启动快照打印成本来源；心跳新增 `reconcile_symbols`（当前实测 3 个） |
| C11 | ✅ | 未知黑名单自动复检：启动时批量（实测清掉全部 7 条旧条目：FLOW/TRUMP/MEGA/RE/BABYDOGE/MASK/BIO），运行期每 10 分钟至多复检 1 个，恢复即移除并推送 |

### 6.3 验证期补丁（v5.17，C12）：已落地

**问题（重启验证时实证发现）**：模拟盘行情只有部分币对持续有成交推送——VINE-USDT 订阅成功
但 40 秒 0 条成交帧（对照 BTC-USDT 同窗口 21 条）。凡"有持仓但收不到 tick"的币对，其止盈/回本
清仓评估完全停摆（VINE 历史最大亏损 −99%，随时可回本清仓却等不到行情；心跳显示约 11 个持仓
处于无行情状态）。

**修复**：`_poll_stale_positions()` REST 兜底盯盘——对"有持仓且超过 `STALE_TICK_SEC`(默认 300s)
没收到行情"的币对，按周期用 REST 最新成交价（公开接口 `/api/v5/market/ticker`，价格与下单环境
一致）喂入同一条 `update_price` 止盈/卖出评估路径；每轮最多 `STALE_POLL_MAX_PER_CYCLE`(默认 10)
个、最久未兜底优先；**卖出重试中**的持仓（部分成交/挂单占用退避）改用更短的
`STALE_TICK_SELLING_SEC`(默认 120s) 阈值并优先排队；`_env_missing` 币对跳过；REST 连续 3 次
失败中止本轮（防网络故障拖住主循环）。心跳新增 `stale_positions`；INFO 落盘白名单补上
`trade_event`（交易事件与兜底启用信息此前只飘控制台，run.log 捞不到）。

**验证记录（2026-10-18 02:48 定稿版重启后）**：
- 心跳：`version=v5.17`、`stale_positions=11`、`reconcile_symbols=3`、`net_failed_symbols=0`、`env_missing_symbols=18`；
- VINE 自动了结链路：02:45:42 由兜底价 0.93459 触发"回本清仓"，自动市价卖出成交部分
  （6.3993 股 @0.91177，已按 v5.15 口径比例结转 +0.23 USDT 入账、tradeRecord 落行；订单历史接口
  显示的 accFillSz=2.0567 与余额差额不符，以余额核对为准：1036.6567→1030.2574 恰为 6.3993）；
  之后按 120s 节奏自动重试（02:48:38 → 02:50:38 → 02:52:39 → 02:54:39…），持仓行随兜底价实时更新；
- 残量 1030.2574 股因模拟盘**买盘稀缺**（市价/限价多被模拟撮合拒绝或 0 成交）暂时只能
  "有机会就成交一点"——属模拟环境流动性限制、非程序缺陷；系统每 2 分钟自动重试直至清仓

**回归验证**：`test_v517_stale_fallback.py` 14 项新增（含日志白名单与兜底轮询各分支）；全量 5 个测试文件 **181 项全过**
（121+11+12+23+14）。`test_okx_strategy.py` 的 `make_state` 工厂同步补齐 v5.16/v5.17 新字段。

> **v5.20 升级**：C12 已推广为「全市场行情补齐」——批量接口每 60s 一轮覆盖持仓 + 买入候选，
> 逐币单查与名额轮转淘汰；本节的 `STALE_POLL_*`/`STALE_TICK_SELLING_SEC` 常量不再参与节流
> （仅保留 `STALE_TICK_SEC` 用于心跳 `stale_positions` 判定）。详见 6.7。

### 6.4 批次三（v5.18，C7 锁内下单重构）：已落地

**改动范围**：`okx_autoTrade_TrytoConnectOKX1.py`（v5.18，文件头含完整变更日志）+ 新增
`test_v518_order_executor.py`（19 项回归）+ `test_okx_strategy.py` 的 `make_state` 工厂补字段。
**未改动任何数据文件**。备份：`backups/okx_autoTrade_v517_20261018-095459.py`（改动前全量）。

**设计要点（锁内决定 → 锁外 REST → 锁内记账）**：
- 行情线程 `update_price` 的 5 处下单调用点（4 卖 1 买）改走 `_request_sell/_request_buy`：
  锁内只做零网络预检（`_can_buy_light`/`_can_sell`、买点复查、余额冷却与失败退避检查）并投递
  任务，毫秒级返回（原先余额强刷 + 下单 + 等成交最长数秒全程持锁）。
- `OrderExecutor` 单线程串行执行任务；REST（余额强刷、下单、`_wait_fill`、部分成交补单、
  成交后余额）全部在锁外；仅在 `_buy_prepare/_sell_prepare`（读本地决策）与
  `_buy_apply/_sell_apply`（写本地账务）两个短暂阶段持 ENGINE_LOCK。
- `_execute_buy/_execute_sell` 保留为同步实现（prepare→place→apply 顺序调用），与旧实现
  逐分支等价（错误分类、avail 缩放、部分成交比例结转、避退时长 30s/120s/60s 等全部保真），
  供测试与 `ORDER_EXECUTOR_ENABLED=0` 回退使用。
- 每币对 `order_in_flight` 门闩：在途期间同币对的重复买卖请求直接跳过（debug 日志）。
- 任务结束（成功/失败/异常）在 `MarketEngine._run_order_job` 的 finally 中清除在途标记并按
  闸门 flush 脏账本；订单线程队列满/停止中投递返回 False 并回滚标记。
- 新增开关：`ORDER_EXECUTOR_ENABLED`（默认 1）、`ORDER_QUEUE_MAX`（默认 64）；心跳新增
  `orders_pending`/`orders_in_flight`；提交成功落一条 `trade_event` INFO（含「订单线程执行」
  标记），运行日志可追踪"锁内提交 → 锁外成交"全链路。

**收尾修正（2026-10-18 10:44:45 重启生效）**：运行期重探遇到 `code=51001`（当前环境无此产品）
的 DEBUG 日志不再误标"网络失败"，与启动探测（P1-3）口径统一（纯日志措辞，逻辑不变；回归 200/200）。

**VINE 残量自然了结（2026-10-18 06:30:49，v5.17 生效期）**：经 C12 兜底盯盘以模拟盘价
0.89396 触发"回本清仓"，余量 1030.2574 股全部卖出，到手 920.09 USDT、**+19.23 USDT（+2.13%）**，
ordId=4018822683236110336；本地账本（positions 无 VINE、pair_status `is_sold=True`、tradeRecord
SELL 行）与平台残量均已清零——用户要求的"强制清账"由行情到达后自愈完成，**无需人工干预**。

**回归验证（2026-10-18 09:58）**：全量 6 个测试文件 **200/200**：
```bash
cd /home/ubuntu/okx_real
for f in test_okx_strategy.py test_v514_reconcile.py test_v515_partial_fill.py test_v516_batch2.py test_v517_stale_fallback.py test_v518_order_executor.py; do /home/ubuntu/venv/bin/python3 $f; done
# 121 + 11 + 12 + 23 + 14 + 19 = 200 OK
```
新测试覆盖：提交不触 REST、executor=None 同步回退、在途门闩防重复、`market_sell_base`
睡眠期间主线程仍能拿到 ENGINE_LOCK（锁外 REST 的直接证明）、on_trade 毫秒级返回、worker
买卖全流程落账、REST 异常持仓保留/回退本地量、队列满与停止投递拒绝、异常后 in-flight
必清除、心跳字段、`add_state` 注入开关、粉尘对账在途跳过。

**重启验证（2026-10-18）**：10:00:34 首启；10:04:45 补充提交日志行后二次重启；10:28:17 用户手动
stop/start（正常收尾）；10:44:45 重探日志口径修正后三次重启。服务心跳 `version=v5.18`、
`orders_pending=0`、`orders_in_flight=0`；重启后无 ERROR；订单线程为懒启动（首个订单任务时才
创建线程），当前无在途订单。首个异步订单出现时，run.log 将有「（订单线程执行）」提交行 +
「API买入/卖出成交」入账行可核对全链路。10:34/10:39 重启验证期 W-USDT、MASK-USDT 先后正常
出现买入信号激活（MASK 为 C11 复检恢复的币对），行情链路健康。

### 6.5 遗留待办（2026-10-18 v5.18 时点）

| # | 事项 | 说明 |
|---|---|---|
| 1 | ~~C9 key 轮换~~ | **用户决定忽略**（模拟盘，不做轮换；如需做随时可提） |
| 2 | ~~VINE 残量清仓~~ | **已自愈了结**（06:30:49 全量卖出，+19.23 USDT，见 6.4） |
| 3 | ~~C7 锁内下单重构~~ | **已落地 v5.18**（见 6.4） |

> 截至 v5.18，优化建议清单全部清零（C1~C12 均 ✅ 或用户明确忽略），无遗留阻塞项。

### 6.6 政策变更（v5.19，2026-10-18）：不可交易产品直接排除（用户决定）

**用户决定要点**：「产品不存在的、直接加入黑名单，不再重试，持久化保存；地域限制的也一样，这些产品都是不可交易产品」；
「已知完全不可交易的产品，加入买队列时应该被排除」。v5.15 的"环境缺失等待自动重探"（P1-1/P1-3）随之作废。

**变更对照**：

| # | 路径 | 变更前（≤v5.18） | 变更后（v5.19） |
|---|---|---|---|
| 1 | 启动探测 `code=51001` | 记 `_env_missing`、不写黑名单、等待自动重探 | **常规黑名单持久化**（reason「当前交易环境无此产品(51001)」），不再重试 |
| 2 | 启动探测 51155/compliance/restriction | 误归"网络类"（`_net_failed`）→ 无限重探 | **常规黑名单持久化**（reason「交易地域/合规限制: …」），不再重试 |
| 3 | 运行期重探 `_reprobe_due_states` | 覆盖 `_env_missing` + `_net_failed` 两类 | 仅 `_net_failed`（启动时网络抖动）；重探时才确认 51001/地域限制的**当场入黑名单并停止重试** |
| 4 | 下单错误 51001（`_buy_apply`） | 落入"未知异常黑名单"（C11 会 24h 复检恢复，与"不再重试"相悖） | **常规黑名单持久化**，不进 C11 复检通道 |
| 5 | 买入队列同步 `_sync_buy_queue_row` | 常规/未知黑名单 + 超范围剔除 | 追加 `_env_missing`/`_region_blocked` 兜底剔除（**不可交易产品绝不允许进入买入队列**） |
| 6 | 买入队列新增 `_add_to_buy_queue` | 卖出后回填"静默期_排除"（不看黑名单） | 黑名单/环境缺失/地域限制/超范围一律不落行 |

**验证（2026-10-18 11:09:22 重启生效）**：
- 重启后 20 个不可交易产品（BLUR/EDGE/KAT/PROVE/PYUSD/ROBO/WET/AI/DASH/DATA/IRYS/NES/AUDF/AUDM/BRL1/PAXG/TAO/USAT/USD1/USDS）全部落黑名单：文件 57 → 77 条（持久化），启动日志 20 条 WARN「已加入黑名单（不可交易产品，不再重试）」；下次启动命中黑名单直接跳过、不再探测。
- 买入队列 46 → 26 行（20 行剔除；剩 19 待买入 + 5 静默期 + 2 已持仓），抽查 AI/DASH/PAXG/TAO/USD1 均不在队列。
- 心跳 `version=v5.19`、`net_failed=0`；重启后 **0 条 ERROR、0 条重探日志**（此前"重探仍网络失败"刷屏消失）。
- 回归新增 `test_v519_env_missing_blacklist.py`（9 项：启动探测 51001/地域限制入黑名单并持久化、网络类不入、reason 落盘、黑名单币跳过探测、环境缺失不参与重探、队列同步剔除、队列新增拒绝、正常币不受影响）；`test_v515` 重探用例改写为新口径；主回归新增下单 51001 用例。全量 7 个测试文件 **211/211 通过**（122+11+13+23+14+19+9）。

**全量回归命令**（每次改动后重跑；=211 项）：
```bash
cd /home/ubuntu/okx_real
for f in test_okx_strategy.py test_v514_reconcile.py test_v515_partial_fill.py test_v516_batch2.py test_v517_stale_fallback.py test_v518_order_executor.py test_v519_env_missing_blacklist.py; do /home/ubuntu/venv/bin/python3 $f; done
```

### 6.7 全市场行情补齐（v5.20，2026-10-18）：用户反馈「启动后未收到行情持续」修复

**用户反馈**：「启动后未收到行情，持续这个状态什么原因，修复一下，行情数据取不到，所有计算都无法进行」；
`journalctl -n 20` 可见大量「XX-USDT 启动后未收到行情，启用 REST 兜底盯盘」以及旧进程的历史
「重探仍网络失败（51001）」。

**排查结论（回答"是不是异常"）**：
- **不是程序故障，是模拟盘行情源特性**：公共 WS 只推成交帧（`trades` 频道），模拟盘冷门币对长时间
  无成交，整程收不到 tick。实证：v5.19 重启后 26 个持仓中 22 个"启动后未收到行情"；且"买入候选
  （无持仓币对）"此前**完全没有兜底**，买点/反弹/漂移计算完全停摆。
- 用户看到的 51001 重探行均来自**旧进程**（PID 139000，10:38，v5.19 之前）；v5.19 起这些产品已入
  黑名单不再重试——重启后复测 0 条。
- 实测批量接口 `GET /api/v5/market/tickers?instType=SPOT`（带模拟盘标头）**一次 0.08s 返回全部
  565 个现货最新价**，冷门币对（NOT/MERL/CSPR/IOST 等）全部有数据——足以作为全市场行情底座。

**变更内容（v5.20；策略阈值与买卖规则未动）**：
- 新增 `fetch_all_ticker_prices()`：批量最新价（公开接口、锁外调用）；**报价兜底**——从未成交的新
  上市产品（last 为空）用买一/卖一报价（实证 RE-USDT：instruments 状态 live 但 0 成交、仅 bidPx 0.7455）。
- `_poll_stale_positions`（v5.17 C12）改写为 `_poll_market_gap`：每 `MARKET_GAP_INTERVAL_SEC`
  （默认 60s）一轮，把"静默超过 `MARKET_GAP_TICK_SEC`（默认 45s）"的币对**全部**喂入同一条
  `update_price` 路径——
  - 覆盖**持仓 + 买入候选**（可交易且未在常规/未知黑名单、观察列表、超范围；`position_only` 无仓不喂）；
  - 不可交易产品（环境缺失/地域限制）跳过；卖出重试中的持仓排序最前（退避到期尽快重试）；
  - 逐币单查（旧 C12）与「每轮最多 N 个」名额轮转**淘汰**（批量成本 1 次请求，不再需要）。
- 心跳新增 `market_gap_fed`（上轮补齐喂入数量）；首次补齐每币对打印一次
  「启用 REST 行情补齐（最新价 …）」；批量不可用/币对缺失仅 DEBUG 且下轮自动重试。

**验证（2026-10-18 14:10:05 与 14:17:33 两次重启）**：
- 首轮补齐在启动 6 秒内完成：42~45 个币对一次性补齐（含全部持仓与买入候选）；此后每 60s 一轮，
  心跳 `market_gap_fed` 稳定 38~40、`stale_positions=0`——**"启动后未收到行情"不再持续**（转为受控的
  60s 自动补价，每币只提示一次日志）。
- 冷门币对计算恢复流动：重启后 W-USDT / MASK-USDT / BIO-USDT 等在首轮补价即激活买入信号（此前要靠
  偶发成交帧）；RE-USDT 报价兜底生效（0.7455 补齐一次，因超出计算范围被正确移出买入列表，不参与交易）。
- 0 条 ERROR、0 条 51001、0 条补齐异常；心跳 `version=v5.20`、`orders 0/0`、`ws true`。
- 回归：`test_v517_stale_fallback.py` 重写升级（14 → 22 项：批量接口解析/报价兜底/持仓+候选喂入/
  排除规则/节流/缺失币对容错/卖出优先排序）；全量 7 个测试文件 **219/219 通过**（122+11+13+23+22+19+9）。
- 备份：`backups/okx_autoTrade_v520_20261018-141004.py`（v5.20 首版）、
  `backups/okx_autoTrade_v520_20261018-141733.py`（报价兜底版）。

**全量回归命令**（每次改动后重跑；=219 项）：
```bash
cd /home/ubuntu/okx_real
for f in test_okx_strategy.py test_v514_reconcile.py test_v515_partial_fill.py test_v516_batch2.py test_v517_stale_fallback.py test_v518_order_executor.py test_v519_env_missing_blacklist.py; do /home/ubuntu/venv/bin/python3 $f; done
```

### 6.8 概念落地（v6 计划，2026-10-19）：阶段 1/2/3 已上线（◐，v6.0），阶段 4/5 待做
- 依据：`okx_real手写稿程序优化-清单确认.md`（用户逐条答复）+ `概念定义整理与待确认清单.md`（Q1~Q17）；
  设计单：`概念落地设计单_v1.md`（第一部分=已确认直接实施；第二部分=待确认放最后）。
- 数据核对：主数据文件 sheet3「历史幅度计算」就位（117 币，D..S 十六档，B/C 线性 16 等分；LAT [0.0003474, 5] → 回撤上 4.68752）；
  「已精减汇总.xlsx」无 sheet3（读取容忍缺表）；`已涨幅度.xlsx` Sheet1 结构就位（F..U 现空）。
- 已确认待实施（⏳）：层梯表=固定层界 [F/b, F/a] 16 等分（sheet1/sheet2 固定输入）；换层替代超范围剔除；
  买点收敛两类（回撤下=高位买点 / 极限下=低位买点；120 分钟+守卫+取消/作废转移）；清仓三条
  （已涨幅度回撤上 / 破高位中间 / 破地板）+ 回本清仓保留；动态止盈改"已涨幅度无效（空或<5%）时兜底"；
  清除 1% 反弹、四档买点、漂移重绑、配对卖点回本豁免、碎股清理定时任务；`已涨幅度.xlsx` 动态维护与推送（≥20s 节流）；
  sheet3 历史幅度：回撤上出局提醒、极限下机会提醒、回撤下历史买点、低位中间/极限上/极限中/极限下穿越提醒+轨迹表。
- 用户答复（2026-10-19 已全部确认，含 4 处修正）：Q5=**A**（固定中点 12.5/16）；Q7=限价买单@执行价（同意）；
  清仓限价暂定=买一价+15s 重挂（同意）；sheet3：**历史买点=价格自下上破极限下→买入**（修正原"回撤下买入"），
  上破极限中/极限上/低位中间=仅提醒+轨迹，下破回撤上=有持仓清仓+提醒、无持仓仅提醒，轨迹表=新建 `历史提醒记录.xlsx`，
  **B/C 由程序随新高/新低自动合并更新**（不回写输入文件）；`已涨幅度.xlsx` **只写 A~E**（F..U 保留文件公式自动计算）；
  回本清仓下一买点按买入类型（高位买入→本层低位买点；低位买入→下一层高位买点）；.env 参数名确认（RISEN_RANGE_MIN_PCT=0.05 等）。
  答复归档：`概念落地设计单_v1.md`（v1.1）第二部分。
- 实施进展（2026-10-19）：**阶段 1 基础件已入库**——`LayerLadder`（层界 [low, high] 梯表，换层=层界 ×2/÷2）、
  `LayerSwitchTracker`（越界换层，一次跨多层）、`HistoryRange`（sheet3 历史幅度，新高/新低内存合并）、`_read_history_sheet`（sheet3 解析）。
- 实施进展（2026-10-19，**阶段 2+3 已上线并重启生效，版本 v6.0**）：
  - 买点状态机（限价买）：高位买点=下破回撤下(13/16) 激活 → 120min 不创新低且不破高位中间(12/16) → ≤执行价(12.5/16) 限价买入；
    低位买点=≤极限下(1/16) 激活 → 120min 不创新低且不破地板 → ≤执行价(0.5/16) 限价买入；回升上破激活线=撤信号；
    破高位中间=作废（下一买点=低位买点，深区自动转移；上层屏蔽 `next_layer` 由换层解除）。限价单**按 tickSz 对齐取整并格式化**
    （防 51006 拒单）；限价单挂着未成交 → 自动撤单（防孤儿挂单），交回重试路径。旧机制清除：四档买点、1% 反弹确认、
    漂移重绑、买入队列消费、超范围剔除（`out_of_range` 门槛移除）。
  - 清仓（限价卖，暂按最新价；**15s 重挂机制待补**）：①已涨幅度（新低→最低+最高重置；新高→仅最高）有效（≥5%）且启用后破回撤上(15/16)；
    ②高位买点持仓破**买入层**高位中间(12/16)；③低位买点持仓破**买入层**地板；④回本清仓保留；已涨幅度无效或迁移未启用 → 动态止盈兜底。
    下一买点：清仓①→本层高位买点；②/回本(高位买入)→低位买点；③/回本(低位买入)→下一层高位买点。
  - 换层：价格越界自动 ×2/÷2（替代超范围剔除）；无持仓向上换层=忽略并屏蔽（不高位接盘），回落换层后恢复；
    下破地板=下一层按梯表评估。
  - 数据清理（用户指令）：`okx_ding_ok_out_of_range.xlsx`、`okx_ding_ok_buy_queue.csv`、`okx_ding_ok_pair_status.csv`、
    `okx_ding_ok_high_low.csv` 移入 `okx_ding_ok_data/archive/v6_cleanup_20261019-103945/`（归档可回滚）；
    positions/cooldown/tradeRecord/funds/心跳等保留；v6 不再读写超范围/配对/累计高低/买入队列。
  - 存量持仓迁移：29 条按 legacy 接管，已涨区间播种 [min(买价,现价), max(买价,现价)]，**创出播种新高后启用清仓①**
    （防上线即连环清仓）；legacy 无清仓②③（无买入层固定档位）。
  - 验证（2026-10-19 三次重启：10:39:43 PID 230815 → 10:41:48 PID 231075 → 10:46:51 PID 231506，当前运行中）：
    心跳 `version=v6.0`、ws 连接、29 持仓、orders 0/0、0 条 ERROR/Traceback；
    **LAT 触及层顶自动换层** [0.00030518, 0.00061035]→[0.00061035, 0.00122070]（旧机制=超范围剔除，已废除）；
    RE/STETH 等同样自动换层；REST 补价约 51 币正常；迁移播种 29 条齐（第三次重启起 28 条=TRUMP 已持久化、不再重复播种）。
  - 上线当日读日志/复核数据发现并修复的三个问题（均修复并重启验证）：
    ① **限价单价格未对齐 tickSz**（必被交易所按 51006 拒单）：`_place_order` 增加 `_round_to_tick`
      （Decimal 取整到最近档）与 `_fmt_px`（按 tick 小数位格式化，防科学计数法）；
    ② **legacy 已涨幅度推送过早**：推送条件加 `risen_armed`（legacy 创出播种新高、真正启用清仓①时才推送）；
    ③ **positions.csv 整表重写"洗掉"v6 字段**（根因：`load_positions` 重建字典时丢弃新列——未标脏行经
      load→save 后 entry_type/risen 归零，重启重复播种）：`load_positions` 原样带回 v6 九字段；
      新增 `TestRisenPersistence` 专项回归。修复后实测：29/29 行持久化，多轮 flush 后不丢。
  - 测试：专项 `test_v6_ladder_core.py` 重写（12 项：bounds API 11 + positions 持久化回环 1）；策略测试 `TestBuySignalRebind`→`TestV6BuyFsm`（9 项）、
    v516 死区类→`TestV6SignalTransitions`（3 项）、超范围热点→换层断言；测试桩补 `px`/`entry_type` 形参与 v6 字段。
    全量回归 **233/233 通过**（125+11+13+22+22+19+9+12）。
  - 备份：`backups/okx_autoTrade_v6.0_20261019-103917_初版.py`（阶段 2/3 初版）；回滚基准（v5.20）不变。
  - 后续：阶段 4（`已涨幅度.xlsx` A~E 读写 + 推送）、阶段 5（sheet3 提醒/轨迹/历史买点 + `历史提醒记录.xlsx`）、清仓限价 15s 重挂补强。
  - 巡检修复批次（2026-10-19 13:20:03 重启生效，PID 9209；用户授权三处）：
    ① 清仓3 下一买点：下破换层当拍 `_v6_layer_check` 已清零标记，但清仓3 分支又置 `"next_layer"`，把下一买点
      多屏蔽一层（复买执行价≈设计的一半）→ 改为保持空标记，在已下移的当前层按"下一层高位买点"评估；
    ② 地板等值边界：低位买点三处守卫 `price > floor` → `>= floor`（恰好等于地板=未破地板，
      按设计"不破地板 + ≤0.5/16 执行"仍合格）；
    ③ 静默期废止（用户决定"全部不再冻结"）：`_sell_apply` 全清分支不再写静默期与 `静默期_排除` 队列行——
      v5"卖出后 7 天禁买"会冻结设计单规定的"清仓后下一买点"（原"保留"口径由本批次替代；
      cooldown 读取路径与 `COOLDOWN_DAYS` 字段保留兼容，不再有新写入）。
    测试：新增 `test_exact_floor_activates_and_fires`、`TestV6ClearNextBuy.test_qing3_next_buy_evaluates_in_shifted_layer`
    （含"卖出不写静默期"断言）；全量回归 **235/235**（127+11+13+22+22+19+9+12）、全链路探针 17/17；
    重启验证：心跳 v6.0、29 持仓、0 挂单、0 ERROR、无重复播种、cooldown.csv 无新行。
    备份：`backups/okx_autoTrade_v6.0_20261019-130216_清仓3下一买点+地板等值修复前.py`、
    `backups/okx_autoTrade_v6.0_20261019-131256_静默期废止前.py`。
  - 巡检记录（2026-10-19 14:30，用户操作触发；程序行为经核对正确，无策略代码改动）：
    模拟盘账户重置 + 手动卖出 BTC/ETH/OKB 换 USDT：13:45:08 运行期对账发现平台已无 29 个 legacy 持仓 →
    清本地记录并告警"请人工核对"（正确设计行为）；13:56:21 同机制再清 BTC/ETH/OKB 三个监听仓。
    当前账户 101,613.88 USDT、0 持仓（冷启动，各币 v6 买点从零评估）。
    新增回归钉扎 `TestV6BuyFsm.test_void_then_low_transfer_executes_low_buy`（高位作废 → 低位买点激活 →
    限价买入全链 + "回升高位带被 low 屏蔽不复活"断言）；`test_okx_strategy` 128 项通过。
    遗留观察：扁平币种 `v6_next_buy` 重启丢失——**已于 15:29 修复，见下条**。
   - 修复批次（2026-10-19 15:29:01 首次重启生效；15:33:12 二次重启同步启动横幅，PID 18583；用户授权）：
     ① 扁平币种 `v6_next_buy` 持久化（修复上条遗留观察）：`BUY_QUEUE_HEADER` 新增 `v6_next_buy` 列
       （旧表头读取时自动迁移补空列）；扁平态构造时从 buy_queue 行读回标记；新增 `_persist_next_buy()`
       在全部标记变化点落盘（作废/下破换层/清仓2/3/4/深区/失真清账/粉尘清账/卖出全成交），行不存在且
       可买时按启动同步同口径补建"待买入"行 → 重启不再丢失"作废→下一买点=低位买点"转移。
       部署边沿（一次性）：FET-USDT 现价 0.1923 正处于高位带 [0.19053, 0.19733) 内、且 14:01:56 作废后
       标记仅存内存 → 停服后先 seed FET 行 `v6_next_buy=low` 再启动；启动验证：FET REST 补齐价 0.1917
       落入高位带内但无"高位买点激活"（同批补齐的 BREV/MEGA 等均有换层日志，证明 FSM 确已处理行情）→
       标记读回生效、无复活。
     ② 新铁律（用户决定）：个股最大亏损 12.5% 底线——`_v6_manage_position` 在记录 max_loss 后、清仓4 前
       增判：`profit_pct ≤ -12.5%` → 市价止损清仓（优先于其余清仓规则，所有买入类型生效）；下一买点按
       买入类型（高位→low，低位→next_layer，legacy/其他→空）。卖出链新增 `market=True` 参数
       （`_request_sell/_execute_sell/_sell_prepare/_order_sell_job`/执行器任务 tuple），`sell_px=None` →
       市价单；其余清仓维持"限价@最新价"。另一条铁律"亏损>5%记录回本即清仓"为既有实现
       （清仓4 + 止盈混合口径），本批未改。
     测试：新增 `TestV6StopLoss`（市价单 px=None 断言/-12.4% 不触发/-12.5% 恰触发/优先于清仓1/低买
     next_layer 持久化）4 项；新增 `test_flat_next_buy_persists_and_survives_restart`、
     `test_flat_layer_shift_marker_persists`、`test_qing2_marker_persists_to_buy_queue` 及
     `test_deep_zone_sets_next_low` 行断言；`test_qing3_*` 输入改 0.49（避开止损线专测清仓3 链路）；
     `test_v518_*` 桩函数补 `market` 参数。全量回归 **243/243**（135+11+13+22+22+19+9+12）、
     全链路探针 18/18（新增 TestStopLossChain）。备份：
     `backups/okx_autoTrade_v6.0_20261019-144836_扁平币next_buy持久化前.py`、
     `backups/okx_autoTrade_v6.0_20261019-151702_12.5%止损前.py`。
     重启验证：15:28:25 停止（正常收尾落盘）→ seed FET → 15:29:01 启动；心跳 v6.0、0 持仓、0 挂单、
     0 ERROR；buy_queue 7 列 51 行完整、FET 行 `low` 保留（启动同步重写后仍为 low）。15:33:12 二次重启
     （同步启动日志横幅）后 FET 标记仍为 `low`，补齐价 0.1925 落入高位带仍无激活事件 → 双次重启验证通过。
     启动横幅已同步更新（卖出规则摘要加入"铁律：个股亏损达12.5%市价止损清仓"）。
   - 参数外置化批次（2026-10-19 17:25:47 重启生效，PID 26602；用户要求："明确要求在 .env 中可以调的参数
     按要求设置机制、修改代码，并用中文标注参考用途"）：全文档（设计单 v1.1 / 手写稿 / 概念清单 / 运行文档）
     梳理出"明确标注 .env 可调"的参数 = E3 四键；另按用户要求把两条铁律与动态止盈口径一并外置，共 12 键
     （`.env` 新增带中文注释的 v6 参数块，逐键注记用途与出处）：
     · 代码原已读取：`REF_LOW_MINUTES`、`RISEN_RANGE_MIN_PCT`；`RISEN_PUSH_THROTTLE_SEC` 本次接入
       已涨幅度生效推送的 interval（此前只读未用；无效/为空提示属阶段 4，届时复用同键）；
     · 新增 env 读取：两条铁律（`HARD_STOP_LOSS_PCT` 默认 0.125 / `BREAKEVEN_CLEAR_LOSS_PCT` 默认 0.05）
       与动态止盈常量 + 止盈价地板（`TAKE_PROFIT_ACTIVATE_PCT / CLEAR_PCT / TOLERANCE_PCT / TOLERANCE_SLOPE /
       BUCKET / MIN_MARGIN_PCT`）；替换全部字面量（-0.125 / -0.05 / 0.20 / 0.065 / 1.05），日志与启动
       横幅数值动态渲染；默认值=原口径，零行为变化；
     · `SELL_REPRICE_SEC` 属设计单 §4「清仓单 …… 每 15 秒撤单重挂」功能键（标注"暂定/待后续规范"，
       列在后续补强），已写入 .env 并注记"代码暂未读取"，功能落地时直接接读；
     · 安全网：env_num 缺省/空串/非法值回退默认并打印 `[配置] … 非法值`（启动 stdout → journald）；
       xlsx 死参数注释同步改为"阈值类走 .env 外置调参"口径。
     测试：新增 `TestEnvTuning` 9 项——①子进程（cwd 无 .env）验证模块级常量默认回退 + 环境变量注入全部
     生效 + 非法值回退；②进程内验证 `SymbolState` 构造即时读取三键 + 已涨幅度推送节流接线（属性值原样
     传入）；③行为级调参对照（止损线调 10% 后 -10.2% 触发/-9.8% 不动、回本门槛调 3% 后 -3.1% 记录回本
     即清、激活门槛调 5%、地板调 2%、清仓档调 15%，均含默认值对照组）。全量回归 **252/252**
     （144+11+13+22+22+19+9+12）、全链路探针 18/18。备份：
     `backups/okx_autoTrade_v6.0_20261019-171354_参数外置化前.py`。
     重启验证：无 `[配置]` 非法值告警；横幅数值渲染同口径（12.5% / 5% / 6.5% / 20%）；心跳 v6.0、
     0 持仓、0 挂单、ws 连接、行情线程存活；buy_queue 7 列 52 行、FET 行 `low` 保留；`.env` 权限 600 不变。
- 实施顺序：阶段 1 层底座（不依赖待确认项，可先行）→ 2 买点状态机+限价买入 → 3 清仓+限价卖单+删旧机制
  → 4 已涨幅度.xlsx 读写推送 → 5 sheet3 提醒/轨迹/历史买点；每阶段：备份 → 改码 → 219 全量回归+专项 → 重启验证 → 本节记录。

---

*本报告基于 2026-10-17 21:46 JST 运行态生成；此后行情与账目会变化，引用数字请注明日期。*
*2026-10-18：批次一（v5.15）→ 批次二（v5.16）→ 验证期补丁（v5.17）→ 批次三（v5.18 C7 锁内下单重构）→ v5.19（不可交易产品直接排除）→ v5.20（全市场行情补齐）全部落地并重启生效；C6 数据修正已执行；C9 经用户决定忽略；VINE 残量已自愈了结。进度以第 6 节为准。*

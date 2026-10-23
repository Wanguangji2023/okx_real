# v5.12 逐项优化日志（可中断续做）

- 目标文件: `okx_real/okx_autoTrade_TrytoConnectOKX1.py`（v5.11, 3069 行）
- 改前备份: `okx_real/okx_autoTrade_TrytoConnectOKX1.py.bak_v5.11_20261012`
- 回归测试: `cd /home/ubuntu/okx_real && .venv/bin/python -m unittest test_okx_strategy -v`
- 基线: 2026-10-12 17:52 **33 项全部通过**
- **当前状态（2026-10-12 21:05）: R1~R15 + R4（含"丢弃旧版"删除 8 个表外价位 + 表外价位复活守卫测试）全部完成，回归 106 项全通过，`VERSION` = v5.12（3382 行），并且已随用户 20:56 的手动重启**上线运行**（新 pid 203453，旧 pid 931 优雅退出）。详见文末"上线验证"。
  条目清单已无待办；后续候选见文末"尚未排期的候选"，需用户点头才开工。**
- 注意: 主程序正在运行（pid 203453，`/home/ubuntu/venv/bin/python3`，内存里已是 v5.12 代码）。**任何后续改动只落盘，不重启、不 kill 进程**，重启时机由用户决定（须用 SIGTERM，禁用 `-9`，否则走不到优雅停机落盘）。

## 恢复方法（中断后接着做）

1. 看下表"状态"列，第一条非 `完成` 的即续做起点（`完成` 一律跳过，勿重复改）。
2. 动手前先 `grep` 核对代码里是否已含该条的修改特征（防"改了但日志没写"）；
   状态为 `进行中` 的条目要人工确认改到哪一步，必要时与该条 `改动摘要` 比对。
3. 每条做完必须：跑回归测试 → 回填"状态/完成时间/改动摘要/验证" → 再进下一条。
4. 策略语义相关（R4）单独列为待确认，未获用户答复前**不得改动**。

## 条目清单

| 编号 | 内容 | 风险 | 状态 | 完成时间 | 改动摘要 | 验证 |
|---|---|---|---|---|---|---|
| R1 | `_read_csv` 读异常被吞且缓存空表 → 整表重写抹掉其他持仓/队列行 | P0 | 完成 | 2026-10-12 17:59 | 见施工记录 R1 | 39/39 通过 |
| R2 | `_write_csv_all` 的 `os.replace` 在 `CSV_LOCK` 之外 + 固定 tmp 名 → 并发串写 | P0 | 完成 | 2026-10-12 18:03 | 见施工记录 R2 | 41/41 通过 |
| R3 | 后台账户恢复线程不受 `engine.lock` 保护 → 与行情线程读-改-写竞争丢更新 | P0 | 完成 | 2026-10-12 18:08 | 见施工记录 R3 | 43/43 通过 |
| R4 | `PriceLevels.high_mid` 与 `mid` 同值 → "回调"族 5 个价位塌缩为中点、配对零毛利 | 策略 | 完成 | 2026-10-12 20:07（补充至 20:45） | 见施工记录 R4 + 补充 1/2/3（**用户 2026-10-12 答复授权后执行**；权威表逐条锁定，表外 8 价位已删并加守卫测试） | 106/106 通过 |
| R5 | "买入未成交"误判为未知异常 → 永久打入未知异常黑名单 | P1 | 完成 | 2026-10-12 18:14 | 见施工记录 R5 | 51/51 通过 |
| R6 | 卖出失败路径无退避 → 每 tick 在锁内做 10s REST + 下单 + 等待成交 | P1 | 完成 | 2026-10-12 18:14 | 见施工记录 R6 | 51/51 通过 |
| R7 | 买入信号绑死激活时刻买点：买点漂移后最低价陈旧 → 跳过"反弹1%"确认直接买 | P1 | 完成 | 2026-10-12 18:23 | 见施工记录 R7 | 56/56 通过 |
| R8 | 无 SIGTERM 处理（`finally` 只覆盖 Ctrl+C）；行情线程死亡无人监控 | P1 | 完成 | 2026-10-12 18:41 | 见施工记录 R8 | 63/63 通过 |
| R9 | 配置表一行脏数据 → `load_config` 抛异常 → `sys.exit(1)` 持仓无人盯守 | P1 | 完成 | 2026-10-12 18:46 | 见施工记录 R9 | 67/67 通过 |
| R10 | 启动期 buy_queue 整表重写 O(N²)（`__init__` 与 `add_state` 重复 `_sync_buy_queue`） | P2 | 完成 | 2026-10-12 18:55 | 见施工记录 R10 | 71/71 通过 |
| R11 | xlsx 读写在行情热路径（持锁 load+save 整个工作簿） | P2 | 完成 | 2026-10-12 19:01 | 见施工记录 R11 | 77/77 通过 |
| R12 | WS 假活：服务端停发但 TCP 不断线时永不重连 | P2 | 完成 | 2026-10-12 19:05 | 见施工记录 R12 | 79/79 通过 |
| R13 | `PROFIT_STOP_MAP` 137 行硬表实为线性公式 → 换函数 | P2 | 完成 | 2026-10-12 19:09 | 见施工记录 R13 | 82/82 通过 |
| R14 | 死代码/死配置清理（下破提醒等只建不用、`_balance_insufficient_until` 只读不写） | P2 | 完成 | 2026-10-12 19:17 | 见施工记录 R14 | 82/82 通过 |
| R15 | 小项打包：`COOLDOWN_DAYS` 重复解析未保护、合规黑名单分支未同步内存集合、滞回带窄区间永不恢复、`_round_down` 浮点少算步长 | P2 | 完成 | 2026-10-12 19:34 | 见施工记录 R15 | 96/96 通过 |
| — | **v5.12 上线验证**（用户 20:56 手动重启，pid 203453） | — | 完成 | 2026-10-12 21:05 | 见文末"上线验证" | 9 分钟 97 INFO / 0 ERROR |
| R16 | 配置快照回退：工作簿本身读不出来仍会 `sys.exit(1)`（R9 遗留 1） | P1 | 待办 | | | |
| R17 | `buy_signal_*` 五字段不落盘，重启后激活中的买入信号丢失（R7 遗留） | P2 | 待办 | | | |
| R18 | 收尾 `finally` 里余额快照 REST 在网络不通时拖住退出（R8 遗留） | P2 | 待办 | | | |
| R19 | 窄区间恢复带被压缩后防抖弱于宽区间（R15 遗留 3） | P3 | 待办 | | | |
| R20 | `_can_buy` 的"资金不足"分支不可达（R15 遗留 2） | P3 | 待办 | | | |
| R21 | WS 分片包部分丢失不在静默检测覆盖范围内（R12 遗留） | P2 | 待办 | | | |
| R22 | 策略参数化：`profit_trigger`/`stop_loss`/`profit_step` 表里能填、代码不读 | **策略** | **待确认** | | 让参数生效会直接改变离场阈值（现值 5% vs 代码 6.5%），须用户单独点头 | |

## 逐条施工记录

（每完成一条，在此追加小节：问题、改法、涉及行、测试用例、遗留风险）

### R1 完成 · 2026-10-12 17:59 —— 读失败不得当"空表"落盘

- 问题：`_read_csv` 里 `except Exception: pass` 把 EMFILE/OOM/坏行等读失败当成"文件是空的"，
  并且把这个空结果写进 `_CSV_ROW_CACHE`（缓存键只看 stat 指纹，读失败时指纹不变 → 脏缓存一直生效）。
  而 `_save_state(force=True)` / `flush_dirty_states` / `sync_positions_from_api` / buy_queue 变更
  全是"读全表→改一行→整表重写"，一次读失败就会把其余币对的持仓、买入队列、高低点从盘上抹掉。
- 改法（不动策略语义，只加"不可信就不许整表重写"的闸门）：
  1. 新增 `_CSV_READ_FAILED` 集合：`_read_csv` 读失败时标记该文件，且**失败结果一律不进缓存**；
     任何一次成功读取立即撤销标记。
  2. `_write_csv_all` 开头检查标记：被标记则拒绝整表重写并返回 False（宁可少落一次盘）。
     追加型写入 `_write_csv_row` 不受影响（不基于读数，无抹行风险）。
  3. 落盘结果向上传播：`_write_csv_all`/`save_positions`/`save_buy_queue`/`save_pair_status`/
     `flush_high_low` 返回 bool；`_save_state` 与 `flush_dirty_states` 在写失败/被拒时
     **保留 `_state_dirty`**，`flush_high_low` 被拒时**不清 `_HL_PENDING`**（内存极值是最新值，下周期重试）。
  4. `sync_positions_from_api` 落盘被拒时返回 False（降级日志：不改盘上账本）。
  5. `_can_buy` 增加防线：`POSITIONS_FILE` 处于读失败状态时禁止买入 ——
     "读不到持仓"不等于"没有持仓"，宁漏买不重复建仓。
- 影响位置（改后行号）：`_CSV_READ_FAILED` 定义、`_read_csv`、`_write_csv_all`、`flush_high_low`、
  `save_positions`、`save_pair_status`、`save_buy_queue`、`sync_positions_from_api`、
  `_can_buy`、`_save_state`、`MarketEngine.flush_dirty_states`。
- 新增测试：`test_okx_strategy.py::TestReadFailureGuard` 6 项（坏读数不入缓存、读失败后整表重写被拒、
  脏标记/极值队列保留、读失败期间禁止买入、下次成功读自动恢复）。
- 验证：`.venv/bin/python -m unittest test_okx_strategy` → **Ran 39 tests OK**（基线 33 项未回退）。
- 遗留：读失败会持续拒绝整表写，若长期失败只靠 print 提示 —— R8/R12 一并考虑是否接入心跳与推送。

### R2 完成 · 2026-10-12 18:05 —— 整表写的临时文件与 replace 原子性

- 问题：`_write_csv_all` 用固定名 `文件.csv.tmp`，并且 `os.replace` 在 `CSV_LOCK` 之外执行。
  两个线程写同一个文件时：A 写完 tmp、释放锁 → B 打开同一个 tmp 覆写 → A 的 `replace` 把 B 的
  半截内容提成正式文件；R3 的恢复线程与行情线程同时写 positions.csv 正是这条路径。
- 改法：
  1. 新增 `_csv_tmp_path()`：tmp 名带 `pid + 线程 ident`，并发写者互不踩临时文件。
  2. `_write_csv_all`：临时文件写入 **和** `os.replace` 一并放进 `with CSV_LOCK:` 内（同锁内完成
     写→刷盘→替换→失效缓存→撤销读失败标记）。失败分支按实际 tmp 名清理。
  3. `_ensure_csv_header` 的表结构迁移路径同样改造（原来是固定 `.migrate.tmp` 且替换在锁外）。
- 影响位置：`_csv_tmp_path`、`_write_csv_all`、`_ensure_csv_header`。
- 新增测试：`TestCsvAtomicWrite` 2 项（8 个并发写者 tmp 名互不相同；两线程各写 5/9 行整表 30 轮后，
  盘上必然是其中某一方的完整表、两套前缀不混、无残留临时文件）。
- 验证：**Ran 41 tests OK**。
- 遗留：进程被 kill 时可能残留 `.tmp.<pid>.<tid>` 文件，不影响正确性，R8 里顺带做启动清理。

### R3 完成 · 2026-10-12 18:08 —— 账本读-改-写统一到一把锁

- 问题：行情线程整条链路（`on_trade` → `update_price` → `_save_state`/`flush_dirty_states`）持
  `engine.lock`，而后台账户恢复线程 `_account_recovery_worker` → `_okx_probe_and_sync` →
  `sync_positions_from_api` 的"读全表→对齐平台→写全表"**不持任何锁**，每 60 秒跑一次。
  降级运行期间它可以把行情线程刚写入的持仓行按启动时的旧快照打回（典型丢更新：刚买的币被抹掉、
  刚卖的行被复活）。`CSV_LOCK` 只保证单次文件打开互斥，救不了 read-modify-write。
- 改法：
  1. 新增模块级 `ENGINE_LOCK = threading.RLock()`；`MarketEngine.__init__` 的 `self.lock` 改为引用它
     （保持 `engine.lock` 用法不变，改动面最小；锁序恒为 ENGINE_LOCK → CSV_LOCK，无反向嵌套，不会死锁）。
  2. `sync_positions_from_api` 拆两段：**网络请求在锁外**（不把 10s 超时带进锁），
     返回后的对齐+落盘移入新函数 `_apply_platform_positions()`，全程 `with ENGINE_LOCK:`，
     并保留原有的异常兜底（失败仅打印、返回 False，不影响行情与交易）。
- 影响位置：`ENGINE_LOCK` 定义、`sync_positions_from_api`、新增 `_apply_platform_positions`、`MarketEngine.__init__`。
- 新增测试：`TestLedgerLocking` 2 项（`engine.lock is ENGINE_LOCK`；主线程持锁时平台对齐线程必须等待，
  释放后才完成并返回 True）。
- 验证：**Ran 43 tests OK**。
- 遗留：恢复线程等锁期间若行情线程正在下单（`_execute_sell` 内含 REST + `_wait_fill`，最长约十几秒），
  对齐会顺延 —— 属于预期行为，账户恢复本就不紧急。

### R5 完成 · 2026-10-12 18:14 —— 暂时性买入失败不再永久拉黑

- 问题：`OkxTradeClient.market_buy_quote` 在"下单成功但 `_wait_fill` 8×0.5s 内没查到成交"时返回 `None`，
  `_execute_buy` 把 `None` 一律当"未知错误"走 `_blacklist_unknown_error` → 币对永久进未知异常黑名单，
  只能手工改 CSV 才能恢复。低流动性、成交回执慢、`state=canceled` 都会踩到。
- 改法：
  1. `market_buy_quote` 未成交时返回可判别的 `{"not_filled": True, "state", "ord_id"}`，不再用 `None` 表示未知异常。
  2. 新增 `SymbolState._buy_cooldown()`：`_buy_blocked_until = now + BUY_NOTFILLED_COOLDOWN_SEC(默认300s)`，
     保留买入信号、限流推送一条"买入暂缓"，**不进任何黑名单**；`_execute_buy` 对 `not_filled` 和非 dict 返回都走这里。
  3. 错误分类补 51008/insufficient/balance 分支：`_balance_insufficient_until = now + BUY_BALANCE_COOLDOWN_SEC(600s)`
     —— 顺带把原本"只读不写"的死字段 `_balance_insufficient_until` 接上了真实来源（R15 的一项已在此完成）。
  4. 保持原有语义：51155/合规 → 常规黑名单；51201/订单限制 → 待观察列表；真正的未知错误 → 未知异常黑名单。
  5. 黑名单/观察列表两处补 `self.blacklist.add(...)` / `self.observe_list.add(...)`，
     让内存集合与盘上同步（此前只写 CSV，本进程内 `_can_buy` 仍按老集合判定）。
  6. `_can_buy` 新增"买入未成交冷却中"判定；`market_buy_quote` 未成交日志改 `push=False`（另有 300s 限流推送）。
- 影响位置：`BUY_NOTFILLED_COOLDOWN_SEC`/`BUY_BALANCE_COOLDOWN_SEC` 常量、`OkxTradeClient.market_buy_quote`、
  `SymbolState.__init__`(`_buy_blocked_until`)、`_can_buy`、`_execute_buy`、新增 `_buy_cooldown`。
- 新增测试：`TestBuyErrorClassification` 7 项（未成交→冷却不拉黑、空返回→冷却、冷却期内拒绝再次买入、
  51008→余额冷却、合规→仍进常规黑名单且内存集合同步、真未知错误→仍进未知黑名单、51201→待观察且内存集合同步）。
- 验证：**Ran 51 tests OK**。
- 遗留：`minSz` 过小导致的下单拒绝仍归"未知错误→黑名单"；若实测频繁出现可再细分。

### R6 完成 · 2026-10-12 18:14 —— 卖出失败退避

- 问题：`_execute_sell` 里"核对平台可用量失败"已有 30s 退避（`_sell_blocked_until`），
  但**下单失败**只推一条消息就 `return None`。价格停在止盈价下方时每个行情 tick 都会重走
  `get_balance_detail`(10s 超时) → 下单 → `_wait_fill`(最长 4s)，这些全在 `engine.lock` 内执行，
  行情接收被拖死，其余 60 多个币对的止盈判定一起停摆。
- 改法：下单失败分支同样设 `_sell_blocked_until = now + SELL_FAIL_RETRY_SEC(默认60s)`，
  推送文案补上"多久后自动重试、持仓与止盈激活状态保留"；函数开头的退避检查在 REST 之前，
  因此退避期内一次平台请求都不发。
- 影响位置：`SELL_FAIL_RETRY_SEC` 常量、`_execute_sell` 卖出失败分支。
- 新增测试：`TestSellFailureBackoff` 1 项（失败后退避、退避期内不再调用 `get_balance_detail`、持仓判定不变）。
- 验证：**Ran 51 tests OK**。
- 遗留：止盈激活 + 卖出持续失败时，最长 60s 才重试一次；若交易所长时间拒单需要人工介入（推送已限流提示）。



### R7 完成 · 2026-10-12 18:23 —— 买入信号跟着"当前最佳买点"重绑

- 问题：`_get_buy_level(price)` 每次返回**当前 levels 下仍然高于现价的那个最近买点**，而
  `PriceLevels.update()` 会随新高/新低实时重算全部价位。旧代码只在 `buy_key is None`
  （价格已不在任何买点之下）时才检查取消，一旦价格换档到别的买点，信号仍绑着**激活时刻**的
  `buy_signal_buy_level / buy_price`，`buy_signal_lowest_price` 又只向下更新、永不复位。
  实际路径（levels: 回撤1.4375 / 回调1.25 / 过渡0.96875 / 极限0.59375）：
  0.55 激活极限买点、最低价记 0.55 → 涨到 1.00（仍在回调买点之下，`buy_key` 非 None，
  既不取消也不重绑）→ 再跌回 0.58：`0.58 >= 0.55*1.01` 瞬间成立且 `0.58 < 0.59375`
  → **一路下跌中没有真实反弹，却按"反弹1%确认"买入**，且配对卖点仍是过时的"极限"。
  这正是规格文档 1.6「买入信号与买点的动态漂移」描述的问题。
- 改法：
  1. 新增 `SymbolState._reset_buy_signal()`（:2255）统一复位四个信号字段，
     买入成功路径（原 `_execute_buy` 内联的四行）改为调用它。
  2. 买入信号块重构成 `buy_key is None / else` 两支（:2698 起）：
     有 `buy_key` 时，若信号已激活且 `buy_key != buy_signal_buy_level` → 记 DEBUG 日志 +
     限流推送"🔁 买点漂移"，`_reset_buy_signal()` 后**在同一 tick 按当前买点重新激活**，
     最低价以重绑时刻价重新起算（要求一次真实反弹才买）。
  3. 取消条件不再依赖 `price >= buy_signal_buy_price`：价格回到全部买点之上时 `buy_key` 必然为
     None，直接取消；价格只是脱离旧档位则由第 2 步重绑，覆盖原来漏掉的"回升但仍低于更高买点"。
  4. 买入前先把 `buy_signal_buy_level` / `lowest` 取到局部变量（:2737）——
     `_execute_buy` 成功时会复位信号，原来的告警文案 `买点: {self.buy_signal_buy_level}` 一直打印空值。
- 影响位置：`_get_buy_level` 后新增 `_reset_buy_signal`、`_execute_buy` 买入成功复位、
  `update_price` 无持仓买入信号块与反弹判定告警。
- 新增测试：`TestBuySignalRebind` 5 项（漂移后重绑到当前买点且最低价重新起算；
  持续下行 0.55→1.00→0.60→0.58 **不得买入**（旧代码会买）；重绑后真反弹 1% 仍正常买入且
  配对为 回调/callback_up；告警文案带当前买点；价格回到所有买点之上时取消信号）。
  `make_state` 补齐 `buy_signal_*` 五个字段，测试内 stub `push_notify_throttled` 与 `_execute_buy`。
- 验证：`.venv/bin/python -m unittest test_okx_strategy` → **Ran 56 tests OK**；`py_compile` 通过。
- 遗留：
  1. 买入信号四个字段仍**不落盘**，重启后"已激活的等待中信号"丢失（需重新下穿才激活）。
     若要保活需进 POSITIONS_FILE 或单独文件，属于行为变更，另列条目等确认。
  2. 极端行情下同一 tick 内多次换档只会重绑一次（以本 tick 的 `buy_key` 为准），
     快速穿越多个档位时最低价取当前价而非本 tick 之前的更低点——偏保守（少买），不会多买。

### R8 完成 · 2026-10-12 18:41 —— 干净停机 + 行情线程看门狗 + 残留 tmp 清理

- 问题：
  1. 只有 `except KeyboardInterrupt` 走 `finally`。`kill`（默认 SIGTERM）/ systemd 停止 / 容器重启
     会让进程**当场死在 `while True: time.sleep(1)` 里**，`flush_dirty_states()` 与资金快照都不执行，
     最近 ≤5s 的持仓/配对/队列变更丢失；心跳文件也停在停机前的值，外部监控看不出程序已没了。
  2. 行情线程是 `daemon=True` 且全局唯一，它一旦意外退出（BaseException、后续改动引入的退出路径），
     主进程照常活着、心跳照常写 —— **所有币对的止盈/买入监听静默停摆，无人发现**。
  3. 崩溃或被 kill 时 `_write_csv_all` / `write_heartbeat` 的 `.tmp*` 残留永久留在数据目录（小盘 960MB）。
- 改法：
  1. `STOP_EVENT = threading.Event()`（:364，紧邻 `WS_HEALTH`）。
     `install_signal_handlers(logger)`（:3085）注册 **SIGTERM / SIGINT / SIGQUIT**（不碰 SIGHUP：
     nohup 下 SIGHUP 默认被忽略，注册反而会让学生"关终端"变成停机）。
     `_handle_stop_signal`（:3075）只置位；**第二次停止信号**恢复默认处置并 `os.kill` 当场退出，
     防止收尾卡在锁/网络等待上退不掉。
  2. 主循环改 `while not STOP_EVENT.wait(1.0)`（:3242，替代 `while True: time.sleep(1)`，
     停机响应从"下一次 sleep 结束"变为即时）；`finally` 补：收到停止信号时记一条 shutdown 日志、
     落盘后再写一次带 `shutting_down: True` 的心跳，便于外部判断"是自己关的、几关的"。
  3. 行情线程启动/看护单点化：`start_market_thread()`（:3096，线程带 name）+
     `watch_market_thread()`（:3104，`is_alive()` 为假就原样重拉，记 `WS_HEALTH`、ERROR 日志、
     限流推送"🚨 行情线程退出"）。最小重拉间隔 `MARKET_THREAD_RESTART_MIN_SEC`（默认 30s，env 可调），
     防"线程一启动就崩"铺一堆僵尸线程。心跳新增 `market_thread_alive` / `market_thread_restarts`。
  4. `stream_okx` 外层循环改 `while not STOP_EVENT.is_set()`（:3026），
     重连等待 `time.sleep(RECONNECT_DELAY)` 改 `STOP_EVENT.wait(RECONNECT_DELAY)`（:3067）——
     停机时不必再干等重连间隔，且停机后不再发起新的 WS 连接。
  5. `sweep_stale_tmp_files()`（:187）在 `acquire_single_instance_lock()` 之后（:3126）清理
     `*.tmp*` 残留：只扫 11 个自有数据文件的前缀，**跳过 mtime 距今 <60s 的**（万一锁失效双实例，
     不碰别人正在写的临时文件），非 tmp 文件一律不删。
- 影响位置：新增 `import signal`、`STOP_EVENT`、`MARKET_THREAD_RESTART_MIN_SEC`、
  `sweep_stale_tmp_files`、`_handle_stop_signal`、`install_signal_handlers`、`start_market_thread`、
  `watch_market_thread`；改动 `stream_okx` 外循环与重连等待、`main()` 启动/主循环/`finally`。
- 新增测试：`TestSignalAndWatchdog` 6 项（三个信号都注册且置位；二次信号恢复 SIG_DFL 并 `os.kill`
  ——用假 `os` 捕获、测后还原；`STOP_EVENT` 置位时 `stream_okx` 立即返回且**不调用** `connect_okx_ws`；
  看门狗重拉死线程并写 `WS_HEALTH`；退避窗口内不重复拉起；活线程原样返回）+
  `TestStaleTmpSweep` 1 项（只删过期 tmp，保留新 tmp 与非 tmp 文件）。
- 验证：`.venv/bin/python -m unittest test_okx_strategy` → **Ran 63 tests OK**；`py_compile` 通过。
  另做真实信号冒烟（**未触碰 pid 931**）：临时脚本导入本模块 → `install_signal_handlers` →
  主循环同构 `STOP_EVENT.wait`，`kill -TERM` 后输出 `STOPPED_CLEAN`、退出码 **0**。
- 遗留：
  1. 看门狗只处理"线程整体退出"；WS **连上但半死**（服务端停发、TCP 不断）仍要等 R12 的
     `last_recv` 超时强制重连才能覆盖。
  2. 停机收尾里的 `_update_funds_for_view(get_okx_balance(force_refresh=True))` 是一次真实 REST 调用，
     网络不通时会拖住退出（最坏 10s+ 超时）。若要更利索可挪进 try 并设短超时——属于行为微调，留待确认。


### R9 完成 · 2026-10-12 18:46 —— 一行脏配置不再掀掉整个程序

- 问题：`load_config` 里 `config[inst_id] = {"ref_high": float(ref_high), "ref_low": float(ref_low)}`
  完全没有保护。手工维护的 xlsx 里只要有一个启用币对的高/低价单元格是文本（"2元"）、空、
  或高低倒挂，`float()` 就抛 ValueError → `main()` 的 `except Exception: logger.error(...); sys.exit(1)`
  → **整个程序拒绝启动**。此时本地账本/平台上的持仓没有任何进程在盯：止盈、回本清仓、
  超范围剔除一起停摆，只剩价格自己走。次要问题：`enabled` 判定不 strip，"是 "（尾随空格）静默变"不交易"。
- 改法：
  1. 币对行逐行保护（:1233 起）：`float()` 套 `try/except (TypeError, ValueError)`，
     并补范围合法性校验 `0 < 低价 < 高价`；不合法只把该行记进 `bad_rows` 并 `continue`，
     **其余币对照常加载运行**。`bad_rows` 末尾打印点名 + 限流推送"⚠️ 配置表有脏行"（:1294）。
  2. `inst_id` / `enabled` 统一 `str(...).strip()`（enabled 再 `.upper()`），
     键名与开关都按规范化后的值入账。
  3. 未启用行（NO/空）依旧先判开关再解析，脏数据在不启用的行上不打扰、不告警。
  4. 新增纯函数 `config_startup_ok(config, held_positions)`（:1195）并在 `main()` 用它决策（:3183）：
     **配置表一行好数据都没有时，只要本地账本还有持仓就不退出**，改为"仅持仓管理"模式继续跑
     （平台持仓由既有的启动同步循环 `add_state(..., position_only=True)` 自动纳入监听，不买入），
     并 ERROR 日志 + 推送提示尽快修表；既无有效配置又无持仓才 `sys.exit(1)`（保持原语义）。
- 影响位置：`config_startup_ok`（新增）、`load_config` 币对行解析 + 脏行汇总、`main()` 空配置分支。
- 新增测试：`TestConfigDirtyRow` 4 项
  （一行脏不影响其他币对加载：文本/空/倒挂/低价为 0 四种坏行 + 一行未启用的坏数据；
   `inst_id`/`enabled` 首尾空格规范化；全部行都脏时返回空 dict 且**不抛异常**；
   `config_startup_ok` 三态决策——有配置 / 无配置有持仓 / 两者都无）。
  测试自建临时 xlsx，stub `push_notify_throttled`，`CONFIG_FILE` 测后还原。
- 验证：`.venv/bin/python -m unittest test_okx_strategy` → **Ran 67 tests OK**；`py_compile` 通过。
- 遗留：
  1. 工作簿本身读不出来（文件缺失 / xlsx 损坏 / 被 Excel 独占锁定）仍会 `sys.exit(1)`。
     要彻底免疫需要"上次有效配置快照"回退（新增一份缓存文件、改变配置来源单一性），
     属于行为变更，等用户确认后再做（可编入 R16）。
  2. 脏行只跳过该币对，**已在持仓中的币对若配置被写坏会失去买入档位**（持仓仍由 position_only
     路径继续盯卖出），这点与 R9 主目标一致，不算回归。

### R10 完成 · 2026-10-12 18:55 —— 启动期买入队列：N 次整表重写合成 1 次

- 问题：`_sync_buy_queue()` 是"整表 load → 改自己那一行 → 整表 save"，而它在启动期被调用 **2N 次**：
  `SymbolState.__init__`（:2119）一次、`MarketEngine.add_state`（:2949）又一次。
  队列表本身有 N 行，每次 save 都全量重写并 `os.fsync`（R2 的原子写）→ 启动 I/O 量级 **O(N²)**；
  60+ 币对在小盘（1 核 / 960MB）上启动要反复重写几千行次。
  另外 `__init__` 那次同步是**基于错误信息**的：此时 `has_position` / `high` / `low` / `cooldown`
  还没被 `add_state` 从账本回填，先写一遍"待买入"，紧接着 `add_state` 再改成"已持仓_排除"——
  多一次整表写，还留了一个"刚起来就误判可买"的时间窗。
- 改法：
  1. 拆出**不碰磁盘**的行级方法 `_sync_buy_queue_row(rows) -> (rows, changed)`（:2156）：
     把原方法体改成在调用方已载入的 `rows` 上操作；黑名单/超范围分支不再绕道
     `_remove_from_buy_queue()`（那又是独立的一次 load+save），改为就地过滤自己的行。
     `_sync_buy_queue()` 保留为"load → row 方法 → save if changed"，**运行期单币对语义不变**。
  2. `SymbolState.__init__` 去掉那次提前的 `_sync_buy_queue()`（:2119 注释说明）。
  3. `MarketEngine.add_state` 不再逐币对同步（:2955），新增
     `MarketEngine.sync_all_buy_queue()`（:2958）：一次 `load_buy_queue()` → 遍历
     `self.states` 逐行同步 → **只 `save_buy_queue()` 一次**；无改动则完全不写盘。
     返回值用 `save_buy_queue` 的 bool（R1），失败时 `main()` 记 ERROR，后续 tick 会自然重试。
  4. `main()` 在两个 `add_state` 循环（配置表币对 + 平台持仓 position_only 币对）都建好之后
     调用一次（:3273）。
- 影响位置：`SymbolState.__init__`、`_sync_buy_queue` / 新增 `_sync_buy_queue_row`、
  `MarketEngine.add_state`、新增 `MarketEngine.sync_all_buy_queue`、`main()` 启动流程。
- 效果：启动期队列表整表写 2N 次 → **最多 1 次**（实测单测里 12 个币对只写 1 次、无改动时 0 次）。
- 新增测试：`TestBuyQueueStartupBatch` 4 项（构造 8 个 `SymbolState` 全程 0 次队列表写；
  `sync_all_buy_queue` 12 个币对只写 1 次且四类行语义正确——已持仓_排除/静默期_排除/待买入，
  黑名单与超范围剔除、position_only 不入队、观察列表不加新行；
  内容无变化时**不写盘**；运行期单币对 `_sync_buy_queue()` 仍能独立落盘）。
- 验证：`.venv/bin/python -m unittest test_okx_strategy` → **Ran 71 tests OK**；`py_compile` 通过。
- 遗留：
  1. `add_state` 里仍逐币对 `load_high_low()/load_positions()/load_pair_status()/load_cooldown()`
     （各 N 次整表读）。这些读命中 `_CSV_ROW_CACHE`（同指纹不重读，R1 之前的 mtime 缓存）所以实际
     磁盘读远小于 N，但**表在 add_state 期间被外部改动时**会各自读到不同快照——属于可接受的小概率
     一致性问题，若要彻底消除需要"启动期账本快照"一次性传入（改动面较大，未动）。
  2. `_is_in_cooldown()` 在同步过程中可能自己触发一次整表写（静默期到期翻转），保留原行为。


### R11 完成 · 2026-10-12 19:01 —— 超范围 xlsx 审计挪出锁内热路径

- 问题：`add_to_out_of_range()` / `mark_recovered_in_out_of_range()` 是 openpyxl 的
  **整本 load_workbook + save**（解析/重压全部 sheet，小盘上几十~几百毫秒），却被
  `update_price()` 的两个翻转分支直接调用（:2698 越界剔除、:2705 回区间恢复），
  而 `update_price` 全程在 `on_trade` 的 `with self.lock`（= ENGINE_LOCK，R3 后是全局账本锁）里。
  结果：**一次超范围翻转就把所有币对的行情处理一起堵死**；行情密集时（大面积波动、
  配置改档）多个币对连续翻转，锁内串行做 N 次整本重写，止盈判定整体延迟。
  附带问题：`wb.save(OUT_OF_RANGE_FILE)` 是直接覆盖原文件（非原子），进程中途被 kill 会留下
  半截 zip 结构的 xlsx，审计表从此打不开。
- 改法：事件入队 + 主线程批量落盘。
  1. `_XLSX_OOR_OPS` 队列 + `_XLSX_OOR_LOCK`（:1030）。两个公开入口签名不变，
     改为**只入队**（:1034 / :1048）：入队时按 `(op类型, inst_id)` 去重，锁内零磁盘操作。
  2. `_apply_out_of_range_ops(ops)`（:1059）：一次 load（不存在则按 `OUT_OF_RANGE_HEADER` 新建）→
     在**同一份内存表**上应用全部事件 → 一次 save。事件顺序即入队顺序，
     `add` 与 `recover` 混在一批里也正确（先追加后改 reason）。
     "仅记一次"的判定从原来的 `load_out_of_range()`（又一次整本读）改成扫已存在行建 `excluded` 集合。
  3. 写盘改**临时文件 + `os.replace`** 原子替换（复用 R2 的 `_csv_tmp_path`），
     成功后清掉 `_XLSX_SET_CACHE` 让 `load_out_of_range()` 重新解析；失败时 tmp 被删除。
  4. `flush_out_of_range_ops()`（:1120）由 `MarketEngine.maintenance()` 每秒调用一次（:3071，
     **在 `engine.lock` 之外**，主线程执行），并在 `main()` 的 `finally` 收尾时再刷一次（:3382）。
     写失败时事件**放回队首**（可晚到，不能悄悄丢审计），下个周期自动重试。
  5. `sweep_stale_tmp_files()`（R8）把 `OUT_OF_RANGE_FILE` 也纳入前缀清理（新增的 xlsx tmp）。
- 影响位置：`_XLSX_OOR_OPS`/`_XLSX_OOR_LOCK`、`mark_recovered_in_out_of_range`、
  `add_to_out_of_range`、新增 `_apply_out_of_range_ops` / `flush_out_of_range_ops`、
  `MarketEngine.maintenance`、`main()` finally、`sweep_stale_tmp_files`。
- 权衡：xlsx 审计表最多滞后一个 maintenance 周期（~1s）；进程被 SIGKILL 时未落盘的翻转会丢记录，
  但**不影响交易判定**——`out_of_range` 是内存状态，重启后由价格与配置区间重新推导。
- 新增测试：`TestOutOfRangeDeferredWrite` 6 项（入队不碰磁盘；一次 flush 写 5 条且队列清空后不重复写；
  同币对"仅记一次"（队列内去重 + 表内已有记录不再加行）；recover 改写 reason 且
  `load_out_of_range()` 立即不再包含该币对（缓存失效正确）；写失败回队后可再次成功落盘且不留 tmp；
  `update_price` 越界翻转走热路径时**只入队、不产生 xlsx 文件**）。
  另修测试脚手架：`TempFilesMixin` 把 `OUT_OF_RANGE_FILE` 映射成 `.csv` 后缀，
  openpyxl 按扩展名拒绝读取 → 该文件现映射为 `.xlsx`（真实程序里本来就是 xlsx）。
- 验证：`.venv/bin/python -m unittest test_okx_strategy` → **Ran 77 tests OK**；`py_compile` 通过。
- 遗留：`load_out_of_range()` 仍是整本读（启动期 + `SymbolState.__init__` 各一次），
  有 `_XLSX_SET_CACHE` 指纹缓存，热路径不再调用，量级可接受。

### R12 完成 · 2026-10-12 19:05 —— 链路静默（WS 假活）主动重连

- 问题：`stream_okx` 内层循环只在 `recv_message()` **抛异常**时才走重连。
  如果 TCP 连接没断但对端不再发任何东西（NAT/中间设备把单向链路掐掉、服务端半死、订阅被静默丢弃），
  `recv` 只会不停 `socket.timeout`，而原逻辑在 `except socket.timeout` 分支里
  仅仅是"距上次收数 ≥ PING_INTERVAL 就再发一个 ping"（:3147 旧代码）——
  ping 写得进本地缓冲就永远"成功"，**程序看起来连着（`WS_HEALTH.connected` 仍为 True、
  进程活着、心跳照写），行情却无限期停摆**，止盈/买入判定全部冻结。
- 改法：
  1. 新增 `WS_STALL_TIMEOUT_SEC = PING_INTERVAL × WS_STALL_FACTOR(默认 3)`（:233，env 可调）
     —— 正常时我们自己每 25s 一次 ping、OKX 会回 pong（或自带 ping），所以 75s 全静默已非"行情清淡"。
  2. 抽出纯函数 `ws_stall_action(idle_sec)`（:3133）：`''` 继续等 / `'ping'` 发心跳 / `'stall'` 断开重连，
     阈值判断与 I/O 分离，单测直接覆盖边界。
  3. `except socket.timeout` 分支（:3163）改为按 `action` 分派：`stall` 时置
     `WS_HEALTH["connected"]=False`、`last_error="连接静默 Ns：无任何行情/pong 回包"`、
     `stall_reconnects += 1`，ERROR 日志（`push=False`，避免与限流推送重复）+
     限流推送"📡 行情静默重连"，然后 `break` 跳出内层循环 → `finally` 关闭 conn →
     外层 `while not STOP_EVENT` 重新 `connect_okx_ws()` + 重新订阅（R8 后该循环已受停止位管控）。
  4. `WS_HEALTH` 增加 `stall_reconnects` / `thread_restarts` 两个计数（:366），
     心跳文件里能直接看到"静默重连过几次、行情线程重启过几次"，`watch_market_thread` 同步写
     `thread_restarts`（R8 的看门狗计数不再只活在局部变量里）。
- 影响位置：`WS_STALL_TIMEOUT_SEC` 常量、`WS_HEALTH`、新增 `ws_stall_action`、
  `stream_okx` 的 `socket.timeout` 分支、`watch_market_thread`。
- 新增测试：`TestWsStallReconnect` 2 项（阈值边界：24s 不动作 / 25s ping / 74s 仍 ping / 75s stall；
  全静默假连接：`recv` 恒超时 → 连接被关闭一次、`WS_HEALTH.last_error` 记录"静默"、
  `connected=False`、`stall_reconnects=1`，且测后把 `connect_okx_ws`/`WS_HEALTH`/`STOP_EVENT` 全部还原）。
- 验证：`.venv/bin/python -m unittest test_okx_strategy` → **Ran 79 tests OK**；`py_compile` 通过。
- 遗留：静默阈值是"完全没收到任何帧"，若链路只是**丢部分包**（仍有零星回包）则不会触发；
  进一步可用 OKX `last` 序号/时间戳缺口检测，属于新增功能，未纳入本次。

### R13 完成 · 2026-10-12 19:09 —— 动态止盈硬表换成线性公式

- 问题：`PROFIT_STOP_MAP` 用 136 个元组硬编码 `(盈利 → 回撤容忍)`（:413 起，占 ~138 行）。
  逐点核对后确认它就是一条线性规则 + 两个边界：
  `stop = 0.015 - 0.1 × (profit - 0.065)`，按 **0.1% 分档取档低边**，
  `profit < 0.065 → 0.015`，`profit ≥ 0.20 → 0`（表里唯一一个"不线性"的点是最后一行
  `(0.200, 0)`，公式在 0.200 处会给 0.0015 —— 即"≥20% 立即清仓"是人为覆盖，不是斜率延续）。
  硬表的问题：改一个边界要重算整表、容易写出跳档/重复键，且 138 行数据把策略真正关心的
  两个参数（起点 6.5%、斜率 0.1）埋在噪声里。
- 改法：删表，`get_stop_loss()` 改为纯函数（:412-431）：
  ```python
  STOP_LOSS_BASE=0.015  STOP_LOSS_TRIGGER_PCT=0.065  STOP_LOSS_ZERO_PCT=0.20
  STOP_LOSS_SLOPE=0.1   STOP_LOSS_BUCKET=0.001
  ```
  分档用 `int(profit/BUCKET + 1e-9) * BUCKET` 向下取整到 0.1% 档低边
  （`+1e-9` 防 `0.070*1000 = 69.999…` 这类浮点截断把档位算低一档 —— 结果会更松 1 个 bp）。
- 等价性证据：改动前先把 v5.11 原表整表导出为 `doc_txt/profit_stop_map_v5.11.json`（136 档，
  2276 字节，留作回归基线），再用公式对 **1365 个校验点**（每档档低边 + 档内 9 个十分点 +
  表外上下边界）逐点比对：**不一致 0 条**。
- 影响位置：`PROFIT_STOP_MAP` 删除、`get_stop_loss` 重写、5 个 `STOP_LOSS_*` 常量。
  唯一调用点 `_check_take_profit`（`stop_ratio = get_stop_loss(profit_pct)`，
  以及 `stop_ratio == 0 and profit_pct >= 0.20` 的立即清仓分支）语义不变。
- 新增测试：`TestStopLossTable` 由 2 项扩到 5 项，改为**对着 v5.11 基线表**跑：
  逐档等价、档内等价、表外边界、单调不回松、原 5 个抽查点。
- 验证：`.venv/bin/python -m unittest test_okx_strategy` → **Ran 82 tests OK**；`py_compile` 通过。
- 遗留：`STOP_LOSS_*` 仍是代码常量（配置表里的 `profit_trigger`/`stop_loss` 两项属于
  `UNUSED_PARAMS`，见 R14），要让它们可调需要打通"系统参数 → 止盈公式"这条链，
  属于行为变更，未纳入本次。

### R14 完成 · 2026-10-12 19:17 —— 死代码 / 死字段清理

- 问题：v5.x 迭代中留下一批**只定义不使用**（或**只写不读**）的常量、字段与方法。它们不影响
  交易正确性，但会误导后续维护（"看名字像有下破提醒功能"其实整条链路没人消费），并且
  `SymbolState.__init__` 里 16 个僵尸字段随每个币对、每次状态加载白白分配 set/dict。
- 判定口径（删前逐个 `grep -c` 核对，全部只在备份里出现 1 次=仅定义，或仅"定义 + 写入"）：
  - 仅定义、无任何读取点：`DEFAULT_PUSH_INTERVAL`、`BREAK_ALERT_MAX_PER_DAY`、
    `BREAK_ALERT_MIN_INTERVAL_SEC`、`BASE_TIME_NODES`。
  - 只建不用：`below_pullback_since` / `below_callback_since` / `below_transition_since` /
    `below_limit_since`、`last_new_high_ts`、`last_new_low_ts`、`high_alert_sent`、
    `low_alert_sent`、`break_alerts`、`broken_levels`、`self.total_funds`（SymbolState 那个，
    与配置侧 `UNUSED_PARAMS` 里的 `total_funds` 无关）。
  - 只写不读：`_profit_notified_steps`（备份 3 处全是 `= set()` 赋值，无一处读取，也不落状态表）。
    `_balance_insufficient_until` 的"只读不写"已在 R6 顺带修好（见第 112 行备注），本条不再处理。
  - 空壳方法：`Logger.set_dingtalk`（v5.0 起废弃，推送通道统一由 `.env` 的 `NOTIFY_CHANNEL` 决定，
    函数体只有 `pass` 且全仓无调用）、`MarketEngine._check_buy_queue_all`（只剩一行
    "执行买入队列批量检查（备用）"日志，买入逻辑实际由 `update_price` 的反弹机制承担）。
- 改法：删除上述 4 个常量行、16 个字段定义/写入行、2 个方法；测试 `make_state()` 里同步去掉
  `st._profit_notified_steps = set()`。买入信号 5 个字段、`_last_profit` 等**在用**的下划线字段未动。
  配置侧 `UNUSED_PARAMS`（`PARAM_HEADER` 里的中文列映射、`DEFAULT_SYSTEM_PARAMS` 兜底值）三处
  `total_funds` 是活代码（用于给表里出现的无效参数名做显式忽略），保留。
- 影响位置：常量区（原 `DEFAULT_PUSH_INTERVAL` 等）、`Logger`（`_ensure_log_file` 与
  `_should_write_log` 之间）、`SymbolState.__init__`（原 1999-2015 一带）、
  `update_price` 新高/新低分支（现 `okx_autoTrade_TrytoConnectOKX1.py:2700-2708`）、
  `MarketEngine` 末尾方法之后）、`test_okx_strategy.py` 的 `make_state()`。
  文件 3069 → **3273 行**（R7~R14 累计净变化：新增功能多于删除）。
- **本次事故记录（已修复，勿重复踩）**：批量删除用的一次性脚本把 `l == "        pass"` 也列为
  匹配项，除 `set_dingtalk` 自身那处外，又误删了 1 处**合法**的 `except Exception: pass` 语句体
  （`sample_system_load`，备份第 288 行；备份第 789 行那处早在 R1 就已改成 `read_ok` 逻辑，不在场内）。
  落盘后 `py_compile` 报 `IndentationError: expected an indented block after 'except' statement`
  （line 328）。已按备份补回 `pass`，
  并用 `grep -c "^        pass$"`（现仅剩 1 处，即补回的那处；8 空格缩进以上的
  `^            pass$` 现有 8 处、备份 6 处，多出的 2 处是 R8/R11 新增代码，**无一误删**）
  + `py_compile` + 全量回归确认无残留。**运行中的 pid 931 全程未被触碰**（其内存里仍是 v5.11 代码，
  只是磁盘上的新代码尚未加载），因此事故期间交易与持仓盯守不受影响。
- 验证：`.venv/bin/python -m py_compile` 通过；`.venv/bin/python -m unittest test_okx_strategy`
  → **Ran 82 tests OK**（用例数不变：R14 纯删死代码，无需新增用例；被删字段原本就没有测试覆盖）。
- 遗留：
  1. `UNUSED_PARAMS` 里的 `profit_trigger` / `stop_loss` / `profit_step` 等仍是"表里能填、代码不读"
     的死配置——要让它们生效属于策略参数化改造（与 R4 同类），未获授权不动。
  2. 状态 CSV 的历史列（若曾导出过这些字段）不会因本次删除而报错：加载走 `dict.get` 白名单，
     多余列被忽略、缺失列取默认值。

### R15 完成 · 2026-10-12 19:34 —— 小项打包（5 项）

- 问题与改法（逐条独立，可单独回滚）：
  1. **.env 数值项解析无保护**：全文件 21 处 `float(os.getenv(...))` / `int(os.getenv(...))`，
     任意一处填了错别字（`OUT_OF_RANGE_HYSTERESIS_PCT=0,005` 这种逗号）就在 import 阶段抛
     `ValueError` → 程序压根起不来 → 所有持仓无人盯守。新增
     `env_num(name, default, cast=float)`（`okx_autoTrade_TrytoConnectOKX1.py:206`）：
     缺省/空串/非法值一律回退默认并打印 `[配置] X 非法值 '…'，沿用默认 …`，
     21 处裸解析中 20 处改为 `env_num`（第 21 处见下条，直接删除），行为对**合法值完全等价**。
  2. **`COOLDOWN_DAYS` 重复解析**：`load_config` 已有带保护的 env→system_params 合并
     （`:1288`），`main()` 又 `int(os.getenv("COOLDOWN_DAYS", system_params...))` 覆盖一遍且无保护
     ——env 值非法时 load_config 只是告警，main() 会当场崩。删掉 main 里这次解析
     （现 `:3260` 只打印 `system_params['cooldown_days']`，单一来源）；`MIN_BUY_AMOUNT` 同样收敛为
     "打印用 env_num、生效用 `self.min_buy_amount`"。
  3. **合规/不可交易判定只写 CSV、不同步内存集合**：`_can_buy` 读的是 `self.blacklist`
     （构造时的快照），所以 `SymbolState.__init__` 里"启动检测不可交易 → 加入黑名单"这条分支
     写完表后本进程内该集合仍缺这一项。补 `self.blacklist.add(inst_id)`（`:2088`），
     与 R5 时已修好的合规分支（`:2382` `self.blacklist.add(self.inst_id)`）保持一致。
     （`recheck_startup_blacklist` 只**移除**且在建 state 之前跑，无同类问题。）
  4. **窄区间一次越界永久剔除**：恢复条件 `range_low×(1+p) ≤ price ≤ range_high×(1-p)`，
     当 `high/low < (1+p)/(1-p)`（p=0.5% 时约 1.01005，例如 1.00~1.005 这种窄区间）上下界交叉、
     恢复带为空集，越界一次就永久剔除，只能手工改 xlsx 或重启。抽出纯函数
     `range_recover_band(low, high, pct=None)`（`:307`）：把 p 压到不超过
     `(high-low)/(high+low)` 的一半，保证带**非空且严格落在区间内**；宽区间（绝大多数配置）
     p 不变，恢复带与原来逐位相同。调用点 `update_price:2718`，日志改为打印真实恢复带与实际滞回。
  5. **`_round_down` 浮点少算一个步长**：`int(float(value)/float(step))` 会把
     `0.3/0.1 = 2.9999999999999996` 算成 2 个 lot（少买/少卖一档），且小数位数是按
     `str(step).rstrip("0")` 数的——`step=1e-05` 这类科学计数法没有小数点 → decimals=0 →
     数量被错误取整到整数。改用 `Decimal` 向下取整（`:1557`，唯一调用点 `:1696` 卖出数量），
     异常仍回退原值。
- 顺带（同一函数体内，非行为变更）：`_execute_buy` 的余额闸门原写死 `if balance < 110`，
  与可配的 `MIN_BUY_AMOUNT` 脱钩（MIN_BUY_AMOUNT 调到 500 时闸门仍是 110，单子必被 OKX 拒）。
  现按 `self.min_buy_amount × BUY_BALANCE_MARGIN`（新 env 项，默认 1.1 → 100×1.1 = **110，与原行为一致**）
  计算，并把这条"余额不足"接到已有的 `_balance_insufficient_until` 冷却上（R6 留下的字段，
  此前只有下单返回 51008 才置位）：闸门放在最前面，冷却期内直接 return，
  不再每个行情 tick 打一次 `get_okx_balance(force_refresh=True)` 的 REST。
- 影响位置：`:206`(新 env_num)、`:307`(新 range_recover_band)、`:336`(新 BUY_BALANCE_MARGIN)、
  `:1557`(_round_down)、`:2088`、`:2339-2353`(_execute_buy 余额闸门)、`:2718`(update_price 恢复带)、
  `:3260`(main 去重复解析)，以及 21 处 env 读取点。文件 3273 → **3327 行**。
- 新增测试 14 项（82 → **96**）：`TestEnvNum` 3（合法/空/缺省、非法回退不抛、int 转换含 `"7.5"`）、
  `TestRoundDown` 4（0.3/0.1 不再掉一档、正常向下取整、科学计数法步长、非法步长回退）、
  `TestRangeRecoverBand` 3（宽区间不变、窄区间非空且落在区间内、退化输入返回原区间）、
  `TestBuyBalanceGate` 4（低余额置冷却、冷却期内不再查余额、闸门跟随 MIN_BUY_AMOUNT、
  默认阈值与旧 110 等价）。
- 验证：`.venv/bin/python -m py_compile` 通过；`.venv/bin/python -m unittest test_okx_strategy`
  → **Ran 96 tests OK**（原有 82 项无一改动断言，全部继续通过，说明是纯增强而非行为变更）。
- 遗留：
  1. `env_num` 只覆盖数值项；`NOTIFY_CHANNEL` / `OKX_TRADE_MODE` 等字符串项仍裸读（填错最多
     走默认通道，不会崩启动），暂不纳入。
  2. `_can_buy` 里 `if buy_amount > balance: buy_amount = balance` 之后的
     `if balance < buy_amount: return False, "资金不足"` 分支不可达（已被上一句夹住）。
     要真正确实"资金不足就别买"需要改的是夹取策略，属于行为变更，未动。
  3. 窄区间的恢复带被压缩后比配置的 0.5% 更宽（相对区间中点对称），防抖强度弱于宽区间；
     若希望窄区间干脆不自动恢复，应显式配置，而不是靠现在这种"带为空"的副作用。

### R4 完成 · 2026-10-12 20:07 —— 回调族价位塌缩（用户答复授权后执行）

- 用户答复原文："建议改法 high_mid = (high + mid) / 2 你是对的，改进执行"。
- 问题：`PriceLevels.update()` 里 `high_mid = (high + low) / 2` 与 `mid` 完全同值，于是
  - "回调"族 `callback1_mid = (high_mid + mid)/2 = mid`，`callback_up = callback2_down = callback3 = callback4 = mid`
    —— 5 个价位全部塌缩到区间中点，**回调买点 == 回调卖点**，名义毛利 0，扣双边 taker 手续费后必亏；
  - "回撤"族则因锚点错误而横跨两个四分带（`[mid, high]`），买点 0.8125×high、卖点 0.9375×high。
  从代码结构看四族的锚点序列本应是 `high / high_mid / mid / low_mid / low`（每族一个 1/4 带，
  族内再二分），`callback1_mid = (high_mid + mid)/2` 这一句就是"回调带 = [mid, high_mid]"的直接证据。
- 改法（`PriceLevels.update`，现 `:1317` 起）：先算 `mid`，再 `high_mid = (high + mid) / 2`
  （high==low 时自然等于 high，原 `if high != low` 保护冗余，已去掉），其余 16 个价位公式一字未动。
  副作用范围经 grep 核实为**零**：`high_mid` / `mid` 在 `PriceLevels` 之外没有任何引用点。
- 效果（配置表 64 个币对全部是 high = 2×low，故比例统一）：

  | 族 | 买点(旧→新) | 卖点(旧→新) | 毛利(旧→新) |
  |---|---|---|---|
  | 回撤 | 0.8125h → 0.90625h | 0.9375h → 0.96875h | 15.4% → **6.9%** |
  | 回调 | 0.75h（=卖点） | 0.75h | **0%** → **8.0%** |
  | 过渡 | 0.65625h | 0.71875h | 9.5%（不变） |
  | 极限 | 0.53125h | 0.59375h | 11.8%（不变） |

  注意这不只是"修好回调"：**回撤族由"深买点+厚目标(15.4%)"变成"浅买点+薄目标(6.9%)"**
  （买点离高点更近，更容易被触发；每族买点→卖点价差统一为 (high-low)/8，旧回撤是 (high-low)/4）。
  若希望保留旧的 15.4% 目标，需要单独把 `pullback_up` 或 `pullback2_down` 再拉开，属另一项策略决策。
- 历史数据兼容：`pair_sell_line_price` 是买入时刻冻结并写进持仓账本的（`:2418` 取 `getattr(levels, sell_key)`，
  卖出判定 `:2750` 读的是落盘值），因此**已有持仓仍按买入时的旧卖点走**，只有重启后的新买入用新价位。
  旧"回调"对（买=卖=中点）在普通持仓分支只打 debug 日志、不直接卖出，由动态止盈负责离场，
  故滞留的相等卖点不会造成错误成交，最坏是少触发一次"亏损超5%回本豁免"。
- 影响位置：`PriceLevels.update`（`:1317-1349`）、文件头 docstring 第 16 条。
- 新增测试 3 项（96 → **99**），并把原来默认"买卖线可相等"的断言收紧为严格大于：
  `test_quarter_anchors`（四个锚点 + 四族买点的绝对值，含过渡/极限不变的对照）、
  `test_pairs_have_positive_gross_margin`（逐族毛利 > 5% 且 > 4×taker 费率，即足以覆盖进出双边手续费）、
  `test_update_recomputes_from_new_range`（行情刷高低点后四分结构仍成立）。
  `test_pair_map_complete` 里那句"`assertGreaterEqual`，注：high_mid==mid 使配对买卖线可相等"的历史注释已删除。
- 验证：`.venv/bin/python -m py_compile` 通过；`unittest test_okx_strategy` → **Ran 99 tests OK**；
  真实配置只读冒烟（stub 掉推送）逐族毛利与上表一致。
- 遗留：回撤族变薄（6.9%）后，`buy_ratio=0.02` × 64 币对的成交频率会明显上升，
  单币对停留时间变短——上线后建议先看一轮 demo 的触发密度再决定是否收窄买点。

#### R4 补充 · 2026-10-12 20:20 —— 用户给出权威价位表声明，已做逐条机器比对

用户随后贴出价位表的正式定义（"A+B" 指 A、B 的中间值）：

```
最高 > 高位中间 > 中间 > 低位中间 > 最低，族内 上 > 中 > 下
高位中间 = 最高+中间      中间 = 最高+最高(应为"最低"，见下)   低位中间 = 中间+最低
回撤上 = 最高+回撤中      回撤中 = 最高+高位中间   回撤下 = 回撤中+高位中间
回调上 = 高位中间+回调中  回调中 = 高位中间+中间   回调下 = 回调中+中间
过渡上 = 中间+过渡中      过渡中 = 中间+低位中间   过渡下 = 过渡中+低位中间
极限上 = 低位中间+极限中  极限中 = 低位中间+最低   极限下 = 极限中+最低
```

- **比对结论：R4 改完的实现与这份声明 15 个价位逐条完全一致**（`test_okx_strategy.TestLadderSpec`，
  5 组区间：真实配置的 0.0490641~0.0981281、2.0~0.5、100~50、7.3~1.1、1e-7~5e-8，
  误差 < `high×1e-12`；另含锚点链与族内 `上>中>下` 的顺序断言）。
  其中 `高位中间 = 最高+中间` 正是 R4 采用的 `high_mid = (high + mid) / 2`，
  即 v5.11 的 `high_mid = (high+low)/2` 与声明不符（把高位中间错当区间中点），才连带让回调族塌缩。
- **一处按笔误处理**："中间 = 最高+最高" 若照字面实现则 `中间 == 最高`，
  与同一份声明里"最高 > 高位中间 > 中间"自相矛盾（且四个族全部塌到最高价）。
  按上下文取为 **`中间 = (最高 + 最低) / 2`**，代码现状即如此；如原意不同请指出。
- 引擎只消费声明里的 `*_上`（卖点）与 `*_下`（买点）：`buy_levels = {回撤下, 回调下, 过渡下, 极限下}`、
  `sell_levels = {回撤上, 回调上, 过渡上, 极限上}`、`pair_map` 把同族"下→上"配成对（回撤/回调/过渡/极限四对）。
  `*_中`（`pullback1_mid` 等）只作为构造上下两档的中间量，不直接参与下单判定。
- 声明未涵盖、代码里额外算出的 8 个属性：`pullback3/pullback4`、`callback3/callback4`、
  `transition3/transition4`、`limit3/limit4`。全仓 grep 确认**除赋值外零引用**（既不下单也不打印），
  属于"只建不用"，与 R14 同类。（已按用户 20:35"丢弃旧版"删除，见下方 R4 补充 3。）
- 新增测试 4 项（99 → **103**）：`test_every_declared_level`（15 价位逐条）、
  `test_anchor_ordering`（最高>高位中间>中间>低位中间>最低）、
  `test_family_ordering_up_mid_down`（四族各自 上>中>下）、
  `test_buy_and_sell_levels_are_declared_names`（买卖点字典就是声明里的"下/上"，且配对同族）。

#### R4 补充 2 · 2026-10-12 20:30 —— 用户重发声明并补全 17 点全序，确认"逻辑无错误即应用到程序"

- 用户第二版声明把上一处的笔误改正为 **`中间 = 最高 + 最低`**（即区间中点，与代码现状一致，
  上面"按笔误处理"的说明到此作废），并补出完整排序链：

  ```
  最高 > 回撤上 > 回撤中 > 回撤下 > 高位中间 > 回调上 > 回调中 > 回调下 > 中间
      > 过渡上 > 过渡中 > 过渡下 > 低位中间 > 极限上 > 极限中 > 极限下 > 最低
  ```

- **验算：逻辑无错误。** 每个价位都是相邻锚点的中点 ⇒ 各点可写成 `a×最高 + (1-a)×最低`，
  `a` 依次为 1、15/16、14/16、13/16、12/16、11/16、10/16、9/16、8/16、7/16、6/16、5/16、4/16、
  3/16、2/16、1/16、0 —— 严格递减且**十六等分、间距处处相等 =（最高-最低）/16**，
  与声明的全序完全一致（对任意 最高 > 最低 成立，与比值无关）。
- **与程序比对：当前实现即该表，无需再改动。**（`PriceLevels.update` `:1313-1338`，
  R1~R15 的其他改动均未触及价位公式；`high_mid`/`mid` 在类外零引用。）
  四族买点 = 各带下沿内侧第 2 格（13/16、9/16、5/16、1/16 处），
  卖点 = 各带上沿内侧第 1 格（15/16、11/16、7/16、3/16 处），同族配对，买卖价差 2 格 =（最高-最低）/8。
- 新增测试 2 项（103 → **105**）：`test_full_declared_ordering_chain`（17 点全序逐对断言，
  5 组区间含 1e-7~5e-8 这种极小价位）、`test_declared_chain_is_evenly_spaced`
  （相邻间距全部 = (high-low)/16，能同时抓住"少一档/多一档/锚点错"这类结构性偏差）。
- （上一节末尾"仍待表态"的 8 个死属性已按用户答复处理，见 R4 补充 3。）

#### R4 补充 3 · 2026-10-12 20:35 —— "丢弃旧版"：删掉权威表里不存在的 8 个价位

- 用户答复"丢弃旧版"，即按声明的 17 点全序为准，删除旧版遗留、表里没有的 8 个价位属性：
  `pullback3` / `pullback4` / `callback3` / `callback4` / `transition3` / `transition4` /
  `limit3` / `limit4`（上一节我误记为"10 个"，实际 grep 到 8 行赋值）。
- 删除前的安全核对（均为零引用才动手）：
  1. 全仓 `grep -n "pullback3\|pullback4\|callback3\|…"` → 只有这 8 行赋值，无任何读取点；
  2. 引擎取价只有三条路径：`buy_levels` / `sell_levels` 两个字典（键固定为 `*_2_down` 与 `*_up`）、
     `pair_map` 的 4 组配对、`getattr(self.levels, key)` 三处（`:2327`/`:2357`/`:2429`），
     `key` 全部来自上述字典，不可能取到 `*_3`/`*_4`；
  3. 启动打印"价格点位"（`:3288-3293`）逐字段显式写名，也不含 `*_3`/`*_4`；
  4. 不存在 `vars(levels)` / `__dict__` 遍历或序列化价位对象的代码，故少 8 个属性不影响落盘与恢复；
  5. 测试文件对这 8 个属性零引用。
- 同时把 `PriceLevels.update` 的注释换成用户声明的完整全序 + 十六等分说明（`:1320-1325`），
  让这段代码自带权威规格，后续再有人动公式时注释即对照物。
- 影响位置：`okx_autoTrade_TrytoConnectOKX1.py:1317-1349`（`PriceLevels.update` 由 33 行降到 25 行）。
  文件 3385 → **3381 行**（删 8 行价位、注释换为用户声明的完整全序）。
- 验证：`.venv/bin/python -m py_compile` 通过；`unittest test_okx_strategy` → **Ran 105 tests OK**
  （`TestLadderSpec` 的 6 项规格守卫全部覆盖剩余 15 个价位与 17 点全序，删完仍逐条相等）。
- 补一道回归守卫（20:45，`test_okx_strategy.py` 的 `TestLadderSpec.test_no_undeclared_levels`）：
  把 `PriceLevels(2.0, 0.5)` 实例上的 float 属性集合与"声明表 15 项 + high/low"做集合相等断言，
  多一个（表外价位复活）或少一个（把声明里的价位删了）都会红。→ **Ran 106 tests OK**（105 → 106）。
- 说明：**未**删除 `okx_autoTrade_TrytoConnectOKX1.py.bak_v5.9_20261012` / `.bak_v5.11_20261012`
  两个改前备份（"丢弃旧版"按上下文指价位表里的旧版残留价位；备份文件是回滚依据，
  删 irreversible，需要单独确认）。

## 收尾 · 2026-10-12 20:07 —— 版本号与全量验证（R1~R15 全部完成）

- `VERSION` `v5.11` → **`v5.12`**；文件头 docstring 补 v5.12 变更清单 16 条（R1~R15 + R4 策略项），
  每条一句结论并指向本文档。
- **行号口径**：本文各节的 `:行号` 会随文件增删漂移（本次 v5.12 相对 v5.11 净 +312 行）。
  R14/R15/R4 三节已按 20:07 的最终文件校正；R1~R13 各节仍是各自完工当时的位置。
  **续做或复核时一律以 `grep` 到的当前行号为准，不要照抄。**
- 文件行数：3069（v5.11 基线）→ **3382**；`PriceLevels` 现有 17 个价位属性 = 声明的 17 点，不多不少；测试 33 → **106 项**。
- 最后一次全量验证（20:45，"丢弃旧版"之后）：`py_compile` 通过 + `Ran 106 tests OK`（含新增的
  `test_no_undeclared_levels` 表外价位守卫）；改动仅在 docstring 与测试文件，策略代码未再动。
- 全量验证（20:07）：
  - `.venv/bin/python -m py_compile okx_autoTrade_TrytoConnectOKX1.py` 通过；
  - `.venv/bin/python -m unittest test_okx_strategy` → **Ran 103 tests OK**（含 R4 价位表规格守卫）；
  - 真实配置只读冒烟（子进程内 stub 掉 `push_notify_throttled`，不发任何消息）：
    `load_config()` 读到 **64 个币对**、无脏行，`buy_ratio=0.02`、`cooldown_days=7`、
    `trade_mode=demo` 生效；`get_stop_loss` 抽查 5%/6.5%/10%/20% → 1.5%/1.5%/1.15%/0，
    与原表一致；`range_recover_band` 宽区间 (0.5025, 1.99) 与原公式逐位相同、
    窄区间 1.00~1.005 得到非空带 (1.0012, 1.0037)；R4 后 64 个币对的四族毛利
    回撤 6.9% / 回调 8.0% / 过渡 9.5% / 极限 11.8%（回调由 0% 修好，回撤由 15.4% 收窄）。
- 进程：**全程未重启、未 kill pid 931**（内存里仍是 v5.11 代码，已连续运行约 2 小时）。
  以上 16 项改动都在磁盘上，等用户择机重启才生效。重启后 `.env` 里新增可配项：
  `BUY_BALANCE_MARGIN`(1.1)、`WS_STALL_FACTOR`(3)、`MARKET_THREAD_RESTART_MIN_SEC`(30)；
  且任何 .env 数值项写错都不再崩启动（回退默认 + 打印 `[配置] X 非法值 …`）。
- 重启前提醒（重启瞬间会发生的事，避免误判为异常）：
  1. R4 的新价位只作用于**重启后的新买入**，已有持仓的配对卖点沿用落盘时的旧值；
  2. 启动会做一次 `sync_all_buy_queue()`（一次读写整表）与 `sweep_stale_tmp_files()`；
  3. `kill` 该进程请用 `SIGTERM`（R8 会走优雅收尾：脏账本落盘 + 超范围批量落盘 + 心跳标注），
     不要 `kill -9`。
- 尚未排期的候选（各条 遗留 汇总，需用户点头才开工）：
  1. **R16**：配置快照回退 —— 工作簿本身读不出来（文件缺失 / xlsx 损坏 / 被 Excel 独占锁定）
     仍会 `sys.exit(1)`，需要"上次有效配置快照"才彻底免疫（新增一份缓存文件，R9 遗留 1）；
  2. `buy_signal_*` 五个字段不落盘，重启后激活中的买入信号丢失（R7 遗留）；
  3. 收尾 `finally` 里的余额快照 REST 调用在网络不通时会拖住退出（最坏 10s+ 超时，R8 遗留）；
  4. 窄区间恢复带被压缩后防抖弱于宽区间（R15 遗留 3）；
  5. `_can_buy` 的"资金不足"分支不可达（R15 遗留 2）；
  6. WS 分片包部分丢失不在静默检测覆盖范围内（R12 遗留）；
  7. 策略参数化：`UNUSED_PARAMS` 里的 `profit_trigger` / `stop_loss` / `profit_step` 表里能填、代码不读。

## 上线验证 · 2026-10-12 21:05 —— 用户手动重启，v5.12 已在运行

- 用户于 20:56 自行重启（旧 pid 931 退出，新 **pid 203453**，`STARTED 20:56:01`，PPID=1、独立 SID，
  stdout/stderr 由 `systemd-journal` 接管 → `journalctl _PID=203453` 可查，`console.out` 不再是出口）。
- **启动横幅**：`okx_ding_ok v5.12` / 工作目录 `/home/ubuntu/okx_real`；`[配置] 系统参数生效: buy_ratio=0.02
  cooldown_days=7 trade_mode=demo`，并打印 `UNUSED_PARAMS` 提示（`data_source`/`profit_trigger` 无实际用途）
  —— 这是 R15 的 `env_num` 与 R9/R14 的配置自检在真实进程里首次跑通。
- **健康度（重启后 9 分钟）**：心跳 `version=v5.12`、`symbols=64`、`open_positions=1`、
  `ws.connected=true`（20:56:06 连上，`last_msg_ts` 与心跳同秒，`consecutive_fail=0`、
  `stall_reconnects=0`、`thread_restarts=0`）、`market_thread_alive=true`、`push_pending=0`；
  `run.log` 20:56 之后 **97 条 INFO、0 条 WARN/ERROR/Traceback**，全程未发出任何真实推送。
- **启动筛选口径核对**：64 = 30（行情线程订阅）+ 33（黑名单跳过）+ 1（待观察 YFI）；
  其中 10 个币对开局即"价格超出计算范围"（不参与买入但仍订阅），与重启前的账本一致；
  黑名单复检 47 个 `[启动检测不可交易]` 全部仍不可交易、无移除（R15 的启动内存黑名单同步在这条路径上）。
- **R4 新价位已生效**（RVN-USDT，区间 0.0011504297~0.002371，启动打印）：
  回调上 0.0019895718 / 回调2下 0.0018370005，
  手算 `high_mid=(high+mid)/2=0.0020658574`、`callback1_mid=0.0019132861` → `callback_up=0.00198957`
  逐位吻合（旧公式这里等于 mid=0.00176071，与卖点重合、零毛利）。
- **历史持仓不受影响已实证**：`pair_status.csv` 里 RVN-USDT 的 `sell_line_price=0.00176071484375`
  正是买入时（15:53，旧代码）冻结的旧 mid，重启后原样读回（`:2129` / `:2960` 从 pair_status 恢复，
  `POSITIONS_HEADER` 不含该字段但 `sell_line_price` 列在 pair_status 里）。即"仅新买入按新价位"成立。
- **一条需要用户判断的现象**：`sys.degraded=true` 是稳态而非偶发——判据含
  `load1 > cpu_cores`（`:414-416`），本机 1 核、`load1` 长期 2.9~3.5（其他进程所致，本进程 `proc_cpu_pct`
  仅 0.5%），于是状态落盘间隔被长期放宽为 30s（设计值 5s）。内存里 peak/止盈推进不受影响，
  只是硬 kill 时最多丢 30s 账本；`mem_available_mb` 122~177MB 未触阈值。若要按"只有本进程吃 CPU 才降频"，
  属于参数/判据调整，未获授权未动（可并入候选 4）。
- **日志排雷**：`journalctl _PID=203453` 会混进 **9月23 日同 pid 的历史记录**（`/home/ubuntu/code/okx/okx1.py`
  v2.6 的 traceback），看日志必须加 `--since "2026-10-12 20:55"`，否则会把旧事故当成新事故。



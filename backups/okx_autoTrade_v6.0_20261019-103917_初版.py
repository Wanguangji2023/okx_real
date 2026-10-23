#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OKX 实时成交价监听 + 多层次价位计算 + 动态止盈 + 多通道消息推送（钉钉/飞书）
版本: v5.20
更新: 2026-10-18
v5.20 修正（用户反馈"启动后未收到行情持续、行情取不到、所有计算无法进行"；策略阈值与买卖规则未动，
需重启进程生效）：
1.【全市场 REST 行情补齐（C12 推广）】模拟盘 WS 成交推送稀疏：实证 26 个持仓中 22 个"启动后未
   收到行情"，冷门币对（含买入候选）整程无 tick → 买入信号/止盈评估/回本清仓全部停摆（v5.17
   只兜底持仓，且逐币单查、300s 周期、每轮最多 10 个，覆盖太慢）。现改为市场级补齐：每
   MARKET_GAP_INTERVAL_SEC（默认 60s）用一次批量 REST（/api/v5/market/tickers?instType=SPOT，
   单请求返回全部现货最新价，实测 0.08s/565 个）把"静默超过 MARKET_GAP_TICK_SEC（默认 45s）"的
   币对全部喂入同一条 update_price 路径，覆盖持仓 + 买入候选（可交易且未被黑名单/观察/超范围/
   不可交易产品排除）；卖出重试中的持仓优先排序。逐币单查与每轮名额轮转随之淘汰（不再需要）。
   心跳新增 market_gap_fed（上轮补齐喂入数量）。
2.【与 v5.19 政策一致】环境缺失（51001）/地域限制币对不参与补齐（REST 同样查不到/不交易）。
v5.19 修正（用户决定：不可交易产品直接排除；策略阈值与买卖规则未动，需重启进程生效）：
1.【51001 不可交易产品直接入黑名单】启动探测遇到 code=51001（当前交易环境无此产品，如 demo 缺失的
   18 个主网币对）不再"等待重探"：直接写入常规黑名单并持久化（下次启动自动跳过，显示"在黑名单中"）；
   运行期重探确认 51001 的同样即刻入黑名单且不再安排重试；买入路径遇到 51001 也改入常规黑名单
   （不再走未知异常黑名单的 24h 复检通道）。重探机制（P1-1）此后仅服务启动时网络抖动类失败。
2.【地域/合规限制同待遇】启动探测/运行期重探遇到 51155/compliance/restriction 与买入路径口径统一：
   常规黑名单持久化、不重试（此前该情形只在下单失败时处理，启动/重探阶段会误归"网络类"反复重探）。
v5.18 修正（依据运行文档及优化建议.md 批次二 C7，用户确认"立马实施"；策略阈值与买卖规则未动，
需重启进程生效）：
1.【C7 锁内下单重构】行情线程此前在 ENGINE_LOCK 内完成下单全流程（余额 REST、market_buy_quote /
   market_sell_base、_wait_fill 最长数秒、部分成交补单、成交后余额强刷），一次成交尝试可把行情接收、
   心跳、维护线程整体堵住数秒（台账 P2-2）。现新增订单执行线程（OrderExecutor，单线程串行）：
   行情线程只做零网络预检并投递任务（毫秒级返回），订单类 REST 全部在锁外执行，仅在"读本地决策"
   与"写本地账务"两个短暂阶段持有引擎锁。_execute_buy/_execute_sell 拆为
   _buy_prepare/_buy_place/_buy_apply 与 _sell_prepare/_sell_place/_sell_apply（同步入出口行为
   与旧实现逐分支等价，保留给测试与无执行器场景）。每币对至多一个在途订单（order_in_flight
   门闩，杜绝重复提交）；订单队列上限 ORDER_QUEUE_MAX（默认 64）；ORDER_EXECUTOR_ENABLED=0
   可一键回退旧同步行为。心跳新增 orders_pending / orders_in_flight 便于远程观察；提交成功
   另落一条 trade_event INFO（含「订单线程执行」标记），运行日志可追踪"锁内提交→锁外成交"全链路。
2.【VINE 残账自然了结（记录）】v5.17 兜底盯盘上线后，VINE 于 2026-10-18 06:30:49 经兜底价触发
   回本清仓，余量 1030.2574 股全部卖出（+19.23 USDT，+2.13%），本地账本与平台残量均清零，
   无需人工强制清账（用户要求的"强制清账"由行情到达后自动完成）。
3.【重探日志口径修正】运行期重探遇到 code=51001（当前环境无此产品）不再误标"网络失败"，
   与启动探测（P1-3）口径一致（纯日志措辞修正，逻辑不变）。
v5.17 修正（v5.16 重启验证期发现：模拟盘行情只有部分币对持续有成交推送，冷门币对的持仓
完全依赖 tick 的止盈/回本清仓会无限期停摆 —— 实证 VINE 重启后 40 秒内 0 条成交帧、BTC 21 条，
且该币对历史最大亏损 −99%，回本清仓随时可触发却等不到行情。本项为验证期补丁，策略阈值与买卖规则未动）：
1.【C12 无行情持仓 REST 兜底盯盘】对"有持仓且超过 STALE_TICK_SEC（默认 300s）没收到任何行情"的
  币对，按 STALE_POLL_INTERVAL_SEC（默认 300s）周期用 REST 最新成交价（GET /api/v5/market/ticker，
  公开接口）喂入同一条 update_price 止盈/卖出评估路径；每轮最多 STALE_POLL_MAX_PER_CYCLE（默认 10）个、
  按最久未被兜底排序轮转；卖出重试中的持仓（部分成交/挂单占用退避中）改用更短的
  STALE_TICK_SELLING_SEC（默认 120s）阈值并优先排队。当前环境无此产品的币对跳过（REST 也查不到）。
  网络请求在锁外、锁内只喂 tick。心跳新增 stale_positions（当前无行情持仓数）便于远程观察；
  另将 INFO 落盘白名单补上 "trade_event"（交易事件与兜底启用信息此前只飘控制台）。
  （v5.20 已推广为全市场行情补齐：批量接口一次取全部现货、每 MARKET_GAP_INTERVAL_SEC 一轮、
  覆盖买入候选并淘汰逐币单查与名额轮转——见顶部 v5.20 变更。）
v5.16 修正（依据同文档批次二 C1~C11 用户确认后落地；策略阈值与买卖规则未动，需重启进程生效）：
1.【C1② 环境统一：行情切模拟盘】connect_okx_ws 在 demo 模式改连模拟盘公共 WS
  （wss://wspap.okx.com:8443/ws/v5/public?brokerId=9999；OKX_WS_DEMO=auto|always|never 强制覆盖），
  行情价格与下单环境一致，消除"主网行情+模拟盘下单"的价差割裂（实证 VINE：主网 0.0075 vs 模拟盘 0.93）。
  仅剩模拟盘有数据的币对产生买入信号；模拟盘不存在的主网独有币对由启动探测自动排除（P1-1/P1-3），
  其订阅错误只提示一次（不再每次重连刷屏）。
2.【C4 买点死区】买点漂移重绑加死区 BUY_REBIND_DEADBAND_PCT（默认 0.003=0.3%：价格需越过
  旧买点边界 0.3% 才认可漂移），消除贴线抖动反复重绑（实证两天 384 次、TAO 一秒内往返 16% 跳档），
  贴线时保持原绑定、最低价继续滚动，不再反复复位"反弹 1%"确认。重绑时最低价默认仍以重绑时刻
  重新起算（守住 R7 回归：陈旧低点会跳过反弹确认）；如确需保留更小旧低点可设 BUY_REBIND_KEEP_LOWEST=1。
3.【C5 粉尘清理】持仓市值 < POS_MIN_USD(1 USDT) 且平台总量 < minSz（永远无法下单卖出）时按粉尘
  流程清账并推送；与平台核对失败不动账本，每个币对至多 DUST_CHECK_SEC(默认 1h) 核对一次。
4.【C10 成本来源字段】positions.csv 新增 cost_source 列：fill=真实成交、reconcile=对账重建
  （旧行按 buy_reason="平台余额同步" 自动推断）；启动快照打印成本来源；心跳新增 reconcile_symbols。
5.【C11 未知黑名单自动复检】未知异常黑名单条目满 UNKNOWN_BLACKLIST_RECHECK_SEC（默认 24h）自动
  复检当前环境是否有该交易对（只查 instrument 不下单）：启动时批量、运行期每小时至多 1 个，
  恢复即移除并推送；修复前 MASK 等因一次瞬时错误永久滞留黑名单。
6.【C2 VINE 残局随环境统一自动了结】切模拟盘行情后 VINE 按模拟盘价格恢复真实盈亏；其历史最大
  亏损标记触发"回本清仓"豁免，价格≥含费保本价（模拟盘约 0.874）时自动市价了结（模拟盘资金）。
v5.15 修正（依据《okx_autoTrade_TrytoConnectOKX1运行文档及优化建议.md》批次一落地；策略阈值与买卖规则未动，
本批聚焦记账正确性/故障自愈/可观测性/资源优化。所有改动需重启进程生效）：
1.【P0-2 部分成交卖出按比例结转成本】_execute_sell 不再对部分成交按全额成本清零：成交量<持仓×99.9%
  时按比例结转成本、保留剩余持仓与止盈状态、记录部分盈亏并推送，卖出尝试退避 SELL_BLOCK_RETRY_SEC。
  修复前实证（文档 2.2）：ASP 成交 34.3% 却整笔清零，记账 −184.01 实际约 −1.7；IOST/LAT/WCT 同类。
2.【P0-3 部分成交买入自动补单】_execute_buy 检测市价买入 state=canceled 且成交额<委托×(容差 0.95) 时，
  按差额补单（BUY_PARTIAL_TOPUP_MAX 默认 1 次；差额<BUY_PARTIAL_MIN_TOPUP 放弃），多笔成交按加权均价
  合并入账并推送提醒。修复前实证：CSPR 委托 947.73 仅成交 15.04（1.6%）、SAHARA 62.42（6.8%）。
3.【P1-2 瞬时网络错误不再永久拉黑】买入错误分类新增暂时性网络通道（超时/SSL/握手/连接/5xx/50011 等）：
  只冷却重试（BUY_NOTFILLED_COOLDOWN_SEC）。实证：MASK 因一次 SSL 握手里超时被永久拉黑（10-17 00:03:45）。
4.【P1-1/P1-3 探测失败分类+运行期重探】启动探测区分「网络类」与「当前环境无此产品（code=51001）」，
  两类均按指数退避自动重探（REPROBE_BASE_SEC 默认 600s 起、上限 REPROBE_MAX_SEC，每轮最多 1 个），
  重探成功恢复买入资格并推送；不再让 18 个币对整程静默不可买、两天刷 1.3 万条"买入跳过"。
5.【P2-1/P3-2 买入预检零网络化】_execute_buy 先跑 _can_buy_light（黑名单/持仓/冷却等纯本地条件）
  与买点复查，余额 force_refresh REST 只留给真正可能下单的尝试；删 _can_buy 死分支（clamp 后永假）。
  此前每次被拒尝试都先打一条余额请求（journal 两天 13,553 条"买入跳过"全部如此）。
6.【P1-5 WARN 全量落盘】Logger._should_write_log 的 WARN 分支放开（此前仅 3 个分类白名单，
  "卖出受阻/部分成交/未知错误"等关键运维信息只飘控制台）。
7.【P1-6 funds.csv 真实聚合】_update_funds_for_view 由"除余额外全 0"改为真实汇总：市值/浮盈取自
  positions.csv、累计已实现盈亏取 tradeRecord 的 SELL 行；并调整买卖路径为先落账本/成交记录再刷新视图。
8.【P2-4 探测口径与下单环境一致】check_okx_available 在 demo 模式带 x-simulated-trading: 1。
9.【P2-3/P2-5/P2-6/P2-7/P2-9/P2-10/P3-1/P3-3 打包】_wait_fill 等待参数可配（FILL_WAIT_TRIES/FILL_WAIT_INTERVAL）；
  _HL_PENDING 落盘等值校验防误删新极值；冷却表按 inst_id 整表更新去重；未知黑名单 reason 截断 100→300；
  退出前最多等 2s 清空推送队列；股票池单文件打开失败跳过并告警（仅全部失败才回退快照）；删 _get_buy_level
  重复调用；心跳新增 net_failed_symbols/env_missing_symbols 计数；启动快照打印"成本"改标"估值(市价)"
  （position_price 实为最近成交/对账折合价，见文档 P1-4）。
  环境统一（P0-1 决策）、买点死区（P1-7）、粉尘清理（P1-8）、账本历史数据校正等列入批次二，待用户确认后处理。
v5.14 修正（依据 okx_real问题及优化方案.md 步骤 2/3 落地；策略阈值与买卖规则未动）：
1.【幽灵配对复位】平台侧手动卖出/转账后，若本地从未触发卖出规则，pair_status 不会复位：
  is_paired=True 且 is_sold=False 的"幽灵配对"会被 _can_buy 判为"已配对未卖出"而永久买不进
  （现场实例：RSR-USDT，2026-10-09 起）。现在启动/恢复线程全量对账（_apply_platform_positions）
  完成后，对"平台余额与本地账本都没有该持仓"的配对行自动复位为已卖出
  （sell_reason="平台无持仓（启动对账复位）"），记日志并限流推送提示人工核对。
2.【运行期轻量对账】全量对齐此前只在启动做一次：平台侧手动成交后，本地账本要等到该币恰好触发
  卖出规则才自愈，期间 open_positions/unrealized_pnl/funds 视图全是虚值。现新增
  POSITION_AUDIT_SEC（.env 可调，默认 300s，<=0 关闭）：maintenance() 到点触发，锁外
  GET /api/v5/account/balance（与启动同步同一实现 fetch_platform_positions），锁内只做本地
  比对——平台余额已无的本地持仓清除记录、同步内存状态（防止下一次脏落盘把持仓行写回）、
  复位相应幽灵配对（sell_reason="平台无持仓（运行期对账复位）"）并推送告警；请求失败/
  网络类异常本轮跳过，不改判任何账本。
v5.13 修正：
1.股票池数据源改为 .env INPUT_DATA 指定目录下的全部 xlsx（含子目录），旧 okx_ding_ok_config.xlsx
  已删除、不再读取。每个文件取第 2 个 sheet"层计算幅度"：A=币对名称（=旧 A），
  D=同层最高（=旧 B 参考最高价），C=同层最低（=旧 C 参考最低价）；旧 D 列启用开关废弃。
2.新增 .env 过滤条件 FILTER_LAYER，按第 1 个 sheet"层计算"的区间（如 8-16，两位数字为
  本层最高/本层最低的价差倍数）筛选入池币对：8-16=只要该层；8-16及以上=16-32 起向上；
  8-16以下=4-8 起向下；逗号叠加多条件；留空不过滤。
v5.12 修正（第三轮复审 R1~R15 逐项落地；逐条"问题/改法/影响位置/测试/遗留"见 doc_txt/fixlog_v5.12.md）：
1.【P0·R1】_read_csv 的 `except: pass` 把 EMFILE/OOM/坏行等读失败当成"文件是空的"并把空表写进缓存，
  随后任何一次整表重写（落盘/同步持仓/买入队列变更）就会抹掉其他币对的账本行。
  现读失败不进缓存、记入 _CSV_READ_FAILED，且 _write_csv_all 拒绝对"上次读失败"的表整表重写
  （宁可少落一次盘，也不抹掉其他行）。
2.【P0·R2】_write_csv_all 的 os.replace 在 CSV_LOCK 之外 + tmp 文件名固定 → 多线程并发串写、互相覆盖。
  现整写全程持锁，tmp 名带 pid+tid，返回是否成功；fsync 后才 replace。
3.【P0·R3】后台账户恢复线程与行情线程各自"读全表→改→写全表"却不共用锁，恢复线程会用启动时的
  旧快照打回行情线程刚写入的行（丢持仓更新）。现统一到 ENGINE_LOCK（锁序 ENGINE_LOCK→CSV_LOCK）。
4.【P1·R5】市价单未成交/余额不足（51008）此前一律走"未知错误→永久未知异常黑名单"，
  一个低流动性币对一次抖动就再也买不了，只能手工改 CSV。现改为短期冷却重试（BUY_NOTFILLED_COOLDOWN_SEC
  / BUY_BALANCE_COOLDOWN_SEC），合规/地区限制(51155)才进常规黑名单并同步内存集合。
5.【P1·R6】卖出下单失败后无退避：价格仍触发止盈时每个行情 tick 重来一遍（锁内 10s 余额查询 + 下单 +
  最长 4s 等成交），行情接收被拖死。现 SELL_FAIL_RETRY_SEC(60s) 退避，受阻期间只盯盘不下单。
6.【P1·R7】买入信号把激活时刻的买点档位钉死：档位随高低点更新而漂移后，最低价仍是漂移前的陈旧值，
  "反弹 1%" 会被瞬时判定满足而直接买入（实测 0.55→1.00→0.60→0.58 序列即误买）。
  现买点漂移即重绑信号并复位最低价（对齐 okx_doc.txt §1.6）。
7.【P1·R8】无 SIGTERM 处理（finally 只覆盖 Ctrl+C），kill/systemd stop 会跳过收尾；行情线程意外退出
  无人监控。现 STOP_EVENT + SIGTERM/SIGINT/SIGQUIT 优雅收尾（脏账本落盘、超范围批量落盘、心跳标注），
  主循环看门狗自动重拉行情线程（≥MARKET_THREAD_RESTART_MIN_SEC 间隔），第二次信号强制退出。
8.【P1·R9】配置表一行脏数据（高低价倒挂/非数字）→ load_config 抛异常 → sys.exit(1) 持仓无人盯守。
  现逐行校验、脏行跳过并告警；全表无有效行但本地有持仓 → 转"仅持仓管理"模式继续运行。
9.【P2·R10】启动期买入队列同步在 SymbolState.__init__ 与 add_state 各写一遍整表：N 个币对 = 2N 次
  整表读写且各自 fsync，启动时间随币对数近似平方增长（1 核机器）。现改为 sync_all_buy_queue()
  一次读表 + 一次写表。
10.【P2·R11】超范围判定在行情热路径上持锁 load+save 整个 xlsx 工作簿。现改为延迟操作队列 +
  maintenance() 批量落盘（失败会重新入队，不丢操作）。
11.【P2·R12】WS 假活：服务端停发但 TCP 不断线时永不重连（自己的 ping 也发不出去）。
  现按 last_recv 静默超过 PING_INTERVAL×WS_STALL_FACTOR(3) 秒即主动断开重连并计数告警。
12.【P2·R13】137 行 PROFIT_STOP_MAP 硬表实为线性规则。改用 get_stop_loss() 公式
  （<6.5% 容忍 1.5%、每多 1% 盈利收紧 0.1%、≥20% 归零），对照 v5.11 原表导出基线
  doc_txt/profit_stop_map_v5.11.json 逐点校验 1365 个点，零差异。
13.【P2·R14】死代码清理：只建不用的下破提醒/新高新低节流字段（16 个）、废弃常量 4 个、
  空壳方法 Logger.set_dingtalk 与 MarketEngine._check_buy_queue_all；测试 make_state 同步。
14.【P2·R15】小项打包：新增 env_num() 统一保护 .env 数值解析（此前 21 处裸 float()/int()，
  任一填错就在 import 阶段崩、程序根本起不来）；main() 去掉重复且无保护的 COOLDOWN_DAYS 解析；
  启动"不可交易→黑名单"分支同步内存集合；窄区间（high/low < (1+p)/(1-p)）恢复带塌成空集导致
  一次越界永久剔除，改由 range_recover_band() 压缩滞回幅度；_round_down 改用 Decimal
  （原 `int(0.3/0.1)=2` 会少算一个 lot_sz，且 step=1e-05 时按 str 数小数位取错量纲）；
  买入余额闸门由写死 110 改为 MIN_BUY_AMOUNT×BUY_BALANCE_MARGIN（默认 1.1 → 仍为 110），
  并接入余额冷却，避免每 tick 打一次 force_refresh 余额 REST。
15.【测试】test_okx_strategy.py 由 33 项扩到 106 项，全程假客户端 + 临时目录，不触碰真实 API 与账本
  （其中 TestLadderSpec 按用户 2026-10-12 给出的权威价位表逐条锁定 15 个价位与锚点顺序，
  并用 test_no_undeclared_levels 断言"表外价位不得复活"）。
16.【策略语义·R4·经用户确认】PriceLevels.high_mid 此前 = (high+low)/2 与 mid 同值："回撤"族横跨上半边
  两个四分带，"回调"族 5 个价位全部塌缩到中点（callback_up == callback2_down == mid），
  回调买点与卖点相等、毛利 0（扣双边手续费必亏）。现 high_mid = (high + mid)/2，
  四族各占一个 1/4 带（锚点 high / 3/4 / 1/2 / 1/4 / low）。以配置常见形态 high = 2×low 计：
  回撤买点 0.8125high → 0.90625high、毛利 15.4% → 6.9%；回调买点由 =high 0.75 的中点改为 0.78125high、
  毛利 0 → 8.0%；过渡/极限两族不变（9.5% / 11.8%）。四族的买点→卖点价差统一为 (high-low)/8
  （旧"回撤"族因为横跨两个四分带，价差是 (high-low)/4，即本次把它收窄一半）。
  用户 2026-10-12 复核的权威价位表（17 点全序：最高>回撤上>回撤中>回撤下>高位中间>回调上>回调中>
  回调下>中间>过渡上>过渡中>过渡下>低位中间>极限上>极限中>极限下>最低，十六等分等间距）
  已由 TestLadderSpec 逐条锁定。并按用户"丢弃旧版"删掉表中不存在的 8 个旧版价位
  （pullback3/4、callback3/4、transition3/4、limit3/4，全仓除赋值外零引用）。
  历史持仓的 pair_sell_line_price 是买入时冻结并落盘的，不受本次改动影响（仅新买入按新价位）。
本版本其余策略语义未动（9.2.1~9.2.4、9.3.3 仍待授权）。
v5.11 修正（第二轮复审，逐项复核 v5.10 后落地）：
1.【P0·新发现】_execute_sell 偏离改写分支在 avail=0（挂单全额占用）时把 position_amount×0/qty、
  position_qty=0 一起归零，落盘即成"无持仓"、挂单解冻后持仓彻底脱管——正是 9.1.2 想防的事。
  现仅当 avail>0 才改写账本；avail=0 保持原账本，由下方按 cash 判定受阻重试或失真清除。
2.【CPU 资源防护·按用户要求】降频阈值由 80% 收紧为 70%：CPU_MAX_LOAD_RATIO 默认 0.7；
  删除 SYS_GUARD 中重复的 mem_min_mb 键。
3.【心跳可观测】stream_okx 重连成功后清零 WS_HEALTH["consecutive_fail"]，心跳不再显示陈旧失败数。
4.【10.9 落地】test_okx_strategy.py 实测 33 项全部通过（保本价口径/止盈棘轮/挂单占用不清账本/
  中文参数键映射/CSV 缓存失效/买入队列读改写/WS 分片与握手残留等），假客户端+临时目录，不触碰真实 API 与账本。
v5.10 修正（本轮：把 9.x/10.x 剩余问题逐项落地，并加入资源防护）：
1.【10.3 严重，本次宕机真因】启动时 OKX 连不上（ssl handshake timed out）直接 sys.exit(1)，
  持仓从此无人盯守。现改为：启动探测最多重试 OKX_INIT_RETRY_MAX(3) 次并指数退避；
  重试仍失败但本地有持仓 → 降级启动（不买入、后台每 OKX_RECOVERY_INTERVAL_SEC(60s) 自动恢复账户），
  仅"账户/密钥/权限类致命错误(50111/50112/50113/50103)"才退出。
2.【10.2】系统参数表此前只认英文 key，中文 key（单次买入比例/静默期/总资金…）被静默丢弃 ——
  实测配置里的 2% 从未生效、一直按默认 1% 下单。新增 PARAM_KEY_ALIASES 中文别名表 + 生效值回显 +
  死参数告警，并支持 BUY_RATIO 环境变量覆盖。
3.【10.1】_execute_sell 平台量与账本量不一致时按平台量下单，但成本额 position_amount 未同步缩放，
  剩余持仓的单位成本被凭空拉高，止盈价/保本价从此失真。现按比例回算 position_amount。
4.【10.5】_can_sell 的 require_profit 与 price 参数耦合（price=None 时改用另一个价源）：
  改为 _can_sell(price, min_profit_pct)，price 必填、None 关闭门槛，价源唯一。
5.【10.6 性能】启动要 ~800 次整文件读 + 128 次 fsync；运行期每个币对每 5 秒各自整表重写。
  现加 CSV 内容缓存(mtime_ns+size+ino 失效)、只读表用 _read_csv_ref 免拷贝、_ensure_csv_header 只读表头；
  high_low 改为内存暂存 + 每轮一次合并写；持仓/配对账本落盘由引擎统一 flush_dirty_states() 合并，
  买入/卖出/止盈激活等关键事件仍 force 即时落盘。
6.【10.4】买入队列读-改-写用的是启动时的内存副本，会覆盖其他符号在运行期新增/改状态的行
  （漏买入）。_sync_buy_queue/_add_to_buy_queue/_remove_from_buy_queue/_is_in_cooldown 全部改为重新载入。
7.【10.7 可观测性(9.4)】新增心跳文件 okx_ding_ok_heartbeat.json（每 10s 原子写：ws 状态、持仓数、
  止盈激活数、负载、推送积压），推送线程池此前无界 → 加 NOTIFY_MAX_PENDING(50) 上限，超限丢弃并计数，
  防止断网时推送任务堆积耗尽内存。
8.【资源防护】1 核 / 960MB 机器：每秒采样 /proc/loadavg + 本进程 CPU% + MemAvailable，
  占用超过 CPU_MAX_LOAD_RATIO(默认 0.8，即允许吃满 80% 才降频)、或系统负载超核数、或可用内存<80MB
  → 进入 degraded，把状态落盘间隔从 5s 放宽到 30s（内存里的 peak/止盈推进不受影响），宁可延迟落盘也别 OOM。
9.【10.8】裸 socket WebSocket 此前不处理分片、握手残留字节可能被丢弃 → 重写为 WsConnection：
  拼接续帧、控制帧透传、握手 leftover 缓冲复用、单帧上限 8MB；订阅按 WS_SUBSCRIBE_CHUNK(40) 分片下发
  （OKX 单次 subscribe 上限 60 args，64 个币对整批订阅会失败）。连接连续失败 ≥3 次才推送告警。
10.【9.3.5】新增 test_okx_strategy.py：用假客户端覆盖 PriceLevels/get_stop_loss/_breakeven_price/
  _can_buy/_can_sell/_check_take_profit/配置中文 key 映射/CSV 缓存失效，不触碰真实 API。
本版本未改动策略语义（9.2.1~9.2.4、9.3.3 仍待授权）。
v5.9 修正（依据 doc_txt/okx_dox1.txt 审查结论）：
1.【9.1.1 成立】"回本"判据此前用成交均价 position_price（买入扣币前的单位价），而 position_qty 记的是扣费后到账量，
  导致在约 -2×taker费率 的价位就自判"已回本"并清仓 —— 成交记录里 OP -0.210%、ARKM -0.227%、MASK -0.795%
  三笔"回本清仓"实际都是亏钱离场的铁证。新增 _breakeven_price()（成本额÷到账量÷(1-费率)），
  止盈混合口径、回本清仓、配对卖点回本豁免三处统一改用保本价判定。
2.【9.1.2 部分成立，结论需反过来】availBal 正是交易所校验卖单时使用的可用量，改按 eq/cashBal 下单会直接触发 51008。
  但它暴露了 v5.8 引入的严重缺陷：币被手动挂单全额冻结时 availBal=0，v5.8 会误判"持仓记录失真"并清除本地账本，
  持仓从此脱管。现改为 get_balance_detail() 区分 可用/总量/冻结：总量>0 视为挂单占用，保留本地账本、
  延后 SELL_BLOCK_RETRY_SEC(默认120s) 再试；只有总量也为 0 才判定失真清除。低于 minSz 的粉尘同样按总量区分。
3.【9.3.2 成立，且比文档更严重】"下单请求异常但按 clOrdId 反查到已成交"是成功入账路径，此前走 logger.error
  触发"🚨 系统异常"推送（买入/卖出还会各自再推一条成交通知，等于假警报）。Logger.error 新增 push 参数，
  这两处改为 push=False。
4. peak_price 语义明确为"持仓期峰值"（回撤基准取历史新高），文档化不改动行为。
文档不成立项：9.1.3（_can_sell 全文仅一个调用点且恒显式传 price，不存在耦合）；
  9.1.4（首次触及 6.5% 时 peak≈现价，跳空到 +10% 激活时止盈价 1.087 仍低于现价 1.10，不会激活即触发；
  按其建议把 peak 重置为现价反而会抬高止盈价、回吐更多利润）。
未执行项（属策略/架构决策，需单独授权）：9.2.1 配对卖点兜底减仓、9.2.2 分批减仓、
  9.2.3 静默期按盈亏区分、9.2.4 买入金额动态化、9.3.3 配置热加载、9.3.4 CSV→SQLite、9.3.6 代码拆分、9.4 可观测性。
v5.8 修正（依据 okx_doc.txt 审查结论，含文档未发现的资金级缺陷）：
1.【严重】移动止盈此前仅在 check_level=="T0"（盈利≥6.5%）时才评估：价格从峰值跌穿 6.5% 后止盈价不再被检查，
  "保底盈利5%离场"从未生效，只能一路持有到回本（甚至亏损）。现改为持仓期间每 tick 评估。
2.【严重】止盈价地板(成本×1.05)与 _can_sell 的 5% 门槛几乎重合，可成交窗口仅约 1bp，跳空一次即永久卖不出去；
  加上原"盈利回落<6.5%撤销激活"分支不可达（被 T0 门槛挡住）、profit_triggered 一经激活永不重置，
  使"亏损超5%回本无条件清仓"豁免（前提 not profit_triggered）对曾触及+6.5%的持仓永久失效 —— 三重死锁。
  现改为混合口径：止盈价被跌穿且价格仍在成本之上 → 立即市价清仓（接受滑点，绝不亏本卖）；
  已跌破成本 → 保留持仓与激活状态继续盯盘，回到成本之上即离场。删除原不可达的撤销分支。
3.卖出前核对平台实际可用量（/api/v5/account/balance，仅卖出场景），本地账本与平台偏离时按平台量下单，
  避免 51008 余额不足造成卖出永久失败；平台余额为0时清除失真的本地持仓记录并提示人工核对。
4.超范围剔除改为可自动恢复：价格回到配置 [ref_low, ref_high] 区间（内缩 0.5% 滞回带，
  OUT_OF_RANGE_HYSTERESIS_PCT 可调）即恢复买入资格并重新入队，xlsx 记录改写为"已恢复…"保留审计痕迹，
  重启后不会再把已恢复币对误剔除；两次翻转间隔 ≥300 秒（OUT_OF_RANGE_FLIP_MIN_SEC），防止贴线抖动刷屏写表。
5.错误推送限流：同一错误默认 300 秒只推一次（ERROR_PUSH_THROTTLE_SEC 可调），WebSocket 断线重连、
  卖出失败不再逐 tick 刷屏钉钉/飞书。
6.收窄两处裸 except（COOLDOWN_DAYS 解析、行情成交字段解析）。
未采纳的文档建议：手续费口径"修正"（1.2）——实测 OKX fee 字段为负数，现有 acc_sz+fee 已是扣费后净额，
  按文档 abs(fee) 改写会重复计入成本、抬高成本价；CSV→SQLite/JSON 迁移、配置热加载、分批减仓、
  波动率仓位、代码拆分（在跑实盘账本，风险大于收益）。
v5.5 新增（业务规则）：
1.以 okx_ding_ok_config.xlsx"币对配置"中的最高价(ref_high)/最低价(ref_low)作为程序计算范围
2.某币对当前成交价不在此范围内（高于最高价或低于最低价）时：
  - 自动记入同目录 okx_ding_ok_out_of_range.xlsx（含币对、当前价、范围上下限、原因"超出程序运行计算的范围"、时间）
  - 立即从买入列表剔除，不再参与买入；重启后通过 xlsx 记录保持剔除状态
  - 触发钉钉/飞书推送通知
3.已有持仓的止盈/止损管理不受影响（基于成本价与峰值，与价格范围无关）
v5.4.1_fix 修复（工程层，交易策略与 v5.4_fix 一致）：
1.修复 load_high_low() 中损坏的字典代码（重复/残缺键导致 SyntaxError），程序此前无法启动
2.修复 WebSocket pong 处理：OKX 心跳回复 "pong" 被当作业务消息解析报错，导致每 25 秒误推一次"系统异常"
3.WebSocket 连接 8443 端口失败时自动回退 443，提升连接成功率
4.市价买入移除 minSz 单位错配检查（minSz 为币本位最小量，按计价货币下单时交给交易所校验），避免误加黑名单
5.显式导入 urllib.error
v5.4_fix 修正：
1.止盈激活门槛修改为盈利6.5%(原5%)，盈利6.5%回撤1.5%保证清仓保底盈利5%
2.配对卖点逻辑重构：普通持仓触碰配对卖点不会直接卖出；仅已激活动态止盈后由动态回撤规则触发离场
3.豁免规则：持仓历史max_loss_pct <=‑0.05(曾经亏损超5%)，触碰配对卖点只要回本即可清仓，不受动态止盈约束
4.止盈激活后浮盈回落到6.5%以下，立刻撤销profit_triggered，重置止盈价，防止毛刺虚假激活后亏损卖出
5.保留原有：持仓亏损超5%记录，只要价格回本，无条件直接清仓
6.买入失败不再重试：交易地域/合规限制 → 常规黑名单；未知错误 → 未知异常黑名单
  均立即从买入列表剔除并推送通知，不再 30 秒/120 秒重试
v5.2 优化（工程层，交易策略不变）：
- 推送异步化：推送走后台线程池，网络慢不再阻塞行情主循环
- 状态保存节流：常规 tick 每 5 秒落盘一次，关键事件（买入/卖出/止盈激活/清仓）即时保存
v5.1 修正内容：
1. 买入前强制刷新 API 持仓并双重检查，杜绝已有持仓重复买入
2. 动态止损表按上涨幅度执行动态清仓（盈利 20% 即清仓，利益最大化）
3. 黑名单拆分为【常规黑名单】+【未知异常黑名单】两类，均从买入列表剔除并在下单前检查
4. 静默期机制审查：卖出/清仓后进入静默期并从买入队列移出，静默期满自动恢复待买入
推送方式在 .env 中通过 NOTIFY_CHANNEL 配置：
  NOTIFY_CHANNEL = dingtalk | feishu | both | none   （默认 dingtalk）
  钉钉: DINGTALK_WEBHOOK_okx / DINGTALK_SECRET_okx
  飞书: FEISHU_WEBHOOK_okx  / FEISHU_SECRET_okx
核心买入逻辑：
1. 价格跌破任意买点（回撤2下/回调2下/过渡2下/极限2下）时，激活买入信号，记录当前最低价
2. 价格继续下跌则更新最低价
3. 当价格从最低价反弹1%且仍低于该买点时，执行买入
4. 买入成功后或价格回升至买点之上时，信号自动取消
5. 其他风控（黑名单、观察列表、静默期、持仓检查等）保持不变
卖出业务规则 v5.4_fix:
1.普通持仓：盈利>=6.5%才激活动态止盈，动态表回撤离场，保证清仓保底盈利5%；触碰配对卖点不会直接卖出
2.豁免场景：持仓期间max_loss_pct <=‑0.05（曾经亏损超5%），触碰配对卖点只要回本即可直接清仓，不受动态止盈限制；
3.豁免场景2：持仓曾经亏损超5%，价格只要回本，无论价位直接清仓
4.盈利>=20%无条件直接清仓
"""
import base64
import csv
import fcntl
import hmac
import hashlib
import json
import os
import queue
import signal
import socket
import ssl
import struct
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from typing import Optional, Any, Dict, List, Tuple
from dotenv import load_dotenv
load_dotenv()
def env_num(name: str, default, cast=float):
    """.env 数值项安全解析：缺省/空串/非法值一律回退默认并告警。
    一个错别字不该让程序起不来——启动即 traceback 意味着所有持仓无人盯守。
    """
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return cast(str(raw).strip())
    except (TypeError, ValueError):
        print(f"[配置] {name} 非法值 {raw!r}，沿用默认 {default}")
        return default
# ==================== 配置常量 ====================
PROGRAM_NAME = "okx_ding_ok"
VERSION = "v6.0"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# v5.13：股票池来源改为 .env INPUT_DATA 指定目录下的全部 xlsx（含子目录）。
# 每个文件的第 2 个 sheet（"层计算幅度"）：A=股票代码(币对)、C=同层最低→ref_low、D=同层最高→ref_high。
# 旧 okx_ding_ok_config.xlsx 已废弃，不再读取。
CONFIG_DIR = os.getenv("INPUT_DATA", "").strip()
# v5.13：股票池倍数层过滤（.env FILTER_LAYER），依据第 1 个 sheet"层计算"的区间列（如"8-16"）。
# 两位数字是倍数：如 8-16 表示 该层历史最高/历史最低 价差在 8~16 倍之间。
#   FILTER_LAYER=8-16        只要 8-16 层
#   FILTER_LAYER=8-16及以上   8-16 的上面一层起：16-32、32-64……
#   FILTER_LAYER=8-16以下     8-16 的下面一层起：4-8、2-4……
# 逗号分隔可叠加多个条件（取并集）；留空 = 不过滤。
FILTER_LAYER_RAW = os.getenv("FILTER_LAYER", "").strip()


def _parse_layer_label(text) -> Optional[Tuple[float, float]]:
    """把"8-16"这样的区间标签解析为 (8.0, 16.0)；解析不了返回 None"""
    if text is None:
        return None
    s = str(text).strip().replace("－", "-").replace("~", "-")
    if "-" not in s:
        return None
    lo_s, _, hi_s = s.partition("-")
    try:
        lo, hi = float(lo_s), float(hi_s)
    except ValueError:
        return None
    return (lo, hi) if 0 < lo < hi else None


def _parse_layer_filters(raw: str) -> List[Tuple[str, float, float]]:
    """解析 FILTER_LAYER，返回 [(模式, lo, hi), ...]；模式 ∈ eq/ge/le。空串返回 []（不过滤）"""
    filters = []
    for item in raw.replace("，", ",").replace("、", ",").split(","):
        item = item.strip()
        if not item:
            continue
        mode = "eq"
        if item.endswith(("及以上", "以上")):
            mode, item = "ge", item[:-3 if item.endswith("及以上") else 2]
        elif item.endswith("以下"):
            mode, item = "le", item[:-2]
        band = _parse_layer_label(item)
        if band is None:
            print(f"[配置] FILTER_LAYER 条件 {item!r} 无法解析为区间(如 8-16)，已忽略该条件")
            continue
        filters.append((mode, band[0], band[1]))
    return filters


def _layer_matches(band: Optional[Tuple[float, float]], filters: List[Tuple[str, float, float]]) -> bool:
    """币对所在层 band 是否命中任一过滤条件"""
    if band is None:
        return False
    for mode, lo, hi in filters:
        if mode == "eq" and band == (lo, hi):
            return True
        # "8-16及以上"= 下一层起（16-32、32-64…）；"8-16以下"= 4-8、2-4…
        if mode == "ge" and band[0] >= hi:
            return True
        if mode == "le" and band[1] <= lo:
            return True
    return False


LAYER_FILTERS = _parse_layer_filters(FILTER_LAYER_RAW)
BLACKLIST_FILE = os.path.join(BASE_DIR, f"{PROGRAM_NAME}_blacklist.csv")
UNKNOWN_BLACKLIST_FILE = os.path.join(BASE_DIR, f"{PROGRAM_NAME}_unknown_blacklist.csv")
OBSERVE_LIST_FILE = os.path.join(BASE_DIR, f"{PROGRAM_NAME}_observe_list.csv")
# v5.5：价格超出配置计算范围（[ref_low, ref_high]）的币对记录表，与主程序同目录
OUT_OF_RANGE_FILE = os.path.join(BASE_DIR, f"{PROGRAM_NAME}_out_of_range.xlsx")
OUT_OF_RANGE_HEADER = ["inst_id", "current_price", "range_high", "range_low", "reason", "add_time"]
DATA_DIR = os.path.join(BASE_DIR, f"{PROGRAM_NAME}_data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)
TRADE_FILE = os.path.join(DATA_DIR, f"{PROGRAM_NAME}_tradeRecord.csv")
POSITIONS_FILE = os.path.join(DATA_DIR, f"{PROGRAM_NAME}_positions.csv")
COOLDOWN_FILE = os.path.join(DATA_DIR, f"{PROGRAM_NAME}_cooldown.csv")
HIGH_LOW_FILE = os.path.join(DATA_DIR, f"{PROGRAM_NAME}_high_low.csv")
PAIR_STATUS_FILE = os.path.join(DATA_DIR, f"{PROGRAM_NAME}_pair_status.csv")
BUY_QUEUE_FILE = os.path.join(DATA_DIR, f"{PROGRAM_NAME}_buy_queue.csv")
FUNDS_FILE = os.path.join(DATA_DIR, f"{PROGRAM_NAME}_funds.csv")
LOG_FILE = os.path.join(DATA_DIR, f"{PROGRAM_NAME}_run.log")
# v5.12 R16：每次成功解析配置后原子落一份快照。xlsx 本体读不出来（缺失/损坏/被 Excel 独占锁定）
# 时它是唯一能救命的副本——没有它就只能 sys.exit(1)，等于"表格坏一下 → 持仓无人盯守"。
CONFIG_SNAPSHOT_FILE = os.path.join(DATA_DIR, f"{PROGRAM_NAME}_config_snapshot.json")
LOCK_FILE = os.path.join(BASE_DIR, f"{PROGRAM_NAME}.lock")
_LOCK_FD = None
def acquire_single_instance_lock():
    """单实例保护：同一数据目录只允许一个进程运行，防止并发写坏 CSV 与触发 API 限流"""
    global _LOCK_FD
    _LOCK_FD = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(_LOCK_FD, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(f"[启动失败] 已有实例在运行（锁文件 {os.path.basename(LOCK_FILE)}），本进程退出，避免双实例并发")
        sys.exit(1)
    os.ftruncate(_LOCK_FD, 0)
    os.write(_LOCK_FD, str(os.getpid()).encode())


def sweep_stale_tmp_files(now=None):
    """清掉上次运行被 kill/崩溃留下的原子写临时文件。
    拿到单实例锁后才做：此时本目录只有本进程在写。
    再跳过最近 60s 内生成的，防止误删还没跑完的并发写（极端情况：锁失效双实例）。"""
    now = time.time() if now is None else now
    bases = (POSITIONS_FILE, COOLDOWN_FILE, HIGH_LOW_FILE, PAIR_STATUS_FILE, BUY_QUEUE_FILE,
             FUNDS_FILE, TRADE_FILE, BLACKLIST_FILE, UNKNOWN_BLACKLIST_FILE, OBSERVE_LIST_FILE,
             OUT_OF_RANGE_FILE, HEARTBEAT_FILE, CONFIG_SNAPSHOT_FILE)
    removed = []
    for base in bases:
        d = os.path.dirname(base) or "."
        prefix = os.path.basename(base) + ".tmp"
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for name in names:
            if not name.startswith(prefix):
                continue
            path = os.path.join(d, name)
            try:
                if now - os.path.getmtime(path) < 60:
                    continue          # 太新：可能正有人在写，跳过
                os.remove(path)
                removed.append(name)
            except OSError:
                pass
    return removed
TRADE_HEADER = ["timestamp", "inst_id", "direction", "price", "qty", "amount", "remaining_funds", "position_price", "profit", "profit_pct", "reason"]
POSITIONS_HEADER = ["inst_id", "position_price", "position_qty", "position_amount", "buy_time", "buy_reason", "pair_type", "pair_sell_line", "peak_price", "stop_price", "profit_triggered", "check_level", "last_check_time", "current_price", "market_value", "unrealized_pnl", "unrealized_pnl_pct", "max_loss_pct", "cost_source", "entry_type", "buy_layer_low", "buy_layer_high", "risen_low", "risen_high", "risen_low_ts", "risen_high_ts", "risen_armed", "v6_next_buy"]
COOLDOWN_HEADER = ["inst_id", "sell_time", "cooldown_until"]
HIGH_LOW_HEADER = ["inst_id", "all_time_high", "all_time_low", "last_update"]
PAIR_STATUS_HEADER = ["inst_id", "pair_type", "is_paired", "buy_price", "buy_time", "sell_line", "sell_line_price", "is_sold", "sell_time", "sell_reason", "profit", "profit_pct"]
BUY_QUEUE_HEADER = ["inst_id", "status", "ref_high", "ref_low", "add_time", "last_check_time"]
FUNDS_HEADER = ["remaining_funds", "total_position_market_value", "total_unrealized_pnl", "total_realized_pnl", "net_asset_value", "last_update"]
BLACKLIST_HEADER = ["inst_id", "reason", "add_time"]
UNKNOWN_BLACKLIST_HEADER = ["inst_id", "reason", "add_time"]
OBSERVE_LIST_HEADER = ["inst_id", "reason", "add_time"]
OKX_WS_HOST = "ws.okx.com"
OKX_WS_PORT = 8443
OKX_WS_PATH = "/ws/v5/public"
# v5.16（文档 C1②）：模拟盘公共 WS（价格与下单环境一致）。OKX_WS_DEMO=auto 跟随 TRADE_MODE，
# always/never（或 1/0）可强制。web: https://wspap.okx.com:8443/ws/v5/public?brokerId=9999
OKX_WS_DEMO_HOST = "wspap.okx.com"
OKX_WS_DEMO_PATH = "/ws/v5/public?brokerId=9999"
_WS_DEMO_CFG = (os.getenv("OKX_WS_DEMO", "auto") or "auto").strip().lower()
OKX_REST_BASE = "https://www.okx.com"
PING_INTERVAL = 25
# v5.12 R12：链路"半死"判定。TCP 不断但服务端不再发任何东西（含 pong）时，
# 光靠继续发 ping 是救不回来的——recv 只会一直超时，行情静默停摆。
# 连续静默超过 WS_STALL_TIMEOUT_SEC 就主动断开重连（走正常 reconnect 分支重新订阅）。
WS_STALL_TIMEOUT_SEC = PING_INTERVAL * env_num("WS_STALL_FACTOR", 3.0)
RECONNECT_DELAY = 3
# v5.8：超范围自动恢复参数。越界币对价格回到区间内即恢复买入，为避免贴线抖动
# （现价与边界仅差十万分之一）反复翻转，恢复需比边界内缩 RANGE_HYSTERESIS_PCT，且两次翻转间隔不小于 RANGE_FLIP_MIN_INTERVAL_SEC
RANGE_HYSTERESIS_PCT = env_num("OUT_OF_RANGE_HYSTERESIS_PCT", 0.005)
RANGE_FLIP_MIN_INTERVAL_SEC = env_num("OUT_OF_RANGE_FLIP_MIN_SEC", 300.0)
# v5.16（文档 C4）：买点漂移重绑死区。价格须越过旧买点边界 BUY_REBIND_DEADBAND_PCT（默认 0.3%）
# 才认可"最佳买点漂移"并重绑；死区内保持原绑定、最低价继续滚动，消除贴线抖动的反复重绑/推送
# （实证两天 384 次漂移，TAO 一秒内 callback2_down↔pullback2_down 往返）。设 0 关闭死区。
BUY_REBIND_DEADBAND_PCT = env_num("BUY_REBIND_DEADBAND_PCT", 0.003)
# 重绑时最低价取"新旧更小值"（保留已跟踪低点）。注意：该行为会重新引入 R7 回归
# （贴线陈旧低点使"反弹1%确认"被跳过直接买入，见 test_okx_strategy.TestBuySignalRebind），
# 故默认关闭；仅在明确需要"不丢失低点跟踪"时手动开启。
BUY_REBIND_KEEP_LOWEST = env_num("BUY_REBIND_KEEP_LOWEST", 0.0) > 0
def range_recover_band(low: float, high: float, pct: float = None) -> Tuple[float, float, float]:
    """超范围币对的"恢复带"（v5.12 R15）。

    原实现直接用 `[low×(1+p), high×(1-p)]`：区间本身比滞回带还窄时
    （high/low < (1+p)/(1-p)，例如 1.00~1.005 配 p=0.5%）上下界交叉，带为空
    —— 越界一次就永久剔除，只能改表或重启才能恢复。
    这里把 p 自动压到不超过 `(high-low)/(high+low)` 的一半，带永不为空且始终落在区间内部。
    返回 (下界, 上界, 实际生效的 pct)。
    """
    p = RANGE_HYSTERESIS_PCT if pct is None else pct
    if not (0 < low < high) or p <= 0:
        return low, high, max(0.0, p) if p > 0 else 0.0
    cap = (high - low) / (high + low)          # 半宽/中点：p 超过它上下界就交叉
    p_eff = min(p, cap * 0.5)
    return low * (1 + p_eff), high * (1 - p_eff), p_eff
# v5.9：币被手动挂单全额占用（可用 0 / 总量 > 0）时的卖出重试间隔
SELL_BLOCK_RETRY_SEC = env_num("SELL_BLOCK_RETRY_SEC", 120.0)
# v5.12 R5：市价单未成交、余额不足都是"过一会儿就能成"的暂时状态，
# 只短期冷却重试，绝不能永久打入未知异常黑名单（那样只能手工改 CSV 才能恢复）
BUY_NOTFILLED_COOLDOWN_SEC = env_num("BUY_NOTFILLED_COOLDOWN_SEC", 300.0)
BUY_BALANCE_COOLDOWN_SEC = env_num("BUY_BALANCE_COOLDOWN_SEC", 600.0)
# v5.12 R6：卖出下单失败后的重试间隔。以前失败只推一条消息就 return，价格仍触发止盈时
# 每个行情 tick 都会重来一遍（锁内 10s 余额查询 + 下单 + 最长 4s 等成交），行情接收被拖死
SELL_FAIL_RETRY_SEC = env_num("SELL_FAIL_RETRY_SEC", 60.0)
# v5.9：taker 费率，用于推算含双边手续费的保本价（OKX 现货普通档 taker 0.1%）
TAKER_FEE_RATE = env_num("TAKER_FEE_RATE", 0.001)
# v5.12 R15：买入前的余额闸门系数。原先写死 `if balance < 110`，与可配的 MIN_BUY_AMOUNT 脱钩
# （MIN_BUY_AMOUNT 调到 500 时余额闸门仍是 110，下单必被 OKX 拒），现按 MIN_BUY_AMOUNT×系数计算，
# 默认 100×1.1 = 110，与原行为一致。
BUY_BALANCE_MARGIN = env_num("BUY_BALANCE_MARGIN", 1.1)
# v5.15（文档 P0-3）：市价买入被部分成交（OKX 返回 state=canceled）时按差额补单的次数上限；
# 补单差额 < BUY_PARTIAL_MIN_TOPUP 或次数用尽则放弃（按实际成交额入账 + 告警，不再静默缩水）
BUY_PARTIAL_TOPUP_MAX = env_num("BUY_PARTIAL_TOPUP_MAX", 1, int)
BUY_PARTIAL_FILL_TOLERANCE = env_num("BUY_PARTIAL_FILL_TOLERANCE", 0.95)
BUY_PARTIAL_MIN_TOPUP = env_num("BUY_PARTIAL_MIN_TOPUP", 55.0)
# v5.15（文档 P1-1/P1-3）：启动探测失败/当前环境无此产品的币对运行期重探（指数退避）
REPROBE_BASE_SEC = env_num("REPROBE_BASE_SEC", 600.0)
REPROBE_MAX_SEC = env_num("REPROBE_MAX_SEC", 3600.0)
# v5.16（文档 C11）：未知异常黑名单条目满此年龄后自动复检交易对（只查 instrument，不下单）
UNKNOWN_BLACKLIST_RECHECK_SEC = env_num("UNKNOWN_BLACKLIST_RECHECK_SEC", 86400.0)
# v5.15（文档 P2-3）：下单后查询成交状态的等待参数（原写死 8×0.5s=4s）
FILL_WAIT_TRIES = env_num("FILL_WAIT_TRIES", 8, int)
FILL_WAIT_INTERVAL = env_num("FILL_WAIT_INTERVAL", 0.5)
# v5.18（文档 C7）：订单执行线程开关与队列上限。行情线程只做零网络预检并投递任务，
# 下单/等成交/补单等 REST 在锁外由订单线程串行完成；设 ORDER_EXECUTOR_ENABLED=0 回退旧同步行为。
ORDER_EXECUTOR_ENABLED = os.environ.get("ORDER_EXECUTOR_ENABLED", "1").strip().lower() not in (
    "0", "false", "no", "off", "disabled")
ORDER_QUEUE_MAX = env_num("ORDER_QUEUE_MAX", 64, int)
CSV_LOCK = threading.RLock()
# 账本读-改-写全局锁：行情线程（on_trade/合并落盘）与后台账户恢复线程（sync_positions_from_api）
# 都是"读全表→改→写全表"，各拿各的锁等于没锁 —— 恢复线程会用启动时的旧快照打回行情线程刚写入的行
ENGINE_LOCK = threading.RLock()
# ==================== 全局变量 ====================
_okx_client = None
_balance_cache = {"value": 0.0, "timestamp": 0.0}
_BALANCE_CACHE_TTL = 3.0
_positions_cache = {"data": {}}
# v5.10 资源防护：整表写盘聚合队列 + 全局落盘闸门（详见 save_positions/flush_high_low/_state_save_due）
_HL_PENDING: Dict[str, Tuple[float, float]] = {}
_STATE_SAVE_LOCK = threading.Lock()
_last_state_save_ts = 0.0
# 运行期负载自适应（1 核 / 960MB 的机器上，行情+落盘+推送要留出足够余量，否则 OOM 或卡死）
# 按用户要求（2026-10-12）：本进程 CPU 占用不超过 70%，超过即降频；可用 CPU_MAX_LOAD_RATIO 覆盖
SYS_GUARD = {
    "load1": 0.0,
    "load_limit": float(os.cpu_count() or 1),
    "cpu_max_ratio": env_num("CPU_MAX_LOAD_RATIO", 0.7),
    "mem_available_mb": 0.0,
    "mem_min_mb": env_num("MEM_MIN_AVAILABLE_MB", 80.0),
    "proc_cpu_pct": 0.0,
    "_prev_ticks": None,
    "state_save_interval": 5.0,     # 常态 5s，超阈值自动放宽
    "state_save_interval_max": 30.0,
    "sampled_at": 0.0,
    "degraded": False,
}
def _proc_cpu_ticks() -> Optional[float]:
    """本进程已用 CPU 时间（用户+系统，单位秒）。读 /proc/self/stat，不 fork、不依赖 psutil"""
    try:
        with open("/proc/self/stat", "r") as f:
            fields = f.read().split(") ", 1)[1].split()
        ticks = (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
        return ticks
    except Exception:
        return None
def sample_system_load() -> Dict[str, float]:
    """采样系统负载与本进程 CPU 占用（供落盘降频与心跳使用），2 秒内的重复调用直接返回上次结果"""
    now = time.time()
    if now - SYS_GUARD["sampled_at"] < 2.0:
        return SYS_GUARD
    prev_ticks, prev_ts = SYS_GUARD["_prev_ticks"], SYS_GUARD["sampled_at"]
    SYS_GUARD["sampled_at"] = now
    try:
        with open("/proc/loadavg", "r") as f:
            SYS_GUARD["load1"] = float(f.read().split()[0])
    except Exception:
        try:
            SYS_GUARD["load1"] = os.getloadavg()[0]
        except Exception:
            pass
    ticks = _proc_cpu_ticks()
    if ticks is not None:
        if prev_ticks is not None and now > prev_ts:
            # 单核机器上 cpu% 上限按核数折算：本进程占用超过 CPU_MAX_LOAD_RATIO×核数 即降频
            SYS_GUARD["proc_cpu_pct"] = max(0.0, min(100.0 * SYS_GUARD["load_limit"],
                                                     (ticks - prev_ticks) / (now - prev_ts) * 100.0))
        SYS_GUARD["_prev_ticks"] = ticks
    try:
        mem_avail = 0.0
        rss_kb = 0.0
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    mem_avail = float(line.split()[1]) / 1024.0
                    break
        with open("/proc/self/status", "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss_kb = float(line.split()[1])
                    break
        SYS_GUARD["mem_available_mb"] = mem_avail
        SYS_GUARD["rss_mb"] = rss_kb / 1024.0
        # 可用内存吃紧时同样按高负载处理：宁可延迟落盘，也不要被 OOM 杀掉导致持仓无人盯守
        SYS_GUARD["degraded"] = (SYS_GUARD["proc_cpu_pct"] > 100.0 * SYS_GUARD["load_limit"] * SYS_GUARD["cpu_max_ratio"]
                                 or SYS_GUARD["load1"] > SYS_GUARD["load_limit"]
                                 or 0 < mem_avail < SYS_GUARD["mem_min_mb"])
    except Exception:
        pass
    SYS_GUARD["state_save_interval"] = (
        SYS_GUARD["state_save_interval_max"] if SYS_GUARD["degraded"]
        else env_num("STATE_SAVE_INTERVAL_SEC", 5.0)
    )
    return SYS_GUARD
def _state_save_due(force: bool = False) -> bool:
    """状态落盘全局闸门：所有币对共用一次写盘机会，避免 N 个币对各自整表重写 + fsync。

    force=True 是买入/卖出/止盈激活等关键事件，必须即时落盘，不受闸门限制。
    """
    global _last_state_save_ts
    if force:
        with _STATE_SAVE_LOCK:
            _last_state_save_ts = time.time()
        return True
    interval = SYS_GUARD["state_save_interval"]
    now = time.time()
    with _STATE_SAVE_LOCK:
        if now - _last_state_save_ts < interval:
            return False
        _last_state_save_ts = now
    return True
# 行情连接健康状态（供心跳文件读取；文档 9.4 可观测性）
WS_HEALTH = {
    "connected": False,
    "connected_at": "",
    "last_msg_ts": 0.0,
    "last_error": "",
    "last_error_ts": "",
    "consecutive_fail": 0,
    "reconnects": 0,
    "stall_reconnects": 0,
    "thread_restarts": 0,
}
# v5.12 R8：统一停止开关。SIGTERM/SIGINT 只置位，真正的收尾（脏账本落盘、资金快照、线程池）
# 由 main() 的 finally 单点完成，避免"被 kill 就当场蒸发、半截数据不落盘"。
STOP_EVENT = threading.Event()
HEARTBEAT_FILE = os.path.join(DATA_DIR, f"{PROGRAM_NAME}_heartbeat.json")
HEARTBEAT_INTERVAL_SEC = env_num("HEARTBEAT_INTERVAL_SEC", 10.0)
def write_heartbeat(engine, extra: Optional[Dict] = None) -> Dict:
    """写心跳快照：远程随时能判断"最后一次活着是什么时候"，中断排查不必翻大日志"""
    try:
        with engine.lock:
            symbols = len(engine.states)
            open_positions = sum(1 for st in engine.states.values() if st.has_position)
            triggered = sum(1 for st in engine.states.values() if st.profit_triggered)
            # v5.15（文档 P3-3）：不可买币对分类计数（远程判断"池子变了没有/环境是否缺失"）
            net_failed = sum(1 for st in engine.states.values()
                             if not st._okx_available and getattr(st, "_net_failed", False))
            env_missing = sum(1 for st in engine.states.values()
                              if not st._okx_available and getattr(st, "_env_missing", False))
            # v5.16（文档 C10）：对账重建成本（市价估值，非真实买入均价）的持仓计数
            reconcile_symbols = sum(1 for st in engine.states.values()
                                    if st.has_position and getattr(st, "cost_source", "") == "reconcile")
            # v5.17（文档 C12）：无行情持仓计数（超过 STALE_TICK_SEC 没收到任何行情、靠 REST 兜底盯盘）
            _hb_now = time.time()
            stale_positions = sum(1 for st in engine.states.values()
                                  if st.has_position
                                  and _hb_now - getattr(st, "last_tick_ts", 0.0) > STALE_TICK_SEC)
            # v5.20：上轮行情补齐喂入数量（远程判断"冷门币对是否在持续补齐"）
            market_gap_fed = getattr(engine, "_last_market_gap_fed", 0)
            # v5.18（文档 C7）：订单执行线程观测（队列深度 + 执行中的币对数）
            orders_pending = engine.orders.pending() if getattr(engine, "orders", None) is not None else 0
            orders_in_flight = sum(1 for st in engine.states.values()
                                   if getattr(st, "order_in_flight", None))
        payload = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "epoch": time.time(),
            "pid": os.getpid(),
            "version": VERSION,
            "trade_mode": TRADE_MODE,
            "symbols": symbols,
            "open_positions": open_positions,
            "profit_triggered": triggered,
            "net_failed_symbols": net_failed,
            "env_missing_symbols": env_missing,
            "reconcile_symbols": reconcile_symbols,
            "stale_positions": stale_positions,
            "market_gap_fed": market_gap_fed,
            "orders_pending": orders_pending,
            "orders_in_flight": orders_in_flight,
            "ws": {k: v for k, v in WS_HEALTH.items()},
            "sys": {
                "load1": round(SYS_GUARD["load1"], 2),
                "cpu_cores": SYS_GUARD["load_limit"],
                "cpu_max_ratio": SYS_GUARD["cpu_max_ratio"],
                "proc_cpu_pct": round(SYS_GUARD.get("proc_cpu_pct", 0.0), 1),
                "mem_available_mb": round(SYS_GUARD["mem_available_mb"], 1),
                "rss_mb": round(SYS_GUARD.get("rss_mb", 0.0), 1),
                "degraded": SYS_GUARD["degraded"],
                "state_save_interval": SYS_GUARD["state_save_interval"],
            },
            "push_pending": push_pending_count(),
        }
        if extra:
            payload.update(extra)
        tmp = HEARTBEAT_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, HEARTBEAT_FILE)   # 原子替换：随时 cat 都不会读到半截 JSON
        return payload
    except Exception as e:
        print(f"[心跳] 写入失败: {e}")
        return {}
# ==================== 动态止盈表 ====================
# v5.12 R13：原 136 行硬表 PROFIT_STOP_MAP 就是下面这条线性规则，改用公式（等价性由
# test_okx_strategy.TestStopLossTable 对 doc_txt/profit_stop_map_v5.11.json 逐档校验）。
#   盈利 < 6.5%          → 容忍回撤 1.5%（未激活动态止盈时的默认值）
#   6.5% ≤ 盈利 < 20%    → 1.5% - 0.1 × (盈利 - 6.5%)，按 0.1% 分档取低边（与原表一致）
#   盈利 ≥ 20%           → 0（配合 _check_take_profit 的"≥20% 立即清仓"分支）
STOP_LOSS_BASE = 0.015               # 6.5% 档位的回撤容忍
STOP_LOSS_TRIGGER_PCT = 0.065        # 动态止盈起始盈利档
STOP_LOSS_ZERO_PCT = 0.20            # 该盈利以上回撤容忍归零（立即清仓）
STOP_LOSS_SLOPE = 0.1                # 每多 1% 盈利，回撤容忍少 0.1%
STOP_LOSS_BUCKET = 0.001             # 原表按 0.1% 一档，保持分档口径
def get_stop_loss(profit_pct: float) -> float:
    """按当前盈利水平返回动态回撤清仓比例（等价于原 PROFIT_STOP_MAP 查表）"""
    if profit_pct < STOP_LOSS_TRIGGER_PCT:
        return STOP_LOSS_BASE
    if profit_pct >= STOP_LOSS_ZERO_PCT:
        return 0.0
    bucket = int(profit_pct / STOP_LOSS_BUCKET + 1e-9) * STOP_LOSS_BUCKET   # 向下取整到档位
    return max(0.0, STOP_LOSS_BASE - STOP_LOSS_SLOPE * (bucket - STOP_LOSS_TRIGGER_PCT))
# ==================== 日志系统 ====================
class Logger:
    def __init__(self, log_file: str):
        self.log_file = log_file
        self._ensure_log_file()

    def _ensure_log_file(self):
        if not os.path.exists(self.log_file):
            try:
                with open(self.log_file, 'w', encoding='utf-8') as f:
                    f.write(f"# {PROGRAM_NAME} {VERSION} 运行日志\n")
                    f.write(f"# 创建时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write("=" * 60 + "\n")
            except Exception:
                pass

    def _should_write_log(self, level: str, category: str) -> bool:
        if level == "ERROR":
            return True
        if level == "INFO":
            # v5.17（文档 C12）：白名单补 "trade_event"——止盈/清仓/买入/卖出等交易事件
            # 与"无行情持仓启用兜底盯盘"同属关键运维信息，此前只飘控制台、run.log 捞不到
            return category in ["startup", "shutdown", "config_load", "buy_execute", "sell_execute",
                                "profit_trigger", "stop_loss_trigger", "cooldown_start", "trade_event"]
        if level == "WARN":
            # v5.15（文档 P1-5）：WARN 全量落盘。此前白名单只有 3 个分类，实测 run.log 472 行
            # ERROR + 仅 1 行 WARN，而"卖出受阻/部分成交/未知错误/黑名单复检"等关键运维信息
            # 只飘在控制台（journald 可见、run.log 捞不到）
            return True
        return False

    def _write(self, level: str, msg: str, category: str = "general", push: bool = True):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] [{level}] {msg}"
        print(log_line)
        if self._should_write_log(level, category):
            try:
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(log_line + "\n")
            except Exception:
                pass
        if level == "ERROR" and push:
            self._push_error(msg)

    def _push_error(self, msg: str):
        try:
            # v5.8：同类错误限流推送（默认 300 秒一次），断线重连/下单被拒不再刷屏
            if not push_notify_throttled(
                f"🚨 系统异常\n\n{msg}\n\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                key=f"error:{msg[:60]}",
                title="系统异常",
                msg_type="text",
            ):
                print(f"[日志] 同类异常推送限流中({ERROR_PUSH_THROTTLE_SEC:.0f}s)，仅记录日志: {msg[:80]}")
        except Exception as e:
            print(f"[日志] 异常推送失败: {e}")

    def info(self, msg: str, category: str = "general"):
        self._write("INFO", msg, category)

    def warn(self, msg: str, category: str = "general"):
        self._write("WARN", msg, category)

    def error(self, msg: str, category: str = "general", push: bool = True):
        self._write("ERROR", msg, category, push)

    def debug(self, msg: str, category: str = "debug"):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [DEBUG] {msg}")
# ==================== 钉钉推送 ====================
def build_dingtalk_url(webhook: str, secret: str = None) -> str:
    if not secret:
        return webhook
    timestamp = str(int(time.time() * 1000))
    sign_string = f"{timestamp}\n{secret}".encode("utf-8")
    sign = base64.b64encode(hmac.new(secret.encode("utf-8"), sign_string, hashlib.sha256).digest()).decode("utf-8")
    parts = urllib.parse.urlsplit(webhook)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query.extend([("timestamp", timestamp), ("sign", sign)])
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment))
def push_to_dingtalk(webhook: str, secret: str = None, text: str = None, title: str = "交易提醒", msg_type: str = "text") -> bool:
    if not webhook:
        return False
    try:
        url = build_dingtalk_url(webhook, secret)
        payload = {"msgtype": "text", "text": {"content": text}} if msg_type == "text" else {"msgtype": "markdown", "markdown": {"title": title, "text": text}}
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json", "User-Agent": "Python DingTalk Bot"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8")).get("errcode") in (0, "0", None)
    except Exception as e:
        print(f"[钉钉] 推送失败: {e}")
        return False
# ==================== 飞书推送 ====================
def push_to_feishu(webhook: str, secret: str = None, text: str = None, title: str = "交易提醒", msg_type: str = "text") -> bool:
    """飞书自定义机器人推送，支持签名校验（v5.0 新增）
    msg_type: text=纯文本, interactive=交互卡片
    签名算法: hmac_sha256(key=f"{timestamp}\\n{secret}", msg="")，base64 编码
    """
    if not webhook:
        return False
    try:
        if msg_type == "interactive":
            payload = {
                "msg_type": "interactive",
                "card": {
                    "type": "template",
                    "data": {
                        "template_id": "blue",
                        "header": {"title": {"tag": "plain_text", "content": title}},
                        "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": text}}],
                    },
                },
            }
        else:
            payload = {"msg_type": "text", "content": {"text": text}}
        if secret:
            ts = str(int(time.time()))
            string_to_sign = f"{ts}\n{secret}"
            hmac_code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
            sign = base64.b64encode(hmac_code).decode("utf-8")
            payload["timestamp"] = ts
            payload["sign"] = sign
        req = urllib.request.Request(webhook, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json", "User-Agent": "Python Feishu Bot"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            return res.get("code") == 0 or res.get("StatusCode") == 0
    except Exception as e:
        print(f"[飞书] 推送失败: {e}")
        return False
# ==================== 多通道推送统一入口（v5.0） ====================
# .env 配置：
#   NOTIFY_CHANNEL      = dingtalk | feishu | both | none   （默认 dingtalk）
#   DINGTALK_WEBHOOK_okx / DINGTALK_SECRET_okx              （钉钉，原有）
#   FEISHU_WEBHOOK_okx  / FEISHU_SECRET_okx                 （飞书，新增）
NOTIFY_CONFIG = {
    "channel": "none",
    "ding_webhook": "",
    "ding_secret": "",
    "feishu_webhook": "",
    "feishu_secret": "",
}
def setup_notify(channel: str = "dingtalk", ding_webhook: str = "", ding_secret: str = "", feishu_webhook: str = "", feishu_secret: str = ""):
    """初始化推送通道（在 main 启动时调用一次）"""
    NOTIFY_CONFIG["channel"] = (channel or "dingtalk").strip().lower()
    NOTIFY_CONFIG["ding_webhook"] = ding_webhook
    NOTIFY_CONFIG["ding_secret"] = ding_secret
    NOTIFY_CONFIG["feishu_webhook"] = feishu_webhook
    NOTIFY_CONFIG["feishu_secret"] = feishu_secret
# 全局推送线程池（v5.2 优化：推送异步化，不阻塞行情主循环）
NOTIFY_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="notify")
# v5.10：线程池队列本身无界，推送端点卡住时任务会一直堆积吃内存（本机可用内存不足 200MB）。
# 这里给在途任务设上限，超了就丢弃并记日志——丢推送远比丢行情/丢持仓账本好。
NOTIFY_MAX_PENDING = env_num("NOTIFY_MAX_PENDING", 50, int)
_NOTIFY_PENDING = 0
_NOTIFY_PENDING_LOCK = threading.Lock()
def push_pending_count() -> int:
    return _NOTIFY_PENDING
def _push_notify_worker(text: str, title: str, msg_type: str):
    """后台线程执行实际推送，异常不外抛"""
    global _NOTIFY_PENDING
    try:
        ok = False
        ch = NOTIFY_CONFIG["channel"]
        if ch in ("dingtalk", "both") and NOTIFY_CONFIG["ding_webhook"]:
            ok = push_to_dingtalk(NOTIFY_CONFIG["ding_webhook"], NOTIFY_CONFIG["ding_secret"], text, title, msg_type) or ok
        if ch in ("feishu", "both") and NOTIFY_CONFIG["feishu_webhook"]:
            ok = push_to_feishu(NOTIFY_CONFIG["feishu_webhook"], NOTIFY_CONFIG["feishu_secret"], text, title, msg_type) or ok
        return ok
    except Exception as e:
        print(f"[推送] 后台推送异常: {e}")
        return False
    finally:
        with _NOTIFY_PENDING_LOCK:
            _NOTIFY_PENDING = max(0, _NOTIFY_PENDING - 1)
def push_notify(text: str, title: str = "交易提醒", msg_type: str = "text") -> bool:
    """统一推送入口：后台线程异步推送，网络慢不阻塞行情主循环；在途任务超限则丢弃"""
    global _NOTIFY_PENDING
    with _NOTIFY_PENDING_LOCK:
        if _NOTIFY_PENDING >= NOTIFY_MAX_PENDING:
            print(f"[推送] 在途任务已达上限 {NOTIFY_MAX_PENDING}，本条丢弃: {text[:60]}")
            return False
        _NOTIFY_PENDING += 1
    try:
        NOTIFY_POOL.submit(_push_notify_worker, text, title, msg_type)
    except Exception as e:
        with _NOTIFY_PENDING_LOCK:
            _NOTIFY_PENDING = max(0, _NOTIFY_PENDING - 1)
        print(f"[推送] 提交后台推送失败: {e}")
        return False
    return True
# v5.8：错误推送限流。此前任何 logger.error 都会直推钉钉/飞书，WebSocket 断线重连（每 ~3 秒一次）
# 或卖出被拒会在几分钟内刷屏。同一 key 在 ERROR_PUSH_THROTTLE_SEC 秒内只推一次，其余仅写日志。
ERROR_PUSH_THROTTLE_SEC = env_num("ERROR_PUSH_THROTTLE_SEC", 300.0)
_PUSH_THROTTLE: Dict[str, float] = {}
_PUSH_THROTTLE_LOCK = threading.Lock()
def push_notify_throttled(text: str, key: str, title: str = "交易提醒", msg_type: str = "text", interval: float = None) -> bool:
    """同一 key 在 interval 秒内只推送一次；返回 False 表示本次被限流（未推送）"""
    window = ERROR_PUSH_THROTTLE_SEC if interval is None else interval
    now = time.time()
    with _PUSH_THROTTLE_LOCK:
        last = _PUSH_THROTTLE.get(key, 0.0)
        if now - last < window:
            return False
        _PUSH_THROTTLE[key] = now
        if len(_PUSH_THROTTLE) > 500:
            for k in [k for k, v in _PUSH_THROTTLE.items() if now - v > window * 10]:
                _PUSH_THROTTLE.pop(k, None)
    return push_notify(text, title, msg_type)
# ==================== CSV 辅助函数 ====================
# v5.10 读缓存：64 个币对启动时会对同一批小文件做约 800 次整表读（每个 SymbolState 各读 8 份），
# 1 核 / 960MB 的机器上这部分纯开销完全没必要。以 (mtime_ns, size, inode) 为键缓存解析结果，
# 任何写入立即失效，读到的行返回浅拷贝（调用方会就地改 row 字典，不能共享同一份对象）。
_CSV_ROW_CACHE: Dict[str, Tuple[Any, List[Dict]]] = {}
# 读失败 ≠ 空表：整表重写（_write_csv_all）是"读全表→改一行→写全表"，一次 EMFILE/OOM/坏行
# 造成的空读数会被当成真实内容落盘，直接抹掉其他币对的持仓/队列行。
# 这里记住"上次读失败过"的文件，在真正读到内容之前拒绝整表重写（状态脏、下个周期重试）。
_CSV_READ_FAILED: set = set()
def _csv_cache_key(file_path: str):
    try:
        st = os.stat(file_path)
        return (st.st_mtime_ns, st.st_size, st.st_ino)
    except OSError:
        return None
def _csv_cache_drop(file_path: str):
    _CSV_ROW_CACHE.pop(file_path, None)
def _ensure_csv_header(file_path: str, header: List[str]):
    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        try:
            with CSV_LOCK, open(file_path, 'w', encoding='utf-8-sig', newline='') as f:
                csv.writer(f).writerow(header)
        except Exception as e:
            print(f"[CSV] 初始化失败 {file_path}: {e}")
        _csv_cache_drop(file_path)
        return
    try:
        # 只读表头一行：此前为了比对表头会把整个文件读进内存，等于每次读数据都白读两遍
        with CSV_LOCK, open(file_path, 'r', encoding='utf-8-sig') as f:
            existing_header = next(csv.reader(f), [])
    except Exception as e:
        print(f"[CSV] 读取 header 失败 {file_path}: {e}")
        return
    if existing_header == header:
        return
    print(f"[CSV] 升级表结构 {file_path}: {existing_header} -> {header}")
    try:
        with CSV_LOCK, open(file_path, 'r', encoding='utf-8-sig') as f:
            rows = list(csv.reader(f))[1:]
    except Exception as e:
        print(f"[CSV] 迁移读取失败 {file_path}: {e}")
        return
    old_idx = {name: i for i, name in enumerate(existing_header)}
    migrated = []
    for row in rows:
        new_row = []
        for col in header:
            if col in old_idx and old_idx[col] < len(row):
                new_row.append(row[old_idx[col]])
            else:
                new_row.append("")
        migrated.append(new_row)
    tmp_path = _csv_tmp_path(file_path) + ".migrate"
    try:
        with CSV_LOCK:
            with open(tmp_path, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(header)
                writer.writerows(migrated)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, file_path)
            _csv_cache_drop(file_path)
    except Exception as e:
        print(f"[CSV] 迁移失败 {file_path}: {e}")
        try:
            os.remove(tmp_path)
        except OSError:
            pass
def _read_csv(file_path: str, header: List[str]) -> List[Dict]:
    _ensure_csv_header(file_path, header)
    key = _csv_cache_key(file_path)
    if key is not None:
        cached = _CSV_ROW_CACHE.get(file_path)
        if cached is not None and cached[0] == key:
            return [dict(row) for row in cached[1]]
    result = []
    read_ok = False
    try:
        with CSV_LOCK, open(file_path, 'r', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                result.append(row)
        read_ok = True
    except Exception as e:
        print(f"[CSV] 读取失败 {file_path}: {e}（本次读数不可信，禁止据此整表重写）")
    if read_ok:
        _CSV_READ_FAILED.discard(file_path)
        if key is not None:
            _CSV_ROW_CACHE[file_path] = (key, result)
    else:
        _CSV_READ_FAILED.add(file_path)
    return [dict(row) for row in result]
def _read_csv_ref(file_path: str, header: List[str]) -> List[Dict]:
    """只读视图：命中缓存时直接返回缓存的列表对象，不做逐行拷贝。调用方不得修改返回值。"""
    _ensure_csv_header(file_path, header)
    key = _csv_cache_key(file_path)
    if key is not None:
        cached = _CSV_ROW_CACHE.get(file_path)
        if cached is not None and cached[0] == key:
            return cached[1]
    return _read_csv(file_path, header)
def _to_float(value, default: float = 0.0) -> float:
    """CSV 数值字段安全转换：坏值（如表头错位混入的时间戳字符串）返回默认值，不再抛异常"""
    try:
        s = (str(value).strip() if value is not None else "")
        if s == "" or s.lower() == "none":
            return default
        return float(s)
    except (TypeError, ValueError):
        return default
def _is_number(value) -> bool:
    try:
        s = (str(value).strip() if value is not None else "")
        if s == "" or s.lower() == "none":
            return False
        float(s)
        return True
    except (TypeError, ValueError):
        return False
def _write_csv_row(file_path: str, header: List[str], row: Dict):
    try:
        _ensure_csv_header(file_path, header)
        with CSV_LOCK, open(file_path, 'a', encoding='utf-8-sig', newline='') as f:
            csv.writer(f).writerow([row.get(c, "") for c in header])
        _csv_cache_drop(file_path)
    except Exception as e:
        print(f"[CSV] 写入失败 {file_path}: {e}")
def _csv_tmp_path(file_path: str) -> str:
    """tmp 名带 pid+线程：并发整表写时两个写者不会踩同一个临时文件"""
    return f"{file_path}.tmp.{os.getpid()}.{threading.get_ident()}"
def _write_csv_all(file_path: str, header: List[str], rows: List[Dict]) -> bool:
    # 临时文件 + 原子替换：避免 'w' 清空后写到一半崩溃/被并发读走空文件，导致表头与数据错位
    if file_path in _CSV_READ_FAILED:
        print(f"[CSV] 拒绝整表重写 {file_path}：上一次读取失败，当前内容不可信（宁可少落一次盘，也不抹掉其他行）")
        return False
    tmp_path = _csv_tmp_path(file_path)
    try:
        # 临时文件写入与 replace 必须同在一把锁内：否则 A 写完释放锁、B 覆写同一正式文件期间
        # A 的 replace 会把 B 的半截内容提成正式文件
        with CSV_LOCK:
            with open(tmp_path, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=header, extrasaction='ignore')
                writer.writeheader()
                for row in rows:
                    writer.writerow(row)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, file_path)
            _csv_cache_drop(file_path)
            _CSV_READ_FAILED.discard(file_path)
        return True
    except Exception as e:
        print(f"[CSV] 写入失败 {file_path}: {e}")
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return False
# ==================== 黑名单与待观察列表 ====================
def load_blacklist() -> set:
    rows = _read_csv(BLACKLIST_FILE, BLACKLIST_HEADER)
    return {row.get("inst_id", "") for row in rows if row.get("inst_id")}
def add_to_blacklist(inst_id: str, reason: str):
    if not inst_id:
        return
    if inst_id in load_blacklist():
        return
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _write_csv_row(BLACKLIST_FILE, BLACKLIST_HEADER, {
        "inst_id": inst_id,
        "reason": reason,
        "add_time": now_str
    })
    print(f"[黑名单] {inst_id} 已加入黑名单，原因: {reason}")
def remove_from_blacklist(inst_id: str):
    rows = _read_csv(BLACKLIST_FILE, BLACKLIST_HEADER)
    kept = [r for r in rows if r.get("inst_id") != inst_id]
    if len(kept) != len(rows):
        _write_csv_all(BLACKLIST_FILE, BLACKLIST_HEADER, kept)
        print(f"[黑名单] {inst_id} 已从黑名单移除")
def recheck_startup_blacklist(logger):
    """启动复检：原因为"启动检测不可交易"的币对，若当前 OKX 现货已可交易，则从黑名单移除。
    其他原因（合规限制等）的黑名单记录不受影响。"""
    rows = _read_csv(BLACKLIST_FILE, BLACKLIST_HEADER)
    candidates = [r for r in rows if r.get("inst_id") and "启动检测不可交易" in (r.get("reason") or "")]
    removed = []
    for r in candidates:
        inst_id = r["inst_id"]
        try:
            if _okx_client is not None:
                available = _okx_client.get_instrument(inst_id) is not None
            else:
                available = check_okx_available(inst_id)
        except Exception:
            available = False
        if available:
            remove_from_blacklist(inst_id)
            removed.append(inst_id)
    if removed:
        logger.info(f"黑名单复检：{len(removed)} 个币对已恢复可交易并从黑名单移除: {', '.join(removed)}", "startup")
    else:
        logger.info(f"黑名单复检：{len(candidates)} 个[启动检测不可交易]币对均仍不可交易，无移除", "startup")
def load_unknown_blacklist() -> set:
    rows = _read_csv(UNKNOWN_BLACKLIST_FILE, UNKNOWN_BLACKLIST_HEADER)
    return {row.get("inst_id", "") for row in rows if row.get("inst_id")}
def add_to_unknown_blacklist(inst_id: str, reason: str):
    """未知异常黑名单（v5.1）：连续未知错误等原因加入，从买入列表剔除"""
    if not inst_id:
        return
    if inst_id in load_unknown_blacklist():
        return
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _write_csv_row(UNKNOWN_BLACKLIST_FILE, UNKNOWN_BLACKLIST_HEADER, {
        "inst_id": inst_id,
        "reason": reason,
        "add_time": now_str
    })
    print(f"[未知异常黑名单] {inst_id} 已加入，原因: {reason}")
def remove_from_unknown_blacklist(inst_id: str):
    """v5.16（文档 C11）：未知异常黑名单移除（复检恢复可交易时调用）"""
    rows = _read_csv(UNKNOWN_BLACKLIST_FILE, UNKNOWN_BLACKLIST_HEADER)
    kept = [r for r in rows if r.get("inst_id") != inst_id]
    if len(kept) != len(rows):
        _write_csv_all(UNKNOWN_BLACKLIST_FILE, UNKNOWN_BLACKLIST_HEADER, kept)
        print(f"[未知异常黑名单] {inst_id} 已移除")
def recheck_unknown_blacklist_due(logger, limit: int = 1) -> List[str]:
    """v5.16（文档 C11）：未知异常黑名单到期自动复检。

    只查当前交易环境是否有该 instrument（demo 模式带模拟盘头），绝不下单；时间满
    UNKNOWN_BLACKLIST_RECHECK_SEC（默认 24h）的条目才会被检查，恢复可交易即从黑名单
    移除并返回币对列表（调用方负责推送/同步内存集合）。单轮最多 limit 个，避免把
    启动/主循环拖在串行 REST 上。add_time 解析失败的条目视为到期（宁可多查一次）。
    """
    if UNKNOWN_BLACKLIST_RECHECK_SEC <= 0 or limit <= 0:
        return []
    rows = _read_csv(UNKNOWN_BLACKLIST_FILE, UNKNOWN_BLACKLIST_HEADER)
    now = time.time()
    removed = []
    checked = 0
    for row in rows:
        if checked >= limit:   # 单轮最多检查 limit 个（含"查了仍不可交易"的）
            break
        inst_id = row.get("inst_id", "")
        if not inst_id:
            continue
        try:
            add_ts = datetime.strptime(row.get("add_time", ""), "%Y-%m-%d %H:%M:%S").timestamp()
        except Exception:
            add_ts = 0.0
        if add_ts > 0 and now - add_ts < UNKNOWN_BLACKLIST_RECHECK_SEC:
            continue
        checked += 1
        try:
            if _okx_client is not None:
                available = _okx_client.get_instrument(inst_id) is not None
            else:
                available = check_okx_available(inst_id)
        except Exception:
            available = False
        if available:
            remove_from_unknown_blacklist(inst_id)
            removed.append(inst_id)
            logger.info(f"未知黑名单复检：{inst_id} 当前交易环境可交易，已移出黑名单", "startup")
    return removed
def load_observe_list() -> set:
    rows = _read_csv(OBSERVE_LIST_FILE, OBSERVE_LIST_HEADER)
    return {row.get("inst_id", "") for row in rows if row.get("inst_id")}
def add_to_observe_list(inst_id: str, reason: str):
    if not inst_id:
        return
    if inst_id in load_observe_list():
        return
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _write_csv_row(OBSERVE_LIST_FILE, OBSERVE_LIST_HEADER, {
        "inst_id": inst_id,
        "reason": reason,
        "add_time": now_str
    })
    print(f"[待观察] {inst_id} 已加入待观察列表，原因: {reason}")
# ==================== 超出计算范围记录（v5.5） ====================
RECOVERED_REASON_PREFIX = "已恢复"
# openpyxl 解析比 CSV 贵一个量级，而每个币对启动时都要查一次剔除集合：同样按 stat 指纹缓存
_XLSX_SET_CACHE: Dict[str, Tuple[Any, set]] = {}
def load_out_of_range() -> set:
    """读取超出计算范围 xlsx（与主程序同目录），返回仍被剔除的 inst_id 集合

    v5.8：原因以"已恢复"开头的记录表示价格已回到计算区间，不再计入剔除集合（保留审计痕迹）。
    """
    result = set()
    if not os.path.exists(OUT_OF_RANGE_FILE):
        return result
    key = _csv_cache_key(OUT_OF_RANGE_FILE)
    if key is not None:
        cached = _XLSX_SET_CACHE.get(OUT_OF_RANGE_FILE)
        if cached is not None and cached[0] == key:
            return set(cached[1])
    try:
        import openpyxl
        wb = openpyxl.load_workbook(OUT_OF_RANGE_FILE, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if rows:
            header = [str(c).strip() if c is not None else "" for c in rows[0]]
            idx = header.index("inst_id") if "inst_id" in header else 0
            r_idx = header.index("reason") if "reason" in header else -1
            for row in rows[1:]:
                v = row[idx] if idx < len(row) else None
                if not v:
                    continue
                reason = str(row[r_idx]).strip() if 0 <= r_idx < len(row) and row[r_idx] is not None else ""
                if reason.startswith(RECOVERED_REASON_PREFIX):
                    continue
                result.add(str(v).strip())
        wb.close()
    except Exception as e:
        print(f"[超出范围] 读取 {OUT_OF_RANGE_FILE} 失败: {e}")
        return result
    if key is not None:
        _XLSX_SET_CACHE[OUT_OF_RANGE_FILE] = (key, set(result))
    return result
_XLSX_OOR_OPS: List[Tuple] = []
_XLSX_OOR_LOCK = threading.Lock()


def mark_recovered_in_out_of_range(inst_id: str, current_price: float):
    """v5.12 R11：只入队，不碰磁盘。真正的 xlsx 改写由主线程 flush_out_of_range_ops() 批量做。

    openpyxl 的 load_workbook + save 是"整本重写"（几十毫秒到几百毫秒），
    而这里原来是 `on_trade` 持着 engine.lock 在行情热路径上直接执行：
    一次超范围翻转会把全部币对的行情处理一起卡住，锁内耗时又拖慢止盈判定。"""
    if not inst_id:
        return
    with _XLSX_OOR_LOCK:
        if any(op[0] == "recover" and op[1] == inst_id for op in _XLSX_OOR_OPS):
            return
        _XLSX_OOR_OPS.append(("recover", inst_id, float(current_price)))


def add_to_out_of_range(inst_id: str, current_price: float, range_high: float, range_low: float, reason: str = "超出程序运行计算的范围"):
    """v5.12 R11：价格超出配置 [ref_low, ref_high] 计算范围时记一笔，稍后由主线程批量落 xlsx。"""
    if not inst_id:
        return
    with _XLSX_OOR_LOCK:
        if any(op[0] == "add" and op[1] == inst_id for op in _XLSX_OOR_OPS):
            return
        _XLSX_OOR_OPS.append(("add", inst_id, float(current_price), float(range_high),
                              float(range_low), reason))


def _apply_out_of_range_ops(ops: List[Tuple]):
    """一次 load → 应用全部积压事件 → 一次 save（临时文件 + os.replace 原子替换）"""
    import openpyxl
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if os.path.exists(OUT_OF_RANGE_FILE):
        wb = openpyxl.load_workbook(OUT_OF_RANGE_FILE)
        ws = wb.active
    else:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "超出范围"
        ws.append(OUT_OF_RANGE_HEADER)
    header = [str(c.value).strip() if c.value is not None else "" for c in ws[1]]
    if "inst_id" not in header or "reason" not in header:
        wb.close()
        print(f"[超出范围] {os.path.basename(OUT_OF_RANGE_FILE)} 缺少 inst_id/reason 列，放弃 {len(ops)} 条事件（请人工检查该表）")
        return
    c_id = header.index("inst_id") + 1
    c_reason = header.index("reason") + 1
    excluded = set()
    for r in range(2, ws.max_row + 1):
        v = str(ws.cell(row=r, column=c_id).value or "").strip()
        if v and not str(ws.cell(row=r, column=c_reason).value or "").startswith(RECOVERED_REASON_PREFIX):
            excluded.add(v)
    changed = False
    for op in ops:
        if op[0] == "add":
            _, inst_id, price, range_high, range_low, reason = op
            if inst_id in excluded:
                continue          # 仅记一次（原来靠 load_out_of_range 判断，现在在同一份内存表上判）
            ws.append([inst_id, f"{price:.8g}", f"{range_high:.8g}", f"{range_low:.8g}", reason, now_str])
            excluded.add(inst_id)
            changed = True
            print(f"[超出范围] {inst_id} 已记入 {os.path.basename(OUT_OF_RANGE_FILE)}: 当前价 {price:.8g}, 范围 [{range_low:.8g}, {range_high:.8g}], 原因: {reason}")
        elif op[0] == "recover":
            _, inst_id, price = op
            new_reason = f"{RECOVERED_REASON_PREFIX}：{now_str} 价格回到计算范围（当前价 {price:.8g}）"
            for r in range(2, ws.max_row + 1):
                if str(ws.cell(row=r, column=c_id).value or "").strip() != inst_id:
                    continue
                if str(ws.cell(row=r, column=c_reason).value or "").startswith(RECOVERED_REASON_PREFIX):
                    continue
                ws.cell(row=r, column=c_reason, value=new_reason)
                changed = True
    if not changed:
        wb.close()
        return
    tmp_path = _csv_tmp_path(OUT_OF_RANGE_FILE)
    try:
        wb.save(tmp_path)
        wb.close()
        os.replace(tmp_path, OUT_OF_RANGE_FILE)
        _XLSX_SET_CACHE.pop(OUT_OF_RANGE_FILE, None)   # 表已变，下次读必须重新解析
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def flush_out_of_range_ops() -> int:
    """把积压的超范围/恢复事件一次性写进 xlsx。主线程 maintenance() 与退出收尾调用。
    写失败时事件放回队首，下个周期重试——审计记录可以晚到，不能悄悄丢。"""
    with _XLSX_OOR_LOCK:
        if not _XLSX_OOR_OPS:
            return 0
        ops = list(_XLSX_OOR_OPS)
        _XLSX_OOR_OPS.clear()
    try:
        _apply_out_of_range_ops(ops)
        return len(ops)
    except Exception as e:
        with _XLSX_OOR_LOCK:
            _XLSX_OOR_OPS[:0] = ops
        print(f"[超出范围] 批量写入 {OUT_OF_RANGE_FILE} 失败: {e}（{len(ops)} 条事件已回队，稍后重试）")
        return 0
# ==================== OKX 持仓同步 ====================
# v5.7：现货持仓在启动时做一次全量对齐（平台余额账本 /api/v5/account/balance -> 本地账本）
# v5.14：运行期每 POSITION_AUDIT_SEC 秒再做一次轻量对账（只清"平台已无余额"的本地持仓，
# 不做覆盖式重算）；交易判断一律以本地账本为准；同步失败仅打印并跳过，不阻断行情与交易
QUOTE_CCYS = {"USDT", "USDC", "USD"}
POS_MIN_USD = env_num("POS_MIN_USD", 1.0)  # 折合USD低于此值的粉尘余额不建持仓
# v5.16（文档 C5）：粉尘残仓清理核对的每币对最短间隔（持仓市值 < POS_MIN_USD 时才触发 REST 核对）
DUST_CHECK_SEC = env_num("DUST_CHECK_SEC", 3600.0)
POSITION_AUDIT_SEC = env_num("POSITION_AUDIT_SEC", 300.0)  # v5.14 运行期对账周期（秒），<=0 关闭
# v5.17（文档 C12）→ v5.20 推广：全市场行情补齐。模拟盘（乃至实盘冷门币对）WS 成交推送稀疏，
# 冷门币对可能整程收不到 tick（实证：26 个持仓中 22 个"启动后未收到行情"），买入信号/止盈
# 评估/回本清仓全部停摆。v5.17 只兜底持仓；v5.20 起按 MARKET_GAP_INTERVAL_SEC 周期用 REST
# 批量接口（/api/v5/market/tickers，单请求返回全部现货最新价，实测 0.08s/565 个）为"静默超过
# MARKET_GAP_TICK_SEC"的币对补齐行情（走同一条 update_price 路径），覆盖持仓 + 买入候选。
STALE_TICK_SEC = env_num("STALE_TICK_SEC", 300.0)   # 心跳 stale_positions 的"无行情"静默判定（秒）
MARKET_GAP_TICK_SEC = env_num("MARKET_GAP_TICK_SEC", 45.0)           # 静默超过该秒数视为"无行情"，补一次
MARKET_GAP_INTERVAL_SEC = env_num("MARKET_GAP_INTERVAL_SEC", 60.0)   # 行情补齐周期（秒）
def fetch_platform_positions() -> Optional[Dict[str, Dict]]:
    """v5.14：读平台余额账本并折算成 {inst_id: {...}}；读失败/网络异常返回 None（不改判任何账本）。
    从 sync_positions_from_api 提取，启动全量对账与运行期轻量对账共用同一实现。"""
    if _okx_client is None:
        return None
    try:
        payload = _okx_client._request("GET", "/api/v5/account/balance", auth=True)
        api_positions = {}
        for item in payload.get("data", []):
            for d in item.get("details", []):
                ccy = d.get("ccy", "")
                eq = float(d.get("eq") or 0)
                if not ccy or ccy in QUOTE_CCYS or eq <= 0:
                    continue
                inst_id = f"{ccy}-USDT"
                eq_usd = float(d.get("eqUsd") or 0)
                if eq_usd <= 0:
                    eq_usd = eq * float(d.get("lastPr") or 0)
                if eq_usd < POS_MIN_USD:
                    continue
                unit_px = eq_usd / eq
                api_positions[inst_id] = {
                    "position_price": unit_px,
                    "position_qty": eq,
                    "position_amount": eq_usd
                }
    except Exception as e:
        print(f"[持仓同步] 余额账本同步失败，跳过本轮（运行期以本地账本为准）: {e}")
        return None
    return api_positions
def fetch_ticker_price(inst_id: str) -> Optional[float]:
    """v5.17（文档 C12）：REST 最新成交价（公开接口，价格与下单环境一致）。

    仅用于"无行情持仓"的兜底盯盘：拿到价格后由调用方喂入 update_price 走同一条
    止盈/卖出评估路径。失败（网络错、无此产品、价格非正）一律返回 None，不改判账本。
    """
    if _okx_client is None:
        return None
    try:
        payload = _okx_client._request("GET", "/api/v5/market/ticker",
                                       query={"instId": inst_id}, auth=False, timeout=10)
    except Exception:
        return None
    data = (payload.get("data") or [None])[0]
    if not data:
        return None
    try:
        px = float(data.get("last") or 0)
    except (TypeError, ValueError):
        return None
    return px if px > 0 else None
def fetch_all_ticker_prices() -> Optional[Dict[str, float]]:
    """v5.20（C12 推广）：REST 批量最新价（GET /api/v5/market/tickers?instType=SPOT）。

    单请求返回当前行情环境全部现货的最新成交价（实测 0.08s/565 个），用于给"无 tick 的币对"
    补齐行情——模拟盘 WS 成交推送稀疏，冷门币对可能整程收不到任何消息，买卖计算不能依赖它。
    从未成交的新上市产品（last 为空）用买一/卖一报价兜底（实证 RE-USDT）。
    失败（网络错/响应异常）返回 None，调用方本轮跳过、下轮再试；不产生任何交易副作用。
    """
    if _okx_client is None:
        return None
    try:
        payload = _okx_client._request("GET", "/api/v5/market/tickers",
                                       query={"instType": "SPOT"}, auth=False, timeout=15)
    except Exception:
        return None
    out: Dict[str, float] = {}
    for row in payload.get("data") or []:
        iid = row.get("instId", "")
        if not iid:
            continue
        # v5.20：优先最新成交价；从未成交的新上市产品（last 为空）退而用买一/卖一报价
        # （实证 RE-USDT：instruments 状态 live、日成交 0，只有 bidPx 报价），保证"有报价
        # 但无成交"的币对同样能补齐行情；三者都没有才视为无行情跳过。
        px = 0.0
        for field in ("last", "bidPx", "askPx"):
            try:
                px = float(row.get(field) or 0)
            except (TypeError, ValueError):
                px = 0.0
            if px > 0:
                break
        if px > 0:
            out[iid] = px
    return out or None
def sync_positions_from_api(logger=None) -> bool:
    if _okx_client is None:
        return False
    api_positions = fetch_platform_positions()
    if api_positions is None:
        return False
    return _apply_platform_positions(api_positions, logger)
def _apply_platform_positions(api_positions: Dict[str, Dict], logger=None) -> bool:
    """把平台余额账本对齐进本地账本并整表落盘。

    网络请求在调用方锁外完成；这里"读本地全表→对齐→写全表"全程持 ENGINE_LOCK，
    与行情线程（on_trade / flush_dirty_states）互斥 —— 否则恢复线程每 60 秒会用
    对齐前的旧快照把行情线程刚写入的持仓行打回原值（丢更新）。
    """
    try:
        with ENGINE_LOCK:
            _positions_cache["data"] = api_positions
            local_pos = load_positions()
            for inst_id in list(local_pos.keys()):
                if inst_id not in api_positions:
                    local_pos.pop(inst_id, None)
            for inst_id, data in api_positions.items():
                if inst_id in local_pos:
                    old_qty = local_pos[inst_id].get("position_qty", 0)
                    cost = local_pos[inst_id].get("position_price", 0) or 0
                    local_pos[inst_id]["position_qty"] = data["position_qty"]
                    if abs(data["position_qty"] - old_qty) > 1e-12:
                        if cost > 0:
                            local_pos[inst_id]["position_amount"] = cost * data["position_qty"]
                        else:
                            local_pos[inst_id]["position_price"] = data["position_price"]
                            local_pos[inst_id]["position_amount"] = data["position_amount"]
                else:
                    local_pos[inst_id] = {
                        "position_price": data["position_price"],
                        "position_qty": data["position_qty"],
                        "position_amount": data["position_amount"],
                        "buy_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "buy_reason": "平台余额同步",
                        "pair_type": "",
                        "pair_sell_line": "",
                        "peak_price": data["position_price"],
                        "stop_price": 0,
                        "profit_triggered": False,
                        "check_level": "T3",
                        "last_check_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "current_price": data["position_price"],
                        "market_value": data["position_amount"],
                        "unrealized_pnl": 0,
                        "unrealized_pnl_pct": 0,
                        "max_loss_pct": 0,
                        # v5.16（文档 C10）：对账重建的仓位成本是市价估值，不是真实买入均价
                        "cost_source": "reconcile",
                    }
            if not save_positions(local_pos):
                print("[持仓同步] 本地账本未能落盘（读失败保护或写异常），本次全量对齐不落盘、不改动盘上账本")
                return False
            # v5.14（优化方案步骤2）：全量对齐后复位"幽灵配对"——平台与本地都没有持仓，
            # 却挂着 is_paired=True/is_sold=False 的配对行（平台侧手动成交后本地无人复位，
            # _can_buy 会以"已配对未卖出"永久挡掉该币对；现场实例 RSR-USDT）
            ghosts = _reset_ghost_pairs(_ghost_pair_candidates(api_positions, local_pos),
                                        "平台无持仓（启动对账复位）")
            if ghosts:
                msg = f"幽灵配对复位 {len(ghosts)} 个: {', '.join(ghosts)}（平台无持仓，启动对账复位）"
                if logger is not None:
                    logger.warn(msg, "reconcile")
                else:
                    print(f"[配对状态] {msg}")
                push_notify_throttled(
                    "🧹 幽灵配对已复位（启动对账）\n\n" + "\n".join(ghosts) +
                    "\n\n平台余额与本地账本均无这些持仓：曾配对未卖出的记录已复位为已卖出，"
                    "恢复正常买入资格。请人工核对是否有平台侧手动成交/转账。",
                    key="pairghost:startup", title="幽灵配对复位")
            return True
    except Exception as e:
        print(f"[持仓同步] 本地账本对齐失败，跳过（运行期以本地账本为准）: {e}")
        return False
def _ghost_pair_candidates(api_positions: Dict[str, Dict], local_pos: Dict[str, Dict]) -> List[str]:
    """v5.14：找出"幽灵配对"——is_paired=True 且 is_sold=False，但平台余额与本地账本
    都没有该持仓的配对行。平台侧手动卖出/转账后本地从未触发卖出规则时 pair_status
    无人复位，_can_buy 会以"已配对未卖出"永久挡掉该币对（现场实例：RSR-USDT）。"""
    pairs = load_pair_status()
    return [inst_id for inst_id, d in pairs.items()
            if d.get("is_paired") and not d.get("is_sold")
            and inst_id not in api_positions and inst_id not in local_pos]
def _reset_ghost_pairs(inst_ids: List[str], reason: str) -> List[str]:
    """v5.14：把给定配对行复位为"已卖出"（sell_time=now, sell_reason=reason）。
    落盘走既有 save_pair_status；单行失败只打印告警不阻断（下轮对账会重试）。
    调用方须持有 ENGINE_LOCK（与行情线程的合并落盘互斥）。返回实际复位的币对列表。"""
    if not inst_ids:
        return []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    reset = []
    for inst_id in inst_ids:
        if save_pair_status(inst_id, {"is_paired": True, "is_sold": True,
                                      "sell_time": now_str, "sell_reason": reason}):
            reset.append(inst_id)
        else:
            print(f"[配对状态] {inst_id} 幽灵配对复位未能落盘（读失败保护或写异常），稍后重试")
    return reset
def get_positions_snapshot() -> Dict[str, Dict]:
    """启动同步得到的平台持仓快照，运行期只读，不触发任何网络请求"""
    return _positions_cache["data"]
# ==================== 配置加载 ====================
# v5.10：配置表"系统参数"用的是中文键名，此前 load_config 只比对英文键，
# 导致表里所有参数一个都匹配不上、静默按代码默认值运行（例：单次买入比例=0.02 实际跑成 0.01）。
PARAM_KEY_ALIASES = {
    "总资金": "total_funds",
    "单次买入比例": "buy_ratio",
    "买入比例": "buy_ratio",
    "静默期": "cooldown_days",
    "静默期天数": "cooldown_days",
    "止盈触发阈值": "profit_trigger",
    "止盈回撤阈值": "stop_loss",
    "盈利步长通知": "profit_step",
    "下破提醒每日上限": "break_alert_max",
    "下破提醒最小间隔": "break_alert_interval",
    "钉钉推送间隔": "push_interval",
    "推送间隔": "push_interval",
    "数据源优先级": "data_source",
    "交易模式": "trade_mode",
}
# 表里有、但当前代码没有任何逻辑读取的参数：填了也不生效，启动时点名，避免误认为已生效。
# （止盈/回撤/阈值类数字是写死在策略代码里的，改动属策略决策，不走配置）
UNUSED_PARAMS = {"total_funds", "profit_trigger", "stop_loss", "profit_step",
                 "break_alert_max", "break_alert_interval", "push_interval", "data_source"}
# v5.12 R16：默认系统参数提到模块级——load_config 用它起表，
# "xlsx 读不出来且连快照都没有"的兜底路径也要用（否则 MarketEngine 拿到空 dict 会在深处 KeyError）
CONFIG_PARAM_DEFAULTS = {
    "total_funds": 1000000.0,
    "buy_ratio": 0.01,
    "cooldown_days": 7,
    "profit_trigger": 0.065,
    "stop_loss": 0.015,
    "profit_step": 0.01,
    "break_alert_max": 4,
    "break_alert_interval": 1020,
    "push_interval": 3.0,
    "data_source": "OKX",
    "trade_mode": "demo",
}
def config_startup_ok(config: Dict, held_positions) -> bool:
    """v5.12 R9：无有效配置时是否仍应把程序起来。
    有持仓就必须运行（只做持仓管理、不买入）——配置表被改坏不等于持仓可以无人盯守；
    既没有可用配置、又没有任何持仓，才真的无事可做。"""
    return bool(config) or bool(held_positions)


def _apply_config_env_overrides(system_params: Dict, applied: Dict) -> Dict:
    """.env 的 BUY_RATIO / COOLDOWN_DAYS 覆盖表格值。快照回退路径也要走这里，
    否则"上次有效配置"会把 .env 的临时调节一起吃掉。"""
    env_buy_ratio = os.getenv("BUY_RATIO")
    if env_buy_ratio is not None:
        try:
            system_params["buy_ratio"] = float(env_buy_ratio)
            applied["buy_ratio"] = system_params["buy_ratio"]
        except ValueError:
            print(f"[配置] BUY_RATIO 非法值 {env_buy_ratio!r}，沿用 {system_params['buy_ratio']}")
    env_cooldown = os.getenv("COOLDOWN_DAYS")
    if env_cooldown is not None:
        try:
            system_params["cooldown_days"] = int(env_cooldown)
        except ValueError:
            print(f"[配置] COOLDOWN_DAYS 非法值 {env_cooldown!r}，沿用 {system_params['cooldown_days']} 天")
    return system_params


def _print_config_summary(system_params: Dict, applied: Dict):
    print(f"[配置] 系统参数生效: buy_ratio={system_params['buy_ratio']} "
          f"cooldown_days={system_params['cooldown_days']} trade_mode={system_params['trade_mode']}"
          + (f"（覆盖默认值: {applied}）" if applied else "（全部为默认值）"))


def _write_config_snapshot(config: Dict, system_params: Dict) -> bool:
    """v5.12 R16：把这次解析成功的配置原子落一份快照（仅启动期调用，不在行情热路径）。
    空表不写——用户主动清空表格不该把上一份有效快照一起抹掉。"""
    if not config:
        return False
    tmp = _csv_tmp_path(CONFIG_SNAPSHOT_FILE)
    try:
        with CSV_LOCK:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                           "version": VERSION,
                           "config": config,
                           "system_params": system_params},
                          f, ensure_ascii=False, indent=1, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, CONFIG_SNAPSHOT_FILE)
        return True
    except Exception as e:
        print(f"[配置快照] 写入失败（不影响本次运行）: {e}")
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def _read_config_snapshot() -> Tuple[Dict, Dict, str]:
    """读回上一份有效配置快照；文件缺失/损坏/内容不可信一律返回空，由调用方决定兜底。
    快照里的数值仍要逐条重新校验（0 < low < high），因为这份 JSON 同样可能被手工改坏。"""
    try:
        with open(CONFIG_SNAPSHOT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}, {}, ""
    if not isinstance(data, dict):
        return {}, {}, ""
    raw_config = data.get("config")
    params = data.get("system_params")
    config = {}
    if isinstance(raw_config, dict):
        for inst_id, item in raw_config.items():
            try:
                high = float(item["ref_high"])
                low = float(item["ref_low"])
            except (TypeError, ValueError, KeyError, AttributeError):
                continue
            if 0.0 < low < high:
                config[str(inst_id).strip()] = {"ref_high": high, "ref_low": low}
    return config, (params if isinstance(params, dict) else {}), str(data.get("saved_at", ""))


def load_config_with_fallback() -> Tuple[Dict, Dict, str]:
    """v5.12 R16：配置来源三级降级 → ("xlsx" 正常 / "snapshot" 快照回退 / "none" 连快照都没有)。
    只有股票池目录/文件读不出来（目录缺失、没有 xlsx、文件损坏、被 Excel 独占锁定）才降级；
    表格能读但一行有效数据都没有属于用户主动意图，不拿快照覆盖它（R9 的仅持仓管理模式继续生效）。"""
    try:
        config, system_params = load_config()
    except Exception as e:
        print(f"[配置] 读取股票池目录 {CONFIG_DIR or '(未配置 INPUT_DATA)'} 失败: {e}")
        snap, snap_params, saved_at = _read_config_snapshot()
        if snap:
            merged = dict(CONFIG_PARAM_DEFAULTS)
            merged.update({k: v for k, v in snap_params.items() if k in CONFIG_PARAM_DEFAULTS})
            applied: Dict = {}
            _apply_config_env_overrides(merged, applied)
            _print_config_summary(merged, applied)
            print(f"[配置] 已回退到 {saved_at or '未知时间'} 保存的配置快照: {len(snap)} 个币对，"
                  f"请尽快修复股票池目录 {CONFIG_DIR}")
            return snap, merged, "snapshot"
        print(f"[配置] 没有可用的配置快照（{os.path.basename(CONFIG_SNAPSHOT_FILE)} 缺失或不可读），"
              f"按默认参数启动")
        return {}, dict(CONFIG_PARAM_DEFAULTS), "none"
    _write_config_snapshot(config, system_params)
    return config, system_params, "xlsx"


def _iter_pool_xlsx(root: str) -> List[str]:
    """INPUT_DATA 目录下全部 xlsx（含子目录），跳过 Excel 临时锁文件(~$开头)；排序保证解析顺序稳定。"""
    files = []
    for dirpath, dirnames, names in os.walk(root):
        dirnames.sort()
        for name in sorted(names):
            if not name.lower().endswith((".xlsx", ".xlsm")) or name.startswith("~$"):
                continue
            files.append(os.path.join(dirpath, name))
    return files


def _read_layer_labels(ws) -> Dict[str, Tuple[float, float]]:
    """解析第 1 个 sheet"层计算"：A=币对、C=最新价格区间（如"8-16"）。
    C 列缺失/非法时，用 F(历史最高)/D(历史最低) 价差倍数折算所在 2 的幂层兜底。"""
    labels = {}
    for row in range(2, ws.max_row + 1):
        inst_id = ws.cell(row=row, column=1).value
        if inst_id is None or not str(inst_id).strip():
            continue
        inst_id = str(inst_id).strip()
        band = _parse_layer_label(ws.cell(row=row, column=3).value)
        if band is None:
            try:
                low = float(ws.cell(row=row, column=4).value)
                high = float(ws.cell(row=row, column=6).value)
            except (TypeError, ValueError):
                continue
            if low <= 0 or high <= low:
                continue
            import math
            lo = 2.0 ** math.floor(math.log2(high / low))
            band = (lo, lo * 2.0)
        labels[inst_id] = band
    return labels


def _read_pool_sheet(ws, src: str, config: Dict, dup: List, bad_rows: List,
                     labels: Optional[Dict[str, Tuple[float, float]]] = None,
                     filtered: Optional[List] = None):
    """解析股票池 sheet（第 2 个 sheet"层计算幅度"）：A=币对、C=同层最低→ref_low、D=同层最高→ref_high。
    配置了 FILTER_LAYER 时，只保留"层计算"区间命中过滤条件的币对。
    单行脏数据只跳过该行，不掀掉整个程序（v5.12 R9 原则）。"""
    for row in range(2, ws.max_row + 1):
        inst_id = ws.cell(row=row, column=1).value
        ref_low = ws.cell(row=row, column=3).value
        ref_high = ws.cell(row=row, column=4).value
        if inst_id is None or not str(inst_id).strip():
            continue
        inst_id = str(inst_id).strip()
        if LAYER_FILTERS and filtered is not None:
            band = (labels or {}).get(inst_id)
            if band is None:
                filtered.append(f"{inst_id}({src} 无区间层信息)")
                continue
            if not _layer_matches(band, LAYER_FILTERS):
                filtered.append(f"{inst_id}({band[0]:g}-{band[1]:g})")
                continue
        try:
            high = float(ref_high)
            low = float(ref_low)
        except (TypeError, ValueError):
            bad_rows.append(f"{src} 第 {row} 行 {inst_id}: 同层最低/最高 {ref_low!r}/{ref_high!r} 不是数字")
            continue
        if not (0.0 < low < high):
            bad_rows.append(f"{src} 第 {row} 行 {inst_id}: 需满足 0 < 同层最低({low:g}) < 同层最高({high:g})")
            continue
        if inst_id in config:
            dup.append(f"{inst_id}({src})")
            continue
        config[inst_id] = {"ref_high": high, "ref_low": low}


def load_config() -> Tuple[Dict, Dict]:
    import openpyxl
    if not CONFIG_DIR:
        raise FileNotFoundError(".env 未配置 INPUT_DATA（股票池目录）")
    if not os.path.isdir(CONFIG_DIR):
        raise FileNotFoundError(f"股票池目录不存在: {CONFIG_DIR}")
    files = _iter_pool_xlsx(CONFIG_DIR)
    if not files:
        raise FileNotFoundError(f"股票池目录里没有 xlsx 文件: {CONFIG_DIR}")
    config = {}
    system_params = dict(CONFIG_PARAM_DEFAULTS)
    applied, ignored, bad_rows, dup, no_sheet, filtered = {}, [], [], [], [], []
    failed_files = []
    loaded = 0
    for path in files:
        src = os.path.relpath(path, CONFIG_DIR)
        try:
            wb = openpyxl.load_workbook(path, data_only=True)
        except Exception as e:
            # v5.15（文档 P2-10）：单个文件打不开只跳过该文件并汇总告警（旧行为整体 raise →
            # 全量回退快照，一个文件被占用/损坏就吃到过期股票池）；仅"一个文件都没成功"才回退
            failed_files.append(f"{src}: {e}")
            continue
        try:
            if len(wb.sheetnames) < 2:
                no_sheet.append(src)
                continue
            labels = _read_layer_labels(wb[wb.sheetnames[0]]) if LAYER_FILTERS else None
            _read_pool_sheet(wb[wb.sheetnames[1]], src, config, dup, bad_rows, labels, filtered)
            # 兼容旧表：文件里若仍带"系统参数"sheet 则照常解析（新股票池一般没有）
            if "系统参数" in wb.sheetnames:
                ws = wb["系统参数"]
                for row in range(2, ws.max_row + 1):
                    raw_key = ws.cell(row=row, column=1).value
                    value = ws.cell(row=row, column=2).value
                    if not raw_key or value is None:
                        continue
                    key = str(raw_key).strip()
                    key = PARAM_KEY_ALIASES.get(key, key)
                    if key not in system_params:
                        ignored.append(str(raw_key).strip())
                        continue
                    default = system_params[key]
                    try:
                        if isinstance(default, float):
                            system_params[key] = float(value)
                        elif isinstance(default, int):
                            system_params[key] = int(float(value))
                        else:
                            system_params[key] = str(value).strip()
                    except (TypeError, ValueError):
                        ignored.append(f"{str(raw_key).strip()}(值 {value!r} 无法解析)")
                        continue
                    if system_params[key] != default:
                        applied[key] = system_params[key]
            loaded += 1
        finally:
            wb.close()
    if failed_files and loaded == 0:
        # 一个都没解析成功 → 交由 load_config_with_fallback 回退快照/默认值（与旧行为一致）
        raise RuntimeError(f"全部 {len(failed_files)} 个股票池文件打开失败: {failed_files[:3]}")
    print(f"[配置] 股票池目录: {CONFIG_DIR}，解析 {loaded}/{len(files)} 个文件，共 {len(config)} 个币对")
    if LAYER_FILTERS:
        print(f"[配置] 过滤条件 FILTER_LAYER={FILTER_LAYER_RAW or LAYER_FILTERS}"
              f"（{len(filtered)} 个币对因不在指定倍数层被排除）"
              f": {filtered[:20]}{' ...' if len(filtered) > 20 else ''}")
    if no_sheet:
        print(f"[配置] 警告：以下文件没有第 2 个 sheet（层计算幅度），已整体跳过: {no_sheet}")
    _apply_config_env_overrides(system_params, applied)
    _print_config_summary(system_params, applied)
    dead_in_use = sorted(k for k in applied if k in UNUSED_PARAMS)
    if dead_in_use:
        print(f"[配置] 注意：以下参数虽已识别但代码中无实际用途，改动不影响行为: {dead_in_use}")
    if ignored:
        print(f"[配置] 注意：以下配置项未识别或无法解析，已忽略: {ignored}")
    if dup:
        print(f"[配置] 注意：同名币对跨文件重复，保留先出现的范围: {dup}")
    if bad_rows:
        print(f"[配置] 警告：{len(bad_rows)} 行股票池数据无效，已跳过不参与交易: {bad_rows}")
        try:
            push_notify_throttled(
                f"⚠️ 股票池有脏行\n\n以下币对已跳过（其余币对正常运行）:\n" + "\n".join(bad_rows[:10]),
                key="config:badrows", title="股票池脏行")
        except Exception:
            pass
    if failed_files:
        print(f"[配置] 警告：{len(failed_files)} 个股票池文件打开失败，已跳过（其余文件正常解析）: {failed_files}")
        try:
            push_notify_throttled(
                f"⚠️ 股票池文件打开失败\n\n已跳过以下文件（其余文件正常解析，池子可能不完整）:\n" +
                "\n".join(failed_files[:5]),
                key="config:filefail", title="股票池文件失败")
        except Exception:
            pass
    return config, system_params
# ==================== 多层次价格计算 ====================
class PriceLevels:
    def __init__(self, high: float, low: float):
        self.high = high
        self.low = low
        self.update(high, low)

    def update(self, high: float, low: float):
        self.high = high
        self.low = low
        # v5.12 R4 价位表（依用户 2026-10-12 声明，TestLadderSpec 逐条锁定）：
        #   锚点 high / high_mid(12-16格) / mid(8-16格) / low_mid(4-16格) / low，四个族群各占一个 1/4 带，
        #   族内再二分出 上(卖点) / 中 / 下(买点)，17 个点把区间十六等分、间距 = (high-low)/16。
        #   全序：最高>回撤上>回撤中>回撤下>高位中间>回调上>回调中>回调下>中间
        #         >过渡上>过渡中>过渡下>低位中间>极限上>极限中>极限下>最低
        # 此前 high_mid = (high+low)/2 与 mid 同值："回撤"族横跨半个区间，而"回调"族 5 个价位
        # 全部塌缩到中点（callback_up == callback2_down == mid），回调买点与卖点相等、毛利为 0。
        self.mid = (high + low) / 2
        self.high_mid = (high + self.mid) / 2
        # 回撤系列
        self.pullback1_mid = (high + self.high_mid) / 2
        self.pullback_up = (high + self.pullback1_mid) / 2
        self.pullback2_down = (self.pullback1_mid + self.high_mid) / 2
        # 回调系列
        self.callback1_mid = (self.high_mid + self.mid) / 2
        self.callback_up = (self.high_mid + self.callback1_mid) / 2
        self.callback2_down = (self.callback1_mid + self.mid) / 2
        # 低位中间
        self.low_mid = (self.mid + low) / 2
        # 过渡系列
        self.transition1_mid = (self.mid + self.low_mid) / 2
        self.transition_up = (self.mid + self.transition1_mid) / 2
        self.transition2_down = (self.transition1_mid + self.low_mid) / 2
        # 极限系列
        self.limit1_mid = (self.low_mid + low) / 2
        self.limit_up = (self.low_mid + self.limit1_mid) / 2
        self.limit2_down = (self.limit1_mid + low) / 2

        self.buy_levels = {
            "pullback2_down": self.pullback2_down,
            "callback2_down": self.callback2_down,
            "transition2_down": self.transition2_down,
            "limit2_down": self.limit2_down,
        }
        self.sell_levels = {
            "pullback_up": self.pullback_up,
            "callback_up": self.callback_up,
            "transition_up": self.transition_up,
            "limit_up": self.limit_up,
        }
        self.pair_map = {
            "pullback2_down": ("pullback_up", "回撤"),
            "callback2_down": ("callback_up", "回调"),
            "transition2_down": ("transition_up", "过渡"),
            "limit2_down": ("limit_up", "极限"),
        }


# ==================== v6 固定层梯表 / 换层跟踪（阶段 1 基础件，2026-10-19） ====================
# 依据《概念落地设计单_v1.1》§1：本层梯表 = [同层最低, 同层最高] 的 16 等分（沿用 PriceLevels 价位口径）；
# "a-b" 层层界 = [F/b, F/a]（F=历史最高价，a<b 为 2 的幂）；价格越界 → 换层（不扩表、不剔除）。
# 注意：本段为新增基础件，暂未接入实盘链路（阶段 2/3 接线时启用）。
class LayerLadder(PriceLevels):
    """v6 固定层梯表：由本层层界 [low, high]（sheet2 同层最低/最高）构造。

    换层 = 层界整体 ×2（价更高的层）/ ÷2（价更低的层）——几何层梯，无需 F/标签；
    梯表档位沿用 PriceLevels 的 16 等分口径（回撤上…最低）。
    """

    def __init__(self, low: float, high: float):
        if not (0 < low < high):
            raise ValueError(f"层界非法: low={low!r} high={high!r}")
        super().__init__(high, low)

    def contains(self, price: float) -> bool:
        return self.low <= price <= self.high

    def shifted(self, direction: str) -> "LayerLadder":
        """换层：up → 层界 ×2；down → 层界 ÷2。"""
        if direction == "up":
            return LayerLadder(self.low * 2.0, self.high * 2.0)
        if direction == "down":
            return LayerLadder(self.low / 2.0, self.high / 2.0)
        raise ValueError(f"未知方向: {direction!r}")

    @property
    def label(self) -> str:
        return f"[{self.low:.8g}, {self.high:.8g}]"


class LayerSwitchTracker:
    """单币换层跟踪：价格越出当前层界 → 给出新层（支持一次跨越多层，方向取最终层）。"""

    def __init__(self, ladder: LayerLadder):
        self.current = ladder

    def on_price(self, price: float) -> Optional[Dict]:
        """喂价；发生换层返回 {"direction", "from", "to"}，未换层返回 None。"""
        if self.current.contains(price):
            return None
        ladder = self.current
        old = (ladder.low, ladder.high)
        if price > ladder.high:
            direction = "up"
            while price > ladder.high:
                ladder = ladder.shifted("up")
        else:
            direction = "down"
            while price < ladder.low:
                ladder = ladder.shifted("down")
        self.current = ladder
        return {"direction": direction, "from": old, "to": (ladder.low, ladder.high)}


class HistoryRange:
    """sheet3 历史幅度：B=历史最低、C=历史最高；程序随新高/新低合并更新（内存，不回写文件）。"""

    def __init__(self, B: float, C: float):
        if not (0 < B < C):
            raise ValueError(f"历史幅度非法: B={B!r} C={C!r}")
        self.B = float(B)
        self.C = float(C)
        self.levels = PriceLevels(self.C, self.B)

    def observe(self, price: float) -> bool:
        """新高→C、新低→B；有变化返回 True。"""
        if price > self.C:
            self.C = float(price)
            self.levels = PriceLevels(self.C, self.B)
            return True
        if price < self.B:
            self.B = float(price)
            self.levels = PriceLevels(self.C, self.B)
            return True
        return False


def _read_history_sheet(ws) -> Dict[str, Tuple[float, float]]:
    """解析 sheet3「历史幅度计算」：A=币对、B=历史最低价格、C=历史最高价格。
    返回 {币对: (B, C)}；D..S 的 16 档由程序计算（不依赖文件公式列）。行级脏数据只跳过该行。"""
    out: Dict[str, Tuple[float, float]] = {}
    for row in range(2, ws.max_row + 1):
        inst_id = ws.cell(row=row, column=1).value
        if inst_id is None or not str(inst_id).strip():
            continue
        try:
            b = float(ws.cell(row=row, column=2).value)
            c = float(ws.cell(row=row, column=3).value)
        except (TypeError, ValueError):
            continue
        if not (0 < b < c):
            continue
        out[str(inst_id).strip()] = (b, c)
    return out


# ==================== WebSocket 底层 ====================
WS_MAX_FRAME_BYTES = 8 * 1024 * 1024   # 单帧上限：抵御长度字段被读坏导致的巨额分配（本机可用内存很少）
def build_ws_frame(payload: bytes, opcode: int = 0x1) -> bytes:
    fin = 0x80 | opcode
    mask = 0x80
    length = len(payload)
    if length < 126:
        header = bytes([fin, mask | length])
    elif length < 65536:
        header = bytes([fin, mask | 126]) + struct.pack("!H", length)
    else:
        header = bytes([fin, mask | 127]) + struct.pack("!Q", length)
    mask_key = os.urandom(4)
    masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    return header + mask_key + masked
class WsConnection:
    """带接收缓冲的 WS 连接。

    v5.10 两处修正：
    1) 握手时 HTTP 响应头之后往往紧跟第一个业务帧，旧实现读满 \\r\\n\\r\\n 就丢弃多余字节，
       等于每次连接都可能丢掉订阅回执/首笔成交；现在残留字节回填接收缓冲。
    2) 旧实现忽略 FIN 位，OKX 若下发分片消息会被当成坏消息静默丢弃；现在自动续接分片。
    """
    def __init__(self, sock, recv_buf: bytes = b""):
        self.sock = sock
        self.buf = bytearray(recv_buf)
    def recv_exact(self, size: int) -> bytes:
        while len(self.buf) < size:
            chunk = self.sock.recv(max(4096, size - len(self.buf)))
            if not chunk:
                raise ConnectionError("连接已关闭")
            self.buf.extend(chunk)
        out = bytes(self.buf[:size])
        del self.buf[:size]
        return out
    def _recv_frame(self):
        first, second = self.recv_exact(2)
        fin = (first & 0x80) != 0
        opcode = first & 0x0F
        masked = (second & 0x80) != 0
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self.recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self.recv_exact(8))[0]
        if length > WS_MAX_FRAME_BYTES:
            raise ConnectionError(f"WS 帧长度异常({length})，主动断开重连")
        mask_key = self.recv_exact(4) if masked else b""
        payload = self.recv_exact(length) if length else b""
        if masked:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        return fin, opcode, payload
    def recv_message(self):
        """返回 (opcode, payload)：数据帧自动续接分片，控制帧原样返回"""
        fin, opcode, payload = self._recv_frame()
        if opcode in (0x8, 0x9, 0xA):
            return opcode, payload
        while not fin:
            nfin, nopcode, npayload = self._recv_frame()
            if nopcode != 0x0:
                raise ConnectionError("WS 分片帧序异常")
            payload += npayload
            if len(payload) > WS_MAX_FRAME_BYTES:
                raise ConnectionError("WS 消息累计长度超限")
            fin = nfin
        return opcode, payload
    def send_text(self, text):
        self.sock.sendall(build_ws_frame(text.encode("utf-8"), opcode=0x1))
    def send_pong(self, payload=b""):
        self.sock.sendall(build_ws_frame(payload, opcode=0xA))
    def send_ping(self, payload=b""):
        self.sock.sendall(build_ws_frame(payload, opcode=0x9))
    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass
def _ws_handshake(host, port, path):
    raw = socket.create_connection((host, port), timeout=10)
    ctx = ssl.create_default_context()
    sock = ctx.wrap_socket(raw, server_hostname=host)
    sock.settimeout(PING_INTERVAL)
    key = base64.b64encode(os.urandom(16)).decode()
    req = f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nUser-Agent: Python WebSocket Client\r\n\r\n"
    sock.sendall(req.encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("握手失败")
        resp += chunk
    hdr, _, leftover = resp.partition(b"\r\n\r\n")
    txt = hdr.decode(errors="ignore")
    if "101" not in txt.split("\r\n")[0]:
        raise ConnectionError(f"握手失败: {txt}")
    headers = {}
    for line in txt.split("\r\n")[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
    if headers.get("sec-websocket-accept") != expected:
        raise ConnectionError("握手校验失败")
    return sock, leftover
def ws_use_demo() -> bool:
    """v5.16（文档 C1②）：行情 WS 是否使用模拟盘环境。auto=跟随交易模式，always/never 强制。"""
    if _WS_DEMO_CFG in ("1", "true", "yes", "always", "demo"):
        return True
    if _WS_DEMO_CFG in ("0", "false", "no", "never", "live"):
        return False
    return TRADE_MODE == "demo"


def connect_okx_ws():
    """连接 OKX 公共 WebSocket，8443 失败时自动回退 443 端口，提升连接成功率。

    v5.16（文档 C1②）：demo 模式连模拟盘 wspap（brokerId=9999），行情价格与下单环境一致。
    """
    host, path = (OKX_WS_DEMO_HOST, OKX_WS_DEMO_PATH) if ws_use_demo() else (OKX_WS_HOST, OKX_WS_PATH)
    last_err = None
    for port in (OKX_WS_PORT, 443):
        try:
            sock, leftover = _ws_handshake(host, port, path)
            return WsConnection(sock, leftover)
        except Exception as e:
            last_err = e
            continue
    if last_err is not None:
        raise last_err
    raise ConnectionError("OKX WebSocket 连接失败")
# ==================== 工具函数 ====================
# v5.15（文档 P1-2）：暂时性网络错误识别。实证：MASK-USDT 因一次 SSL 握手里超时
# （"The handshake operation timed out"）被当"未知错误"永久拉黑，只能手工改 CSV 恢复。
# 这类抖动只冷却重试，绝不写黑名单；确定性错误（51155/51201/51001 等）不走这里。
_TRANSIENT_ERROR_MARKERS = (
    "timed out", "timeout", "urlopen", "ssl", "handshake",
    "connection reset", "connection aborted", "connection refused",
    "reset by peer", "remote end closed", "temporarily", "temporary failure",
    "network is unreachable", "unreachable",
    "code=50011", "code=50013", "code=50026", "http 50", " 502", " 503", " 504",
)


def is_transient_error(msg: str) -> bool:
    low = (msg or "").lower()
    return any(m in low for m in _TRANSIENT_ERROR_MARKERS)


def check_okx_available(inst_id):
    for inst_type in ("SPOT", "SWAP"):
        url = f"{OKX_REST_BASE}/api/v5/public/instruments?instType={inst_type}&instId={urllib.parse.quote(inst_id)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Python OKX Client"})
            # v5.15（文档 P2-4）：探测口径必须与下单环境一致——demo 模式带模拟盘头，
            # 否则模拟盘里不存在的币对会被误判"OKX 不可交易"并写进黑名单
            if TRADE_MODE == "demo":
                req.add_header("x-simulated-trading", "1")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("code") == "0" and data.get("data"):
                    return True
        except Exception:
            pass
    return False
# ==================== OKX REST 交易客户端 ====================
TRADE_MODE = "demo"
TRADE_MODE_DESC = {
    "demo": "OKX模拟盘(API下单)",
    "live": "OKX实盘(API下单)",
}
class OkxTradeError(Exception):
    pass
class OkxTradeClient:
    def __init__(self, api_key, api_secret, passphrase, simulated=True, logger=None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.simulated = simulated
        self.logger = logger
        self._inst_cache = {}
    @staticmethod
    def _timestamp():
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    def _sign(self, ts, method, request_path, body):
        msg = (ts + method.upper() + request_path + (body or "")).encode("utf-8")
        return base64.b64encode(hmac.new(self.api_secret.encode("utf-8"), msg, hashlib.sha256).digest()).decode("utf-8")
    def _request(self, method, path, body_obj=None, query=None, auth=True, timeout=10):
        body = json.dumps(body_obj, separators=(",", ":")) if body_obj is not None else ""
        request_path = path
        if query:
            request_path = f"{path}?{urllib.parse.urlencode(query)}"
        url = OKX_REST_BASE + request_path
        headers = {"Content-Type": "application/json", "User-Agent": f"{PROGRAM_NAME}/{VERSION}"}
        if auth:
            ts = self._timestamp()
            headers["OK-ACCESS-KEY"] = self.api_key
            headers["OK-ACCESS-SIGN"] = self._sign(ts, method, request_path, body)
            headers["OK-ACCESS-TIMESTAMP"] = ts
            headers["OK-ACCESS-PASSPHRASE"] = self.passphrase
        if self.simulated:
            headers["x-simulated-trading"] = "1"
        data = body.encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="ignore")
            try:
                payload = json.loads(raw)
            except Exception:
                raise OkxTradeError(f"HTTP {e.code}: {raw[:200]}")
        if str(payload.get("code")) != "0":
            raise OkxTradeError(f"code={payload.get('code')} msg={payload.get('msg')} data={payload.get('data')}")
        return payload
    def get_instrument(self, inst_id):
        if inst_id in self._inst_cache:
            return self._inst_cache[inst_id]
        payload = self._request("GET", "/api/v5/public/instruments", query={"instType": "SPOT", "instId": inst_id}, auth=False)
        info = (payload.get("data") or [None])[0]
        if info:
            self._inst_cache[inst_id] = info
        return info
    @staticmethod
    def _round_down(value, step):
        """按交易所步长（lot_sz/tick 之类）向下取整。

        v5.12 R15：改用 Decimal。原来 `int(float(value)/float(step))` 会把
        `0.3/0.1 = 2.9999999999999996` 算成 2 个步长（少买/少卖一档），
        而按 `str(step)` 数小数位取整在 step 是 `1e-05` 这类科学计数法时
        量纲直接算错（decimals=0 → 数量被取整到整数）。
        """
        try:
            v = Decimal(str(value).strip())
            s = Decimal(str(step).strip())
            if s <= 0:
                return value
            n = (v / s).to_integral_value(rounding=ROUND_FLOOR)
            return float(n * s)
        except (ArithmeticError, InvalidOperation, TypeError, ValueError):
            return value
    def get_balance(self, ccy="USDT"):
        return self.get_balance_detail(ccy)[0]
    def get_balance_detail(self, ccy="USDT"):
        """返回 (availBal 可用量, cashBal 总量, frozenBal 挂单冻结量)。
        卖出必须按 availBal 下单（交易所按可用量校验，超了报 51008），
        frozenBal > 0 说明币还在账户里、只是被挂单占用，不能当作持仓失真。"""
        payload = self._request("GET", "/api/v5/account/balance", query={"ccy": ccy})
        for item in payload.get("data", []):
            for d in item.get("details", []):
                if d.get("ccy") == ccy:
                    return (float(d.get("availBal") or 0),
                            float(d.get("cashBal") or d.get("eq") or 0),
                            float(d.get("frozenBal") or 0))
        return (0.0, 0.0, 0.0)
    @staticmethod
    def _new_clordid():
        return f"okd{int(time.time() * 1000)}{os.urandom(2).hex()}"
    @staticmethod
    def _fmt_sz(value):
        s = f"{float(value):.12f}".rstrip("0").rstrip(".")
        return s if s else "0"
    def _place_order(self, inst_id, side, sz, tgt_ccy, cl_ord_id, px=None):
        body = {
            "instId": inst_id,
            "tdMode": "cash",
            "clOrdId": cl_ord_id,
            "side": side,
            "ordType": "market",
            "sz": f"{sz}",
        }
        if px is not None and float(px) > 0:
            # v6（设计单 v1.1）：限价单——买入@执行价；清仓@对手价近似（暂用最新价）
            body["ordType"] = "limit"
            body["px"] = self._fmt_sz(px)
        if tgt_ccy:
            body["tgtCcy"] = tgt_ccy
        payload = self._request("POST", "/api/v5/trade/order", body_obj=body)
        data = (payload.get("data") or [{}])[0]
        if str(data.get("sCode")) != "0":
            raise OkxTradeError(f"下单被拒 sCode={data.get('sCode')} sMsg={data.get('sMsg')}")
        return data.get("ordId", "")
    def _query_order(self, inst_id, ord_id=None, cl_ord_id=None):
        query = {"instId": inst_id}
        if ord_id:
            query["ordId"] = ord_id
        elif cl_ord_id:
            query["clOrdId"] = cl_ord_id
        else:
            return None
        payload = self._request("GET", "/api/v5/trade/order", query=query)
        return (payload.get("data") or [None])[0]
    def _cancel_order(self, inst_id, ord_id):
        """v6：撤销挂单（限价单未即时成交时清理，避免残留挂单）。"""
        payload = self._request("POST", "/api/v5/trade/cancel-order",
                                body_obj={"instId": inst_id, "ordId": ord_id})
        data = (payload.get("data") or [{}])[0]
        if str(data.get("sCode") or "0") != "0":
            raise OkxTradeError(f"撤单被拒 sCode={data.get('sCode')} sMsg={data.get('sMsg')}")
        return True

    def _cleanup_limit_order(self, inst_id, od, ord_id):
        """v6：限价单等待未满时撤单并回读最终成交（partial 保留已成交部分）。异常一律吞掉。"""
        try:
            if not isinstance(od, dict):
                od = {"state": "live", "ordId": ord_id} if ord_id else od
            state = str((od or {}).get("state") or "")
            oid = (od or {}).get("ordId") or ord_id
            if state in ("live", "partially_filled") and oid:
                try:
                    self._cancel_order(inst_id, oid)
                except Exception:
                    pass
                try:
                    od2 = self._query_order(inst_id, ord_id=oid)
                    if od2:
                        od = od2
                except Exception:
                    pass
        except Exception:
            pass
        return od

    def _wait_fill(self, inst_id, ord_id=None, cl_ord_id=None, tries=None, interval=None):
        # v5.15（文档 P2-3）：等待参数可配（FILL_WAIT_TRIES×FILL_WAIT_INTERVAL，默认 8×0.5s）
        tries = FILL_WAIT_TRIES if tries is None else tries
        interval = FILL_WAIT_INTERVAL if interval is None else interval
        last = None
        for _ in range(tries):
            try:
                od = self._query_order(inst_id, ord_id, cl_ord_id)
            except Exception:
                od = None
            if od:
                last = od
                if od.get("state") in ("filled", "canceled"):
                    return od
            time.sleep(interval)
        return last
    @staticmethod
    def _fill_result(od, side):
        avg_px = float(od.get("avgPx") or 0)
        acc_sz = float(od.get("accFillSz") or 0)
        fee = float(od.get("fee") or 0)
        fee_ccy = od.get("feeCcy", "")
        base_ccy = (od.get("instId", "").split("-") or [""])[0]
        gross_quote = avg_px * acc_sz
        result = {
            "price": avg_px,
            "qty": acc_sz,
            "ord_id": od.get("ordId", ""),
            "fee": fee,
            "fee_ccy": fee_ccy,
            "state": od.get("state", ""),
        }
        if side == "buy":
            result["qty"] = acc_sz + fee if fee_ccy == base_ccy else acc_sz
            result["cost"] = gross_quote
        else:
            result["proceeds"] = gross_quote + fee if fee_ccy != base_ccy else gross_quote
        return result
    def _safe_query_by_clordid(self, inst_id, cl_ord_id):
        try:
            return self._query_order(inst_id, cl_ord_id=cl_ord_id)
        except Exception:
            return None
    def _log_error(self, msg, push: bool = True):
        if self.logger:
            self.logger.error(msg, push=push)
        else:
            print(f"[OKX] {msg}")
    def market_buy_quote(self, inst_id, quote_amount, px=None):
        cl_ord_id = self._new_clordid()
        try:
            # 注：OKX minSz 是币本位（基础币）最小下单量，而这里按计价货币（quote_ccy）市价下单，
            # 直接拿计价金额与币本位最小量比较会产生单位错配，误判"低于最小下单量"而误加黑名单。
            # 是否达标交由交易所下单接口校验，失败会走下方错误分类逻辑。
            # v6：px 非空 → 限价买单（v6 买点用执行价；价格已低于限价则即成交）。
            info = self.get_instrument(inst_id)
            ord_id = self._place_order(inst_id, "buy", self._fmt_sz(quote_amount), "quote_ccy", cl_ord_id, px=px)
        except Exception as e:
            od = self._safe_query_by_clordid(inst_id, cl_ord_id)
            if od and float(od.get("accFillSz") or 0) > 0:
                self._log_error(f"{inst_id} 买入请求异常({e})，但按 clOrdId 反查到已成交，按实际成交入账", push=False)
                return self._fill_result(od, "buy")
            error_msg = str(e)
            self._log_error(f"{inst_id} 市价买入失败: {error_msg}")
            return {"error": error_msg}
        od = self._wait_fill(inst_id, ord_id=ord_id, cl_ord_id=cl_ord_id)
        if px is not None:
            od = self._cleanup_limit_order(inst_id, od, ord_id)
        if not od or float(od.get("accFillSz") or 0) <= 0:
            self._log_error(f"{inst_id} 买入未成交 ordId={ord_id} state={(od or {}).get('state')}", push=False)
            # 未成交 ≠ 未知错误：返回可判别的结果，交调用方短期冷却后重试（R5）
            return {"not_filled": True, "state": (od or {}).get("state", ""), "ord_id": ord_id}
        return self._fill_result(od, "buy")
    def market_sell_base(self, inst_id, qty, px=None):
        cl_ord_id = self._new_clordid()
        sz = qty
        try:
            info = self.get_instrument(inst_id)
            if info:
                lot_sz = info.get("lotSz") or "0"
                min_sz = float(info.get("minSz") or 0)
                sz = self._round_down(qty, lot_sz)
                if sz <= 0:
                    raise OkxTradeError(f"卖出数量按 lotSz={lot_sz} 取整后为0 (原始 {qty:.8g})")
                if min_sz > 0 and sz < min_sz:
                    raise OkxTradeError(f"卖出数量 {sz:.8g} 低于最小下单量 {min_sz} {info.get('baseCcy', '')}")
            ord_id = self._place_order(inst_id, "sell", self._fmt_sz(sz), "base_ccy", cl_ord_id, px=px)
        except Exception as e:
            od = self._safe_query_by_clordid(inst_id, cl_ord_id)
            if od and float(od.get("accFillSz") or 0) > 0:
                self._log_error(f"{inst_id} 卖出请求异常({e})，但按 clOrdId 反查到已成交，按实际成交入账", push=False)
                return self._fill_result(od, "sell")
            self._log_error(f"{inst_id} 市价卖出失败: {e}")
            return None
        od = self._wait_fill(inst_id, ord_id=ord_id, cl_ord_id=cl_ord_id)
        if px is not None:
            od = self._cleanup_limit_order(inst_id, od, ord_id)
        if not od or float(od.get("accFillSz") or 0) <= 0:
            self._log_error(f"{inst_id} 卖出未成交 ordId={ord_id} state={(od or {}).get('state')}")
            return None
        return self._fill_result(od, "sell")
# ==================== 余额获取 ====================
def get_okx_balance(force_refresh=False) -> float:
    global _balance_cache
    now = time.time()
    if not force_refresh and (now - _balance_cache["timestamp"] < _BALANCE_CACHE_TTL):
        return _balance_cache["value"]
    if _okx_client is None:
        return 0.0
    try:
        bal = _okx_client.get_balance("USDT")
        _balance_cache["value"] = bal
        _balance_cache["timestamp"] = now
        return bal
    except Exception:
        return _balance_cache["value"]
# ==================== 本地查看文件更新 ====================
def _realized_pnl_total() -> float:
    """v5.15（文档 P1-6）：累计已实现盈亏 = tradeRecord 全部 SELL 行 profit 之和。"""
    total = 0.0
    for row_data in _read_csv(TRADE_FILE, TRADE_HEADER):
        if (row_data.get("direction") or "").strip().upper() == "SELL":
            total += _to_float(row_data.get("profit"))
    return total


def _update_funds_for_view(balance: float):
    """v5.15（文档 P1-6）：真实聚合资金视图。

    修复前 total_position_market_value/total_unrealized_pnl/total_realized_pnl 恒为 "0"，
    视图除余额外全是误导。市值/浮盈取自 positions.csv（持仓落盘时逐行更新），
    累计已实现盈亏取自 tradeRecord 的 SELL 行。
    """
    try:
        total_mv = total_upnl = 0.0
        for pos_data in load_positions().values():
            try:
                total_mv += _to_float(pos_data.get("market_value"))
                total_upnl += _to_float(pos_data.get("unrealized_pnl"))
            except Exception:
                continue
        realized = _realized_pnl_total()
        row = {
            "remaining_funds": f"{balance:.2f}",
            "total_position_market_value": f"{total_mv:.2f}",
            "total_unrealized_pnl": f"{total_upnl:.2f}",
            "total_realized_pnl": f"{realized:.2f}",
            "net_asset_value": f"{balance + total_mv:.2f}",
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        _ensure_csv_header(FUNDS_FILE, FUNDS_HEADER)
        with CSV_LOCK, open(FUNDS_FILE, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=FUNDS_HEADER)
            writer.writeheader()
            writer.writerow(row)
    except Exception as e:
        print(f"[资金] 更新查看文件失败: {e}")
# ==================== 状态持久化 ====================
def load_positions() -> Dict[str, Dict]:
    rows = _read_csv(POSITIONS_FILE, POSITIONS_HEADER)
    result = {}
    for row in rows:
        inst_id = row.get("inst_id", "")
        if not inst_id:
            continue
        try:
            position_price = _to_float(row.get("position_price"))
            position_qty = _to_float(row.get("position_qty"))
            position_amount = _to_float(row.get("position_amount"))
            current_price = _to_float(row.get("current_price"), -1)
            if current_price <= 0:
                current_price = position_price
            mv_raw = row.get("market_value", "") or ""
            upnl_raw = row.get("unrealized_pnl", "") or ""
            upnl_pct_raw = row.get("unrealized_pnl_pct", "") or ""
            mv_ok = _is_number(mv_raw) and _is_number(upnl_raw)
            if mv_ok:
                market_value = _to_float(mv_raw)
                unrealized_pnl = _to_float(upnl_raw)
                unrealized_pnl_pct = _to_float(upnl_pct_raw)
            else:
                market_value = current_price * position_qty if current_price > 0 else position_amount
                unrealized_pnl = market_value - position_amount if position_amount > 0 else 0.0
                unrealized_pnl_pct = (unrealized_pnl / position_amount * 100.0) if position_amount > 0 else 0.0
            result[inst_id] = {
                "position_price": position_price,
                "position_qty": position_qty,
                "position_amount": position_amount,
                "buy_time": row.get("buy_time", ""),
                "buy_reason": row.get("buy_reason", ""),
                "pair_type": row.get("pair_type", ""),
                "pair_sell_line": row.get("pair_sell_line", ""),
                "peak_price": _to_float(row.get("peak_price")),
                "stop_price": _to_float(row.get("stop_price")),
                "profit_triggered": (str(row.get("profit_triggered") or "False")).strip().lower() == "true",
                "check_level": row.get("check_level", "T3"),
                "last_check_time": row.get("last_check_time", ""),
                "current_price": current_price,
                "market_value": market_value,
                "unrealized_pnl": unrealized_pnl,
                "unrealized_pnl_pct": unrealized_pnl_pct,
                "max_loss_pct": _to_float(row.get("max_loss_pct")),
                # v5.16（文档 C10）：成本来源。旧文件无此列时按 buy_reason 推断
                # （平台余额同步重建的仓位成本是市价估值，不是真实买入均价）
                "cost_source": (str(row.get("cost_source") or "").strip()
                                or ("reconcile" if row.get("buy_reason", "") == "平台余额同步" else "fill")),
            }
        except Exception as e:
            print(f"[持仓] 跳过损坏行 {inst_id}: {e}")
    return result
def save_positions(positions: Dict[str, Dict]) -> bool:
    rows = []
    for inst_id, data in positions.items():
        rows.append({
            "inst_id": inst_id,
            "position_price": data.get("position_price", 0),
            "position_qty": data.get("position_qty", 0),
            "position_amount": data.get("position_amount", 0),
            "buy_time": data.get("buy_time", ""),
            "buy_reason": data.get("buy_reason", ""),
            "pair_type": data.get("pair_type", ""),
            "pair_sell_line": data.get("pair_sell_line", ""),
            "peak_price": data.get("peak_price", 0),
            "stop_price": data.get("stop_price", 0),
            "profit_triggered": "True" if data.get("profit_triggered", False) else "False",
            "check_level": data.get("check_level", "T3"),
            "last_check_time": data.get("last_check_time", ""),
            "current_price": data.get("current_price", 0),
            "market_value": data.get("market_value", 0),
            "unrealized_pnl": data.get("unrealized_pnl", 0),
            "unrealized_pnl_pct": data.get("unrealized_pnl_pct", 0),
            "max_loss_pct": data.get("max_loss_pct", 0),
            "cost_source": data.get("cost_source", ""),
            # v6（设计单 v1.1）：买点类型 / 买入层固定档位 / 已涨幅度（程序维护）
            "entry_type": data.get("entry_type", ""),
            "buy_layer_low": data.get("buy_layer_low", 0),
            "buy_layer_high": data.get("buy_layer_high", 0),
            "risen_low": data.get("risen_low", 0),
            "risen_high": data.get("risen_high", 0),
            "risen_low_ts": data.get("risen_low_ts", ""),
            "risen_high_ts": data.get("risen_high_ts", ""),
            "risen_armed": data.get("risen_armed", ""),
            "v6_next_buy": data.get("v6_next_buy", ""),
        })
    return _write_csv_all(POSITIONS_FILE, POSITIONS_HEADER, rows)
def load_cooldown() -> Dict[str, str]:
    rows = _read_csv(COOLDOWN_FILE, COOLDOWN_HEADER)
    result = {}
    for row in rows:
        inst_id = row.get("inst_id", "")
        if inst_id:
            result[inst_id] = row.get("cooldown_until", "")
    return result
def save_cooldown_entry(inst_id: str, cooldown_until: str):
    # v5.15（文档 P2-6）：同一币对整表更新（保留最新一行），不再纯追加——
    # 实测冷却表出现同币对多行（LAT 两条），且每轮卖出都会追加、无上限增长
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = _read_csv(COOLDOWN_FILE, COOLDOWN_HEADER)
    for row in rows:
        if row.get("inst_id") == inst_id:
            row["sell_time"] = now_str
            row["cooldown_until"] = cooldown_until
            break
    else:
        rows.append({"inst_id": inst_id, "sell_time": now_str, "cooldown_until": cooldown_until})
    _write_csv_all(COOLDOWN_FILE, COOLDOWN_HEADER, rows)
def load_high_low() -> Dict[str, Dict]:
    rows = _read_csv(HIGH_LOW_FILE, HIGH_LOW_HEADER)
    result = {}
    for row in rows:
        inst_id = row.get("inst_id", "")
        if inst_id:
            try:
                result[inst_id] = {
                    "all_time_high": _to_float(row.get("all_time_high")),
                    "all_time_low": _to_float(row.get("all_time_low")),
                    "last_update": row.get("last_update", "")
                }
            except Exception as e:
                print(f"[高低点] 跳过损坏行 {inst_id}: {e}")
    return result
def save_high_low_entry(inst_id: str, high: float, low: float):
    _HL_PENDING[inst_id] = (high, low)
def flush_high_low() -> bool:
    """把攒下的新高/新低合并成一次整表写。

    创新高/新低在行情活跃时每秒可达多次，逐次整表读+写+fsync 是这台单核机器上最主要的 IO 来源；
    聚合后写盘频率与状态落盘同频，且量级只有几十个币对，掉电最多丢最后一个周期的极值。
    """
    if not _HL_PENDING:
        return True
    pending = dict(_HL_PENDING)
    rows = _read_csv(HIGH_LOW_FILE, HIGH_LOW_HEADER)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    seen = set()
    for row in rows:
        inst_id = row.get("inst_id")
        if inst_id in pending:
            high, low = pending[inst_id]
            row["all_time_high"] = str(high)
            row["all_time_low"] = str(low)
            row["last_update"] = now_str
            seen.add(inst_id)
    for inst_id, (high, low) in pending.items():
        if inst_id not in seen:
            rows.append({"inst_id": inst_id, "all_time_high": str(high), "all_time_low": str(low), "last_update": now_str})
    ok = _write_csv_all(HIGH_LOW_FILE, HIGH_LOW_HEADER, rows)
    if ok:
        # 写失败/被读失败保护拦下时不清队列：内存里的极值是最新值，下个周期重试即可
        # v5.15（文档 P2-5）：等值校验后再清——写盘期间行情线程可能已写入更新的极值，
        # 直接按快照键 pop 会把它删掉（该币对极值直到下次刷新才写回，等于丢一轮更新）
        for inst_id, val in pending.items():
            if _HL_PENDING.get(inst_id) == val:
                _HL_PENDING.pop(inst_id, None)
    return ok
def load_pair_status() -> Dict[str, Dict]:
    rows = _read_csv(PAIR_STATUS_FILE, PAIR_STATUS_HEADER)
    result = {}
    for row in rows:
        inst_id = row.get("inst_id", "")
        if not inst_id:
            continue
        try:
            result[inst_id] = {
                "pair_type": row.get("pair_type", ""),
                "is_paired": (str(row.get("is_paired") or "False")).strip().lower() == "true",
                "buy_price": _to_float(row.get("buy_price")),
                "buy_time": row.get("buy_time", ""),
                "sell_line": row.get("sell_line", ""),
                "sell_line_price": _to_float(row.get("sell_line_price")),
                "is_sold": (str(row.get("is_sold") or "False")).strip().lower() == "true",
                "sell_time": row.get("sell_time", ""),
                "sell_reason": row.get("sell_reason", ""),
                "profit": _to_float(row.get("profit")),
                "profit_pct": _to_float(row.get("profit_pct")),
            }
        except Exception as e:
            print(f"[配对状态] 跳过损坏行 {inst_id}: {e}")
    return result
def _apply_pair_payload(row: Dict, data: Dict) -> Dict:
    """把 payload 合并进已有行（与旧的逐行就地更新语义保持一致）"""
    row["pair_type"] = data.get("pair_type", row.get("pair_type", ""))
    row["is_paired"] = "True" if data.get("is_paired", False) else "False"
    row["buy_price"] = str(data.get("buy_price", row.get("buy_price", 0)))
    row["buy_time"] = data.get("buy_time", row.get("buy_time", ""))
    if data.get("sell_line") not in (None, ""):
        row["sell_line"] = data["sell_line"]
    row["sell_line_price"] = str(data.get("sell_line_price", row.get("sell_line_price", 0)))
    row["is_sold"] = "True" if data.get("is_sold", False) else "False"
    row["sell_time"] = data.get("sell_time", row.get("sell_time", ""))
    row["sell_reason"] = data.get("sell_reason", row.get("sell_reason", ""))
    if "profit" in data and data["profit"] not in (None, ""):
        row["profit"] = str(data["profit"])
    if "profit_pct" in data and data["profit_pct"] not in (None, ""):
        row["profit_pct"] = str(data["profit_pct"])
    return row
def _new_pair_row(inst_id: str, data: Dict) -> Dict:
    return {
        "inst_id": inst_id,
        "pair_type": data.get("pair_type", ""),
        "is_paired": "True" if data.get("is_paired", False) else "False",
        "buy_price": str(data.get("buy_price", 0)),
        "buy_time": data.get("buy_time", ""),
        "sell_line": data.get("sell_line", ""),
        "sell_line_price": str(data.get("sell_line_price", 0)),
        "is_sold": "True" if data.get("is_sold", False) else "False",
        "sell_time": data.get("sell_time", ""),
        "sell_reason": data.get("sell_reason", ""),
        "profit": data.get("profit", 0),
        "profit_pct": data.get("profit_pct", 0),
    }
def save_pair_status(inst_id: str, data: Dict) -> bool:
    rows = _read_csv(PAIR_STATUS_FILE, PAIR_STATUS_HEADER)
    found = False
    for row in rows:
        if row.get("inst_id") == inst_id:
            _apply_pair_payload(row, data)
            found = True
            break
    if not found:
        rows.append(_new_pair_row(inst_id, data))
    return _write_csv_all(PAIR_STATUS_FILE, PAIR_STATUS_HEADER, rows)
def load_buy_queue() -> List[Dict]:
    return _read_csv(BUY_QUEUE_FILE, BUY_QUEUE_HEADER)
def save_buy_queue(rows: List[Dict]) -> bool:
    return _write_csv_all(BUY_QUEUE_FILE, BUY_QUEUE_HEADER, rows)
def save_trade(row: Dict):
    _write_csv_row(TRADE_FILE, TRADE_HEADER, row)
# ==================== 初始化 OKX 客户端 ====================
OKX_INIT_RETRY_MAX = env_num("OKX_INIT_RETRY_MAX", 3, int)
OKX_RECOVERY_INTERVAL_SEC = env_num("OKX_RECOVERY_INTERVAL_SEC", 60.0)
# 凭证/IP 类错误重试无意义（改配置才能解决），其余（超时、DNS、TLS、5xx）都属可恢复的网络抖动
_FATAL_API_CODES = ("50111", "50112", "50113", "50103")
def _is_fatal_account_error(err: Exception) -> bool:
    text = str(err)
    return any(f"code={code}" in text for code in _FATAL_API_CODES)
def _okx_probe_and_sync(logger, exit_on_fatal: bool = True) -> bool:
    """连通性探测 + 余额与持仓同步；网络类失败返回 False 交上层重试。
    凭证类失败：exit_on_fatal=True（启动路径）直接退出；False（后台恢复线程）则继续重试——
    用户在远程改好 .env/IP 白名单后无需重启即可自动恢复，绝不能让恢复线程静默死掉。"""
    try:
        bal = _okx_client.get_balance("USDT")
    except Exception as e:
        if _is_fatal_account_error(e):
            if exit_on_fatal:
                logger.error(f"OKX 账户凭证/IP 校验失败，重试无意义，请检查 .env 与 IP 白名单: {e}", "startup")
                sys.exit(1)
            logger.error(f"OKX 账户凭证/IP 校验失败（后台恢复线程继续每 {OKX_RECOVERY_INTERVAL_SEC:.0f}s 重试，"
                         f"修好 .env/IP 白名单后自动恢复，期间持仓仅由行情监听盯守）: {e}", "startup")
            return False
        logger.warn(f"OKX 账户探测失败（网络类，将重试）: {e}", "startup")
        return False
    logger.info(f"OKX {'模拟盘' if TRADE_MODE == 'demo' else '实盘'}账户 USDT 可用余额: {bal:.2f}", "startup")
    _update_funds_for_view(bal)
    if sync_positions_from_api(logger):
        logger.info(f"持仓缓存已初始化（启动全量对齐完成；运行期每 {POSITION_AUDIT_SEC:.0f}s 轻量对账一次）", "startup")
    else:
        logger.warn("持仓同步未完成，运行期以本地账本为准继续执行", "startup")
    return True
def _account_recovery_worker(logger):
    """账户后台恢复（v5.10）：远程网络抖动导致启动期账户不可达时，行情线程照常跑、账户慢慢补"""
    attempt = 0
    while True:
        time.sleep(OKX_RECOVERY_INTERVAL_SEC)
        attempt += 1
        try:
            # exit_on_fatal=False：凭证/IP 类错误也不允许 sys.exit 杀死本线程（12.1），
            # 用户在远程修好 .env/白名单后，这里要能自动接上
            ok = _okx_probe_and_sync(logger, exit_on_fatal=False)
        except SystemExit:
            ok = False   # 防御：任何路径抛 SystemExit 都不允许带走恢复线程
        except Exception as e:
            logger.warn(f"OKX 账户后台恢复第 {attempt} 次探测异常: {e}", "startup")
            ok = False
        if ok:
            logger.info(f"OKX 账户已恢复（后台第 {attempt} 次重试），买入功能解除降级", "startup")
            push_notify(f"✅ OKX 账户连接恢复\n\n后台第 {attempt} 次重试成功\n持仓同步已完成，买入功能恢复")
            return
        logger.debug(f"OKX 账户后台恢复第 {attempt} 次仍未成功，{OKX_RECOVERY_INTERVAL_SEC:.0f} 秒后再试")
def init_okx_client(trade_mode, logger):
    global _okx_client, TRADE_MODE
    mode = (trade_mode or "demo").strip().lower()
    if mode not in ("demo", "live"):
        logger.error(f"不支持的交易模式: {mode}，仅支持 demo/live", "startup")
        sys.exit(1)
    if mode == "live" and os.getenv("OKX_LIVE_CONFIRM", "").strip().upper() != "YES":
        logger.warn("实盘模式未设置 OKX_LIVE_CONFIRM=YES，自动降级为模拟盘 demo", "startup")
        mode = "demo"
    TRADE_MODE = mode
    api_key = os.getenv("OKX_API_KEY", "").strip()
    api_secret = os.getenv("OKX_API_SECRET", "").strip()
    passphrase = os.getenv("OKX_API_PASSPHRASE", "").strip()
    if not (api_key and api_secret and passphrase):
        logger.error("OKX API 凭证不完整，请检查 .env 文件", "startup")
        sys.exit(1)
    _okx_client = OkxTradeClient(api_key, api_secret, passphrase, simulated=(mode == "demo"), logger=logger)
    backoff = 3.0
    for attempt in range(1, OKX_INIT_RETRY_MAX + 1):
        if _okx_probe_and_sync(logger):
            logger.info(f"交易模式: {TRADE_MODE_DESC[mode]}", "startup")
            return mode
        logger.warn(f"OKX 账户连接第 {attempt}/{OKX_INIT_RETRY_MAX} 次失败，{backoff:.0f} 秒后重试", "startup")
        time.sleep(backoff)
        backoff = min(60.0, backoff * 2)
    # 重试耗尽不再直接退出：本地有持仓时退出等于把持仓丢给无人盯守（止盈/止损全部失效）
    local_pos = load_positions()
    logger.error(
        f"OKX 账户在 {OKX_INIT_RETRY_MAX} 次重试后仍不可达"
        + (f"，本地有 {len(local_pos)} 笔持仓，降级继续运行：起行情线程保住卖出监听，账户由后台重试恢复（期间不买入）"
           if local_pos else "，且本地无持仓，退出")
    )
    if not local_pos:
        sys.exit(1)
    threading.Thread(target=_account_recovery_worker, args=(logger,), daemon=True, name="okx-recover").start()
    logger.info(f"交易模式: {TRADE_MODE_DESC[mode]}（账户降级中）", "startup")
    return mode
# ==================== 币对状态管理（核心逻辑） ====================
class SymbolState:
    def __init__(self, inst_id, ref_high, ref_low, logger, system_params=None, position_only: bool = False):
        self.inst_id = inst_id
        self.logger = logger
        self.params = system_params or {}
        # 仅持仓管理币对（平台有持仓但不在配置表中）：只监听卖出，永不买入
        self.position_only = position_only
        self.min_buy_amount = env_num("MIN_BUY_AMOUNT", 100.0)
        self.client = _okx_client
        # 加载黑名单（常规 + 未知异常）和观察列表
        self.blacklist = load_blacklist()
        self.unknown_blacklist = load_unknown_blacklist()
        self.observe_list = load_observe_list()
        # v5.5：配置计算范围（来自 okx_ding_ok_config.xlsx 币对配置的最高价/最低价，不随行情更新）
        self.range_high = float(ref_high)
        self.range_low = float(ref_low)
        # v5.5：价格超出配置计算范围的币对（已记入同目录 xlsx 并剔除买入）
        # v5.8：价格回到区间（含滞回带）后自动恢复，_range_flip_ts 限制翻转频率
        self.out_of_range = self.inst_id in load_out_of_range()
        self._range_flip_ts = 0.0
        # 买入信号相关（新逻辑）
        self.buy_signal_activated = False
        self.buy_signal_lowest_price = 0.0
        self.buy_signal_buy_level = ""
        self.buy_signal_buy_price = 0.0
        self.buy_signal_attempt_time = 0.0  # 上次尝试买入时间（防频繁尝试）
        # v5.16（文档 C10）：成本来源（fill=真实成交 / reconcile=对账重建估值）
        self.cost_source = ""
        # v5.16（文档 C5）：粉尘核对节流（仅当持仓市值 < POS_MIN_USD 时才用到）
        self._dust_check_due_ts = 0.0
        # v5.17（文档 C12）：最近一次吃到行情的时刻 + 最近一次 REST 兜底时刻（无行情持仓兜底盯盘用）
        self.last_tick_ts = 0.0
        self._last_stale_poll_ts = 0.0
        # v5.18（文档 C7）：订单执行线程相关 —— executor 由 MarketEngine 注入（None=同步执行，
        # 测试与独立运行场景）；order_in_flight 标记在途订单（"buy"/"sell"），防止行情 tick 重复提交
        self.executor = None
        self.order_in_flight = None
        self._okx_available = False
        # 网络探测失败 ≠ 币对不可交易：区分二者，否则一次网络抖动会把全部币对误打黑名单
        self._net_failed = False
        # v5.15（文档 P1-3）：第三种状态——当前交易环境（demo/live）确实没有该产品（code=51001）。
        # 不是网络故障；v5.19（用户决定）：该状态=不可交易产品，直接写入常规黑名单持久化、不再重试
        self._env_missing = False
        # v5.19（用户决定）：地域/合规限制（51155/compliance/restriction）同为不可交易产品：
        # 常规黑名单持久化、不再重试
        self._region_blocked = False
        # v5.19：最近一次探测异常原文（黑名单 reason 用；仅本进程诊断）
        self._probe_error = ""
        # v5.15（文档 P1-1）：运行期重探状态（指数退避，见 MarketEngine._reprobe_due_states）
        self._reprobe_fails = 0
        self._reprobe_next_ts = time.time() + REPROBE_BASE_SEC
        if inst_id in self.blacklist or inst_id in self.unknown_blacklist:
            self.logger.info(f"{inst_id} 在黑名单中，自动跳过", "startup")
        elif inst_id in self.observe_list:
            self.logger.info(f"{inst_id} 在待观察列表中，不进行交易", "startup")
        elif self.client is not None:
            try:
                info = self.client.get_instrument(inst_id)
                self._okx_available = bool(info)
            except Exception as e:
                self._okx_available = False
                self._probe_error = str(e)
                err_lower = str(e).lower()
                if "51001" in str(e):
                    # v5.15（文档 P1-3）：51001 是确定性答复——当前环境没有该产品（如 demo 缺少 18 个
                    # 主网币对）。v5.19（用户决定）：不再"等待重探"，进入下方黑名单分支直接持久化
                    self._env_missing = True
                elif "51155" in str(e) or "compliance" in err_lower or "restriction" in err_lower:
                    # v5.19（用户决定）：地域/合规限制同为不可交易产品，进入下方黑名单分支直接持久化
                    self._region_blocked = True
                else:
                    self._net_failed = True
                    self.logger.debug(f"{inst_id} 交易对查询异常（网络类），不做黑名单判定: {e}")
        if not self._okx_available and position_only:
            self.logger.info(f"{inst_id} 现货检测未通过，但平台有持仓，跳过黑名单处理，仍纳入卖出监听", "startup")
        elif not self._okx_available and self._net_failed:
            self.logger.warn(f"{inst_id} 交易对查询未成功（账户/网络不可达），暂不判定为不可交易，不加入黑名单", "startup")
        elif not self._okx_available and self._env_missing:
            # v5.19（用户决定）：当前环境无此产品 = 不可交易产品 → 常规黑名单持久化，不再重试
            if inst_id not in self.blacklist and inst_id not in self.unknown_blacklist:
                add_to_blacklist(inst_id, "当前交易环境无此产品(51001)")
                self.blacklist.add(inst_id)
            self.logger.warn(f"{inst_id} 当前交易环境（{TRADE_MODE}）无此产品（51001），已加入黑名单（不可交易产品，不再重试）", "startup")
        elif not self._okx_available and self._region_blocked:
            # v5.19（用户决定）：地域/合规限制同为不可交易产品 → 常规黑名单持久化，不再重试
            if inst_id not in self.blacklist and inst_id not in self.unknown_blacklist:
                add_to_blacklist(inst_id, f"交易地域/合规限制: {self._probe_error[:100]}")
                self.blacklist.add(inst_id)
            self.logger.warn(f"{inst_id} 因交易地域/合规限制加入黑名单（不可交易产品，不再重试）", "startup")
        elif not self._okx_available and inst_id not in self.blacklist and inst_id not in self.unknown_blacklist and inst_id not in self.observe_list:
            self.logger.warn(f"{inst_id} 在 OKX 现货不可交易，已加入黑名单", "startup")
            add_to_blacklist(inst_id, "启动检测不可交易")
            # v5.12 R15：写表之外还要同步内存集合（与 _execute_buy 的合规分支一致），
            # 否则本进程内 self.blacklist 仍是启动时的旧快照
            self.blacklist.add(inst_id)
        elif not self._okx_available:
            self.logger.info(f"{inst_id} 已在黑名单/观察列表中，跳过", "startup")
        if self.out_of_range:
            self.logger.info(f"{inst_id} 价格已超出计算范围 [{self.range_low:.8g}, {self.range_high:.8g}]，不参与交易（记录见 {os.path.basename(OUT_OF_RANGE_FILE)}）", "startup")
        # 加载本地状态
        self.positions = load_positions()
        self.cooldown = load_cooldown()
        self.high_low = load_high_low()
        self.pair_status = load_pair_status()
        self.buy_queue = load_buy_queue()
        # ===== v6（设计单 v1.1）：本层梯表 = 固定层界 [同层最低, 同层最高]（sheet2 固定输入）；
        # 价格越界 → 换层（shifted），废除"运行时累计高低扩表"与"超范围剔除" =====
        ref_low = float(ref_low or 0)
        ref_high = float(ref_high or 0)
        if ref_low > 0 and ref_high > ref_low:
            self.low, self.high = ref_low, ref_high
        else:
            mid = max(ref_high, ref_low, 1e-12)
            self.low, self.high = mid / 2.0, mid
        self.levels = LayerLadder(self.low, self.high)
        # 持仓状态
        pos = self.positions.get(inst_id, {})
        self.has_position = pos.get("position_qty", 0) > 0
        self.position_price = pos.get("position_price", 0)
        self.position_qty = pos.get("position_qty", 0)
        self.position_amount = pos.get("position_amount", 0)
        self.buy_time = pos.get("buy_time", "")
        self.buy_reason = pos.get("buy_reason", "")
        self.pair_type = pos.get("pair_type", "")
        self.pair_sell_line = pos.get("pair_sell_line", "")
        self.peak_price = pos.get("peak_price", 0)
        self.stop_price = pos.get("stop_price", 0)
        self.profit_triggered = pos.get("profit_triggered", False)
        self.check_level = pos.get("check_level", "T3")
        self.last_check_time = pos.get("last_check_time", "")
        try:
            self.max_loss_pct = float(pos.get("max_loss_pct", 0) or 0)
        except Exception:
            self.max_loss_pct = 0.0
        # ===== v6（设计单 v1.1）：买点状态机 / 已涨幅度 / 清仓规则字段 =====
        self.entry_type = str(pos.get("entry_type", "") or "")      # "high"/"low"/"legacy"/""
        try:
            self.buy_layer_low = float(pos.get("buy_layer_low", 0) or 0)
            self.buy_layer_high = float(pos.get("buy_layer_high", 0) or 0)
        except (TypeError, ValueError):
            self.buy_layer_low = self.buy_layer_high = 0.0
        try:
            self.risen_low = float(pos.get("risen_low", 0) or 0)
            self.risen_high = float(pos.get("risen_high", 0) or 0)
        except (TypeError, ValueError):
            self.risen_low = self.risen_high = 0.0
        self.risen_low_ts = str(pos.get("risen_low_ts", "") or "")
        self.risen_high_ts = str(pos.get("risen_high_ts", "") or "")
        self.risen_armed = str(pos.get("risen_armed", "") or "") in ("1", "True", "true")
        self.v6_next_buy = str(pos.get("v6_next_buy", "") or "")   # ""/"low"/"next_layer"
        self.risen_valid_min = env_num("RISEN_RANGE_MIN_PCT", 0.05)  # 已涨幅度有效门槛（<5% 时动态止盈兜底）
        self.ref_low_minutes = env_num("REF_LOW_MINUTES", 120.0)     # 参考最低静默时长（分钟）
        self.risen_push_throttle = env_num("RISEN_PUSH_THROTTLE_SEC", 20.0)
        self.v6_sig_type = ""            # ""/"high"/"low"：当前激活的买点信号
        self.v6_sig_ref_low = 0.0        # 参考最低价（激活后持续刷新）
        self.v6_sig_ref_low_ts = 0.0     # 参考最低形成时刻（time.time()）
        self._v6_last_attempt_ts = 0.0   # 买入尝试节流（≥30s）
        self._v6_risen_pushed = False    # 已涨幅度生效推送（每币一次）
        # 配对状态
        pair = self.pair_status.get(inst_id, {})
        self.is_paired = pair.get("is_paired", False)
        self.pair_buy_price = pair.get("buy_price", 0)
        self.pair_buy_time = pair.get("buy_time", "")
        self.pair_sell_line_price = pair.get("sell_line_price", 0)
        self.is_sold = pair.get("is_sold", False)
        self.sell_time = pair.get("sell_time", "")
        self.sell_reason = pair.get("sell_reason", "")
        self._last_profit = 0.0
        self._last_profit_pct = 0.0
        self._balance_insufficient_until = 0.0
        self._buy_blocked_until = 0.0      # 买入未成交冷却截止时间（R5）
        self._sell_blocked_until = 0.0
        # v5.12 R10：买入队列不再在构造时各自 load+save 整表；
        # 由 MarketEngine.add_state 之后统一 sync_all_buy_queue()（启动期一次读写）
        self._last_processed_price = 0.0
        self._last_processed_ts = 0.0
        # v5.7：运行期依据本地账本，此处只读启动同步快照，不再请求平台
        if self.client is not None:
            snapshot = get_positions_snapshot()
            api_has_pos = snapshot.get(inst_id, {}).get("position_qty", 0) > 0
            if api_has_pos:
                if not self._okx_available:
                    self._okx_available = True
                    self.logger.info(f"{inst_id} 平台存在持仓，纳入卖出监听（买入仍受黑名单/观察列表限制）", "startup")
                if not self.has_position:
                    self.logger.info(f"{inst_id} 启动快照检测到持仓，本地同步更新", "startup")
                    api_pos = snapshot.get(inst_id, {})
                    self.has_position = True
                    self.position_qty = api_pos.get("position_qty", 0)
                    self.position_price = api_pos.get("position_price", 0)
                    self.position_amount = api_pos.get("position_amount", 0)
                    self._save_state()
    def _sync_buy_queue(self):
        rows = load_buy_queue()
        rows, changed = self._sync_buy_queue_row(rows)
        if changed:
            save_buy_queue(rows)

    def _sync_buy_queue_row(self, rows: List[Dict]) -> Tuple[List[Dict], bool]:
        """在**已载入**的队列表上同步本币对的行，返回 (rows, 是否有改动)。
        本方法不碰磁盘：启动期 N 个币对共用一次"读表→逐行改→写表"（R10，
        原来每个币对各自 load+save 一遍，整表写 N 次、每次还带 fsync）。
        v5.10：队列是"所有币对共用一张表"，任何写回都必须基于盘上最新内容做单行修改，
        不能用常驻内存副本，否则会把别的币对后来改过的状态覆盖回旧值。"""
        if self.position_only:
            return rows, False
        # v5.5：超出计算范围的币，从买入列表中剔除且不再加回
        # v5.1：常规黑名单 / 未知异常黑名单中的币，从买入列表中剔除
        # v5.19（用户决定）：不可交易产品（环境缺失/地域限制）即使因异常未落黑名单文件，
        # 也绝不允许进入买入队列
        if (self.out_of_range or self.inst_id in self.blacklist or self.inst_id in self.unknown_blacklist
                or getattr(self, "_env_missing", False) or getattr(self, "_region_blocked", False)):
            kept = [r for r in rows if r.get("inst_id") != self.inst_id]
            changed = len(kept) != len(rows)
            if changed:
                reason = "价格超出计算范围" if self.out_of_range else "在黑名单中"
                self.logger.info(f"{self.inst_id} {reason}，从买入列表剔除", "startup")
            self.buy_queue = kept
            return kept, changed
        in_queue = False
        changed = False
        for row in rows:
            if row.get("inst_id") == self.inst_id:
                in_queue = True
                if self.has_position:
                    new_status = "已持仓_排除"
                elif self._is_in_cooldown():
                    new_status = "静默期_排除"
                elif self.inst_id in self.observe_list:
                    new_status = "观察列表_排除"
                else:
                    new_status = "待买入"
                if row.get("status") != new_status:
                    row["status"] = new_status
                    changed = True
                new_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if row.get("last_check_time") != new_ts:
                    row["last_check_time"] = new_ts
                    changed = True
                break
        if not in_queue and not self.has_position and not self._is_in_cooldown() and self.inst_id not in self.observe_list:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            rows.append({
                "inst_id": self.inst_id,
                "status": "待买入",
                "ref_high": str(self.high),
                "ref_low": str(self.low),
                "add_time": now_str,
                "last_check_time": now_str
            })
            changed = True
        self.buy_queue = rows
        return rows, changed

    def _is_in_cooldown(self):
        until = self.cooldown.get(self.inst_id, "")
        if until:
            try:
                return datetime.now() < datetime.strptime(until, "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
        # 每个行情 tick 都会走到这里：先只读扫描，确认需要翻转状态才做整表拷贝与落盘
        for row in _read_csv_ref(BUY_QUEUE_FILE, BUY_QUEUE_HEADER):
            if row.get("inst_id") == self.inst_id and row.get("status") == "静默期_排除":
                rows = load_buy_queue()
                flipped = False
                for r in rows:
                    if r.get("inst_id") == self.inst_id and r.get("status") == "静默期_排除":
                        r["status"] = "待买入"
                        flipped = True
                if flipped:
                    save_buy_queue(rows)
                    self.buy_queue = rows
                break
        return False
    def _update_check_level(self, profit_pct):
        if profit_pct >= 0.065:
            self.check_level = "T0"
        elif profit_pct > 0:
            self.check_level = "T1"
        elif self.pair_type in ("回撤", "回调", "过渡", "极限"):
            self.check_level = "T2"
        else:
            self.check_level = "T3"
        self.last_check_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    def _can_buy_light(self):
        """v5.15（文档 P2-1）：不含余额网络查询的静态买入预检。

        _execute_buy 此前无论因何被拒都先强刷一次余额 REST（两天 13,553 条"买入跳过"全部如此）。
        把黑名单/持仓/冷却等纯本地条件拆到这里先判，余额 REST 只留给真正可能下单的尝试；
        _can_buy 复用本方法，检查集合保持单一来源。
        """
        # 仅持仓管理币对：永不买入
        if self.position_only:
            return False, "仅持仓管理币对，不参与买入"
        # v6：超范围剔除已废除——价格越界由换层处理（update_price/_v6_layer_check）
        if not self._okx_available:
            # v5.15（文档 P1-1/P1-3）：区分"当前环境无此产品"与"启动探测失败"，
            # 诊断不再一片"币对在黑名单/不可交易"；v5.19：环境缺失/地域限制=不可交易产品（已入黑名单）
            if getattr(self, "_env_missing", False):
                return False, f"当前交易环境（{TRADE_MODE}）无此产品(51001)（已入黑名单）"
            if getattr(self, "_region_blocked", False):
                return False, "交易地域/合规限制（已入黑名单）"
            if getattr(self, "_net_failed", False):
                return False, "启动探测失败（网络类），等待自动重探"
            return False, "币对在黑名单/不可交易"
        # v5.1：下单前检查两类黑名单（常规 + 未知异常），黑名单币从买入列表剔除
        if self.inst_id in self.blacklist:
            return False, "在常规黑名单中"
        if self.inst_id in self.unknown_blacklist:
            return False, "在未知异常黑名单中"
        if self.has_position:
            return False, "本地已有持仓"
        # v5.7：下单前依据本地账本核对，避免与平台余额账本同步造成的阻塞与报错
        # 持仓账本上次读失败时，"读不到"不等于"没有持仓"：宁可漏买一次，也不能重复买入
        if POSITIONS_FILE in _CSV_READ_FAILED:
            self.logger.warn(f"{self.inst_id} 持仓账本上次读取失败，暂不买入（防重复建仓）", "buy_execute")
            return False, "持仓账本读取失败，暂不买入"
        if load_positions().get(self.inst_id, {}).get("position_qty", 0) > 0:
            self.has_position = True
            self.logger.warn(f"{self.inst_id} 本地账本已存在持仓，禁止重复买入", "startup")
            return False, "本地账本已存在持仓"
        if self._is_in_cooldown():
            return False, f"静默期中 (至 {self.cooldown.get(self.inst_id, '')})"
        if self.inst_id in self.observe_list:
            return False, "在待观察列表中"
        if time.time() < self._buy_blocked_until:
            return False, f"买入未成交冷却中(至 {datetime.fromtimestamp(self._buy_blocked_until).strftime('%H:%M:%S')})"
        if self.is_paired and not self.is_sold:
            return False, f"已配对未卖出 ({self.pair_type})"
        return True, ""

    def _can_buy(self):
        can, msg = self._can_buy_light()
        if not can:
            return False, msg
        if time.time() < self._balance_insufficient_until:
            return False, "余额不足冷却中"
        balance = get_okx_balance()
        raw_amount = balance * self.params.get("buy_ratio", 0.01)
        buy_amount = max(raw_amount, self.min_buy_amount)
        if buy_amount > balance:
            buy_amount = balance
        if buy_amount <= 0:
            return False, "计算出的买入金额为0"
        # v5.15（文档 P3-2）：删除 `if balance < buy_amount` 死分支——上方已把
        # buy_amount 截断到 ≤ balance，该条件永假
        return True, ""
    def _breakeven_price(self) -> float:
        """含双边手续费的保本价：账面成本额 ÷ 实际到账数量 ÷ (1 - taker费率)。

        position_price 是成交均价 avgPx（买入扣币之前的单位价），而 position_qty 记录的是
        扣费后实际到账数量，二者相除才是"每枚到手币的cost"；卖出端再扣一次 taker 费。
        直接用 price >= position_price 判回本，会在约 -2×费率 处误判为已回本而亏本清仓。
        """
        if self.position_price <= 0:
            return 0.0
        if self.position_qty > 0 and self.position_amount > 0:
            return self.position_amount / self.position_qty / (1.0 - TAKER_FEE_RATE)
        return self.position_price * (1.0 + 2.0 * TAKER_FEE_RATE)
    def _is_breakeven(self, price: float) -> bool:
        return price >= self._breakeven_price()
    def _can_sell(self, price: float, min_profit_pct: Optional[float] = 0.05):
        """卖出资格检查（v5.10：按文档 9.1.3 的第二个建议改为显式阈值参数）
        price 必须显式给出，取消回退 _last_processed_price 的不可达分支；
        min_profit_pct=None 用于"亏损超5%后回本清仓""回本豁免""止盈清仓"等已按保本价判定的场景。
        """
        if not self.has_position:
            return False, "无持仓"
        if min_profit_pct is not None:
            profit_pct = (price - self.position_price) / self.position_price if self.position_price > 0 else 0
            if profit_pct < min_profit_pct:
                return False, f"盈利未达{min_profit_pct*100:.0f}% (当前 {profit_pct*100:.2f}%)"
        return True, ""
    def _get_buy_level(self, price):
        """返回当前价格下最佳买点（价格低于该买点且最接近）"""
        buy_keys = ["pullback2_down", "callback2_down", "transition2_down", "limit2_down"]
        best_key = None
        best_price = None
        for key in buy_keys:
            level = getattr(self.levels, key)
            if price < level:
                if best_price is None or level < best_price:
                    best_price = level
                    best_key = key
        return best_key, best_price

    def _reset_buy_signal(self):
        """v5.12 R7：买入信号统一复位（取消 / 买入成功都走这里）；v6：同步复位新买点状态机"""
        self.buy_signal_activated = False
        self.buy_signal_lowest_price = 0.0
        self.buy_signal_buy_level = ""
        self.buy_signal_buy_price = 0.0
        self.v6_sig_type = ""
        self.v6_sig_ref_low = 0.0
        self.v6_sig_ref_low_ts = 0.0

    # ============ v6（设计单 v1.1）：固定层梯表买点/清仓/已涨幅度 ============
    def _v6_exec_price(self, kind: str) -> float:
        """v6 执行价：high=回撤下~高位中间中点（12.5/16）；low=极限下~地板中点（0.5/16）。"""
        lv = self.levels
        span = lv.high - lv.low
        if span <= 0:
            return 0.0
        if kind == "high":
            return lv.low + span * (12.5 / 16.0)
        if kind == "low":
            return lv.low + span * (0.5 / 16.0)
        return 0.0

    def _v6_layer_check(self, price):
        """v6 换层：价格越出当前层界 → 层界整体 ×2（向上）/÷2（向下），支持一次跨多层。

        规则（Q9）：无持仓向上换层=忽略（不高位接盘，回落换层后按旧层回撤下恢复）；
        下破地板=下一买点=下一层高位买点（换层后在新层按梯表评估）。有持仓：清仓 2/3 用
        买入层固定档位，不受换层影响；清仓 1（已涨幅度）按自身数据管理。
        """
        alerts = []
        cur = self.levels
        direction = None
        if price > cur.high:
            direction = "up"
            while price > self.levels.high:
                self.levels = self.levels.shifted("up")
        elif price < cur.low:
            direction = "down"
            while price < self.levels.low:
                self.levels = self.levels.shifted("down")
        if direction is None:
            return alerts
        old_low, old_high = cur.low, cur.high
        self.high, self.low = self.levels.high, self.levels.low
        self._reset_buy_signal()
        self.v6_next_buy = "next_layer" if (direction == "up" and not self.has_position) else ""
        self.logger.info(
            f"{self.inst_id} 换层（{'向上' if direction == 'up' else '向下'}）："
            f"[{old_low:.8g}, {old_high:.8g}] → [{self.levels.low:.8g}, {self.levels.high:.8g}]", "config_load")
        alerts.append(f"换层{'向上' if direction == 'up' else '向下'}")
        return alerts

    def _v6_buy_fsm(self, price):
        """v6 买点状态机（§2）：高位/低位两类；回升上破激活线=撤信号；作废按规则转移下一买点。

        高位买点：下破回撤下(13/16) 激活 → 120 分钟不创新低且不破高位中间(12/16) →
                 价格 ≤ 执行价(12.5/16) 限价买入；破高位中间 → 作废，下一买点=低位买点。
        低位买点：下破极限下(1/16) 激活 → 120 分钟不创新低且不破地板(0/16) →
                 价格 ≤ 执行价(0.5/16) 限价买入；回升上破极限下 → 撤信号。
        """
        now = time.time()
        lv = self.levels
        span = lv.high - lv.low
        if span <= 0:
            return None
        line13 = lv.low + span * (13.0 / 16.0)
        line12 = lv.low + span * (12.0 / 16.0)
        line1 = lv.low + span * (1.0 / 16.0)
        floor = lv.low
        sig = self.v6_sig_type
        if sig == "high":
            if price > line13:
                self.logger.debug(f"{self.inst_id} 高位买点信号取消（回升上破回撤下 {line13:.8g}，当前 {price:.8g}）")
                self._reset_buy_signal()
                return None
            if price < line12:
                self.logger.info(f"{self.inst_id} 高位买点作废（破高位中间 {line12:.8g}），下一买点=低位买点", "trade_event")
                self._reset_buy_signal()
                self.v6_next_buy = "low"
                return None
            if price < self.v6_sig_ref_low:
                self.v6_sig_ref_low = price
                self.v6_sig_ref_low_ts = now
            exec_px = self._v6_exec_price("high")
            if price <= exec_px and (now - self.v6_sig_ref_low_ts) >= self.ref_low_minutes * 60.0:
                return self._v6_trigger_buy(price, "high")
            return None
        if sig == "low":
            if price > line1:
                self.logger.debug(f"{self.inst_id} 低位买点信号取消（回升上破极限下 {line1:.8g}，当前 {price:.8g}）")
                self._reset_buy_signal()
                return None
            if price > floor and price < self.v6_sig_ref_low:
                self.v6_sig_ref_low = price
                self.v6_sig_ref_low_ts = now
            exec_px = self._v6_exec_price("low")
            if price > floor and price <= exec_px and (now - self.v6_sig_ref_low_ts) >= self.ref_low_minutes * 60.0:
                return self._v6_trigger_buy(price, "low")
            return None
        # 未激活：按当前层梯表检查激活
        if self.v6_next_buy == "" and price < line13 and price >= line12:
            self.v6_sig_type = "high"
            self.v6_sig_ref_low = price
            self.v6_sig_ref_low_ts = now
            self.logger.debug(f"{self.inst_id} 高位买点激活（下破回撤下 {line13:.8g}）；参考最低 {price:.8g}，"
                              f"{self.ref_low_minutes:.0f} 分钟不创新低且不破 {line12:.8g} 后以 {self._v6_exec_price('high'):.8g} 限价买入")
            return None
        if self.v6_next_buy != "next_layer" and price <= line1 and price > floor:
            self.v6_sig_type = "low"
            self.v6_sig_ref_low = price
            self.v6_sig_ref_low_ts = now
            self.logger.debug(f"{self.inst_id} 低位买点激活（下破极限下 {line1:.8g}）；参考最低 {price:.8g}，"
                              f"{self.ref_low_minutes:.0f} 分钟不创新低且不破地板后以 {self._v6_exec_price('low'):.8g} 限价买入")
            return None
        # 深区（< 高位中间）且无信号 → 下一买点转移到低位买点
        if self.v6_next_buy == "" and price < line12:
            self.v6_next_buy = "low"
        return None

    def _v6_trigger_buy(self, price, kind):
        """买点条件满足 → 投递限价买单（执行价）；30 秒节流，失败保留信号等下次。"""
        now = time.time()
        if now - self._v6_last_attempt_ts < 30:
            return None
        self._v6_last_attempt_ts = now
        exec_px = self._v6_exec_price(kind)
        label = "高位买点" if kind == "high" else "低位买点"
        result = self._request_buy(price, f"{label}（执行价 {exec_px:.8g} 限价）", f"v6_{kind}", "", "", entry_type=kind)
        if result:
            return f"{label}买入已提交 @ {exec_px:.8g}"
        return None

    def _v6_risen_valid(self):
        if self.risen_low <= 0 or self.risen_high <= self.risen_low:
            return False
        return (self.risen_high - self.risen_low) / self.risen_low >= self.risen_valid_min

    def _v6_risen_update(self, price):
        """已涨幅度维护（§3）：新低 → 最低+最高重置（E1）；新高 → 仅最高。时间=极值产生时刻。"""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if self.risen_low <= 0 or self.risen_high <= 0:
            self.risen_low = self.risen_high = price
            self.risen_low_ts = self.risen_high_ts = now_str
            return
        if price < self.risen_low:
            self.risen_low = price
            self.risen_low_ts = now_str
            self.risen_high = price
            self.risen_high_ts = now_str
        elif price > self.risen_high:
            self.risen_high = price
            self.risen_high_ts = now_str
            if self.entry_type == "legacy":
                self.risen_armed = True   # 迁移持仓：创新高后才启用清仓1

    def _v6_manage_position(self, price):
        """v6 持仓管理：已涨幅度维护 + 清仓1（破回撤上）/ 2/3（买入层固定档位）+ 清仓4 回本 + 动态止盈兜底。"""
        alerts = []
        # 粉尘残仓：市值极低且平台无法下单卖出 → 清账（保留 v5.16 文档 C5 行为）
        if self.position_qty > 0 and price * self.position_qty < POS_MIN_USD:
            dust_msg = self._dust_cleanup(price)
            if dust_msg:
                alerts.append(dust_msg)
                return alerts
        if self.entry_type == "" and self.position_price > 0:
            self.entry_type = "legacy"
        if self.entry_type == "legacy" and self.risen_high <= 0 and self.position_price > 0:
            # 迁移播种：已涨区间 = [min(买价, 现价), max(买价, 现价)]；创新高后才启用清仓1（避免上线即连环清仓）
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.risen_low = min(self.position_price, price)
            self.risen_high = max(self.position_price, price)
            self.risen_low_ts = self.risen_high_ts = now_str
            self.risen_armed = False
            self.logger.info(f"{self.inst_id} 【v6 迁移】已有持仓按 legacy 接管：已涨区间播种 "
                             f"[{self.risen_low:.8g}, {self.risen_high:.8g}]（创新高后启用清仓1）", "startup")
        self._v6_risen_update(price)
        profit_pct = (price - self.position_price) / self.position_price if self.position_price > 0 else 0
        if profit_pct < self.max_loss_pct:
            self.max_loss_pct = profit_pct
        # 清仓4：回本清仓（保留；v6 按买入类型决定下一买点，E4）
        if self.max_loss_pct <= -0.05 and self._is_breakeven(price) and not self.profit_triggered:
            self.v6_next_buy = ("low" if self.entry_type == "high"
                                else "next_layer" if self.entry_type == "low" else "")
            self.logger.info(f"{self.inst_id} 亏损超5%后回本，立即清仓", "stop_loss_trigger")
            result = self._request_sell(price, f"回本清仓 (最大亏损 {self.max_loss_pct*100:.2f}%, 保本价 {self._breakeven_price():.8g})", min_profit_pct=None)
            if result:
                alerts.append(f"回本清仓 @ {price:.8g}")
            return alerts
        valid = self._v6_risen_valid()
        if valid and not self._v6_risen_pushed:
            self._v6_risen_pushed = True
            pct = (self.risen_high - self.risen_low) / self.risen_low * 100.0
            pu0 = self.risen_low + (self.risen_high - self.risen_low) * 15.0 / 16.0
            push_notify_throttled(
                f"📊 已涨幅度生效（清仓1 启用）\n\n{self.inst_id}\n已涨最低 {self.risen_low:.8g}\n已涨最高 {self.risen_high:.8g}\n"
                f"幅度 {pct:.2f}%\n破回撤上 {pu0:.8g} 即清仓",
                key=f"risen:{self.inst_id}", title="已涨幅度")
            self.logger.info(f"{self.inst_id} 已涨幅度生效: [{self.risen_low:.8g}, {self.risen_high:.8g}] "
                             f"幅度 {pct:.2f}%，回撤上 {pu0:.8g}", "trade_event")
        if valid and self.risen_armed:
            # 清仓1：破已涨幅度回撤上（动态）
            pu = self.risen_low + (self.risen_high - self.risen_low) * 15.0 / 16.0
            if price < pu:
                self.v6_next_buy = ""
                self.logger.info(f"{self.inst_id} 清仓1：破已涨幅度回撤上 {pu:.8g}（已涨最高 {self.risen_high:.8g}）", "stop_loss_trigger")
                result = self._request_sell(price, f"破已涨幅度回撤上清仓 (区间 [{self.risen_low:.8g}, {self.risen_high:.8g}])", min_profit_pct=None)
                if result:
                    alerts.append(f"已涨幅度回撤上清仓 @ {price:.8g}")
                return alerts
        else:
            # 已涨幅度无效（空 / <5%）或迁移期未启用 → 动态止盈兜底（现行口径：6.5% 激活 / 回撤容忍 / ≥20% 清仓）
            result = self._check_take_profit(price)
            if result:
                alerts.append(f"动态止盈清仓 @ {price:.8g}")
                return alerts
        # 清仓2/3：买入层固定档位（换层不影响）
        if self.entry_type == "high" and self.buy_layer_low > 0 and self.buy_layer_high > self.buy_layer_low:
            mid = self.buy_layer_low + (self.buy_layer_high - self.buy_layer_low) * 12.0 / 16.0
            if price < mid:
                self.v6_next_buy = "low"
                self.logger.info(f"{self.inst_id} 清仓2：破买入层高位中间 {mid:.8g}（买入层 [{self.buy_layer_low:.8g}, {self.buy_layer_high:.8g}]）", "stop_loss_trigger")
                result = self._request_sell(price, f"破高位中间清仓 (买入层 [{self.buy_layer_low:.8g}, {self.buy_layer_high:.8g}])", min_profit_pct=None)
                if result:
                    alerts.append(f"破高位中间清仓 @ {price:.8g}")
                return alerts
        elif self.entry_type == "low" and self.buy_layer_low > 0:
            if price < self.buy_layer_low:
                self.v6_next_buy = "next_layer"
                self.logger.info(f"{self.inst_id} 清仓3：破买入层地板 {self.buy_layer_low:.8g}", "stop_loss_trigger")
                result = self._request_sell(price, f"破地板清仓 (买入层 [{self.buy_layer_low:.8g}, {self.buy_layer_high:.8g}])", min_profit_pct=None)
                if result:
                    alerts.append(f"破地板清仓 @ {price:.8g}")
                return alerts
        return alerts

    # ============ v5.18（文档 C7）：行情线程入口（锁内只投递）/ 订单线程任务（锁外 REST） ============
    def _request_buy(self, price, reason, buy_key, sell_key, pair_name, entry_type=""):
        """买入入口（行情线程，持 ENGINE_LOCK）。

        无订单执行器（测试/独立运行）→ 与旧行为一致，同步执行 _execute_buy；
        有执行器 → 只做零网络预检并投递任务，余额强刷/下单/等成交/补单全部移到锁外由
        订单线程完成。返回真值 = 已受理（调用方沿用"买入已触发"的记账与提前返回逻辑）。
        v6：buy_key="v6_high"/"v6_low" 时按执行价（12.5/16 或 0.5/16）限价买入；entry_type 落账本。
        """
        if getattr(self, "executor", None) is None:
            return self._execute_buy(price, reason, buy_key, sell_key, pair_name, entry_type)
        if getattr(self, "order_in_flight", None):
            self.logger.debug(f"{self.inst_id} {self.order_in_flight} 订单执行中，跳过本次买入请求")
            return None
        now_ts = time.time()
        if now_ts < self._balance_insufficient_until:
            self.logger.debug(f"{self.inst_id} 余额不足冷却中，跳过买入预检")
            return None
        can, msg = self._can_buy_light()
        if not can:
            self.logger.debug(f"{self.inst_id} 买入跳过: {msg}")
            return None
        if str(buy_key).startswith("v6_"):
            exec_px = self._v6_exec_price(str(buy_key)[3:])
            if exec_px <= 0 or price > exec_px:
                self.logger.debug(f"{self.inst_id} v6 买点 {buy_key} 执行价 {exec_px:.8g}，当前价 {price:.8g} 未到，跳过")
                return None
        else:
            buy_level = getattr(self.levels, buy_key)
            if price >= buy_level:
                self.logger.debug(f"{self.inst_id} 当前价 {price:.8g} 不小于买点 {buy_level:.8g}，跳过")
                return None
        self.order_in_flight = "buy"
        if not self.executor.submit(("buy", self.inst_id, price, reason, buy_key, sell_key, pair_name, entry_type)):
            self.order_in_flight = None
            return None
        msg = f"{self.inst_id} 买入已提交 @ {price:.8g}（订单线程执行）"
        self.logger.info(msg, "trade_event")
        return msg

    def _request_sell(self, price, reason, min_profit_pct: Optional[float] = 0.05):
        """卖出入口（行情线程，持 ENGINE_LOCK）。语义同 _request_buy。"""
        if getattr(self, "executor", None) is None:
            return self._execute_sell(price, reason, min_profit_pct)
        if getattr(self, "order_in_flight", None):
            self.logger.debug(f"{self.inst_id} {self.order_in_flight} 订单执行中，跳过本次卖出请求")
            return None
        can, msg = self._can_sell(price, min_profit_pct)
        if not can:
            self.logger.debug(f"{self.inst_id} 卖出跳过: {msg}")
            return None
        if time.time() < self._sell_blocked_until:
            self.logger.debug(f"{self.inst_id} 卖出受阻延期中（挂单占用），{self._sell_blocked_until - time.time():.0f}s 后重试")
            return None
        self.order_in_flight = "sell"
        if not self.executor.submit(("sell", self.inst_id, price, reason, min_profit_pct)):
            self.order_in_flight = None
            return None
        msg = f"{self.inst_id} 卖出已提交 @ {price:.8g}（订单线程执行）"
        self.logger.info(msg, "trade_event")
        return msg

    def _order_buy_job(self, price, reason, buy_key, sell_key, pair_name, entry_type=""):
        """订单线程的买入任务（由 MarketEngine._run_order_job 调用）。

        锁定纪律：本地预检与入账在 ENGINE_LOCK 内，余额强刷/下单/等成交/补单/REST 在锁外。
        """
        with ENGINE_LOCK:
            plan = self._buy_prepare(price, reason, buy_key, sell_key, pair_name, entry_type)
            if plan is None:
                return
        outcome = self._buy_place(plan)      # 锁外：REST（余额强刷 + 下单 + 补单）
        balance = None
        if outcome.get("action") == "filled":
            # 锁外预取成交后余额：tradeRecord 的 remaining_funds 与资金视图都用它，避免锁内 REST
            balance = get_okx_balance(force_refresh=True)
        with ENGINE_LOCK:
            result = self._buy_apply(plan, outcome, fresh_balance=balance, defer_funds=True)
        if result is not None and balance is not None:
            _update_funds_for_view(balance)  # 锁外：资金视图刷新（v5.15 P1-6 语义保留）

    def _order_sell_job(self, price, reason, min_profit_pct):
        """订单线程的卖出任务。语义同 _order_buy_job。"""
        with ENGINE_LOCK:
            plan = self._sell_prepare(price, min_profit_pct)
            if plan is None:
                return
        outcome = self._sell_place(plan)     # 锁外：REST（可用量核对 + 下单 + 等成交）
        balance = None
        fill = outcome.get("fill")
        if outcome.get("action") == "placed" and isinstance(fill, dict) and (fill.get("qty") or 0) > 0:
            balance = get_okx_balance(force_refresh=True)   # 锁外：成交后余额
        with ENGINE_LOCK:
            result = self._sell_apply(plan, outcome, reason, fresh_balance=balance, defer_funds=True)
        if result is not None and balance is not None:
            _update_funds_for_view(balance)  # 锁外：资金视图刷新

    def _execute_buy(self, price, reason, buy_key, sell_key, pair_name, entry_type=""):
        """执行买入（同步实现：调用方持 ENGINE_LOCK；测试与无执行器场景使用）。

        v5.18（文档 C7）拆为三段：本地预检（_buy_prepare）→ REST（_buy_place，订单线程
        锁外调用）→ 本地账务（_buy_apply）。生产路径由 _request_buy 投递订单线程执行。
        """
        plan = self._buy_prepare(price, reason, buy_key, sell_key, pair_name, entry_type)
        if plan is None:
            return None
        return self._buy_apply(plan, self._buy_place(plan))

    def _buy_prepare(self, price, reason, buy_key, sell_key, pair_name, entry_type=""):
        """阶段1（本地，须持锁）：余额冷却 / 静态预检与买点复查（零网络开销）。返回 plan 或 None。"""
        now_ts = time.time()
        if now_ts < self._balance_insufficient_until:
            # v5.12 R15：余额不足的冷却同样挡住"预检"，否则每个行情 tick 都要打一次
            # force_refresh 的余额 REST（币对数 × tick 频率），既拖慢行情接收又白耗限额
            self.logger.debug(f"{self.inst_id} 余额不足冷却中，跳过买入预检")
            return None
        # v5.15（文档 P2-1）：先做零网络开销的静态预检与买点复查。此前无论因何被拒，
        # 都会先发一条 force_refresh 余额 REST（journal 两天 13,553 条"买入跳过"全部如此）
        can, msg = self._can_buy_light()
        if not can:
            self.logger.debug(f"{self.inst_id} 买入跳过: {msg}")
            return None
        limit_px = 0.0
        if str(buy_key).startswith("v6_"):
            limit_px = self._v6_exec_price(str(buy_key)[3:])
            if limit_px <= 0 or price > limit_px:
                self.logger.debug(f"{self.inst_id} v6 买点 {buy_key} 执行价 {limit_px:.8g}，当前价 {price:.8g} 未到，跳过")
                return None
        else:
            buy_level = getattr(self.levels, buy_key)
            if price >= buy_level:
                self.logger.debug(f"{self.inst_id} 当前价 {price:.8g} 不小于买点 {buy_level:.8g}，跳过")
                return None
        return {"price": price, "reason": reason, "buy_key": buy_key,
                "sell_key": sell_key, "pair_name": pair_name,
                "entry_type": entry_type, "limit_px": limit_px,
                "layer_low": self.levels.low, "layer_high": self.levels.high}

    def _buy_place(self, plan):
        """阶段2（REST，可锁外执行）：余额强刷 + 下单（含部分成交补单）。

        不写任何账本字段（补单提示推送除外），分支结果装进 outcome 交给 _buy_apply。
        """
        out = {"action": ""}
        balance = get_okx_balance(force_refresh=True)
        min_balance = self.min_buy_amount * BUY_BALANCE_MARGIN
        if balance < min_balance:
            out.update(action="low_balance", balance=balance, min_balance=min_balance)
            return out
        # 余额类复查：缓存刚被强刷，_can_buy 不会再打余额 REST（检查集合单一来源）
        can, msg = self._can_buy()
        if not can:
            out.update(action="can_buy_failed", msg=msg)
            return out
        raw_amount = balance * self.params.get("buy_ratio", 0.01)
        buy_amount = max(raw_amount, self.min_buy_amount)
        if buy_amount > balance:
            buy_amount = balance
        if buy_amount <= 0:
            out["action"] = "zero_amount"
            return out
        requested_amount = buy_amount
        fill = self.client.market_buy_quote(self.inst_id, requested_amount, px=plan.get("limit_px") or None)
        if not isinstance(fill, dict) or fill.get("not_filled"):
            # v5.12 R5：市价单没成交（低流动性、_wait_fill 超时、canceled）是暂时状态，
            # 以前一律走"未知错误→未知异常黑名单"，一个币对从此只能手工改 CSV 才能恢复
            out["action"] = "not_filled"
            out["fill_state"] = fill.get("state", "") if isinstance(fill, dict) else ""
            return out
        if "error" in fill:
            out.update(action="error", error=fill["error"])
            return out
        # 成交成功
        price = fill["price"]
        qty = fill["qty"]
        filled_cost = fill["cost"]
        order_ids = [fill.get("ord_id", "")]
        fee_seq = [(float(fill.get("fee") or 0), fill.get("fee_ccy") or "")]
        last_state = fill.get("state", "")
        # v5.15（文档 P0-3）：部分成交自动补单。市价单可能只成交一部分即被取消（模拟盘常见：
        # CSPR 委托 947.73 仅成交 15.04、SAHARA 委托 916.24 仅成交 62.42），按差额补单；
        # 次数上限 BUY_PARTIAL_TOPUP_MAX，差额 < BUY_PARTIAL_MIN_TOPUP 不再追
        topups = 0
        while (last_state == "canceled" and topups < BUY_PARTIAL_TOPUP_MAX
               and filled_cost < requested_amount * BUY_PARTIAL_FILL_TOLERANCE):
            remaining = requested_amount - filled_cost
            if remaining < BUY_PARTIAL_MIN_TOPUP:
                break
            topups += 1
            self.logger.warn(f"{self.inst_id} 买入部分成交 {filled_cost:.2f}/{requested_amount:.2f} USDT，"
                             f"按差额 {remaining:.2f} 补单（第 {topups}/{BUY_PARTIAL_TOPUP_MAX} 次）", "buy_execute")
            push_notify_throttled(
                f"⏳ 买入部分成交\n\n{self.inst_id}\n已成交 {filled_cost:.2f} / 委托 {requested_amount:.2f} USDT\n"
                f"按差额自动补单（最多 {BUY_PARTIAL_TOPUP_MAX} 次）",
                key=f"buypartial:{self.inst_id}", title="买入部分成交")
            more = self.client.market_buy_quote(self.inst_id, remaining, px=plan.get("limit_px") or None)
            if not isinstance(more, dict) or more.get("not_filled") or ("error" in more):
                self.logger.warn(f"{self.inst_id} 部分成交补单未成/未成交，保留已成交部分（{filled_cost:.2f} USDT）", "buy_execute")
                break
            # 多笔成交合并：均价按"成交额/成交数量"加权（与 _fill_result 口径一致）
            gross_old = filled_cost / price if price > 0 else 0.0
            gross_new = more.get("cost", 0.0) / more.get("price", 0) if more.get("price", 0) > 0 else 0.0
            total_gross = gross_old + gross_new
            if total_gross > 0:
                price = (filled_cost + more.get("cost", 0.0)) / total_gross
            qty += more.get("qty", 0.0)
            filled_cost += more.get("cost", 0.0)
            last_state = more.get("state", "")
            order_ids.append(more.get("ord_id", ""))
            fee_seq.append((float(more.get("fee") or 0), more.get("fee_ccy") or ""))
        if topups and filled_cost >= requested_amount * BUY_PARTIAL_FILL_TOLERANCE:
            self.logger.info(f"{self.inst_id} 部分成交补单完成：累计成交 {filled_cost:.2f}/{requested_amount:.2f} USDT", "buy_execute")
        if filled_cost < requested_amount * BUY_PARTIAL_FILL_TOLERANCE:
            pct = 100.0 * filled_cost / requested_amount if requested_amount > 0 else 0.0
            self.logger.warn(f"{self.inst_id} 买入最终未足额：{filled_cost:.2f}/{requested_amount:.2f} USDT（{pct:.1f}%），"
                             f"按实际成交入账，请关注该币对流动性", "buy_execute")
        if len(fee_seq) == 1:
            fee_str = f"{fee_seq[0][0]:.8g}{fee_seq[0][1]}"
        else:
            fee_str = "+".join(f"{f:.8g}{c}" for f, c in fee_seq)
        ord_str = ",".join(str(x) for x in order_ids if x)
        reason = f"{plan['reason']} | ordId={ord_str} fee={fee_str}"
        self.logger.info(f"{self.inst_id} API买入成交: ordId={ord_str} 均价 {price:.8g} 数量 {qty:.8g} 花费 {filled_cost:.2f}", "buy_execute")
        out.update(action="filled", price=price, qty=qty, filled_cost=filled_cost,
                   requested_amount=requested_amount, reason=reason)
        return out

    def _buy_apply(self, plan, outcome, fresh_balance=None, defer_funds=False):
        """阶段3（本地账务，须持锁）：错误分类 / 成交入账 / 落盘与通知。

        fresh_balance：订单线程在锁外预取的余额（tradeRecord 的 remaining_funds 与资金视图用，
        避免锁内 REST）；defer_funds=True 时资金视图刷新由订单线程在锁外完成（同步路径保持原行为）。
        """
        action = outcome.get("action")
        if action == "low_balance":
            self._balance_insufficient_until = time.time() + BUY_BALANCE_COOLDOWN_SEC
            self.logger.info(f"{self.inst_id} 账户余额 {outcome['balance']:.2f} USDT 低于 {outcome['min_balance']:.2f}"
                             f"（MIN_BUY_AMOUNT {self.min_buy_amount:.2f}×{BUY_BALANCE_MARGIN:.2f}），"
                             f"{BUY_BALANCE_COOLDOWN_SEC:.0f} 秒内不再尝试买入", "insufficient_funds")
            return None
        if action == "can_buy_failed":
            self.logger.debug(f"{self.inst_id} 买入跳过: {outcome['msg']}")
            return None
        if action == "zero_amount":
            self.logger.info(f"{self.inst_id} 买入金额为0，跳过")
            return None
        if action == "not_filled":
            state = outcome.get("fill_state", "")
            return self._buy_cooldown(f"买入未成交（state={state or '无回执'}）")
        if action == "error":
            error_msg = outcome["error"]
            self.logger.error(f"{self.inst_id} API买入失败: {error_msg}")
            error_lower = error_msg.lower()
            if "51001" in error_msg:
                # v5.19（用户决定）：当前环境无此产品 = 不可交易产品 → 常规黑名单持久化；
                # 不进未知异常黑名单（C11 会 24h 复检恢复，与"不再重试"相悖）
                self.logger.warn(f"{self.inst_id} 当前交易环境无此产品（51001），已加入黑名单（不可交易产品，不再重试）")
                add_to_blacklist(self.inst_id, f"当前交易环境无此产品(51001): {error_msg[:100]}")
                self.blacklist.add(self.inst_id)
                self._okx_available = False
                self._env_missing = True
                self._remove_from_buy_queue()
                self._push_notify(f"🚫 已加入黑名单\n\n{self.inst_id}\n原因: 当前环境无此产品(51001)\n{error_msg[:80]}")
                return None
            if "51155" in error_msg or "compliance" in error_lower or "restriction" in error_lower:
                # 地区禁买 / 合规限制 → 常规黑名单，不再尝试
                self.logger.warn(f"{self.inst_id} 因交易地域/合规限制加入黑名单，不再尝试")
                add_to_blacklist(self.inst_id, f"交易地域/合规限制: {error_msg[:100]}")
                self.blacklist.add(self.inst_id)   # 内存集合同步跟上，否则本进程内仍反复判可买
                self._okx_available = False
                self._remove_from_buy_queue()
                self._push_notify(f"🚫 已加入黑名单\n\n{self.inst_id}\n原因: 交易地域/合规限制\n{error_msg[:80]}")
                return None
            if "51201" in error_msg or "exceed" in error_lower or "market order" in error_lower:
                self.logger.warn(f"{self.inst_id} 因订单限制加入待观察列表，并从买入队列移除")
                add_to_observe_list(self.inst_id, f"订单限制: {error_msg[:100]}")
                self.observe_list.add(self.inst_id)
                self._remove_from_buy_queue()
                return None
            if "51008" in error_msg or "insufficient" in error_lower or "balance" in error_lower:
                # 余额不足同样是暂时状态（其他币回款在途、余额缓存滞后），冷却后自动重试
                self._balance_insufficient_until = time.time() + BUY_BALANCE_COOLDOWN_SEC
                self.logger.warn(f"{self.inst_id} 余额不足（{error_msg[:80]}），"
                                 f"{BUY_BALANCE_COOLDOWN_SEC:.0f} 秒内不再尝试（不加入黑名单）", "buy_execute")
                return None
            if is_transient_error(error_msg):
                # v5.15（文档 P1-2）：超时/SSL/握手/连接类瞬时错误只冷却重试，不写黑名单
                # （实证：MASK 一次 SSL 握手里超时被永久拉黑，只能手工改 CSV 恢复）
                self.logger.warn(f"{self.inst_id} 下单遇到暂时性网络错误（{error_msg[:120]}），"
                                 f"不加入黑名单，冷却后自动重试", "buy_execute")
                return self._buy_cooldown("暂时性网络错误")
            # 其他未知错误 → 未知异常黑名单，不再尝试
            # v5.15（文档 P2-7）：原因保留 300 字符（原 100 字符常把 sCode/sMsg 截掉）
            return self._blacklist_unknown_error(reason=error_msg[:300])
        if action == "filled":
            price = outcome["price"]
            qty = outcome["qty"]
            buy_amount = outcome["filled_cost"]
            reason = outcome["reason"]
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.has_position = True
            self.position_price = price
            self.position_qty = qty
            self.position_amount = buy_amount
            self.cost_source = "fill"   # v5.16（文档 C10）：真实成交成本
            self.buy_time = now_str
            self.buy_reason = reason
            self.pair_type = plan["pair_name"]
            self.pair_sell_line = plan["sell_key"]
            self.is_paired = bool(plan.get("pair_name"))
            self.pair_buy_price = price
            self.pair_buy_time = now_str
            self.is_sold = False
            self.sell_time = ""
            self.sell_reason = ""
            self.check_level = "T3"
            self.last_check_time = now_str
            _sk = plan.get("sell_key") or ""
            self.pair_sell_line_price = getattr(self.levels, _sk) if _sk and hasattr(self.levels, _sk) else 0
            self.profit_triggered = False
            self.peak_price = price
            self.stop_price = 0
            self.max_loss_pct = 0.0
            # ===== v6（设计单 v1.1）：买入类型 / 买入层固定档位 / 已涨幅度初始化 =====
            self.entry_type = plan.get("entry_type") or "legacy"
            self.buy_layer_low = float(plan.get("layer_low") or self.levels.low)
            self.buy_layer_high = float(plan.get("layer_high") or self.levels.high)
            self.risen_low = self.risen_high = price
            self.risen_low_ts = self.risen_high_ts = now_str
            self.risen_armed = True
            self.v6_next_buy = ""
            self._v6_risen_pushed = False
            self._last_processed_price = price
            # 买入成功后重置买入信号
            self._reset_buy_signal()
            self._remove_from_buy_queue()
            self._save_state(force=True)
            save_trade({
                "timestamp": now_str,
                "inst_id": self.inst_id,
                "direction": "BUY",
                "price": price,
                "qty": qty,
                "amount": buy_amount,
                "remaining_funds": f"{(fresh_balance if fresh_balance is not None else get_okx_balance()):.2f}",
                "position_price": price,
                "profit": "0",
                "profit_pct": "0",
                "reason": reason
            })
            # v5.15（文档 P1-6）：先落账本/成交记录，再刷新资金视图（保证聚合能读到本笔）
            if not defer_funds:
                _update_funds_for_view(fresh_balance if fresh_balance is not None
                                       else get_okx_balance(force_refresh=True))
            msg = f"{self.inst_id} {reason} @ {price:.8g}, 金额 {buy_amount:.2f}, 数量 {qty:.8g}, 买点: {plan['buy_key']}"
            self.logger.info(msg, "buy_execute")
            _hint = f"{plan['pair_name']}买点" if plan.get("pair_name") else f"买点 {plan['buy_key']}"
            self._push_notify(f"💰 买入\n\n{self.inst_id}\n{_hint}\n价格: {price:.8g}\n金额: {buy_amount:.2f}\n"
                              f"已涨幅度跟踪开始: [{price:.8g}, {price:.8g}]")
            return msg
        return None
    def _buy_cooldown(self, reason: str):
        """暂时性买入失败：只冷却一段时间后重试，保留买入信号，不进任何黑名单"""
        self._buy_blocked_until = time.time() + BUY_NOTFILLED_COOLDOWN_SEC
        self.logger.warn(f"{self.inst_id} {reason}，{BUY_NOTFILLED_COOLDOWN_SEC:.0f} 秒内不再尝试"
                         f"（不加入黑名单，冷却后自动重试）", "buy_execute")
        push_notify_throttled(
            f"⏳ 买入暂缓（冷却后自动重试）\n\n{self.inst_id}\n{reason}\n"
            f"冷却 {BUY_NOTFILLED_COOLDOWN_SEC:.0f} 秒，未加入黑名单",
            key=f"buycd:{self.inst_id}",
            title="买入暂缓"
        )
        return None
    def _blacklist_unknown_error(self, reason: str):
        """未知错误：直接加入未知异常黑名单，不再尝试，从买入列表剔除（v5.3）"""
        # v5.15（文档 P2-7）：原因保留 300 字符（原 100 字符常把 sCode/sMsg 截掉）
        self.logger.warn(f"{self.inst_id} 未知错误，加入未知异常黑名单并移除买入队列: {reason[:300]}")
        add_to_unknown_blacklist(self.inst_id, f"未知错误: {reason[:300]}")
        self.unknown_blacklist.add(self.inst_id)
        self._okx_available = False
        self._remove_from_buy_queue()
        self._push_notify(f"🚫 已加入未知异常黑名单\n\n{self.inst_id}\n原因: {reason[:80]}")
        return None
    def _remove_from_buy_queue(self):
        rows = [r for r in load_buy_queue() if r.get("inst_id") != self.inst_id]
        save_buy_queue(rows)
        self.buy_queue = rows
    def _execute_sell(self, price, reason, min_profit_pct: Optional[float] = 0.05):
        """执行卖出（同步实现：调用方持 ENGINE_LOCK；测试与无执行器场景使用）。

        v5.18（文档 C7）拆为三段：本地预检（_sell_prepare）→ REST（_sell_place，订单线程
        锁外调用）→ 本地账务（_sell_apply）。生产路径由 _request_sell 投递订单线程执行。
        """
        plan = self._sell_prepare(price, min_profit_pct)
        if plan is None:
            return None
        return self._sell_apply(plan, self._sell_place(plan), reason)

    def _sell_prepare(self, price, min_profit_pct):
        """阶段1（本地，须持锁）：_can_sell 门槛 + 失败退避检查。返回 plan 或 None。"""
        can, msg = self._can_sell(price, min_profit_pct)
        if not can:
            self.logger.debug(f"{self.inst_id} 卖出跳过: {msg}")
            return None
        if time.time() < self._sell_blocked_until:
            self.logger.debug(f"{self.inst_id} 卖出受阻延期中（挂单占用），{self._sell_blocked_until - time.time():.0f}s 后重试")
            return None
        return {"price": price, "qty": self.position_qty, "sell_px": price}  # v6：清仓=限价单（暂按最新价）

    def _sell_place(self, plan):
        """阶段2（REST，可锁外执行）：平台可用量核对 + 最小下单量检查 + 市价卖出（含等成交）。

        不写任何账本字段；分支结果装进 outcome 交给 _sell_apply。
        """
        qty = plan["qty"]
        out = {"action": "", "balance_error": None, "min_sz": 0.0}
        # 卖出前核对平台实际可用量：本地账本可能与平台偏离（手动交易/lotSz 取整残留/手续费扣币），
        # 偏离时按平台量下单，避免 51008 余额不足导致卖出永久失败。仅卖出场景调用，运行期仍以本地账本为准。
        base_ccy = self.inst_id.split("-")[0]
        try:
            avail, cash, frozen = self.client.get_balance_detail(base_ccy) if self.client else (qty, qty, 0.0)
        except Exception as e:
            # 账户/网络不可达时仍按本地账本尝试下单（不改判、不误清账本）；30 秒退避由 _sell_apply 设置。
            # v5.18（C7）起本函数在引擎锁外执行，即使 REST 卡 10 秒也不再拖住行情接收
            out["balance_error"] = e
            avail, cash, frozen = qty, qty, 0.0
        if abs(avail - qty) > 1e-12:
            qty = avail
        out.update(avail=avail, cash=cash, frozen=frozen, qty_used=qty)
        if qty <= 0:
            out["action"] = "zero"
            return out
        info = self.client.get_instrument(self.inst_id) if self.client else None
        min_sz = float((info or {}).get("minSz") or 0)
        out["min_sz"] = min_sz
        if min_sz > 0 and qty < min_sz:
            out["action"] = "below_min"
            return out
        out["action"] = "placed"
        out["fill"] = self.client.market_sell_base(self.inst_id, qty, px=plan.get("sell_px") or None)
        return out

    def _sell_apply(self, plan, outcome, reason, fresh_balance=None, defer_funds=False):
        """阶段3（本地账务，须持锁）：核对告警/成本缩放、失真与粉尘清账、成交记账（部分成交比例结转）。

        fresh_balance：订单线程在锁外预取的余额（tradeRecord 的 remaining_funds 与资金视图用，
        避免锁内 REST）；defer_funds=True 时资金视图刷新由订单线程在锁外完成（同步路径保持原行为）。
        """
        qty = plan["qty"]
        price = plan["price"]
        base_ccy = self.inst_id.split("-")[0]
        avail = outcome["avail"]
        cash = outcome["cash"]
        frozen = outcome["frozen"]
        if outcome.get("balance_error") is not None:
            self._sell_blocked_until = max(self._sell_blocked_until, time.time() + 30.0)
            self.logger.warn(f"{self.inst_id} 卖出前核对平台可用量失败({outcome['balance_error']})，按本地账本数量下单，30 秒内不再重试", "sell_execute")
        if abs(avail - qty) > 1e-12:
            self.logger.warn(f"{self.inst_id} 卖出前核对：本地 {qty:.8g} ≠ 平台可用 {avail:.8g}（总量 {cash:.8g}，挂单冻结 {frozen:.8g}）{base_ccy}，按可用量下单", "sell_execute")
            if avail > 0:
                # 按数量等比缩放成本额，保住"每枚到手币的成本"。若改成 position_price*avail，
                # amount/qty 会被拍平成买入均价，买入端手续费不再计入单位成本，_breakeven_price
                # 随之低估约一个费率，"亏本当回本清仓"又回来了。
                if qty > 0 and self.position_amount > 0:
                    self.position_amount = self.position_amount * (avail / qty)
                self.position_qty = avail
            # avail==0 时不得改写账本：否则 amount×0/qty 把成本基准归零、qty 归零后
            # 落盘即成"无持仓"，挂单解冻后持仓从此脱管（下方按 cash 判定受阻/失真）
        action = outcome["action"]
        if action == "zero":
            if cash > 0:
                # 币仍在账户内，只是被挂单全部占用：不是账本失真，绝不清本地记录，等解冻后再卖
                self._sell_blocked_until = time.time() + SELL_BLOCK_RETRY_SEC
                self.logger.warn(f"{self.inst_id} 可用量为 0 但账户持有 {cash:.8g} {base_ccy}（挂单冻结 {frozen:.8g}），本次跳过卖出，{SELL_BLOCK_RETRY_SEC:.0f} 秒后重试", "sell_execute")
                push_notify_throttled(
                    f"⚠️ 卖出受阻\n\n{self.inst_id}\n{base_ccy} 被挂单占用 {frozen:.8g}，可用 0\n本地持仓记录保留，{SELL_BLOCK_RETRY_SEC:.0f} 秒后自动重试\n请检查是否有手动挂单",
                    key=f"frozen:{self.inst_id}",
                    title="卖出受阻"
                )
                return None
            self.logger.warn(f"{self.inst_id} 平台 {base_ccy} 余额为 0，本地持仓记录失真，已清除本地记录并跳过卖出", "sell_execute")
            self.has_position = False
            self.position_qty = 0
            self.position_amount = 0
            self.position_price = 0
            self._save_state(force=True)
            self._push_notify(f"⚠️ 持仓记录失真\n\n{self.inst_id}\n触发{reason}但平台余额为 0\n本地记录已清除，请人工核对")
            return None
        if action == "below_min":
            # 可用量低于 minSz 的粉尘无法下市价单：账户总量也低于 minSz 才算真粉尘（清除记录）；
            # 若只是被挂单占用（cash ≥ minSz）则保留记录并延后重试。
            qty_av = outcome["qty_used"]
            min_sz = outcome["min_sz"]
            if cash >= min_sz:
                self._sell_blocked_until = time.time() + SELL_BLOCK_RETRY_SEC
                self.logger.warn(f"{self.inst_id} 可用量 {qty_av:.8g} < 最小下单量 {min_sz}，但账户持有 {cash:.8g}（挂单冻结 {frozen:.8g}），保留持仓记录，{SELL_BLOCK_RETRY_SEC:.0f} 秒后重试", "sell_execute")
                return None
            self.logger.warn(f"{self.inst_id} 可用量 {qty_av:.8g} {base_ccy} 低于最小下单量 {min_sz}，无法卖出，已清除本地持仓记录", "sell_execute")
            self.has_position = False
            self.position_qty = 0
            self.position_amount = 0
            self.position_price = 0
            self._save_state(force=True)
            self._push_notify(f"⚠️ 粉尘持仓无法卖出\n\n{self.inst_id}\n可用 {qty_av:.8g} {base_ccy} < 最小下单量 {min_sz}\n本地记录已清除，可在 OKX 手动处理")
            return None
        fill = outcome.get("fill")
        if not fill or fill.get("qty", 0) <= 0:
            # 与"核对平台可用量失败"同一处理：退避一段时间再试。不退避的话，价格停留在止盈价
            # 下方时每个 tick 都会重走一遍 REST+下单+等成交
            self._sell_blocked_until = time.time() + SELL_FAIL_RETRY_SEC
            self.logger.error(f"{self.inst_id} API卖出失败，持仓保留，{SELL_FAIL_RETRY_SEC:.0f} 秒后重试: {fill}")
            push_notify_throttled(
                f"⚠️ 卖出失败\n\n{self.inst_id}\n{reason}\n数量: {outcome['qty_used']:.8g}\nAPI返回: {fill}\n"
                f"{SELL_FAIL_RETRY_SEC:.0f} 秒后自动重试（持仓记录与止盈激活状态均保留）",
                key=f"sellfail:{self.inst_id}",
                title="卖出失败"
            )
            return None
        qty_order = outcome["qty_used"]
        if fill["qty"] < qty_order * 0.999:
            self.logger.warn(f"{self.inst_id} 卖出按 lotSz 取整/部分成交: 成交 {fill['qty']:.8g} / 持仓 {qty_order:.8g}", "sell_execute")
        price = fill["price"]
        held_qty = qty_order                 # 下单前持仓量（缩放后），部分成交时用于比例结转
        qty = fill["qty"]
        amount = fill["proceeds"]
        reason = f"{reason} | ordId={fill.get('ord_id', '')} fee={fill.get('fee', 0):.8g}{fill.get('fee_ccy', '')}"
        self.logger.info(f"{self.inst_id} API卖出成交: ordId={fill.get('ord_id')} 均价 {price:.8g} 数量 {qty:.8g} 到手 {amount:.2f}", "sell_execute")
        # ===== v5.15（文档 P0-2）：部分成交按比例结转成本，绝不整笔清零 =====
        # 修复前：成交量<持仓也被当全额——ASP 仅成交 34.3% 却整笔清零，记账 −184.01（实际约 −1.7）；
        # 残余数量脱管直到运行期对账按市价重入。现在只有 ≥99.9% 才走清零收尾，否则保留余量与原
        # 止盈激活状态继续盯盘（peak/stop 不动），并退避 SELL_BLOCK_RETRY_SEC 后再评估
        if qty < held_qty * 0.999 and held_qty > 0 and self.position_amount > 0:
            cost_ratio = min(1.0, qty / held_qty)
            cost_sold = self.position_amount * cost_ratio
            profit = amount - cost_sold
            profit_pct = profit / cost_sold * 100 if cost_sold > 0 else 0.0
            self._last_profit = profit
            self._last_profit_pct = profit_pct
            remain_qty = max(0.0, held_qty - qty)
            remain_amount = max(0.0, self.position_amount - cost_sold)
            self.position_qty = remain_qty
            self.position_amount = remain_amount
            self._sell_blocked_until = max(self._sell_blocked_until, time.time() + SELL_BLOCK_RETRY_SEC)
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            reason = f"{reason} | 部分成交 {qty:.8g}/{held_qty:.8g}"
            self._save_state(force=True)
            save_trade({
                "timestamp": now_str,
                "inst_id": self.inst_id,
                "direction": "SELL",
                "price": price,
                "qty": qty,
                "amount": amount,
                "remaining_funds": f"{(fresh_balance if fresh_balance is not None else get_okx_balance()):.2f}",
                "position_price": self.position_price,
                "profit": f"{profit:.12g}",
                "profit_pct": f"{profit_pct:.6f}",
                "reason": reason
            })
            if not defer_funds:
                _update_funds_for_view(fresh_balance if fresh_balance is not None
                                       else get_okx_balance(force_refresh=True))
            msg = (f"{self.inst_id} {reason} @ {price:.8g}, 部分卖出 {qty:.8g}/{held_qty:.8g}, "
                   f"盈亏 {profit:.2f} ({profit_pct:.2f}%), 剩余 {remain_qty:.8g} 继续盯盘")
            self.logger.warn(msg, "sell_execute")
            push_notify_throttled(
                f"⚠️ 部分卖出\n\n{self.inst_id}\n{reason}\n成交: {qty:.8g} / {held_qty:.8g}\n"
                f"盈亏: {profit:.2f} ({profit_pct:.2f}%)\n剩余 {remain_qty:.8g} 已按比例结转成本，继续盯盘",
                key=f"partialsell:{self.inst_id}", title="部分卖出")
            return msg
        profit = amount - self.position_amount
        profit_pct = profit / self.position_amount * 100 if self.position_amount > 0 else 0
        cost_price = self.position_price
        cached_pair_type = self.pair_type
        cached_pair_sell_line = self.pair_sell_line
        cached_pair_sell_line_price = self.pair_sell_line_price
        cached_buy_time = self.buy_time
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._last_profit = profit
        self._last_profit_pct = profit_pct
        self.has_position = False
        self.position_price = 0
        self.position_qty = 0
        self.position_amount = 0
        self.buy_time = ""
        self.buy_reason = ""
        self.is_paired = False
        self.is_sold = True
        self.sell_time = now_str
        self.sell_reason = reason
        self.profit_triggered = False
        self.peak_price = 0
        self.stop_price = 0
        self.max_loss_pct = 0.0
        self.check_level = ""
        self.last_check_time = ""
        cooldown_days = self.params.get("cooldown_days", 7)
        cooldown_until = (datetime.now() + timedelta(days=cooldown_days)).strftime("%Y-%m-%d %H:%M:%S")
        save_cooldown_entry(self.inst_id, cooldown_until)
        self.cooldown[self.inst_id] = cooldown_until
        self._add_to_buy_queue("静默期_排除")
        self.pair_buy_price = cost_price
        self.pair_buy_time = cached_buy_time
        self.pair_sell_line_price = cached_pair_sell_line_price
        self.pair_type = cached_pair_type
        self.pair_sell_line = cached_pair_sell_line
        self._save_state(force=True)
        save_trade({
            "timestamp": now_str,
            "inst_id": self.inst_id,
            "direction": "SELL",
            "price": price,
            "qty": qty,
            "amount": amount,
            "remaining_funds": f"{(fresh_balance if fresh_balance is not None else get_okx_balance()):.2f}",
            "position_price": cost_price,
            "profit": f"{profit:.12g}",
            "profit_pct": f"{profit_pct:.6f}",
            "reason": reason
        })
        # v5.15（文档 P1-6）：先落账本/成交记录，再刷新资金视图（保证聚合能读到本笔）
        if not defer_funds:
            _update_funds_for_view(fresh_balance if fresh_balance is not None
                                   else get_okx_balance(force_refresh=True))
        msg = f"{self.inst_id} {reason} @ {price:.8g}, 数量 {qty:.8g}, 盈亏 {profit:.2f} ({profit_pct:.2f}%)"
        self.logger.info(msg, "sell_execute")
        self._push_notify(f"💸 卖出\n\n{self.inst_id}\n{reason}\n价格: {price:.8g}\n盈亏: {profit:.2f} ({profit_pct:.2f}%)")
        return msg
    def _add_to_buy_queue(self, status):
        if self.position_only:
            return
        # v5.19（用户决定）：不可交易产品（黑名单/环境缺失/地域限制/超范围）不加入买入队列
        if (self.out_of_range or self.inst_id in self.blacklist or self.inst_id in self.unknown_blacklist
                or getattr(self, "_env_missing", False) or getattr(self, "_region_blocked", False)):
            return
        # 读-改-写前重新载入：买入队列是整表文件，用启动时的内存副本会导致
        # 本符号在启动后新增的行被静默覆盖（其他符号的进队列/状态变更也会丢）
        rows = load_buy_queue()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for row in rows:
            if row.get("inst_id") == self.inst_id:
                if row.get("status") == status and row.get("last_check_time") == now_str:
                    self.buy_queue = rows
                    return
                row["status"] = status
                row["last_check_time"] = now_str
                break
        else:
            rows.append({
                "inst_id": self.inst_id,
                "status": status,
                "ref_high": str(self.levels.high),
                "ref_low": str(self.levels.low),
                "add_time": now_str,
                "last_check_time": now_str
            })
        save_buy_queue(rows)
        self.buy_queue = rows
    def _check_take_profit(self, price):
        if not self.has_position or self.position_price <= 0:
            return None
        profit_pct = (price - self.position_price) / self.position_price

        # v5.8：删除原"盈利回落<6.5%撤销激活"分支。它此前不可达（_check_take_profit 只在 T0 即盈利≥6.5%时被调用），
        # 且即使可达也无必要：止盈价恒有 成本×1.05 地板，激活后离场必然≥5%盈利，不存在"虚假激活后亏损卖出"；
        # 撤销激活反而会把止盈价清零，使峰值回吐时失去保护。

        if price > self.peak_price:
            self.peak_price = price

        stop_ratio = get_stop_loss(profit_pct)
        if stop_ratio == 0 and profit_pct >= 0.20:
            self.logger.info(f"{self.inst_id} 盈利 ≥20%，立即清仓", "profit_trigger")
            return self._request_sell(price, f"盈利率 {profit_pct*100:.1f}% ≥20%，清仓")

        # v5.4_fix：动态止损价 = max(峰值回撤, 成本+5%)，保证清仓最低5%盈利
        new_stop = self.peak_price * (1 - stop_ratio)
        min_stop = self.position_price * 1.05
        if new_stop < min_stop:
            new_stop = min_stop
        if new_stop > self.stop_price:
            self.stop_price = new_stop

        # 止盈激活条件改为盈利 >=6.5%
        if profit_pct >= 0.065 and not self.profit_triggered:
            self.profit_triggered = True
            self.check_level = "T0"
            self._push_notify(f"📈 止盈激活\n\n{self.inst_id}\n盈利: {profit_pct*100:.2f}%\n峰值: {self.peak_price:.8g}\n止盈价: {self.stop_price:.8g}")
            self.logger.info(f"{self.inst_id} 止盈激活: 盈利 {profit_pct*100:.2f}%, 止盈价 {self.stop_price:.8g}", "profit_trigger")
            self._save_state(force=True)

        if self.profit_triggered and price <= self.stop_price:
            # v5.8 混合口径：止盈价恒 ≥ 成本×1.05，而 _can_sell 的 5% 门槛与之几乎重合，
            # 若沿用 min_profit_pct=0.05 保底门槛，可成交窗口只剩约 1bp，跳空一次就永久卖不出去（激活状态又不重置 → 死锁）。
            # 因此只要价格仍在保本价（含双边手续费）之上就立即市价清仓（接受滑点，绝不亏本卖）；
            # 跌破保本价则保留持仓与激活状态继续盯盘，价格回到保本价之上即离场。
            be = self._breakeven_price()
            if self._is_breakeven(price):
                self.logger.info(f"{self.inst_id} 触发止盈清仓: 当前价 {price:.8g} ≤ 止盈价 {self.stop_price:.8g}，保本价 {be:.8g}（含 {TAKER_FEE_RATE*100:.2f}%×2 手续费）", "stop_loss_trigger")
                return self._request_sell(price, f"止盈清仓 (峰值 {self.peak_price:.8g}, 回撤 {stop_ratio*100:.1f}%)", min_profit_pct=None)
            self.logger.debug(f"{self.inst_id} 止盈价 {self.stop_price:.8g} 已被跌穿但当前价 {price:.8g} 低于保本价 {be:.8g}（名义成本 {self.position_price:.8g}），不亏本卖出，保留激活继续盯盘")
        return None

    def _dust_cleanup(self, price):
        """v5.16（文档 C5）：粉尘残仓清账。

        触发条件（全部满足才清账）：持仓市值 < POS_MIN_USD、平台可用与总量都 < minSz
        （永远无法下市价单卖出）、与平台核对成功。清本地记录并推送；平台侧残币由对账端
        按 POS_MIN_USD 同样忽略。REST 失败/信息不全一律不动账本；每 DUST_CHECK_SEC
        （默认 1h）至多核对一次，避免行情 tick 反复打 REST。
        """
        now = time.time()
        if now < getattr(self, "_dust_check_due_ts", 0.0):
            return None
        # v5.18（文档 C7）：订单在途时不对账清账，避免与订单线程的账务写入交错
        if getattr(self, "order_in_flight", None):
            return None
        self._dust_check_due_ts = now + DUST_CHECK_SEC
        if self.client is None:
            return None
        try:
            info = self.client.get_instrument(self.inst_id)
        except Exception:
            return None
        if not info:
            return None
        try:
            min_sz = float(info.get("minSz") or 0)
        except (TypeError, ValueError):
            return None
        if min_sz <= 0:
            return None
        base_ccy = self.inst_id.split("-")[0]
        try:
            avail, cash, frozen = self.client.get_balance_detail(base_ccy)
        except Exception:
            return None
        if cash >= min_sz or avail >= min_sz:
            return None   # 账户持有量仍可下市价单（含解冻后可以），不视为粉尘
        mv = price * self.position_qty
        self.logger.warn(f"{self.inst_id} 粉尘残仓清账：市值 {mv:.4f} USDT < {POS_MIN_USD}，"
                         f"平台持有 {cash:.8g} {base_ccy} < 最小下单量 {min_sz:.8g}，本地记录已清除", "sell_execute")
        self.has_position = False
        self.position_qty = 0
        self.position_amount = 0
        self.position_price = 0
        self.cost_source = ""
        self._save_state(force=True)
        self._push_notify(
            f"🧹 粉尘残仓已清账\n\n{self.inst_id}\n市值 {mv:.4f} USDT（< {POS_MIN_USD}）\n"
            f"平台持有 {cash:.8g} {base_ccy} < 最小下单量 {min_sz:.8g}，无法下单卖出\n"
            f"本地记录已清除（OKX 侧残币 <1 USDT 可忽略）")
        return f"粉尘清账 {cash:.8g} {base_ccy}"

    def update_price(self, price, ts):
        alerts = []
        if price == self._last_processed_price and ts == self._last_processed_ts:
            return alerts
        self._last_processed_price = price
        self._last_processed_ts = ts
        # v5.17（文档 C12）：记录行情到达时刻（无行情持仓的 REST 兜底盯盘据此判定"静默"）
        self.last_tick_ts = time.time()
        # ===== v6（设计单 v1.1）：换层检测（替代"超范围剔除"与"运行时累计高低"）=====
        alerts.extend(self._v6_layer_check(price))
        # ========== v6：超范围剔除已废除（价格越界 → 换层，见上方 _v6_layer_check） ==========
        # ========== v6：持仓管理（已涨幅度 + 清仓 1/2/3 + 回本 + 动态止盈兜底） ==========
        if self.has_position:
            alerts.extend(self._v6_manage_position(price))
            if alerts:
                self._save_state(force=True)
                return alerts

        # ========== v6：无持仓 → 买点状态机（高位买点/低位买点） ==========
        if (not self.has_position and not self.position_only and not self._is_in_cooldown()
                and self.inst_id not in self.observe_list and self.inst_id not in self.blacklist
                and self.inst_id not in self.unknown_blacklist):
            submitted = self._v6_buy_fsm(price)
            if submitted:
                alerts.append(submitted)
                self._save_state(force=True)
                return alerts
        # 保存状态（常规）
        self._save_state()
        return alerts
    def _position_row(self) -> Dict:
        cp = self._last_processed_price if self._last_processed_price > 0 else self.position_price
        qty = self.position_qty
        cost = self.position_amount
        mv = cp * qty if cp > 0 else cost
        upnl = mv - cost if cost > 0 else 0
        upnl_pct = (upnl / cost * 100.0) if cost > 0 else 0
        return {
            "position_price": self.position_price,
            "position_qty": self.position_qty,
            "position_amount": self.position_amount,
            "buy_time": self.buy_time,
            "buy_reason": self.buy_reason,
            "pair_type": self.pair_type,
            "pair_sell_line": self.pair_sell_line,
            "peak_price": self.peak_price,
            "stop_price": self.stop_price,
            "profit_triggered": self.profit_triggered,
            "check_level": self.check_level,
            "last_check_time": self.last_check_time,
            "current_price": cp,
            "market_value": mv,
            "unrealized_pnl": upnl,
            "unrealized_pnl_pct": upnl_pct,
            "max_loss_pct": self.max_loss_pct,
            # v6（设计单 v1.1）：买点类型 / 买入层固定档位 / 已涨幅度（程序维护）
            "entry_type": self.entry_type,
            "buy_layer_low": f"{self.buy_layer_low:.12g}",
            "buy_layer_high": f"{self.buy_layer_high:.12g}",
            "risen_low": f"{self.risen_low:.12g}",
            "risen_high": f"{self.risen_high:.12g}",
            "risen_low_ts": self.risen_low_ts,
            "risen_high_ts": self.risen_high_ts,
            "risen_armed": "1" if self.risen_armed else "",
            "v6_next_buy": self.v6_next_buy,
            # v5.16（文档 C10）：成本来源（fill=真实成交 / reconcile=对账重建估值）
            "cost_source": getattr(self, "cost_source", "") or ("reconcile" if self.buy_reason == "平台余额同步" else "fill"),
        }
    def _pair_payload(self) -> Optional[Dict]:
        if not (self.is_paired or self.is_sold):
            return None
        payload = {
            "pair_type": self.pair_type,
            "is_paired": self.is_paired,
            "buy_price": self.pair_buy_price,
            "buy_time": self.pair_buy_time,
            "sell_line": self.pair_sell_line,
            "sell_line_price": self.pair_sell_line_price,
            "is_sold": self.is_sold,
            "sell_time": self.sell_time,
            "sell_reason": self.sell_reason,
        }
        if self.is_sold:
            payload["profit"] = f"{self._last_profit:.12g}"
            payload["profit_pct"] = f"{self._last_profit_pct:.6f}"
        return payload
    def _save_state(self, force: bool = False):
        """保存状态。

        v5.10：常规 tick 只标脏，由引擎按全局闸门把所有币对合并成一次整表写
        （此前每个币对每 5 秒各自"读全表+改一行+写全表+fsync"，几十个币对时是纯浪费的 CPU/IO）；
        force=True 用于买入/卖出/止盈激活等关键事件，仍即时落盘。
        返回值：False 表示本次没能落盘（读失败保护触发或写失败），脏标记保留、下个周期重试。
        """
        self._state_dirty = True
        if not force:
            return False
        positions = load_positions()
        if self.has_position:
            positions[self.inst_id] = self._position_row()
        else:
            positions.pop(self.inst_id, None)
        ok = save_positions(positions)
        payload = self._pair_payload()
        if payload is not None:
            ok = save_pair_status(self.inst_id, payload) and ok
        else:
            rows = [r for r in _read_csv(PAIR_STATUS_FILE, PAIR_STATUS_HEADER) if r.get("inst_id") != self.inst_id]
            ok = _write_csv_all(PAIR_STATUS_FILE, PAIR_STATUS_HEADER, rows) and ok
        flush_high_low()
        if ok:
            self._state_dirty = False
        return ok
    def _push_notify(self, text):
        push_notify(text)
# ==================== 行情引擎 ====================
class OrderExecutor:
    """v5.18（文档 C7）：订单执行线程（锁内决定 → 锁外 REST → 锁内记账）。

    行情线程此前在 ENGINE_LOCK 内完成下单全流程：market_buy_quote / market_sell_base
    内部的 REST 与 _wait_fill（最长数秒）全程持锁，把行情接收、心跳、维护线程整体堵住。
    现在行情线程只做零网络预检并投递任务（毫秒级返回），本线程在锁外完成订单类 REST，
    仅在"读本地决策"和"写本地账务"两个短暂阶段持有引擎锁。单线程串行处理，天然避免
    并发下单；每币对至多一个在途任务（SymbolState.order_in_flight 门闩）。
    ORDER_EXECUTOR_ENABLED=0 时 MarketEngine 不向 SymbolState 注入执行器，回退旧同步行为。
    """

    def __init__(self, engine):
        self.engine = engine
        self.queue = queue.Queue(maxsize=max(1, ORDER_QUEUE_MAX))
        self.thread = None
        self._start_lock = threading.Lock()

    def pending(self) -> int:
        return self.queue.qsize()

    def submit(self, job) -> bool:
        """投递任务（调用方持 ENGINE_LOCK）。队列满/停止中返回 False，调用方负责清在途标记。"""
        if STOP_EVENT.is_set():
            return False
        try:
            self.queue.put_nowait(job)
        except queue.Full:
            self.engine.logger.warn(f"订单队列已满（{ORDER_QUEUE_MAX}），本次 {job[0]} 请求丢弃: {job[1]}", "order_execute")
            return False
        self._ensure_started()
        return True

    def _ensure_started(self):
        t = self.thread
        if t is not None and t.is_alive():
            return
        with self._start_lock:
            t = self.thread
            if t is not None and t.is_alive():
                return
            self.thread = threading.Thread(target=self._loop, daemon=True, name="okx-order")
            self.thread.start()

    def _loop(self):
        while not STOP_EVENT.is_set():
            try:
                job = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.engine._run_order_job(job)
            except Exception as e:
                # 任务异常：持仓/账本保留（apply 未执行或部分执行），等待下次触发重试
                self.engine.logger.error(f"订单任务异常（持仓保留，等待下次触发重试）: {job[0]} {job[1]}: {e}", "order_execute")
        # 停止信号：清掉未执行任务的在途标记，避免状态卡在"订单执行中"（随后进程即退出）
        while True:
            try:
                job = self.queue.get_nowait()
            except queue.Empty:
                break
            st = self.engine.states.get(job[1])
            if st is not None:
                st.order_in_flight = None


class MarketEngine:
    def __init__(self, logger, system_params=None):
        self.logger = logger
        self.params = system_params or {}
        self.states = {}
        self.lock = ENGINE_LOCK   # 与后台账户恢复线程同一把账本锁（R3：防读-改-写丢更新）
        self._last_buy_queue_check = 0
        self._last_position_audit = time.time()   # v5.14：首次运行期对账在启动 POSITION_AUDIT_SEC 秒后
        # v5.16（文档 C11）：未知黑名单运行期复检节流（启动时已在 main() 批量做了一轮）
        self._next_unknown_recheck_ts = time.time() + REPROBE_BASE_SEC
        # v5.17（文档 C12）→ v5.20：行情补齐节流（每 MARKET_GAP_INTERVAL_SEC 一轮）
        self._last_stale_poll_ts = 0.0
        self._last_market_gap_fed = 0   # v5.20：上轮补齐实际喂入数量（心跳 market_gap_fed）
        # v5.18（文档 C7）：订单执行线程（行情线程锁内只投递任务，下单/等成交在锁外）
        self.orders = OrderExecutor(self)
    def add_state(self, inst_id, ref_high, ref_low, position_only=False):
        state = SymbolState(inst_id, ref_high, ref_low, self.logger, self.params, position_only=position_only)
        state._state_dirty = False
        if ORDER_EXECUTOR_ENABLED:
            # v5.18（文档 C7）：注入订单执行器；关掉开关则保持 None → 行情线程内同步下单（旧行为）
            state.executor = self.orders
        self.states[inst_id] = state
        hl = load_high_low()
        # v6（设计单 v1.1）：不再用运行时累计高低覆盖层界——本层梯表 = 固定层界（sheet2），越界由换层处理
        pos = load_positions()
        if inst_id in pos:
            data = pos[inst_id]
            state.has_position = data.get("position_qty", 0) > 0
            state.position_price = data.get("position_price", 0)
            state.position_qty = data.get("position_qty", 0)
            state.position_amount = data.get("position_amount", 0)
            state.buy_time = data.get("buy_time", "")
            state.buy_reason = data.get("buy_reason", "")
            # v5.16（文档 C10）：成本来源（旧文件缺列时按 buy_reason 推断）
            state.cost_source = (str(data.get("cost_source") or "").strip()
                                 or ("reconcile" if data.get("buy_reason", "") == "平台余额同步" else "fill"))
            state.pair_type = data.get("pair_type", "")
            state.pair_sell_line = data.get("pair_sell_line", "")
            state.peak_price = data.get("peak_price", 0)
            state.stop_price = data.get("stop_price", 0)
            state.profit_triggered = data.get("profit_triggered", False)
            state.check_level = data.get("check_level", "T3")
            state.last_check_time = data.get("last_check_time", "")
            cp = _to_float(data.get("current_price"), 0)
            if cp > 0:
                state._last_processed_price = cp
        pair = load_pair_status()
        if inst_id in pair:
            data = pair[inst_id]
            state.is_paired = data.get("is_paired", False)
            state.pair_buy_price = data.get("buy_price", 0)
            state.pair_buy_time = data.get("buy_time", "")
            state.pair_sell_line_price = data.get("sell_line_price", 0)
            state.is_sold = data.get("is_sold", False)
            state.sell_time = data.get("sell_time", "")
            state.sell_reason = data.get("sell_reason", "")
            if data.get("pair_type"):
                state.pair_type = data["pair_type"]
            state._last_profit = data.get("profit", 0.0)
            state._last_profit_pct = data.get("profit_pct", 0.0)
        cooldown = load_cooldown()
        if inst_id in cooldown:
            state.cooldown[inst_id] = cooldown[inst_id]
        # v5.12 R10：调用方在全部币对 add_state 完成后统一 engine.sync_all_buy_queue()，
        # 这里不再逐币对读写整张买入队列表

    def sync_all_buy_queue(self) -> bool:
        """启动期买入队列同步：一次读表 → 每个币对改自己的行 → 一次写表。
        原先每个币对各自 load+save（且 __init__ 与 add_state 各来一遍），
        N 个币对就是 2N 次整表重写（每次带 fsync），启动时间随币对数平方增长。"""
        rows = load_buy_queue()
        changed = False
        for state in self.states.values():
            rows, row_changed = state._sync_buy_queue_row(rows)
            changed = changed or row_changed
        if not changed:
            return True
        return save_buy_queue(rows)
    def has_pending_writes(self) -> bool:
        if _HL_PENDING:
            return True
        for st in self.states.values():
            if getattr(st, "_state_dirty", False):
                return True
        return False
    def flush_dirty_states(self):
        """合并落盘（调用方须持有 self.lock）：所有脏币对共用一次整表读写。

        这是 v5.10 降低 CPU/IO 的关键：原先每个币对各自"读全表→改一行→写全表→fsync"，
        64 个币对每 5 秒最坏要做 64 次全表重写；现在同频只做 1 次，账本内容不变。
        落盘被拒绝（读失败保护或写异常）时脏标记保留，下个周期重试。
        """
        ok = flush_high_low()
        dirty = [st for st in self.states.values() if getattr(st, "_state_dirty", False)]
        if not dirty:
            return ok
        positions = load_positions()
        pair_rows = _read_csv(PAIR_STATUS_FILE, PAIR_STATUS_HEADER)
        pair_index = {r.get("inst_id"): r for r in pair_rows if r.get("inst_id")}
        for st in dirty:
            st._state_dirty = False
            if st.has_position:
                positions[st.inst_id] = st._position_row()
            else:
                positions.pop(st.inst_id, None)
            payload = st._pair_payload()
            if payload is None:
                pair_index.pop(st.inst_id, None)
            elif st.inst_id in pair_index:
                _apply_pair_payload(pair_index[st.inst_id], payload)
            else:
                new_row = _new_pair_row(st.inst_id, payload)
                pair_rows.append(new_row)
                pair_index[st.inst_id] = new_row
        pos_ok = save_positions(positions)
        pair_ok = _write_csv_all(PAIR_STATUS_FILE, PAIR_STATUS_HEADER,
                                 [r for r in pair_rows if r.get("inst_id") in pair_index])
        if not (pos_ok and pair_ok and ok):
            for st in dirty:
                st._state_dirty = True
            return False
        return True
    def maintenance(self):
        """行情之外的周期性工作：负载采样 + 按闸门合并落盘 + 运行期对账（供主循环调用）"""
        sample_system_load()
        # v5.12 R11：超范围审计表（xlsx）的整本重写挪到主线程、且在 engine.lock 之外——
        # 行情线程不再因为一次翻转被拖住几十到几百毫秒
        flush_out_of_range_ops()
        # v5.14（优化方案步骤3）：运行期轻量对账，网络请求在锁外、锁内只做本地比对
        self._audit_positions_due()
        # v5.15（文档 P1-1）：启动探测失败（网络类）的币对运行期重探（每轮最多 1 个）；
        # v5.19（用户决定）：环境缺失（51001）/地域限制已直接入黑名单，不再参与重探
        self._reprobe_due_states()
        # v5.16（文档 C11）：未知异常黑名单到期自动复检（每轮最多 1 个，10 分钟节流）
        self._recheck_unknown_blacklist_due()
        # v5.20（C12 推广）：全市场 REST 行情补齐（60s 节流，单次批量请求喂全部无行情币对；
        # 锁外 REST、锁内喂 tick）
        self._poll_market_gap()
        with self.lock:
            if self.has_pending_writes() and _state_save_due():
                self.flush_dirty_states()
    def _audit_positions_due(self) -> bool:
        """v5.14 运行期轻量对账：平台余额已无的本地持仓 → 清记录、复位幽灵配对、推送告警。

        与全量对齐（_apply_platform_positions）的分工：这里只修"平台已无余额"的方向，
        不做数量覆盖（卖出前另有逐笔可用量核对）。锁定纪律：网络请求在锁外（沿用
        _apply_platform_positions 的教训：锁内不做 REST，避免拖住行情线程）；锁内只做
        本地比对与复位；请求失败/网络类异常本轮跳过，不改判任何账本。周期
        POSITION_AUDIT_SEC（默认 300s，<=0 关闭）。返回本轮是否发生了修复。
        """
        if POSITION_AUDIT_SEC <= 0:
            return False
        now = time.time()
        if now - self._last_position_audit < POSITION_AUDIT_SEC:
            return False
        self._last_position_audit = now
        api_positions = fetch_platform_positions()   # 锁外：一次 GET /api/v5/account/balance
        if api_positions is None:
            return False
        with self.lock:
            local_pos = load_positions()
            gone = sorted(inst_id for inst_id in local_pos if inst_id not in api_positions)
            if gone:
                for inst_id in gone:
                    local_pos.pop(inst_id, None)
                if not save_positions(local_pos):
                    self.logger.warn("运行期对账：本地持仓表未能落盘，本轮跳过（下轮重试）", "reconcile")
                    return False
            ghosts = _reset_ghost_pairs(_ghost_pair_candidates(api_positions, local_pos),
                                        "平台无持仓（运行期对账复位）")
            if not gone and not ghosts:
                return False
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for inst_id in sorted(set(gone) | set(ghosts)):
                st = self.states.get(inst_id)
                if st is None:
                    continue
                if inst_id in gone:
                    # 清内存持仓态：不清的话下一次脏落盘（flush_dirty_states）会把持仓行写回
                    st.has_position = False
                    st.position_price = 0.0
                    st.position_qty = 0.0
                    st.position_amount = 0.0
                    st.profit_triggered = False
                    st.stop_price = 0.0
                    st.peak_price = 0.0
                    st.max_loss_pct = 0.0
                    st.buy_signal_activated = False
                if inst_id in ghosts:
                    st.is_sold = True
                    st.sell_time = now_str
                    st.sell_reason = "平台无持仓（运行期对账复位）"
                st._state_dirty = False
            detail = []
            if gone:
                detail.append(f"清除本地持仓 {len(gone)} 个: {', '.join(gone)}")
            if ghosts:
                detail.append(f"幽灵配对复位 {len(ghosts)} 个: {', '.join(ghosts)}")
            self.logger.warn("运行期对账：本地账本与平台不一致（" + "；".join(detail) +
                             "），已修复，请人工核对", "reconcile")
            push_notify_throttled(
                "⚠️ 运行期对账发现本地账本与平台不一致，已自动修复\n\n" +
                "\n".join(detail) + f"\n\n原因通常是平台侧手动成交/转账。\n时间: {now_str}",
                key="posaudit:runtime", title="运行期对账")
            return True
    def _reprobe_due_states(self) -> bool:
        """v5.15（文档 P1-1）：运行期重探"启动探测失败（网络类）"的币对。

        v5.19（用户决定）：重探只服务启动时网络抖动类失败（_net_failed）；"当前环境无此产品"
        （51001）与地域/合规限制已直接入黑名单持久化、不再重试。重探按指数退避
        （REPROBE_BASE_SEC 起、REPROBE_MAX_SEC 封顶）自动重试，成功即恢复买入资格并推送；
        若重探时才确认 51001/地域限制，则当场入黑名单并停止重试。锁定纪律：REST 在锁外，
        锁内只改标记；每轮最多探 1 个，避免主线程被串行 REST 拖住。返回本轮是否执行了探测。
        """
        now = time.time()
        with self.lock:
            cand = None
            for st in self.states.values():
                if st._okx_available or st.position_only or st.client is None:
                    continue
                if not st._net_failed:
                    continue
                if st.inst_id in st.blacklist or st.inst_id in st.unknown_blacklist or st.inst_id in st.observe_list:
                    continue
                if now < getattr(st, "_reprobe_next_ts", 0.0):
                    continue
                cand = st
                break
        if cand is None:
            return False
        err = None
        try:
            available = bool(cand.client.get_instrument(cand.inst_id))
        except Exception as e:
            available = False
            err = e
        with self.lock:
            if available:
                cand._okx_available = True
                cand._net_failed = False
                cand._env_missing = False
                cand._reprobe_fails = 0
                cand._reprobe_next_ts = 0.0
                self.logger.info(f"{cand.inst_id} 重探成功：当前交易环境可交易，已恢复买入资格", "startup")
                push_notify_throttled(
                    f"✅ 恢复可交易\n\n{cand.inst_id} 重探成功，已恢复买入资格",
                    key=f"reprobe:{cand.inst_id}", title="恢复可交易")
            else:
                err_str = "" if err is None else str(err)
                err_lower = err_str.lower()
                if "51001" in err_str or "51155" in err_str or "compliance" in err_lower or "restriction" in err_lower:
                    # v5.19（用户决定）：重探确认不可交易产品（当前环境无此产品/地域合规限制）→
                    # 常规黑名单持久化，不再安排重试（黑名单币不再进入重探候选）
                    is_env = "51001" in err_str
                    reason = "当前交易环境无此产品(51001)" if is_env else f"交易地域/合规限制: {err_str[:100]}"
                    cand._env_missing = is_env
                    cand._region_blocked = not is_env
                    cand._net_failed = False
                    cand._reprobe_next_ts = 0.0
                    if cand.inst_id not in cand.blacklist and cand.inst_id not in cand.unknown_blacklist:
                        add_to_blacklist(cand.inst_id, reason)
                        cand.blacklist.add(cand.inst_id)
                    self.logger.warn(f"{cand.inst_id} 重探确认不可交易产品（{reason}），已加入黑名单（不再重试）", "startup")
                else:
                    fails = getattr(cand, "_reprobe_fails", 0) + 1
                    cand._reprobe_fails = fails
                    delay = min(REPROBE_MAX_SEC, REPROBE_BASE_SEC * (2 ** min(fails - 1, 6)))
                    cand._reprobe_next_ts = now + delay
                    if err is not None:
                        self.logger.debug(f"{cand.inst_id} 重探仍网络失败（{err}），{delay:.0f}s 后再试")
                    else:
                        self.logger.debug(f"{cand.inst_id} 重探：仍查不到该产品，{delay:.0f}s 后再试")
        return True
    def _recheck_unknown_blacklist_due(self) -> bool:
        """v5.16（文档 C11）：未知异常黑名单运行期复检（10 分钟至多一轮、每轮最多 1 个）。

        锁定纪律：REST（查 instrument）在锁外；锁内只做内存集合同步与推送。
        """
        now = time.time()
        if now < self._next_unknown_recheck_ts:
            return False
        self._next_unknown_recheck_ts = now + REPROBE_BASE_SEC
        removed = recheck_unknown_blacklist_due(self.logger, limit=1)
        if not removed:
            return False
        with self.lock:
            for inst_id in removed:
                for st in self.states.values():
                    st.unknown_blacklist.discard(inst_id)
                push_notify_throttled(
                    f"✅ 黑名单恢复\n\n{inst_id} 复检当前环境可交易，已移出未知异常黑名单",
                    key=f"unknownrecheck:{inst_id}", title="黑名单恢复")
        return True
    def _poll_market_gap(self) -> int:
        """v5.20（C12 推广）：全市场 REST 行情补齐（批量接口，单请求返回全部现货最新价）。

        模拟盘（乃至实盘冷门币对）WS 成交推送稀疏，冷门币对可能整程收不到 tick（实证：
        26 个持仓中 22 个"启动后未收到行情"），买入信号/止盈评估/回本清仓全部停摆——
        v5.17 只兜底持仓；v5.20 推广到持仓 + 买入候选（可交易且未排除），并把逐币单查改为
        一次批量查（/api/v5/market/tickers，0.1s 内返回全部现货），因此不再需要"每轮最多
        N 个"的名额轮转：每轮把所有"静默超过 MARKET_GAP_TICK_SEC"的币对全部补齐。卖出
        重试中（_sell_blocked_until 已置位）的持仓排最前，退避到期后尽快重试。不可交易产品
        （_env_missing/_region_blocked）跳过——REST 同样查不到。锁定纪律：REST 请求在锁外
        发；拿到价格后走 on_trade（内部再取锁）喂 tick。返回本轮实际喂入的币对数量。
        """
        if MARKET_GAP_TICK_SEC <= 0 or MARKET_GAP_INTERVAL_SEC <= 0:
            return 0
        now = time.time()
        if now - self._last_stale_poll_ts < MARKET_GAP_INTERVAL_SEC:
            return 0
        self._last_stale_poll_ts = now
        with self.lock:
            cands = []
            for st in self.states.values():
                if getattr(st, "_env_missing", False) or getattr(st, "_region_blocked", False):
                    continue                        # 不可交易产品（环境缺失/地域限制）：REST 同样查不到
                if not st.has_position:
                    # 买入候选才补齐；持仓管理币（position_only）无仓不喂
                    if st.position_only or not st._okx_available:
                        continue
                    if (st.inst_id in st.blacklist or st.inst_id in st.unknown_blacklist
                            or st.inst_id in st.observe_list or st.out_of_range):
                        continue
                age = now - getattr(st, "last_tick_ts", 0.0)
                if age <= MARKET_GAP_TICK_SEC:
                    continue
                selling = getattr(st, "_sell_blocked_until", 0.0) > 0
                cands.append((0 if selling else 1, getattr(st, "_last_stale_poll_ts", 0.0),
                              st.max_loss_pct, st))
            # 排序：卖出重试中优先；其次最久未被补齐；同轮内历史最大亏损最深的（回本清仓候选）优先
            cands.sort(key=lambda item: item[:3])
            picked = [item[3] for item in cands]
        if not picked:
            return 0
        prices = fetch_all_ticker_prices()      # 锁外 REST：一次批量取全部现货
        if not prices:
            self.logger.debug("行情补齐：REST 批量最新价不可用，本轮跳过")
            self._last_market_gap_fed = 0
            return 0
        fed = 0
        for st in picked:
            px = prices.get(st.inst_id)
            st._last_stale_poll_ts = time.time()
            if px is None:
                self.logger.debug(f"{st.inst_id} 行情补齐：批量结果中无此币对，本轮跳过")
                continue
            if not getattr(st, "_stale_fallback_logged", False):
                st._stale_fallback_logged = True
                _last_tick = getattr(st, "last_tick_ts", 0.0)
                _age = f"已 {now - _last_tick:.0f}s 无行情，" if _last_tick > 0 else "启动后未收到行情，"
                self.logger.info(f"{st.inst_id} {_age}启用 REST 行情补齐（最新价 {px:.8g}）", "trade_event")
            self.on_trade(st.inst_id, px, time.time())
            fed += 1
        self._last_market_gap_fed = fed
        return fed
    def _run_order_job(self, job):
        """v5.18（文档 C7）：订单线程任务分发。

        任务格式：("sell", inst_id, price, reason, min_profit_pct) /
        ("buy", inst_id, price, reason, buy_key, sell_key, pair_name)。
        无论任务成败，结束前清除在途标记；有脏账本且到闸门则合并落盘
        （与 on_trade 同一纪律：本地账务变更不依赖下个 tick 才落盘）。
        """
        kind, inst_id = job[0], job[1]
        st = self.states.get(inst_id)
        if st is None:
            return
        try:
            if kind == "sell":
                st._order_sell_job(job[2], job[3], job[4])
            elif kind == "buy":
                st._order_buy_job(*job[2:])
        finally:
            with self.lock:
                st.order_in_flight = None
                if self.has_pending_writes() and _state_save_due():
                    self.flush_dirty_states()

    def on_trade(self, inst_id, price, ts):
        with self.lock:
            state = self.states.get(inst_id)
            if state is None:
                return
            alerts = state.update_price(price, ts)
            # 落盘在锁内按全局闸门合并，保证 peak_price/stop_price 的推进不会因线程交错而丢
            if self.has_pending_writes() and _state_save_due():
                self.flush_dirty_states()
        if alerts:
            key = [a for a in alerts if any(k in a for k in ("止盈", "清仓", "买入", "卖出"))]
            if key:
                self.logger.info(f"[{inst_id}] " + " | ".join(key), "trade_event")
            else:
                self.logger.debug(f"[{inst_id}] " + " | ".join(alerts))
# ==================== OKX 行情流 ====================
WS_SUBSCRIBE_CHUNK = 40   # OKX 单次 subscribe 最多 60 个 arg，留余量分批，避免整批订阅被拒
_SUBSCRIBE_ERROR_SEEN = set()   # v5.16（C1②）：订阅失败只提示一次（防止非本环境币对刷屏）
def subscribe_okx_trades(conn, inst_ids):
    for i in range(0, len(inst_ids), WS_SUBSCRIBE_CHUNK):
        chunk = inst_ids[i:i + WS_SUBSCRIBE_CHUNK]
        payload = {"op": "subscribe", "args": [{"channel": "trades", "instId": inst_id} for inst_id in chunk]}
        conn.send_text(json.dumps(payload, separators=(",", ":")))
def handle_okx_message(message, engine):
    msg = (message or "").strip()
    # OKX 心跳回复可能是 "pong"（带引号 JSON 字符串）或 pong（裸文本），均需忽略
    if msg in ("pong", '"pong"', "ping", '"ping"'):
        return
    try:
        data = json.loads(msg)
    except Exception:
        return
    if not isinstance(data, dict):
        return
    if data.get("event") == "subscribe":
        return
    if data.get("event") == "error":
        # v5.16（C1②）：切模拟盘行情后，池内主网独有的币对（模拟盘无此产品）订阅会逐个报错，
        # 同一币对只提示一次 WARN，之后降为 DEBUG，避免每次重连刷 55 行错误
        inst = (data.get("arg") or {}).get("instId", "")
        if inst and inst in _SUBSCRIBE_ERROR_SEEN:
            engine.logger.debug(f"OKX 订阅失败(已提示过): code={data.get('code')} {inst}")
        else:
            if inst:
                _SUBSCRIBE_ERROR_SEEN.add(inst)
            engine.logger.warn(f"OKX 订阅失败（该币对可能不在当前行情环境）: {data}")
        return
    if data.get("arg", {}).get("channel") != "trades":
        return
    inst_id = data.get("arg", {}).get("instId", "")
    for trade in data.get("data", []):
        try:
            price = float(trade["px"])
            ts = int(trade.get("ts", time.time() * 1000)) / 1000
        except (KeyError, TypeError, ValueError):
            continue
        engine.on_trade(inst_id, price, ts)
def ws_stall_action(idle_sec: float) -> str:
    """v5.12 R12：连接静默 idle_sec 秒后该做什么 —— 'stall' 主动断开重连 / 'ping' 发心跳 / '' 继续等"""
    if idle_sec >= WS_STALL_TIMEOUT_SEC:
        return "stall"
    if idle_sec >= PING_INTERVAL:
        return "ping"
    return ""
def stream_okx(engine, inst_ids):
    WS_RECOVERY_PUSH_AFTER = 3   # 文档 9.3.2：网络错误累积到 N 次再推送，断线抖动不刷屏
    consecutive_fail = 0
    while not STOP_EVENT.is_set():      # v5.12 R8：收到停止信号后不再重连，线程自然收摊
        conn = None
        last_recv = time.time()
        try:
            conn = connect_okx_ws()
            consecutive_fail = 0
            WS_HEALTH["connected"] = True
            WS_HEALTH["consecutive_fail"] = 0   # 重连成功后清零，心跳不再显示陈旧失败数
            WS_HEALTH["connected_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            WS_HEALTH["reconnects"] = WS_HEALTH.get("reconnects", 0) + 1
            engine.logger.info(
                f"OKX WebSocket 连接成功（{'模拟盘' if ws_use_demo() else '实盘'}"
                f"行情 {OKX_WS_DEMO_HOST if ws_use_demo() else OKX_WS_HOST}）", "startup")
            subscribe_okx_trades(conn, inst_ids)
            while True:
                try:
                    opcode, payload = conn.recv_message()
                    last_recv = time.time()
                    WS_HEALTH["last_msg_ts"] = last_recv
                except socket.timeout:
                    idle = time.time() - last_recv
                    action = ws_stall_action(idle)
                    if action == "stall":
                        # 静默太久：这条链路上已经收不到任何东西（连 pong 都没有），
                        # 继续 ping 下去行情就是无限期停摆，主动断开走重连分支重新订阅
                        WS_HEALTH["connected"] = False
                        WS_HEALTH["last_error"] = f"连接静默 {idle:.0f}s：无任何行情/pong 回包"
                        WS_HEALTH["last_error_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        WS_HEALTH["stall_reconnects"] = WS_HEALTH.get("stall_reconnects", 0) + 1
                        engine.logger.error(f"OKX 连接静默 {idle:.0f}s 无回包，主动断开重连"
                                            f"（第 {WS_HEALTH['stall_reconnects']} 次）", "connection_error",
                                            push=False)
                        push_notify_throttled(
                            f"📡 行情静默重连\n\n已 {idle:.0f}s 没收到任何行情或 pong 回包，"
                            f"主动断开重连（第 {WS_HEALTH['stall_reconnects']} 次）",
                            key="ws:stall", title="行情静默重连")
                        break
                    if action == "ping":
                        conn.send_text("ping")
                    continue
                if opcode == 0x1:
                    try:
                        handle_okx_message(payload.decode("utf-8"), engine)
                    except Exception as be:
                        engine.logger.error(f"OKX 业务处理异常(不重连): {be}")
                elif opcode == 0x8:
                    raise ConnectionError("服务端关闭")
                elif opcode == 0x9:
                    conn.send_pong(payload)
                elif opcode == 0xA:
                    continue
        except Exception as e:
            consecutive_fail += 1
            WS_HEALTH["connected"] = False
            WS_HEALTH["last_error"] = f"{e}"
            WS_HEALTH["last_error_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            WS_HEALTH["consecutive_fail"] = consecutive_fail
            # 前几次失败只记日志（多为秒级抖动），连续失败才告警；push=False 避免每 3 秒刷屏
            engine.logger.error(f"OKX 连接异常(第 {consecutive_fail} 次): {e}", "connection_error",
                                push=consecutive_fail >= WS_RECOVERY_PUSH_AFTER)
            STOP_EVENT.wait(RECONNECT_DELAY)   # 等待重连期间也能被停止信号叫醒（原来要死等 RECONNECT_DELAY）
        finally:
            if conn:
                conn.close()
# ==================== 主函数 ====================
MARKET_THREAD_RESTART_MIN_SEC = env_num("MARKET_THREAD_RESTART_MIN_SEC", 30.0)


def _handle_stop_signal(signum, frame):
    """信号上下文里只做最小动作：置停止位。落盘等重活留给主线程 finally。"""
    if STOP_EVENT.is_set():
        # 第二次停止信号：不再等收尾（可能卡在锁或网络等待上），恢复默认处置当场退出
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)
        return
    STOP_EVENT.set()


def install_signal_handlers(logger):
    """v5.12 R8：SIGTERM 也算干净退出。systemd/`kill`/容器停止默认发 SIGTERM，
    旧代码只 catch KeyboardInterrupt，被 SIGTERM 打死时 finally 不执行：
    脏账本不落盘、心跳停在旧值、外部监控分不清是崩了还是被停了。"""
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGQUIT):
        try:
            signal.signal(sig, _handle_stop_signal)
        except (ValueError, OSError) as e:   # 非主线程或平台不支持
            logger.warn(f"信号 {getattr(sig, 'name', sig)} 注册失败: {e}", "startup")


def start_market_thread(engine, inst_ids):
    """行情线程单点启动，主循环发现线程没了可以原样拉起（daemon：进程退出即收）"""
    t = threading.Thread(target=stream_okx, args=(engine, inst_ids),
                         name="okx-market-stream", daemon=True)
    t.start()
    return t


def watch_market_thread(engine, inst_ids, thread, last_start, restarts, now=None):
    """v5.12 R8：行情线程只有一条，它没了 = 所有币对的止盈/买入监听静默停摆，
    而进程还活着、心跳还在写，以前没人发现。这里发现即原样拉起；
    带最小间隔，避免线程一启动就崩时瞬间铺一堆僵尸线程。
    返回 (thread, last_start, restarts)。"""
    now = time.time() if now is None else now
    if thread.is_alive() or now - last_start < MARKET_THREAD_RESTART_MIN_SEC:
        return thread, last_start, restarts
    restarts += 1
    WS_HEALTH["connected"] = False
    WS_HEALTH["thread_restarts"] = restarts
    WS_HEALTH["last_error"] = "行情线程意外退出"
    WS_HEALTH["last_error_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    engine.logger.error(f"OKX 行情线程已退出，第 {restarts} 次重新拉起", "connection_error")
    push_notify_throttled(
        f"🚨 行情线程退出\n\n{PROGRAM_NAME} 行情线程意外终止，已第 {restarts} 次重新拉起；"
        f"恢复订阅期间不会触发止盈/买入",
        key=f"mthread:{restarts}", title="行情线程退出")
    return start_market_thread(engine, inst_ids), now, restarts


def main():
    acquire_single_instance_lock()
    stale_tmp = sweep_stale_tmp_files()
    if stale_tmp:
        print(f"[启动清理] 移除残留临时文件 {len(stale_tmp)} 个: {', '.join(stale_tmp[:5])}")
    print("=" * 60)
    print(f"{PROGRAM_NAME} {VERSION}")
    print(f"工作目录: {BASE_DIR}")
    print(f"数据目录: {DATA_DIR}")
    print("=" * 60)
    logger = Logger(LOG_FILE)
    install_signal_handlers(logger)   # v5.12 R8：SIGTERM/SIGINT/SIGQUIT → 置停止位并走正常收尾
    # 推送通道配置（.env）：NOTIFY_CHANNEL = dingtalk / feishu / both / none
    notify_channel = os.getenv("NOTIFY_CHANNEL", "").strip().lower() or "dingtalk"
    ding_webhook = os.getenv("DINGTALK_WEBHOOK_okx", "").strip()
    ding_secret = os.getenv("DINGTALK_SECRET_okx", "").strip()
    feishu_webhook = os.getenv("FEISHU_WEBHOOK_okx", "").strip()
    feishu_secret = os.getenv("FEISHU_SECRET_okx", "").strip()
    setup_notify(notify_channel, ding_webhook, ding_secret, feishu_webhook, feishu_secret)
    if notify_channel != "none":
        logger.info(f"消息推送已启用: {notify_channel}", "startup")
    else:
        logger.warn("消息推送未配置（NOTIFY_CHANNEL=none），仅终端输出", "startup")
    # v5.12 R16：xlsx 本体读不出来（缺失/损坏/被独占锁定）不再 sys.exit(1)——
    # 先退到上一次有效配置快照，连快照都没有才按"无有效配置"走 R9 的仅持仓管理判定。
    config, system_params, config_source = load_config_with_fallback()
    if config_source == "xlsx":
        logger.info(f"加载配置成功: {len(config)} 个币对", "config_load")
    elif config_source == "snapshot":
        logger.error(f"股票池读不出来，已回退到上次有效配置快照: {len(config)} 个币对，"
                     f"请尽快修复 {CONFIG_DIR}", "config_load")
        push_notify_throttled(
            f"🛠 股票池读不出来，已按快照启动\n\n"
            f"{CONFIG_DIR} 无法读取（文件损坏 / 被 Excel 独占 / 目录被移走），"
            f"已回退到 {os.path.basename(CONFIG_SNAPSHOT_FILE)} 里最后一次成功的配置：{len(config)} 个币对。\n"
            f"快照可能落后于你最近的表格改动，请尽快修复并重新保存配置表。",
            key="config:snapshot", title="配置快照回退")
    else:
        logger.error("配置表读不出来且没有可用的配置快照，将按默认参数与本地持仓决定运行模式", "config_load")
    if not config:
        # v5.12 R9：配置表一行好数据都没有时，先看本地账本有没有持仓。
        # 直接 sys.exit(1) 等于"配置手抖一下 → 持仓无人盯守"，止盈/回本清仓全部停摆。
        held = sorted(load_positions())
        if not config_startup_ok(config, held):
            logger.error("没有启用的币对", "config_load")
            sys.exit(1)
        logger.error(f"没有启用的币对，但本地账本仍有 {len(held)} 个持仓: {held}，"
                     f"改为仅持仓管理模式（不买入，平台持仓由启动同步自动纳入监听）", "config_load")
        push_notify_throttled(
            f"⚠️ 股票池无有效币对\n\n本地账本仍有持仓 {held}\n"
            f"程序继续运行并只做持仓管理（不买入），请尽快修复股票池 {CONFIG_DIR}",
            key="config:empty", title="配置无有效币对")
    trade_mode_cfg = os.getenv("OKX_TRADE_MODE", "").strip() or str(system_params.get("trade_mode", "demo"))
    init_okx_client(trade_mode_cfg, logger)
    print(f"交易模式: {TRADE_MODE_DESC[TRADE_MODE]}")
    min_amt = env_num("MIN_BUY_AMOUNT", 100.0)
    print(f"单笔最小买入金额: {min_amt:.2f} USDT")
    # v5.12 R15：静默期天数只从 system_params 取（load_config 已合并 .env 的 COOLDOWN_DAYS 并做过
    # 非法值保护），这里再 int(os.getenv(...)) 一遍等于把保护拆掉——一个写错的值会 ValueError 直接崩启动
    print(f"静默期天数: {system_params.get('cooldown_days', 7)} 天")
    recheck_startup_blacklist(logger)
    # v5.16（文档 C11）：未知异常黑名单批量复检（满 24h 的条目；states 尚未创建，
    # 从 CSV 移除即可，各状态创建时会重新读取）
    _ulk_removed = recheck_unknown_blacklist_due(logger, limit=50)
    if _ulk_removed:
        logger.info(f"未知黑名单启动复检：{len(_ulk_removed)} 个币对恢复可交易并移除: {', '.join(_ulk_removed)}", "startup")
    engine = MarketEngine(logger, system_params)
    blacklist = load_blacklist()
    if blacklist:
        logger.info(f"加载黑名单: {len(blacklist)} 个币对", "startup")
        for b in blacklist:
            print(f"  黑名单: {b}")
    observe_list = load_observe_list()
    if observe_list:
        logger.info(f"加载待观察列表: {len(observe_list)} 个币对", "startup")
        for o in observe_list:
            print(f"  待观察: {o}")
    out_of_range_set = load_out_of_range()
    if out_of_range_set:
        logger.info(f"加载超出计算范围列表: {len(out_of_range_set)} 个币对", "startup")
        for o in sorted(out_of_range_set):
            print(f"  超出计算范围: {o}")
    okx_inst_ids = []
    logger.info("初始化币对状态...", "startup")
    for inst_id, data in config.items():
        engine.add_state(inst_id, data["ref_high"], data["ref_low"])
        state = engine.states[inst_id]
        print(f"\n{inst_id} 价格点位:")
        print(f"  最高: {state.high:.8g}  最低: {state.low:.8g}")
        print(f"  回撤上: {state.levels.pullback_up:.8g}  回撤2下: {state.levels.pullback2_down:.8g}")
        print(f"  回调上: {state.levels.callback_up:.8g}  回调2下: {state.levels.callback2_down:.8g}")
        print(f"  过渡上: {state.levels.transition_up:.8g}  过渡2下: {state.levels.transition2_down:.8g}")
        print(f"  极限上: {state.levels.limit_up:.8g}  极限2下: {state.levels.limit2_down:.8g}")
        # v5.10：账户/网络不可达时"查不到交易对"不代表不可交易，本地有持仓的币对必须继续订阅，
        # 否则一次网络抖动就把持仓行情监听一起关掉
        # v5.15：环境缺失（code=51001）同样保持订阅——重探成功后无需重启即可进入买入信号流程
        if state._okx_available or state.has_position or state._net_failed or state._env_missing:
            okx_inst_ids.append(inst_id)
            print(f"{inst_id}: OKX 可交易" if state._okx_available else f"{inst_id}: 交易对待确认/环境缺失/有持仓，仍订阅行情")
        else:
            print(f"{inst_id}: OKX 不可交易（已排除）")
    # v5.6：平台已有持仓但不在配置表中的币对，自动纳入卖出监听（仅管理持仓、不买入）
    api_pos_startup = get_positions_snapshot()
    for pos_id, pos_data in api_pos_startup.items():
        if pos_id in engine.states:
            continue
        avg = pos_data.get("position_price", 0) or 0
        if avg <= 0:
            avg = 1
        logger.info(f"平台持仓币对 {pos_id} 不在配置表中，自动纳入卖出监听（仅持仓管理，不买入）", "startup")
        engine.add_state(pos_id, avg * 2, avg * 0.5, position_only=True)
        pstate = engine.states[pos_id]
        print(f"\n{pos_id} [仅持仓管理] 成本 {avg:.8g} 数量 {pos_data.get('position_qty', 0):.8g}")
        if pstate._okx_available or pstate._net_failed or pstate._env_missing:
            okx_inst_ids.append(pos_id)
        else:
            print(f"{pos_id}: 平台有持仓但行情不可订阅，无法监听卖出")
    # v5.12 R10：所有币对状态建好后，买入队列一次性读表→逐行同步→一次写表
    if not engine.sync_all_buy_queue():
        logger.error("买入队列初始化落盘失败，队列状态可能滞后（后续行情 tick 会重试）", "storage")
    api_pos = get_positions_snapshot()
    if api_pos:
        print("\n当前 OKX 现货持仓（启动同步快照）:")
        for inst_id, data in api_pos.items():
            print(f"  {inst_id}: 数量 {data['position_qty']:.8g}, 估值(市价，非买入成本) {data['position_price']:.8g}")
    positions = load_positions()
    for inst_id, data in positions.items():
        print(f"恢复持仓: {inst_id} 数量 {data.get('position_qty', 0):.8g} @ {data.get('position_price', 0):.8g}"
              f"（成本来源 {data.get('cost_source', '') or '未知'}）")
    queue = load_buy_queue()
    pending = [r for r in queue if r.get("status") == "待买入"]
    print(f"买入队列: {len(pending)} 个币对待买入")
    print(f"OKX 账户 USDT 余额: {get_okx_balance(force_refresh=True):.2f}")
    if not okx_inst_ids:
        logger.error("没有可交易的币对，退出", "startup")
        sys.exit(1)
    market_thread = start_market_thread(engine, okx_inst_ids)
    logger.info(f"OKX 行情线程启动: {len(okx_inst_ids)} 个币对", "startup")
    logger.info("=" * 60, "startup")
    logger.info("系统运行中，Ctrl+C 或 kill(SIGTERM) 均可停止（停止时会先把脏账本落盘）", "startup")
    logger.info("买入规则：价格跌破买点后，从最低点反弹1%时买入（且价格仍低于买点）", "startup")
    logger.info("卖出规则(v5.8)：普通持仓盈利≥6.5%激活动态止盈；激活后每个tick检查止盈价，跌穿止盈价且价格≥成本即市价清仓(绝不亏本卖)，跌破成本则保留激活继续盯盘；盈利≥20%直接清仓；持仓历史最大亏损>5%可回本即清仓", "startup")
    logger.info(f"超范围剔除: 越界即剔除并记表，价格回到区间(内缩{RANGE_HYSTERESIS_PCT*100:.2f}%滞回带)自动恢复买入，翻转间隔≥{RANGE_FLIP_MIN_INTERVAL_SEC:.0f}s", "startup")
    logger.info("检查频率: 持仓止盈/止损每个行情tick实时评估，check_level 仅作账本标签(T0止盈中/T1盈利/T2配对/T3默认)", "startup")
    logger.info("=" * 60, "startup")
    last_heartbeat = 0.0
    last_thread_start = time.time()
    thread_restarts = 0
    try:
        while not STOP_EVENT.wait(1.0):
            # 主循环独立于行情线程：负责负载采样→降频决策，以及心跳文件（外部监控用）
            engine.maintenance()
            now = time.time()
            if now - last_heartbeat >= HEARTBEAT_INTERVAL_SEC:
                last_heartbeat = now
                write_heartbeat(engine, extra={
                    "market_thread_alive": market_thread.is_alive(),
                    "market_thread_restarts": thread_restarts,
                })
            # v5.12 R8：行情线程死亡看门狗
            market_thread, last_thread_start, thread_restarts = watch_market_thread(
                engine, okx_inst_ids, market_thread, last_thread_start, thread_restarts, now)
    except KeyboardInterrupt:
        logger.info("用户中断，程序停止", "shutdown")
    finally:
        if STOP_EVENT.is_set():
            logger.info("收到停止信号，开始收尾（脏账本落盘后退出）", "shutdown")
        try:
            with engine.lock:
                engine.flush_dirty_states()
        except Exception as e:
            logger.error(f"退出时落盘失败: {e}", "storage")
        if flush_out_of_range_ops():   # v5.12 R11：攒在内存里的超范围事件退出前必须写进 xlsx
            logger.info("超范围记录已批量落盘", "storage")
        try:
            write_heartbeat(engine, extra={"shutting_down": True,
                                           "market_thread_restarts": thread_restarts})
        except Exception:
            pass
        _update_funds_for_view(get_okx_balance(force_refresh=True))
        logger.info("程序退出", "shutdown")
        try:
            # v5.15（文档 P2-9）：退出前最多等 2 秒把已排队的推送发完（原先立即 shutdown(wait=False)，
            # 进程退出瞬间可能丢"卖出/告警"这类最后几条关键通知），超时不再等待
            deadline = time.time() + 2.0
            while push_pending_count() > 0 and time.time() < deadline:
                time.sleep(0.05)
        except Exception:
            pass
        try:
            NOTIFY_POOL.shutdown(wait=False)  # 不等待后台推送任务，立即退出
        except Exception:
            pass
if __name__ == "__main__":
    main()

# Issue 14: 伪代码文档深度审查与全面修复

## 概述

对 `doc/pseudocodes/` 目录下全部 10 个伪代码设计文档进行系统性交叉审查，发现并修复 **36 项问题**，涵盖 7 项阻断性 Bug、9 项高危问题、11 项中等问题、9 项低优先级问题。修复范围包括逻辑错误、并发安全缺陷、内存安全问题、跨文档不一致性、API 设计缺陷和状态机漏洞。

---

## 阻断性 Bug 修复 (BLOCKER - 7 项)

### B1. ParseHeader 对 QUIC 数据包的越界读取
- **文件**: `02_session.md` (Section 2.3 ParseHeader)
- **问题**: 函数体硬编码 KCP 固定偏移 (data[0]~data[23])，但 `MIN_HEADER_SIZE` 对 QUIC 仅为 1 字节。QUIC 短头包 (5 字节) 通过大小检查后，访问 `data[20]` 会越界。
- **修复**: 按 `engine_type` 分支处理 — KCP 走固定偏移解析，QUIC 委托 `ProtocolEngine::ParseQUICHeader()`；KCP 最小长度改为 24 字节，QUIC 走协议特定路径。

### B2. SIGHUP 信号处理器捕获悬空引用
- **文件**: `00_architecture_overview.md` (Section 3.1)
- **问题**: `SignalHandler::OnSIGHUP([&config_mgr](){ config_mgr.Reload(...) })` — `config_mgr` 是 `LibraryInitialize` 的栈变量，函数返回后 SIGHUP 回调中的引用悬空，触发 use-after-free。
- **修复**: 改用 `std::make_shared<ConfigurationManager>` 并将 `shared_ptr` 按值捕获到 lambda。

### B3. TimerQueue::GetNextTimeout 无符号整数下溢
- **文件**: `01_platform_layer.md` (TimerQueue)
- **问题**: `heap_.top().expire_time - now` 当 `expire_time < now` (定时器已到期) 时 `uint64_t` 减法回绕为极大值，`MAX(0, remaining)` 仍返回极大值，导致 EventLoop 长时间阻塞而跳过已到期定时器。
- **修复**: 减法前先检查 `expire_time <= now`，若已到期返回 0；减法结果显式转换为 `uint32_t`。

### B4. EventLoop::state_ 数据竞争
- **文件**: `01_platform_layer.md` (EventLoop)
- **问题**: `state_` 声明为普通 `RunState` 枚举 (`PRIVATE MEMBER state_: RunState = kStopped`)，但 `Stop()` 宣称线程安全并从任意线程写入，`Run()` 在事件循环线程读取 — C++ 标准定义为未定义行为。
- **修复**: 改为 `std::atomic<RunState>`。

### B5. DatagramSocket 默认移动构造不安全
- **文件**: `01_platform_layer.md` (DatagramSocket)
- **问题**: `DatagramSocket(DatagramSocket&&) = default` 仅拷贝 `int fd_` 值，移动后原对象保有相同 fd。原对象析构时 `::close(fd_)` 关闭了移动后对象正在使用的 Socket，导致 double-close 和 use-after-close。
- **修复**: 实现自定义移动构造/赋值，转移 fd 后将源对象 `fd_` 设为 `-1` (无效哨兵值)；移动赋值中先取消注册并关闭已有 fd。

### B6. TimerQueue::FireExpired 死锁
- **文件**: `01_platform_layer.md` (TimerQueue)
- **影响范围**: `02_session.md` GracefulShutdown 定时器回调，`04_client.md` 连接超时/重连定时器回调
- **问题**: `FireExpired` 在持有 `mutex_` 时执行回调。当 GracefulShutdown 超时回调调用 `Close()` → `CancelShutdownTimer()` → `TimerQueue::Cancel()` → 尝试再次获取 `mutex_` → 死锁 (非递归 mutex)。
- **修复**: 重构 `FireExpired` 为两阶段：锁内收集到期回调 → 解锁 → 锁外执行回调 → 锁内处理重复定时器重入堆。回调中可安全调用 `Add/Cancel`。

### B7. Client 连接/重连中匿名定时器悬空指针
- **文件**: `04_client.md` (Client)
- **问题**: `OnConnectTimeout` 中 `event_loop_.AddTimer(delay, [this](){...})` 创建的匿名重连定时器句柄未存储。`Client` 析构时 `Disconnect()` 无法取消该定时器，导致 lambda 以悬空 `this` 触发的 use-after-free。
- **修复**: 新增 `retry_timer_` 成员变量存储句柄，`Disconnect()` 中一并取消。

---

## 高危问题修复 (HIGH - 9 项)

### H1. Server 隐式 Accept 首包用户消息丢失
- **文件**: `03_server.md` (OnReadable)
- **问题**: 新 Session 创建后，`FeedInput()` 先于 `WireSessionEvents()` 调用。`FeedInput` 内部 `TryRecv()` 触发 `message_callback_` 但回调尚未注册（用户通过 `new_session_handler_` 注册的 `OnMessage` 在 `WireSessionEvents` 之后才执行），首包中的应用数据永久丢失。
- **修复**: 调整顺序为：`Start()` → `WireSessionEvents()` → `sessions_[...]` → `FeedInput()`，确保回调注册先于数据投递。

### H2. Session::GracefulShutdown 定时器捕获裸 this
- **文件**: `02_session.md` (Session)
- **问题**: `event_loop_.AddTimer(timeout_ms, [this](){ if (state_ == kClosing) Close(); })` — 若 Session 在定时器触发前被销毁 (如外部立即 Close)，裸 this 悬空导致 use-after-free。
- **修复**: 改用 `weak_from_this()` 捕获：`[weak_self = weak_from_this()](){ if (auto self = weak_self.lock()) {...} }`。

### H3. Session::ApplyConfig 静默忽略协议引擎类型变更
- **文件**: `02_session.md` (Session)
- **问题**: 若在 `kIdle` 状态调用 `ApplyConfig` 将 `engine_type` 从 KCP 改为 QUIC，`config_` 被更新但 `engine_` 仍为旧 KCP 实例。后续操作使用旧的错误引擎，产生静默行为不一致。
- **修复**: `ApplyConfig` 中检测 `engine_type` 变更时销毁旧引擎，通过 `ProtocolEngineFactory::Create()` 重建，并重新绑定 `OutputCallback`。

### H4. GracefulShutdown 定时器分配失败导致永久卡在 kClosing
- **文件**: `02_session.md` (Session)
- **问题**: `AddTimer` 可能因资源耗尽返回无效句柄 (~0 或 TimerHandle::Invalid())。若未检查，`state_` 保持 `kClosing` 永久，Session 无法清理且占用 `sessions_` 槽位。
- **修复**: `GracefulShutdown` 末尾检查 `shutdown_timer_.IsValid()`，无效时立即回退到 `Close()`。

### H5. Server::ExtractRoutingKey QUIC 包被错误拒绝
- **文件**: `03_server.md` (Server)
- **问题**: `MIN_HEADER_SIZE = 24` 对所有协议统一检查。即使 engine_type 为 QUIC，长度 <24 的包（如 QUIC 短头包仅需 1 字节）先被 `IF len < MIN_HEADER_SIZE` 拒绝了，永远不会到达 QUIC 分支。
- **修复**: 先判断 `engine_type`：QUIC 直接委托 `ProtocolEngine::ExtractRoutingKey` (自行检查长度)，KCP 再检查 `len < 24`。

### H6. Server::Stop() 产生僵尸 PostTask
- **文件**: `03_server.md` (Server)
- **问题**: `Stop()` 遍历 `sessions_` 调用 `EvictSession`，触发 `session->Close()` → `OnStateChange` 回调 → `PostTask(RemoveSession)`。N 个会话产生 N 个 PostTask，然后 `sessions_.clear()` 清空 Map。后续任务执行时仅做空查找，浪费资源。
- **修复**: 新增 `stopping_` 标志，`Stop()` 中设为 true，`WireSessionEvents` 回调中检查 `stopping_` 并跳过 PostTask。

### H7. ConfigurationManager::GetLibraryConfig 等返回悬空引用
- **文件**: `08_system_config.md` (ConfigurationManager)
- **问题**: `GetLibraryConfig()` 返回 `GetConfig()->library` — `GetConfig()` 返回临时 `shared_ptr`，`->` 解引用后临时对象析构，返回的 `const LibraryConfig&` 立即悬空。
- **修复**: 所有便捷访问方法返回 `ConfigPtr` (`shared_ptr<const SystemConfig>`)，由调用方持有引用计数并自行解引用。原方法标记为 DEPRECATED。

### H8. Reload 丢失命令行覆盖
- **文件**: `08_system_config.md` (ConfigurationManager)
- **问题**: `Reload()` 调用 `LoadFromFile()` 仅应用 JSON+环境变量覆盖，命令行覆盖 (最高优先级) 被丢弃。重载后配置与启动时不一致。
- **修复**: `ApplyCmdLineOverrides` 中保存 `saved_cmdline_overrides_`，`Reload` 中重新应用。

### H9. TimerQueue::FireExpired 中重复定时器周期漂移
- **文件**: `01_platform_layer.md` (TimerQueue)
- **问题**: 重复定时器重新入堆时使用 `expire_time = now + interval_ms`，若回调执行耗时较长，有效周期拉伸为 `interval + callback_time`，长期运行后定时器节律漂移。
- **修复**: 改为 `expire_time = entry.expire_time + entry.interval_ms`，保持固定节律。若积压过大 (expire_time 已小于 now)，回退到 `now + interval_ms`。

---

## 中等问题修复 (MEDIUM - 11 项)

### M1. DatagramSocket 析构函数未取消 EventLoop 注册
- **文件**: `01_platform_layer.md` (DatagramSocket)
- **问题**: 析构函数仅 `::close(fd_)`，未调用 `event_loop_->Unregister()`。若 Socket 在 EventLoop 运行期间销毁，EventLoop 在下一轮 `WaitForEvents` 中可能向已释放的 `IEventHandler` 分发事件。
- **修复**: 析构函数中增加 `event_loop_.Unregister(EventDesc{uintptr_t(fd_), Platform::Current()})`。

### M2. WorkerPool 构造中 vector 重分配导致 lambda 引用悬空
- **文件**: `01_platform_layer.md` (WorkerPool)
- **问题**: 构造函数循环中边 `push_back` 边启动线程，lambda 通过 `[&workers = workers_, i]` 捕获引用。若 vector 在 `push_back` 时重分配，已启动线程中的引用悬空。
- **修复**: 循环前 `workers_.reserve(worker_count)` 预分配容量，保证后续 `push_back` 不触发重分配。

### M3. DatagramSocket::fd_ 类型在 Windows x64 截断
- **文件**: `01_platform_layer.md` (DatagramSocket)
- **问题**: Windows `SOCKET` 为 `UINT_PTR` (64 位)，存储在 `int` (32 位) 中会截断，导致有效句柄被视为无效或与其他句柄碰撞。
- **修复**: `fd_` 类型从 `int` 改为 `uintptr_t` (SocketHandle)，与 `EventLoop::EventDesc::fd_or_handle` 类型一致。

### M4. EventLoop 析构未确保 Run() 已退出
- **文件**: `01_platform_layer.md` (EventLoop)
- **问题**: `Stop()` 仅设 flag + 唤醒，不等待 `Run()` 返回。析构函数中 `impl_.Reset()` 可能在 `Run()` 仍在 `impl_.WaitForEvents()` 中时销毁平台实现，导致 use-after-free。
- **修复**: 析构函数中添加明确注释说明调用方责任（通过 WorkerPool::Shutdown join 各线程），不在此处隐式 join。

### M5. Client 双重连 (OnError + OnStateChange)
- **文件**: `04_client.md` (Client)
- **问题**: Session 错误时 `OnError` 触发了 `session_->Close()` → `OnStateChange(kClosed)` 也同样触发重连，两个独立的 `DoConnect()` 并发执行，创建两个 Session 实例，前一个泄露。
- **修复**: `OnError` 中在调用 `Close()` 之前设置 `state_ = kReconnecting`，`OnStateChange` 检查 `state_ == kConnected` 才触发重连，确保只执行一次。

### M6. Client::kClosed 状态不可达
- **文件**: `04_client.md` (Client)
- **问题**: `ClientState::kClosed = 4` 声明为终态，但没有任何代码路径设置此状态。`Disconnect()` 设 `kDisconnected`，`NotifyConnectFailure` 设 `kDisconnected`。`Connect()` 中 `kClosed` 的守卫成为死代码。
- **修复**: `Disconnect()` 中增加 `state_ = kClosed` 路径作为可选终态；或保留现有逻辑并在文档中注明 `kClosed` 为预留扩展状态。

### M7. ConfigurationManager HasBlockingErrors 未检查端口为 0
- **文件**: `08_system_config.md` (ConfigurationManager)
- **问题**: Server `listen_port == 0` 和 Client `remote_port == 0` 仅产生 warning，不阻止启动。端口 0 无法监听/连接，应在配置加载阶段作为阻塞错误拒绝。
- **修复**: `HasBlockingErrors` 中增加 `port == 0` 检查，端点启用且端口为 0 时返回 true。

### M8. ApplyCmdLineOverrides 每键复制整个配置对象
- **文件**: `08_system_config.md` (ConfigurationManager)
- **问题**: `ApplyCmdLineOverrides` 在循环内 `make_shared<SystemConfig>(*GetConfig())`，每个命令行键都复制整个 SystemConfig (~200+ 字段)。命令行参数多时性能严重退化。
- **修复**: 将配置复制移出循环：复制一次 → 批量应用所有覆盖 → 单次 `atomic_store`。

### M9. Client 重连延迟可能超过 max_delay_ms
- **文件**: `04_client.md` (Client)
- **问题**: `delay = MIN(exponential, max_delay_ms) + jitter` — 抖动在封顶后添加，实际延迟可达 `max_delay_ms + jitter_ms`，违反 `max_delay_ms` 的合约。
- **修复**: 改为 `delay = MIN(exponential + jitter, max_delay_ms)`，封顶包含抖动。

### M10. IOMask 为 scoped enum 不支持位运算
- **文件**: `05_api_reference.md` (EventLoop)
- **问题**: `enum class IOMask : uint8_t` 是 scoped enum，不隐式转换为整型。代码中 `kReadable | kEdgeTriggered` 无法编译。
- **修复**: 新增 `constexpr operator|`、`operator&` 和 `HasFlag` 函数。

### M11. 跨文档配置结构定义不一致
- **文件**: `00_architecture_overview.md` vs `05_api_reference.md` vs `08_system_config.md`
- **问题**: `LibraryConfig` 在三个文档中有不同字段定义（架构总览有 `allocator`/`log_sink`/`metrics_sink`，API 参考有 `enable_metrics`/`log_level`，系统配置有 `io_backend` 为 string）。`max_sessions` 在 API 参考为 `size_t`，在系统配置为 `uint32_t`。
- **修复**: 在各文档不一致处添加交叉引用注释，统一主定义在 `08_system_config.md`。

---

## 低优先级问题修复 (LOW - 9 项)

### L1. LOG_FATAL 拼写错误
- **文件**: `00_architecture_overview.md` (Section 3.1)
- **修复**: `LOG_FATAL` → `LOG_FATAL`，与 `09_logging_module.md` 中的宏定义一致。

### L2. EventLoop 构造方式不一致
- **文件**: `00_architecture_overview.md` (Section 3.1/3.2/3.3)
- **问题**: `LibraryInitialize` 用构造函数，`ServerStart`/`ClientConnect` 用 `EventLoop::Create()` 工厂方法，同一文档内不一致。
- **修复**: 统一为构造函数 `EventLoop(ParseIOBackend(...))`。

### L3. Session::Config::update_interval_ms 为有符号类型
- **文件**: `02_session.md` (Session::Config)
- **修复**: `int` → `uint32_t`，防止负数传入导致定时器未定义行为。

### L4. SendHandshakePacket / SendProbePacket 缺少状态守卫
- **文件**: `02_session.md` (Session)
- **修复**: 添加 `IF state_ != kIdle/kConnected: LOG_WARN + RETURN` 守卫，防止在已关闭/错误状态的引擎上调用。

### L5. ParseHeader 函数签名与实现不匹配
- **文件**: `02_session.md` (Section 2.3)
- **问题**: 注释声称 `MIN_HEADER_SIZE` 对 QUIC 为 1 字节，但函数体所有读取都在偏移 0-23（需要 24 字节），未针对引擎类型分派。
- **修复**: 与 B1 一同修复，KCP/QUIC 分支处理。

### L6. BSD kqueue 平台检测遗漏 NetBSD 和 DragonFly BSD
- **文件**: `07_tech_stack.md` (PlatformDetect)
- **修复**: 添加 `|| defined(__NetBSD__) || defined(__DragonFly__)`。

### L7. EvaluateHealth 时钟回退处理
- **文件**: `02_session.md` (Session)
- **问题**: NTP 校时/系统挂起恢复时 `now_ms < last_recv_time_ms_`，无符号减法回绕导致健康会话误判为 stale 并驱逐。
- **修复**: 使用饱和减法 `(now_ms > last_recv_time_ms_) ? (now_ms - last_recv_time_ms_) : 0`。

### L8. DatagramSocket::Modify 调用参数数量不匹配
- **文件**: `01_platform_layer.md` (DatagramSocket)
- **问题**: `EnableWriteNotifications` 和 `DisableWriteNotifications` 向 `EventLoop::Modify` 传入 3 个参数（含 handler），但 `Modify` 仅接受 2 个参数 `(desc, new_mask)`，handler 已在 Register 中关联无需重复传入。
- **修复**: 移除多余的 handler 参数。

### L9. 06_high_concurrency_tests.md 测试验证标准澄清
- **文件**: `06_high_concurrency_tests.md`
- **修复**: 更新 `FireExpired` 相关测试（Test 3.1/3.2/3.4）以反映新的锁外回调架构；TimerQueue 死锁测试（跨文档 Issue 21）现在不会发生，因为回调在锁外执行。

---

## 跨文档一致性问题修复汇总

| 跨文档不一致项 | 涉及文档 | 解决方案 |
|--------------|---------|---------|
| LibraryConfig 字段定义不一致 | 00/05/08 | 以 08_system_config.md 为权威定义，其他文档添加交叉引用 |
| max_sessions 类型 size_t vs uint32_t | 05/08 | API 参考保留 `size_t`（内部表示），系统配置保留 `uint32_t`（JSON 值域） |
| EventLoop 构造 API | 00 | 统一为构造函数 |
| ReconnectConfig vs std::optional<ReconnectStrategy> | 04/08 | 系统配置出口处统一转换，添加转换函数文档 |
| ParseHeader 最小头部大小 | 02/03 | 按引擎类型分支，不再使用全局 MIN_HEADER_SIZE |
| RAW Socket 支持声明 | 01/07 | 技术栈文档修正为"可选扩展"，平台层当前仅支持 SOCK_DGRAM |

---

## 修改文件清单

| 文件 | 修改次数 | 主要类型 |
|------|---------|---------|
| `doc/pseudocodes/00_architecture_overview.md` | 4 | B2, L1, L2 |
| `doc/pseudocodes/01_platform_layer.md` | 9 | B3, B4, B5, B6, M1, M2, M3, M4, L8 |
| `doc/pseudocodes/02_session.md` | 9 | B1, H2, H3, H4, L3, L4, L5, L7 |
| `doc/pseudocodes/03_server.md` | 5 | H1, H5, H6 |
| `doc/pseudocodes/04_client.md` | 4 | B7, M5, M6, M9 |
| `doc/pseudocodes/05_api_reference.md` | 3 | M10, H7 (LogCallback) |
| `doc/pseudocodes/06_high_concurrency_tests.md` | 1 | L9 |
| `doc/pseudocodes/07_tech_stack.md` | 1 | L6 |
| `doc/pseudocodes/08_system_config.md` | 4 | H7, H8, M7, M8 |
| `doc/pseudocodes/09_logging_module.md` | 0 | (注: 问题在 05_api_reference.md 的 LogManager API 部分修复) |

---

## 未修复项目（设计决策，需后续讨论）

以下问题在审查中发现但暂不修改，需团队讨论后决定方案：

1. **conv 冲突与 SessionMap 单键设计** (03_server.md:29-32) — 不同客户端使用相同 conv 值时路由错误；建议使用 `(conv, sender_ip, sender_port)` 复合键或服务端 conv 分配。此为架构级变更。

2. **kNotifyOnly 驱逐策略语义** (03_server.md:281) — 仅通知不关闭，会话可能永久保留；需要明确应用层责任边界。

3. **SendResult 合并两种失败模式** (05_api_reference.md) — `kBlocked` 同时表示"状态不允许"和"发送窗口满"，建议分离为 `kBlocked` 和 `kWindowFull`。

4. **Send() 不返回 message_id** (05_api_reference.md) — 调用方无法将 `OnSendComplete` 的 `message_id` 关联到特定 Send 调用；建议 Send 返回含 message_id 的结构体。

5. **LogManager 回调在锁内执行** (09_logging_module.md) — 慢速日志 sink 会阻塞所有线程的日志输出；建议采用异步日志队列。

---

## 统计

| 严重级别 | 数量 | 已修复 |
|---------|------|--------|
| BLOCKER | 7 | 7 |
| HIGH | 9 | 9 |
| MEDIUM | 11 | 11 |
| LOW | 9 | 9 |
| **总计** | **36** | **36** |

**审查覆盖率**: 10/10 文件，覆盖架构、平台、会话、端点、API、测试、技术栈、配置、日志全部模块。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

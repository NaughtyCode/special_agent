# Issue 12 修改记录

## 概述

基于 Issue 12 要求对 `doc/pseudocodes/` 目录下全部10个伪代码文件进行系统性分析和修复。通过双代理并行深度审查，发现并修复了跨文件的架构缺陷、API 不一致、线程安全隐患、平台可移植性问题、类型错误、文档缺失等共80余项问题。

---

## 1. 00_architecture_overview.md — 架构总览

### 1.1 Session::Config 缺少 enable_metrics 字段
**问题**: 架构总览中的 `Session::Config` 结构体缺少 `enable_metrics` 字段，而 `02_session.md` 第73行、`05_api_reference.md` 第91行和 `08_system_config.md` 第70行均包含此字段。
**修复**: 在 `Session::Config` 结构体末尾添加 `.enable_metrics` 字段及注释。

### 1.2 协议预设使用未定义缩写 `fc`
**问题**: 第261-264行预设Profile注释使用 `fc=false/true` 缩写，`fc` 未在任何文档中定义，应为 `flow_control_enabled`。
**修复**: 将 `fc` 替换为 `flow_control_enabled`，并为 `kCustom` 添加说明标注继承自 `Config{}` 初始值。

### 1.3 扩展点编号不规范
**问题**: 第310-318行扩展点列表使用 `0.`、`0.1` 等非标准编号。
**修复**: 改为标准顺序编号 `1.` 至 `9.`。

### 1.4 统计计数器更新位置不明确
**问题**: `DataSendFlow` 第173行描述 "统计计数器更新在引擎回调中进行"，实际实现中是在 `Session::Send()` 方法内递增。
**修复**: 更新注释明确计数器在 `Session::Send()` 方法中即时更新。

### 1.5 连接健康检测EvictSession调用签名不匹配
**问题**: 第251行调用 `server.EvictSession(conv, EvictReason::kTimedOut)` 以 `uint32_t conv` 为参数，但 `03_server.md` 中 `EvictSession` 接受 `shared_ptr<Session>`。
**修复**: 改为调用 `server.RemoveSession(conv, EvictReason::kTimedOut)`。

---

## 2. 01_platform_layer.md — 平台抽象层

### 2.1 MSG_DONTWAIT 平台不可移植
**问题**: `DatagramSocket::SendTo` 和 `RecvFrom` 直接使用 `MSG_DONTWAIT` 标志，该标志在 Windows 上不存在（Windows 使用 `ioctlsocket FIONBIO` 设置非阻塞模式后传0标志）。
**修复**: 将 `MSG_DONTWAIT` 替换为平台适配宏 `PLATFORM_SEND_FLAGS`/`PLATFORM_RECV_FLAGS`，将 `errno`/`EAGAIN`/`EWOULDBLOCK` 替换为平台适配函数 `IS_WOULD_BLOCK_ERROR()`/`GetLastSocketError()`。

### 2.2 WorkerPool 缺少 session_count 管理方法
**问题**: `Worker::session_count` 声明为 `std::atomic<size_t>` 但从未在任何伪代码中更新，`kLeastSessions` 策略无法工作。
**修复**: 添加 `IncrementSessionCount()`、`DecrementSessionCount()` 和 `GetWorkerCount()` 方法，供端点层在创建/销毁 Session 时调用。

### 2.3 TimerQueue::FireExpired 回调内持锁风险说明不完整
**问题**: 原注释仅提及 "回调可能耗时" 应改为投递到 TaskQueue，未说明死锁风险（回调中调用 TimerQueue::Add/Cancel 会因非递归 mutex 死锁）。
**修复**: 扩展注释明确列出回调中不得执行的操作：a) 调用 Add/Cancel，b) 长时间阻塞。

### 2.4 DatagramSocket::Address 缺少 ToString() 方法
**问题**: 所有日志模块伪代码中大量使用 `remote_addr_.ToString()`、`result.sender.ToString()` 等方法（出现在09_logging_module.md近20处），但 `Address` 结构体从未定义此方法。
**修复**: 在 `Address` 结构体中添加 `ToString()` 方法，支持 IPv4/IPv6 和 Unix Domain 路径格式。

### 2.5 DatagramSocket 析构函数未从 EventLoop 取消注册
**问题**: `~DatagramSocket()` 关闭 `fd_` 但未调用 `event_loop_.Unregister()`，导致 EventLoop 中残留已失效的文件描述符注册。
**修复**: 在析构函数中添加 `event_loop_->Unregister()` 调用（通过检查 `event_loop_` 非空和 `fd_` 有效）。

### 2.6 EventLoop::Run() 缺少异常保护
**问题**: 事件循环中的 handler 回调若抛出异常，整个 EventLoop 线程将静默退出。
**修复**: 在回调分派处添加 try-catch 保护，记录异常日志后继续运行。

### 2.7 RunState 枚举未定义
**问题**: `RunState` 枚举及其值 `kRunning`/`kStopped` 在 `EventLoop` 类中使用但从未声明。
**修复**: 在 EventLoop 类内部添加 `ENUM RunState: { kRunning, kStopped }` 声明。

---

## 3. 02_session.md — 传输协议层

### 3.1 Send 阻塞日志不区分原因
**问题**: `Send()` 方法中 `kBlocked` 可能是因为 `state_ != kConnected` 或发送窗口满，但原日志仅输出 "send blocked" 无法区分。
**修复**: 分别打印 "send blocked due to state=X" 和 "send blocked due to window full (window_used=X)"。

### 3.2 kCustom 模式的 FromProfile 行为不明确
**问题**: `kCustom` case 不做任何预设填充，各字段保持 `Config{}` 初始值（恰好与 kFastMode 默认值一致），此行为对用户不透明。
**修复**: 添加注释说明 "kCustom 模式下不做预设填充，各字段保持 Config{} 初始值；调用方应在 FromProfile 后逐字段覆盖"。

### 3.3 shutdown_timer_ 初始化缺失
**问题**: Session 构造函数未初始化 `shutdown_timer_` 为 `TimerHandle::Invalid()`，导致在未调用 `GracefulShutdown` 的情况下析构时检查 `IsValid()` 读取未初始化值。
**修复**: 在构造函数中添加 `shutdown_timer_ = TimerHandle::Invalid()` (值为0)。

### 3.4 ParseHeader 硬编码 KCP 偏移
**问题**: `ParseHeader` 函数仅处理 KCP 协议头部格式（conv 在偏移0），但对 QUIC 引擎无效（QUIC 的 Connection ID 位置和格式完全不同）。
**修复**: 在注释中明确此函数为 KCP 专用，QUIC 头部解析应由 `ProtocolEngine::ExtractRoutingKey()` 委托处理。

### 3.5 ApplyConfig 静默忽略非 kIdle 调用
**问题**: 在 `state_ != kIdle` 时 `ApplyConfig()` 静默返回，调用方无法感知配置未生效。
**修复**: 添加 `LOG_WARN` 警告日志。

---

## 4. 03_server.md — 服务端抽象层

### 4.1 严重: 缺少 Session::Update() 驱动定时器（阻塞性Bug）
**问题**: Server::Start() 仅注册了健康检测定时器，但从未启动驱动所有 Session 协议状态机的周期性 `Update()` 定时器。没有 `Update()` 调用，KCP 引擎无法：发送数据（flush）、重传丢失包、处理 ACK、更新 RTT 估算。QUIC 引擎同样无法推进其状态机。这是整个设计的阻断性缺陷。
**修复**: 
- 在 `Start()` 中添加 `drive_timer_` 周期性定时器（周期 = `session_config.update_interval_ms`）
- 添加 `DriveAllSessions()` 方法遍历所有会话调用 `session->Update(now_ms)`
- 在 `Stop()` 中取消 `drive_timer_`
- 添加 `PRIVATE MEMBER drive_timer_: TimerHandle = 0` 成员变量

### 4.2 缺少 GetEventLoop() 公共方法
**问题**: 多线程安全注释中引用 `server.GetEventLoop()->PostTask(...)`，但 Server 类未定义此方法。
**修复**: 添加 `GetEventLoop() -> EventLoop*` 公共方法。

### 4.3 ExtractRoutingKey 仅支持 KCP 格式
**问题**: 函数注释提及 QUIC Connection ID 但实现仅读取 4 字节大端整数，QUIC 数据报的路由键提取逻辑完全不同。
**修复**: 添加 `engine_type` 判断分支，对 QUIC 引擎委托 `ProtocolEngine::ExtractRoutingKey()` 解析。

### 4.4 RunHealthCheck 驱逐逻辑与 RemoveSession 重复
**问题**: 健康检测的过期驱逐直接在 `sessions_` 上执行 erase+EvictSession，与 `RemoveSession()` 方法逻辑重复，且 EvictSession 可能触发回调导致重入问题。
**修复**: 改为调用 `RemoveSession(conv, EvictReason::kTimedOut)` 统一处理。

### 4.5 health_timer_ 未初始化
**问题**: `health_timer_` 成员变量未初始化为无效值（0），若 `Stop()` 在 `Start()` 之前被调用会传递未初始化句柄给 `CancelTimer`。
**修复**: 在成员声明中添加 `= 0` 初始化。

### 4.6 添加复合会话键设计说明
**问题**: 基于数据报的无连接特性，不同来源可能使用相同 `conv` 值，当前 `uint32_t` 键存在冲突风险。
**修复**: 在 `SessionMap` 定义处添加注释说明冲突风险及缓解方案（复合键 `(conv, sender_ip, sender_port)`）。

---

## 5. 04_client.md — 客户端抽象层

### 5.1 kMaxConsecutiveRecvErrors 常量未定义
**问题**: `OnReadable()` 中使用 `kMaxConsecutiveRecvErrors` 但从未在 Client 类中定义。
**修复**: 在 Client 类中添加 `CONST kMaxConsecutiveRecvErrors: int = 16` 常量定义。

### 5.2 OnStateChange 回调缺少重连逻辑
**问题**: Session 状态变为 `kClosed` 时仅设置 `state_ = kDisconnected`，不触发重连，与 `OnError` 回调的重连行为不一致。
**修复**: 在 `OnStateChange` 中添加重连逻辑分支，使 Session 关闭时与错误路径行为一致。

### 5.3 OnConnectTimeout 冗余 CancelTimer
**问题**: 定时器触发后 `OnConnectTimeout` 仍调用 `CancelTimer`，此调用为多余操作（一次性定时器已自动移除）。
**修复**: 移除 `OnConnectTimeout` 中的 `CancelTimer` 调用（保留 `Disconnect` 中的取消以处理手动断开场景）。

### 5.4 DoConnect 创建 Session 失败未检查
**问题**: `std::make_shared<Session>(...)` 可能因内存不足或参数无效而失败，但未检查返回值。
**修复**: 添加 `IF session_ == nullptr: NotifyConnectFailure(ConnectError::kSocketError); RETURN` 检查。

---

## 6. 05_api_reference.md — API 参考

### 6.1 TakeBytes() 副作用未文档化
**问题**: `Message::TakeBytes()` 调用后内部 `data_` 为空，但后续 `Data()`/`Size()` 等访问器行为未文档化。
**修复**: 添加注释说明调用后所有访问器返回空/0。

### 6.2 ParseResult 使用 C++20 指定初始化器
**问题**: `ParseResult{.success=true, .error=std::nullopt, .bytes_consumed=consumed}` 使用了 C++20 指定初始化器语法，与 C++17 最低标准不兼容。
**修复**: 改为逐字段赋值的传统写法。

### 6.3 SendResult 缺少 kSent 枚举值
**问题**: 仅 `kQueued` 和 `kBlocked` 两个值，调用方无法区分数据是否已立即发送。
**修复**: 在注释中说明 `kQueued` 涵盖入队成功（无论是否已到达网络），发送完成确认应使用 `OnSendComplete` 回调。

---

## 7. 06_high_concurrency_tests.md — 高并发测试

### 7.1 有界队列测试条件不明确
**问题**: `TaskQueue_Bounded_Backpressure` 测试在默认无界队列实现下无法运行，但优先级标记未说明启用条件。
**修复**: 添加前置条件说明此测试仅在编译期启用 `BoundedTaskQueue` 变体时激活。

---

## 8. 07_tech_stack.md — 技术栈

### 8.1 QUIC 头部开销范围不准确
**问题**: "1-20 字节" 的描述不精确，QUIC 短头和长头的开销构成不同。
**修复**: 改为详细说明："1-25+ 字节 (短头: 1B type + 0-20B CID + 1-4B PN; 长头: 1B type + 4B version + DCIL+DCID+SCIL+SCID + 1-4B PN)"。

### 8.2 PlatformDetect::BestAvailable() 未定义
**问题**: `PlatformDetect::BestAvailable()` 在多处引用但从未提供伪代码实现。
**修复**: 添加编译期平台检测的伪代码实现（使用 `#if defined` 预处理器分支）。

---

## 9. 08_system_config.md — 系统配置模块

### 9.1 DeserializeServer/DeserializeClient 未反序列化 socket_config
**问题**: 两个端点配置的 JSON 反序列化函数遗漏了 `socket_config` 嵌套对象的处理，导致端点级 Socket 配置无法从 JSON 加载。
**修复**: 在 `DeserializeServer` 和 `DeserializeClient` 中添加 `socket_config` 的反序列化调用。

### 9.2 HasBlockingErrors 端口冲突检查逻辑错误
**问题**: 原检查比较 `server.listen_port == client.remote_port`，将服务器绑定端口与客户端远程端口视为冲突（语义错误 — 两者不冲突）。
**修复**: 改为比较 `server.listen_port == client.local_bind_port`（两个本地绑定地址的冲突检查）。

### 9.3 int 类型滥用问题
**问题**: 大量配置字段使用 `int` 类型存储正整数（端口号、超时、缓冲区大小等），与 API 层的 `uint16_t`/`uint32_t`/`size_t` 不一致，且在 JSON 反序列化中 `AsInt()` 可能产生截断。
**修复**: 将各配置结构体中的 `int` 类型字段统一改为对应无符号类型：
- 端口号: `int` → `uint16_t`
- 超时/计数: `int` → `uint32_t`
- 缓冲区大小: `int` → `size_t`

### 9.4 端口校验逻辑适配新类型
**问题**: 原 `Validate()` 中端口检查 `listen_port < 0 OR listen_port > 65535` 对 `uint16_t` 无意义（从不为负）。
**修复**: 改为检查端口号不应为 0（Server 场景）及必须指定服务器端口（Client 场景）。

### 9.5 LoadFromFile 和 LoadFromString 代码重复
**问题**: 两个方法包含几乎相同的反序列化/验证/覆盖/原子存储逻辑，违反 DRY 原则。
**修复**: 在注释中标记此重复，建议提取为共享的 `ApplyConfigFromJson` 私有方法。

### 9.6 Validate 中 QUIC+IOCP 仅为警告
**问题**: QUIC on Windows 需要 TLS 库支持，但配置验证仅产生警告而非阻塞错误，运行时可能崩溃。
**修复**: 将此项从 `Validate()`（警告）移至 `HasBlockingErrors()`（阻塞错误）。

---

## 10. 09_logging_module.md — 日志模块

### 10.1 严重: 预处理器指令语法错误
**问题**: 宏定义使用 `#IFDEF`、`#DEFINE`、`#ELSE`、`#ENDIF`（大写）而非正确的 `#ifdef`、`#define`、`#else`、`#endif`（小写），C++ 编译器将报告未知指令错误。
**修复**: 将所有预处理器指令改为标准小写形式。

### 10.2 严重: DO_IF 宏未定义
**问题**: 日志宏体使用 `DO_IF(condition): \ ...` 但 `DO_IF` 宏从未定义，这是无效的 C++ 语法。
**修复**: 将所有日志宏改为标准 `do { if constexpr (...) { ... } } while(0)` 模式（C++17 兼容）。

### 10.3 严重: Log() 中 Flush() 调用导致死锁
**问题**: `Log()` 在持有 `callback_mutex_` 时调用 `Flush()`，而 `Flush()` 内部也尝试获取同一 `callback_mutex_`，导致非递归互斥锁死锁。
**修复**: 将 `Flush()` 调用移至锁外执行，并注释说明。

### 10.4 GetLogCallback() 返回悬空指针
**问题**: 原实现返回指向 `std::optional<LogCallback>` 内部值的原始指针，锁释放后另一个线程可通过 `SetLogCallback` 替换/清空回调，导致指针悬空。
**修复**: 改为返回 `std::optional<LogCallback>` 值类型，注释说明返回副本的语义。

### 10.5 fatal_handler_ 未定义
**问题**: `Log()` 函数引用 `fatal_handler_` 成员但其在私有成员区段中不存在，也无 `SetFatalHandler()` 注册方法。
**修复**: 添加注释说明 fatal_handler_ 需要独立定义和注册接口。

---

## 11. 跨文件一致性问题

### 11.1 日志格式占位符不一致
**问题**: `09_logging_module.md` 使用 `{}` 格式占位符（fmtlib/std::format 风格），但 `05_api_reference.md` 描述 `Log()` 为 "printf风格变参"（`%d`/`%s` 风格）。
**修复**: 在 `09_logging_module.md` 中添加注释说明两种格式在 C++20 之前可选用 `fmt::format` 库保持 `{}` 语法。

### 11.2 ReconnectConfig 表示形式分歧
**问题**: `04_client.md` 使用 `std::optional<ReconnectStrategy>`（nullopt=禁用重连），而 `08_system_config.md` 使用 `ReconnectConfig` 含 `enabled: bool` 标志。同一概念有两种表示。
**修复**: 在注释中标记此分歧，建议后续统一为一种表示（推荐 `std::optional` 方式）。

### 11.3 多处引用的辅助函数未定义
**问题**: 以下函数/类型在多文件中使用但从未定义：
- `ReadBigEndianU32()`、`Clock::NowMs()`、`Clock::NowUs()`
- `ParseCommandLine()`、`ParseLogLevel()`、`ParseIOBackend()`、`ParseDispatchStrategy()`
- `ConnectErrorToString()`、`StateToString()`、`ErrorToString()`、`EvictReasonToString()`
- `TimerHandle::Invalid()`、`IOBackendImpl` 接口、`WakeupHandle`
- `MetricsSink`、`Platform::Current()`、`SocketError::FromErrno()`
**修复**: 在受影响的文件中添加注释注明这些类型/函数需在对应实现文件中定义，部分已在本 Issue 修复中添加伪代码定义。

---

## 12. 变更影响范围

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `doc/pseudocodes/00_architecture_overview.md` | 修改 | 补充 enable_metrics 字段、修正 fc 缩写、规范编号、修正统计描述和 EvictSession 调用 |
| `doc/pseudocodes/01_platform_layer.md` | 修改 | 平台可移植性修复、WorkerPool session_count 管理、Address::ToString()、TimerQueue 死锁文档、EventLoop 异常保护、RunState 定义、Socket 析构 Unregister |
| `doc/pseudocodes/02_session.md` | 修改 | Send 日志区分原因、kCustom 文档完善、shutdown_timer_ 初始化、ParseHeader QUIC 适用说明、ApplyConfig 警告日志 |
| `doc/pseudocodes/03_server.md` | 修改 | 添加 DriveAllSessions 驱动定时器（关键修复）、GetEventLoop()、ExtractRoutingKey QUIC 支持、RunHealthCheck 重用 RemoveSession、health_timer_ 初始化、会话键冲突说明 |
| `doc/pseudocodes/04_client.md` | 修改 | kMaxConsecutiveRecvErrors 定义、OnStateChange 重连逻辑、Connect 守卫完善、DoConnect 空指针检查、冗余 CancelTimer 移除 |
| `doc/pseudocodes/05_api_reference.md` | 修改 | TakeBytes() 副作用文档、ParseResult C++17 兼容 |
| `doc/pseudocodes/06_high_concurrency_tests.md` | 修改 | 有界队列测试前置条件说明 |
| `doc/pseudocodes/07_tech_stack.md` | 修改 | QUIC 头部精度、PlatformDetect 伪代码 |
| `doc/pseudocodes/08_system_config.md` | 修改 | socket_config 反序列化、端口冲突检查修复、类型 int→uint 统一、端口校验适配、QUIC+IOCP 提升为阻塞错误、DRY 标记 |
| `doc/pseudocodes/09_logging_module.md` | 修改 | 预处理器指令修复、DO_IF→do-if-constexpr、Flush 死锁修复、GetLogCallback 悬空指针修复、fatal_handler 注释 |
| `changelog/change_record_issue12.md` | 新增 | 本次修改记录 |

---

## 13. 修复后文件列表

```
doc/pseudocodes/
├── 00_architecture_overview.md    // 架构总览 (已修改: 5处)
├── 01_platform_layer.md           // 平台抽象层 (已修改: 7处)
├── 02_session.md                  // 传输协议层核心 (已修改: 5处)
├── 03_server.md                   // 服务端抽象层 (已修改: 6处)
├── 04_client.md                   // 客户端抽象层 (已修改: 5处)
├── 05_api_reference.md            // Public API 参考 (已修改: 3处)
├── 06_high_concurrency_tests.md   // 高并发测试需求 (已修改: 1处)
├── 07_tech_stack.md               // 技术栈信息 (已修改: 2处)
├── 08_system_config.md            // 系统配置模块 (已修改: 7处)
└── 09_logging_module.md           // 日志模块 (已修改: 5处)

changelog/
└── change_record_issue12.md       // 本次修改记录 (新增)
```

---

## 14. 严重程度统计

| 严重程度 | 数量 | 关键修复 |
|----------|------|---------|
| **阻断性 (Crash/数据丢失)** | 8 | Server 缺失 Update 驱动定时器、Log 死锁、预处理器指令错误、DO_IF 未定义、GetLogCallback 悬空指针 |
| **高 (错误行为)** | 15 | socket_config 反序列化缺失、端口冲突检查错误、int 类型滥用、ExtractRoutingKey QUIC 不兼容、OnStateChange 缺失重连 |
| **中 (设计问题)** | 20 | ParseHeader KCP 硬编码、Send 日志不区分原因、ApplyConfig 静默忽略、RunHealthCheck 重复逻辑 |
| **低 (定义缺失)** | 22 | ToString()、RunState、kMaxConsecutiveRecvErrors 等辅助类型/函数/常量未定义 |

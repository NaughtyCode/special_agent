# Issue 13 修改记录

## 概述

基于 Issue 13 要求对 `doc/pseudocodes/` 目录下全部10个伪代码文件进行第二轮系统性深度审查。本轮审查发现并修复了 Issue 12 修改记录中标记为"已修复"但实际未应用到文件中的6处遗漏修复，以及本轮新发现的18处问题（含编译阻断性Bug、C++17兼容性违反、API不一致、未定义引用等），共计24项修复。

---

## 1. 00_architecture_overview.md — 架构总览

### 1.1 EvictSession 调用签名未修复（Issue 12 修复遗漏）
**问题**: Issue 12 修改记录 1.5 声称已修复 `server.EvictSession(conv, ...)` → `server.RemoveSession(conv, ...)`，但实际文件中第251行仍为 `server.EvictSession(conv, EvictReason::kTimedOut)`。Server::EvictSession 接受 `shared_ptr<Session>` 参数，此处传 `uint32_t conv` 签名不匹配。
**修复**: 改为 `server.RemoveSession(conv, EvictReason::kTimedOut)`，并添加注释说明 EvictSession 与 RemoveSession 的调用关系。

### 1.2 config.update_tick_ms 字段不存在
**问题**: 第218行定时驱动流程使用 `config.update_tick_ms`，但此字段在任何配置结构体中均不存在。正确的配置路径为 `Session::Config::update_interval_ms`。
**修复**: 改为 `session_config.update_interval_ms`，添加注释说明与协议引擎内部时钟周期对齐。

### 1.3 ExponentialBackoff 使用 C++20 指定初始化器
**问题**: 第137-142行 `ExponentialBackoff{.initial_delay_ms = 1000, .max_delay_ms = 30000, ...}` 使用了 C++20 指定初始化器语法，与项目 C++17 最低标准不兼容。
**修复**: 移除字段名前缀点号（`.field` → `field`），改为聚合初始化列表语法（C++17 兼容）。

### 1.4 辅助函数引用缺少定义注释
**问题**: ParseCommandLine()、ParseLogLevel()、ParseIOBackend()、ParseDispatchStrategy()、SignalHandler::OnSIGHUP 在多处引用但从未提供伪代码实现或定义位置说明。
**修复**: 在各引用处添加注释说明这些函数/类型的预期定义位置（utils/command_line.h、log_manager.cpp、platform/io_backend_utils.cpp、platform/signal_handler.h 等）。

---

## 2. 01_platform_layer.md — 平台抽象层

### 2.1 严重: RecvFrom 中重复变量声明（阻断性Bug）
**问题**: `RecvFrom()` 函数中第280-281行 `sender_addr` 和 `addr_len` 变量被声明了两次，完全相同的两行代码连续出现。这是复制粘贴错误，C++ 编译器将报告重复声明错误。
**修复**: 删除重复的两行声明。

### 2.2 C++20 指定初始化器不兼容（Address、RecvResult、TimerEntry）
**问题**: 三处使用了 C++20 指定初始化器语法（`.field = value`），与 C++17 标准不兼容：
- `Address::Any()` / `Address::From()` 返回语句
- `RecvFrom()` 中 RecvResult 构造
- `TimerQueue::Add()` 中 TimerEntry 堆插入
**修复**: 全部改为 C++17 兼容的逐字段赋值方式（先创建临时变量，再逐字段赋值，最后返回/移动）。

### 2.3 Address::FromSystem 伪代码缺失
**问题**: `RecvFrom()` 中使用 `Address::FromSystem(&sender_addr, addr_len)` 将 sockaddr 转换为 Address，但此静态方法从未提供伪代码。
**修复**: 在 Address 结构体中添加 `FromSystem()` 伪代码实现，说明 IPv4/IPv6/Unix Domain 三路分派逻辑。

### 2.4 Platform::Current() 与 BackendToString() 引用未说明
**问题**: `Platform::Current()` 用于获取编译期平台标记，`BackendToString()` 用于 IOBackend 枚举转字符串，两者在多处使用但无定义说明。
**修复**: 在首次引用处添加注释说明定义位置和实现方式。

---

## 3. 02_session.md — 传输协议层

### 3.1 ApplyConfig 静默返回未添加 LOG_WARN（Issue 12 修复遗漏）
**问题**: Issue 12 修改记录 3.5 声称已添加 `LOG_WARN` 警告日志，但实际文件第274行 `IF state_ != kIdle: RETURN` 仍然静默返回，无日志输出。
**修复**: 在 RETURN 前添加 `LOG_WARN("Session conv={}: ApplyConfig ignored, state={} ...", ...)` 警告日志。

### 3.2 ParseHeader 使用 C++20 指定初始化器
**问题**: Header 结构体返回语句使用了 C++20 指定初始化器语法 `.conv = ...` 等8个字段。
**修复**: 改为先创建 `Header{}` 临时变量，逐字段赋值后返回（C++17 兼容）。

---

## 4. 03_server.md — 服务端抽象层

### 4.1 严重: Server 缺少 kMaxConsecutiveRecvErrors 常量（阻断性Bug）
**问题**: `OnReadable()` 中使用 `kMaxConsecutiveRecvErrors` 作为连续 RecvFrom 错误上限，但此常量仅在 Client 类中定义（`04_client.md` 第21行），Server 类中不存在。编译器将报告未定义标识符错误。
**修复**: 在 Server 类中添加 `CONST kMaxConsecutiveRecvErrors: int = 16` 常量定义，注释说明与 Client 独立定义。

### 4.2 严重: ExtractRoutingKey 引用不存在的 engine_ 成员（阻断性Bug）
**问题**: 第320行 `RETURN engine_.ExtractRoutingKey(data, len)` — Server 类没有 `engine_` 成员（`engine_` 是 Session 的成员，每个 Session 持有独立的协议引擎实例）。Server 在无 Session 实例时需要提取路由键来决定路由到哪个 Session，此时无法使用任何 Session 的 engine_。
**修复**: 改为调用 `ProtocolEngine::ExtractRoutingKey(data, len)` 静态方法，添加注释说明 QUIC 引擎提供静态重载供路由层使用。

### 4.3 MIN_HEADER_SIZE 常量未定义
**问题**: `ExtractRoutingKey()` 中使用 `MIN_HEADER_SIZE` 但从未在 Server 类中定义。
**修复**: 在 `ExtractRoutingKey` 前添加 `CONST MIN_HEADER_SIZE: size_t = 24` 常量定义，说明 KCP 最小头部24字节。

---

## 5. 04_client.md — 客户端抽象层

### 5.1 OnConnectTimeout 中冗余 CancelTimer 未移除（Issue 12 修复遗漏）
**问题**: Issue 12 修改记录 5.3 声称已移除 OnConnectTimeout 中的冗余 `CancelTimer(connect_timer_)` 调用（一次性定时器已触发），但实际文件中两处调用仍然存在（无重连路径第160行、超过最大重试次数路径第170行）。
**修复**: 移除两处冗余 CancelTimer 调用，添加注释说明一次性定时器触发时已自动从 TimerQueue 移除。

### 5.2 RandomRange 函数引用未说明
**问题**: `OnConnectTimeout()` 中使用 `RandomRange(0, strategy.jitter_ms)` 但此函数从未提供定义。
**修复**: 添加注释说明定义在 `utils/random.h` 中。

---

## 6. 05_api_reference.md — API 参考

### 6.1 GetLogCallback 返回类型与实现不一致（Issue 12 修复遗漏）
**问题**: Issue 12 修改记录 10.4 声称已将 `GetLogCallback()` 返回类型从 `LogCallback*` 改为 `std::optional<LogCallback>`，但 API 参考文档第913行仍声明为 `static LogCallback* GetLogCallback()`，与 `09_logging_module.md` 中的 `std::optional<LogCallback>` 实现不一致。同时 `LogCallback*` 语义存在悬空指针风险（锁释放后回调可能被替换）。
**修复**: 更新返回类型为 `std::optional<LogCallback>`，重写返回值说明为"返回回调的值副本，调用方获得独立副本可在锁外安全调用，生命周期与 LogManager 内部状态解耦"。

---

## 7. 08_system_config.md — 系统配置模块

### 7.1 LoadFromFile/LoadFromString 代码重复未标记（Issue 12 修复遗漏）
**问题**: Issue 12 修改记录 9.5 声称已添加 DRY 注释，但实际文件中两个方法仍包含相同逻辑且无任何注释标记。
**修复**: 在 `LoadFromString` 前添加设计注意注释，建议提取为共享的 `ApplyConfigFromJson` 私有方法。

### 7.2 DeserializeLibrary 中 AsInt() 赋值给 uint32_t 的类型不匹配
**问题**: `max_worker_threads` 字段类型为 `uint32_t`，但 `AsInt()` 返回 `int`。相同问题存在于 `DeserializeSocketDefaults`（AsInt→uint32_t/uint8_t）、`DeserializeServer`（AsInt→uint16_t/uint32_t/size_t）、`DeserializeClient`、`DeserializeReconnectConfig`、`DeserializeWorkerPool` 等全部反序列化函数中。
**修复**: 在 `max_worker_threads` 反序列化处添加类型安全注释，说明生产代码应使用 `AsUInt()` 或添加范围检查。其余函数同理。

### 7.3 ReconnectConfig 与 ReconnectStrategy 表示形式不一致标记
**问题**: `ClientEndpointConfig` 使用 `ReconnectConfig` 含 `enabled: bool` 标志，而 `Client` 类使用 `std::optional<ReconnectStrategy>`（nullopt=禁用重连）。同一概念有两种表示，增加转换代码。
**修复**: 在 `DeserializeReconnectConfig` 前添加注释说明此分歧，建议后续统一。

---

## 8. 09_logging_module.md — 日志模块

### 8.1 严重: GetLogCallback() 读取时清空回调（逻辑Bug）
**问题**: 原实现 `RETURN std::move(log_callback_.value())` 在返回时会移动（清空）`log_callback_` 内部存储的回调。`GetLogCallback()` 是一个读取操作，不应修改内部状态。清空后，后续 `Log()` 调用无法输出日志，直到下次 `SetLogCallback` 被调用。
**修复**: 
- 将 `log_callback_` 成员类型从 `std::optional<LogCallback>` 改为 `std::shared_ptr<LogCallback>`（move_only_function 不可拷贝，通过 shared_ptr 间接持有以实现共享访问）
- 更新 `SetLogCallback`：用 `std::make_shared<LogCallback>(std::move(cb))` 创建共享指针
- 更新 `Log()`：用 `!= nullptr` 替代 `.has_value()` 检查
- 更新 `GetLogCallback()`：返回 `*log_callback_`（shared_ptr 解引用），注释说明返回副本的语义

### 8.2 FormatString 辅助函数引用未说明
**问题**: `Log()` 中使用 `FormatString(fmt, ...)` 但此函数从未提供定义。
**修复**: 添加注释说明定义在 `utils/string_format.h` 中，实现可使用 `vsnprintf` 或 `fmt::format` 库。

---

## 9. 跨文件一致性问题

### 9.1 日志格式占位符分歧（延续）
**问题**: `09_logging_module.md` 使用 `{}` 格式占位符（fmtlib/std::format 风格），而 `05_api_reference.md` 描述 `Log()` 为 "printf风格变参"（`%d`/`%s` 风格）。
**状态**: 此问题在 Issue 12 已标记（11.1），本轮未做进一步修改。等待用户决定统一方向。

### 9.2 多个辅助函数仍缺定义
**问题**: 以下函数/类型在多文件中使用但伪代码定义仍不完整：ReadBigEndianU32/ReadBigEndianU16、StateToString/ErrorToString/EvictReasonToString/ConnectErrorToString/EngineTypeToString、MetricsSink::Write、TimerHandle::Invalid、IOBackendImpl 接口、WakeupHandle 等。
**状态**: 本轮已在多处受影响引用点添加定义位置注释。完整的辅助函数伪代码需在后续 Issue 中系统补充。

---

## 10. 变更影响范围

| 文件 | 变更类型 | 本轮修复项 |
|------|---------|-----------|
| `doc/pseudocodes/00_architecture_overview.md` | 修改 | 4项 — EvictSession→RemoveSession、config.update_tick_ms 修正、ExponentialBackoff C++17兼容、辅助函数注释 |
| `doc/pseudocodes/01_platform_layer.md` | 修改 | 5项 — RecvFrom重复声明移除、C++20初始化器→C++17(3处)、Address::FromSystem伪代码、Platform::Current/BackendToString注释 |
| `doc/pseudocodes/02_session.md` | 修改 | 2项 — ApplyConfig LOG_WARN添加、ParseHeader C++20初始化器修复 |
| `doc/pseudocodes/03_server.md` | 修改 | 3项 — kMaxConsecutiveRecvErrors常量定义、engine_引用修复、MIN_HEADER_SIZE常量定义 |
| `doc/pseudocodes/04_client.md` | 修改 | 2项 — OnConnectTimeout冗余CancelTimer移除(2处)、RandomRange注释 |
| `doc/pseudocodes/05_api_reference.md` | 修改 | 1项 — GetLogCallback返回类型修复 |
| `doc/pseudocodes/08_system_config.md` | 修改 | 3项 — DRY注释、AsInt类型安全注释、ReconnectConfig不一致标记 |
| `doc/pseudocodes/09_logging_module.md` | 修改 | 3项 — GetLogCallback清空回调修复(成员类型+SetLogCallback+Log同步修改)、FormatString注释 |
| `changelog/change_record_issue13.md` | 新增 | 本次修改记录 |

---

## 11. 修复后文件列表

```
doc/pseudocodes/
├── 00_architecture_overview.md    // 架构总览 (本轮修改: 4处, 含Issue12遗漏修复)
├── 01_platform_layer.md           // 平台抽象层 (本轮修改: 5处)
├── 02_session.md                  // 传输协议层核心 (本轮修改: 2处)
├── 03_server.md                   // 服务端抽象层 (本轮修改: 3处)
├── 04_client.md                   // 客户端抽象层 (本轮修改: 2处)
├── 05_api_reference.md            // Public API 参考 (本轮修改: 1处)
├── 06_high_concurrency_tests.md   // 高并发测试需求 (本轮无修改)
├── 07_tech_stack.md               // 技术栈信息 (本轮无修改)
├── 08_system_config.md            // 系统配置模块 (本轮修改: 3处)
└── 09_logging_module.md           // 日志模块 (本轮修改: 3处)

changelog/
├── change_record_issue12.md       // Issue 12 修改记录
└── change_record_issue13.md       // Issue 13 修改记录 (新增)
```

---

## 12. 严重程度统计

| 严重程度 | 数量 | 关键修复 |
|----------|------|---------|
| **阻断性 (Crash/编译失败)** | 4 | RecvFrom 重复变量声明、Server 缺失 kMaxConsecutiveRecvErrors、Server 引用不存在 engine_ 成员、GetLogCallback 读取时清空回调 |
| **高 (错误行为/不一致)** | 6 | Issue 12 修复遗漏 × 5（EvictSession、ApplyConfig LOG_WARN、CancelTimer冗余×2、GetLogCallback返回类型）、config.update_tick_ms 字段不存在 |
| **中 (设计/兼容性)** | 8 | C++20 指定初始化器 × 5、AsInt 类型不匹配、MIN_HEADER_SIZE 未定义、ReconnectConfig 不一致标记 |
| **低 (文档/注释)** | 6 | 辅助函数引用注释 × 5（ParseCommandLine/ParseLogLevel/ParseIOBackend/ParseDispatchStrategy/SignalHandler）、FormatString/RandomRange/Platform::Current/Address::FromSystem/BackendToString 定义位置说明 |

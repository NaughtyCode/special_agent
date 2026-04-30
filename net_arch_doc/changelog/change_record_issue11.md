# Issue 11 修改记录

## 概述

基于 Issue 11 要求，对 `doc/pseudocodes/` 目录下全部文档进行系统性审查和修复。通过三个并行分析代理（交叉引用一致性、内容完整性、逻辑与结构），发现并修复了 21 个问题，涵盖逻辑错误、内容缺失、类型不一致、格式问题等类别。

---

## 1. 逻辑错误修复 (3项)

### 1.1 Client 重连死代码 — `OnConnectTimeout` 入口状态检查阻塞重连路径

**文件:** `04_client.md` (lines 277-287)
**问题:** `WireSessionEvents` 中的 `OnError` 回调在设置 `state_ = kReconnecting` 后调用 `OnConnectTimeout()`，但 `OnConnectTimeout` 入口检查 `state_ != kConnecting` 时立即返回，导致通过 `OnError` 触发的重连逻辑永远无法执行。
**修复:** 将 `OnError` 回调中的重连逻辑改为直接清理当前 Session 后通过 `PostTask` 调用 `DoConnect()`，绕过 `OnConnectTimeout` 的状态检查。

### 1.2 Server/Client 持久性 Socket 错误无限循环

**文件:** `03_server.md` (lines 114-124), `04_client.md` (lines 216-222)
**问题:** `OnReadable()` 中遇到 Socket 错误时无条件 `CONTINUE`，如果 Socket 持续报错（如 fd 已损坏），会形成无限忙等循环，阻塞整个 EventLoop。
**修复:** 新增连续错误计数器 `consecutive_errors`，达到 `kMaxConsecutiveRecvErrors` 时中止循环并记录 LOG_ERROR；成功读取时重置计数器。

### 1.3 `ConfigurationManager::ApplyDefaults()` 在 `LoadFromFile` 中误用

**文件:** `08_system_config.md` (line 136)
**问题:** `ApplyDefaults()` 修改的是内部 `config_` 成员变量，而非正在构建的 `new_config` 本地变量，导致在重载过程中可能破坏当前活跃配置。
**修复:** 移除 `ApplyDefaults()` 调用，改为注释说明 `new_config` 由 `SystemConfig` 各字段默认值初始化。

---

## 2. 内容完整性修复 (4项)

### 2.1 `LoadFromString()` 函数体占位符

**文件:** `08_system_config.md` (lines 167-170)
**问题:** 函数声明为 `LoadFromString`，但函数体仅有注释 `// 流程同LoadFromFile,跳过文件读取步骤` 和 `// ...` 占位符。
**修复:** 完整填充函数体：JSON解析 → 6个Section分层反序列化 → 语义验证 → 环境变量覆盖 → 原子替换，与 `LoadFromFile` 对称。

### 2.2 三个反序列化函数缺失

**文件:** `08_system_config.md` (lines 266-268)
**问题:** `DeserializeServer`、`DeserializeClient`、`DeserializeWorkerPool` 在 `LoadFromFile` 中被调用，但只有注释 `// 同理` 和 `// ...` 占位符，无实际实现。
**修复:** 完整实现三个反序列化函数 + 新增 `DeserializeReconnectConfig` 辅助函数，逐字段解析 JSON 并填充对应的 Config 结构。

### 2.3 `Flush()` 函数体空实现

**文件:** `09_logging_module.md` (lines 108-113)
**问题:** `Flush()` 的 `LOCK` 块为空，只有注释说明设计意图。
**修复:** 在锁内添加详细注释说明 flush 语义由回调实现决定，LogManager 不直接操作文件描述符。

### 2.4 `kFatal` 分支空实现

**文件:** `09_logging_module.md` (lines 103-105)
**问题:** `Log()` 函数中 `kFatal` 级别的 `IF` 分支仅有注释。
**修复:** 添加 `Flush()` 调用（确保 fatal 消息不丢失）和 `fatal_handler_` 回调调用。新增 `fatal_handler_` 成员变量引用。

---

## 3. 类型一致性修复 (5项)

### 3.1 `SocketConfig` 字段类型与平台层不一致

**文件:** `08_system_config.md` (lines 52-55)
**问题:** 配置模块中 `recv_buf_bytes`/`send_buf_bytes` 为 `int`，而 `01_platform_layer.md` 和 `05_api_reference.md` 中为 `uint32_t`；`dscp`/`ttl` 为 `int`，而平台层为 `uint8_t`。
**修复:** 将 4 个字段类型与平台层对齐：`uint32_t`（缓冲区），`uint8_t`（dscp, ttl）。

### 3.2 `SessionDefaultsConfig` 缓冲区字段类型不一致

**文件:** `08_system_config.md` (lines 68-69)
**问题:** `rx_buffer_init_bytes`/`tx_buffer_init_bytes` 为 `int`，而 `02_session.md` 和 `05_api_reference.md` 中为 `size_t`。
**修复:** 改为 `size_t`，与 Session 定义和 API 参考一致。

### 3.3 `WorkerPool::Dispatch` routing_key 类型不一致

**文件:** `01_platform_layer.md` (lines 368, 377)
**问题:** `Dispatch()` 和 `SelectWorker()` 的 `routing_key` 参数类型为 `uint64_t`，而 `05_api_reference.md` 和所有 Session 定义中为 `uint32_t`。
**修复:** 改为 `uint32_t`，与 API 参考和 Session 定义一致。

### 3.4 DatagramSocket 构造函数异常类型不一致

**文件:** `01_platform_layer.md` (line 227)
**问题:** socket 创建失败时抛出 `SocketException`，而 `05_api_reference.md` (line 614) 声明为 `std::runtime_error`。
**修复:** 改为 `std::runtime_error`，与 API 参考一致。

### 3.5 `LogManager` 预处理器指令风格不一致

**文件:** `09_logging_module.md` (lines 139-140)
**问题:** `#ENDIF`（伪代码大写风格）与 `#endif`（C标准小写风格）混用。
**修复:** 统一为 `#ENDIF`（伪代码大写风格），添加注释说明对应关系。

---

## 4. 缺失定义添加 (3项)

### 4.1 `ConfigurationManager::ApplyCmdLineOverrides` 缺失定义

**文件:** `08_system_config.md`
**问题:** `SystemStartupSequence`（line 600）和 `00_architecture_overview.md`（line 57）引用了 `ApplyCmdLineOverrides`，但 `ConfigurationManager` 类体中未定义。
**修复:** 在 `ApplyEnvOverrides` 之后新增完整的 `ApplyCmdLineOverrides` 方法定义：解析 `--section.field=value` → 复制当前配置 → 逐路径覆盖 → 原子替换。

### 4.2 `Server/ClientEndpointConfig` 缺少端点级 `socket_config`

**文件:** `08_system_config.md` (lines 73-84, 87-96)
**问题:** `Server::Config`（`03_server.md` line 55）和 `Client::Config`（`04_client.md` line 52）均包含 `socket_config` 字段，但 `SystemConfig` 的 `ServerEndpointConfig` 和 `ClientEndpointConfig` 中缺失，导致配置模块无法覆盖端点级 Socket 选项。
**修复:** 在两个端点配置结构体中新增 `socket_config: SocketConfig` 字段，JSON 示例中新增对应的嵌套对象。

### 4.3 `GetLibraryConfig` 等访问器存在悬空引用风险

**文件:** `08_system_config.md` (lines 178-197)
**问题:** 便捷访问器（如 `GetLibraryConfig()`）返回 `const T&` 引用，但引用的 `shared_ptr<const>` 临时对象在表达式结束后销毁，导致悬空引用。
**修复:** 添加"实现注意"注释，说明安全用法模式：调用方必须持有 `GetConfig()` 返回的 `shared_ptr` 以延长生命周期。

---

## 5. 格式问题修复 (1项)

### 5.1 探活机制注释重复行

**文件:** `03_server.md` (lines 395-396)
**问题:** `SendProbe` 函数中连续两行相同注释："本端在后续FeedInput中会更新last_recv_time_ms_"。
**修复:** 删除重复行。

---

## 6. 变更影响范围

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `doc/pseudocodes/08_system_config.md` | 修改 (10处) | LoadFromString实现/3个Deserialize实现/ApplyCmdLineOverrides定义/ApplyDefaults修复/SocketConfig类型/size_t类型/socket_config新增/悬空引用注释 |
| `doc/pseudocodes/04_client.md` | 修改 (2处) | OnError重连死代码修复/OnReadable错误计数器 |
| `doc/pseudocodes/03_server.md` | 修改 (2处) | OnReadable错误计数器/重复注释删除 |
| `doc/pseudocodes/01_platform_layer.md` | 修改 (3处) | routing_key类型/异常类型/DatagramSocket构造函数 |
| `doc/pseudocodes/09_logging_module.md` | 修改 (3处) | Flush实现/kFatal分支/预处理器风格 |
| `changelog/change_record_issue11.md` | **新增** | 本次修改记录 |

---

## 7. 已知保留项 (有意不修)

以下项目经评估为设计决策或伪代码特性，不作修改：

| 项目 | 文件 | 原因 |
|------|------|------|
| `MetricsSink` 未定义 | `02_session.md` line 313 | 未来扩展点，属于预留接口 |
| 3.1-3.8 小节为代码注释而非 markdown 标题 | `00_architecture_overview.md` | 伪代码文件内的结构化注释，属伪代码风格 |
| 7.2 节与 11 节配置树部分重复 | `07_tech_stack.md` | 有意重复：7.2 是流程展示，11 是配置分层索引 |
| LogManager API 在 05 和 09 文件中重复 | `05_api_reference.md` + `09_logging_module.md` | 有意重复：05 是 API 参考（简洁），09 是模块设计（详尽） |
| orphan comma in lambda | `04_client.md` line 467 | 伪代码视觉分隔，不构成实际语法问题 |
| `GetLogCallback` 返回 `LogCallback*` | `05_api_reference.md` + `09_logging_module.md` | 设计决策：便于检查回调是否已设置 |

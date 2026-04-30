# Issue 10 修改记录

## 概述

基于 Issue 10 要求分析 `doc/pseudocodes/` 全部文档，设计并实现一个线程安全的日志模块 (`LogManager`)，提供可外部注入回调的日志系统，支持分级输出、运行时级别过滤、编译期级别裁剪和格式化消息。同时在所有核心逻辑节点注入日志调用，同步更新配置系统、API 参考和技术栈文档。

---

## 1. 新增文件

| 文件 | 说明 |
|------|------|
| `doc/pseudocodes/09_logging_module.md` | 日志模块完整伪代码 (新增) |
| `changelog/change_record_issue10.md` | 本次修改记录 (新增) |

---

## 2. 09_logging_module.md — 日志模块

### 2.1 模块概述

`LogManager` 提供全局日志管理器，核心设计原则：热路径零开销 (编译期级别裁剪) + 回调线程安全 + 库级生命周期管理。

**核心能力:**
- 6 级日志级别: kTrace / kDebug / kInfo / kWarn / kError / kFatal
- 线程安全的回调注册: `SetLogCallback()` 使用互斥锁保护，可从任何线程安全调用
- 运行时级别过滤: 原子变量 `atomic_level_` 实现无锁快速路径检查
- 编译期级别裁剪: `LOG_COMPILE_MIN_LEVEL` 宏在 Release 构建中裁剪 TRACE/DEBUG 级别，编译器完全移除（零运行时开销）
- 格式化在锁外执行: 避免消息格式化耗时影响回调调用延迟
- 6 个日志宏: LOG_TRACE / LOG_DEBUG / LOG_INFO / LOG_WARN / LOG_ERROR / LOG_FATAL，自动注入 `__FILE__` / `__LINE__` / `__FUNCTION__`

### 2.2 文件内容章节

| 章节 | 内容 |
|------|------|
| §1 LogManager 完整伪代码 | 完整类定义: Level枚举/LogCallback类型/SetLogCallback/SetLevel/Log/Flush |
| §2 日志宏定义 (编译期裁剪) | LOG_COMPILE_MIN_LEVEL + 6个LOG_*宏 + DO_IF编译期检查 |
| §3 使用示例 | 基础控制台输出/文件日志/组合回调多路输出 |
| §4 核心逻辑节点日志注入点 | Session生命周期/Server生命周期/Client生命周期/EventLoop生命周期 |
| §5 线程安全设计 | 安全保证/注意事项/性能设计 |

### 2.3 关键设计决策

| 决策 | 原因 |
|------|------|
| LogCallback 为 `std::move_only_function` | 支持捕获 move-only 对象（如 `std::unique_ptr<FILE>`），C++23标准库设施 |
| 回调在锁内串行调用 | 简化回调实现，回调编写者无需自行处理同步 |
| 运行时级别用原子变量 | 热路径 `Log()` 的第一步是无锁原子读取，避免互斥锁开销 |
| 消息格式化在锁外 | 减少锁持有时间，避免格式化耗时阻塞其他线程的日志输出 |
| 编译期裁剪用 `if constexpr` 等价宏 | Release 中 TRACE/DEBUG 参数表达式不会被求值，真正零开销 |

---

## 3. 05_api_reference.md — API 参考

### 3.1 新增 §10: LogManager 类 (Public API)

新增完整的 LogManager Public API 文档，包含 6 个子章节：

| 子章节 | 内容 |
|--------|------|
| 10.1 日志级别 | `LogManager::Level` 枚举定义 (kTrace-kFatal) |
| 10.2 回调类型 | `LogManager::LogCallback` 类型别名 + 线程安全说明 |
| 10.3 Public API | `SetLogCallback` / `GetLogCallback` / `SetLevel` / `GetLevel` / `IsLevelEnabled` |
| 10.4 内部日志输出 | `Log` 静态方法 (由 LOG_* 宏封装) |
| 10.5 日志宏 | 编译期裁剪宏定义 + 6 个 LOG_* 宏 |
| 10.6 使用示例 | 回调注册 + 运行时级别设置 + 日志宏使用 |

### 3.2 LibraryConfig 补充

更新 `LibraryConfig` 结构体，将原来的占位注释替换为完整的日志相关字段：

```
struct LibraryConfig {
    ...
    std::string log_level = "info";     // 运行时日志级别
    std::string log_output = "stdout";  // 日志输出目标 ("stdout"/"stderr"/"callback"/文件路径)
    ...
};
```

### 3.3 章节重新编号

新增 §10 LogManager 后，原 §10 基础类型与工具 顺延为 §11，原 §11 ProtocolEngine 顺延为 §12。

---

## 4. 核心逻辑节点日志注入

### 4.1 01_platform_layer.md — EventLoop

| 注入点 | 级别 | 日志内容 |
|--------|------|---------|
| `Run()` 入口 | LOG_INFO | EventLoop 启动 + 后端类型 |
| `Run()` 退出 | LOG_INFO | EventLoop 停止 |
| `Register()` | LOG_DEBUG | 注册 fd + 事件掩码 |
| `Unregister()` | LOG_DEBUG | 取消注册 fd |
| `AddTimer()` | LOG_TRACE | 定时器添加 + 延迟 + 句柄 |
| `AddPeriodicTimer()` | LOG_TRACE | 周期性定时器添加 |
| `CancelTimer()` | LOG_TRACE | 定时器取消 |
| IO 错误分发 | LOG_WARN | IO 错误 fd + 错误码 |

### 4.2 02_session.md — Session

| 注入点 | 级别 | 日志内容 |
|--------|------|---------|
| 构造函数 | LOG_DEBUG | Session 创建 + conv + 引擎类型 + 远端地址 |
| 析构函数 | LOG_DEBUG | Session 销毁 + 累计收发字节 |
| `Start()` | LOG_INFO | Session 启动 |
| `Close()` | LOG_INFO | 立即关闭 |
| `GracefulShutdown()` | LOG_INFO | 优雅关闭 + 超时时间 |
| `TransitionState()` | LOG_INFO | 状态转换 (old → new) |
| `Send()` 阻塞 | LOG_WARN | 发送阻塞 + 状态/窗口占用 |
| `FeedInput()` | LOG_TRACE | 接收数据报 |
| `NotifyError()` | LOG_ERROR | 错误类型 |

### 4.3 03_server.md — Server

| 注入点 | 级别 | 日志内容 |
|--------|------|---------|
| `Start()` | LOG_INFO | 服务端启动 + 监听地址端口 |
| `Stop()` | LOG_INFO | 服务端停止 + 活跃会话数 |
| `OnReadable()` 新会话 | LOG_INFO | 新会话接受 + conv + 来源地址 |
| `OnReadable()` 新会话 | LOG_DEBUG | 当前会话数 / 最大会话数 |
| `EvictSession()` | LOG_INFO | 驱逐会话 + conv + 原因 |
| `RunHealthCheck()` | LOG_DEBUG | 健康检测统计 (总数/空闲/过期) |
| `RunHealthCheck()` 驱逐 | LOG_WARN | 过期会话超时驱逐 |

### 4.4 04_client.md — Client

| 注入点 | 级别 | 日志内容 |
|--------|------|---------|
| `Connect()` | LOG_INFO | 发起连接 + 目标地址 |
| `DoConnect()` | LOG_DEBUG | 创建会话 + 发送握手 |
| `OnServerFirstResponse()` | LOG_INFO | 连接建立成功 + 地址 + conv |
| `Disconnect()` | LOG_INFO | 断开连接 + 地址 |
| `OnConnectTimeout()` 无重连 | LOG_ERROR | 连接超时失败 |
| `OnConnectTimeout()` 超最大重试 | LOG_ERROR | 超过最大重连次数 |
| `OnConnectTimeout()` 重试中 | LOG_WARN | 超时重试 + 当前/最大次数 |
| `NotifyConnectFailure()` | LOG_ERROR | 连接失败 + 错误类型 |

---

## 5. 00_architecture_overview.md — 架构总览

### 5.1 库初始化流程 (3.1)

在 `LibraryInitialize()` 中新增**步骤4**：初始化日志系统。

- 根据配置中的 `log_level` 调用 `LogManager::SetLevel()`
- 如果 `log_output` 不是 `"callback"`，自动创建默认日志 Sink
- `"callback"` 模式由应用层通过 `LogManager::SetLogCallback()` 注册
- 步骤编号从原来的 4-6 顺延为 5-7

### 5.2 核心模块依赖关系图 (4)

新增 `LogManager` 模块到依赖关系图顶层，与 `ConfigurationMgr` 并列：

```
ConfigurationMgr  LogManager
       │               │
       └───────┬───────┘
          Application
```

### 5.3 关键扩展点 (4)

新增两项：
- `0.1 LogManager` — 日志输出回调由外部注入，支持编译期级别裁剪和运行时级别过滤
- `7. LogSink` — 可替换日志输出目标 (stdout/stderr/文件/远程syslog/自定义回调)

---

## 6. 07_tech_stack.md — 技术栈

### 6.1 设计模式章节 (8)

新增 3 种设计模式：

| 模式 | 应用位置 |
|------|---------|
| 回调注入 | `LogManager::SetLogCallback` — 日志输出回调由外部设置，库不依赖具体日志框架 |
| 编译期裁剪 | `LOG_COMPILE_MIN_LEVEL` + LOG_TRACE/LOG_DEBUG 宏 — Release 构建中完全移除 |
| 双级过滤 | 编译期宏 + 运行时原子变量 — 编译期裁剪不输出级别，运行时原子读取无锁过滤 |

---

## 7. 08_system_config.md — 系统配置

### 7.1 log_output 字段扩展

`LibraryConfig::log_output` 的取值说明更新为支持 `"callback"` 模式：

```
log_output: "stdout" / "stderr" / "callback" / 文件路径
```

JSON 配置文件中新增注释说明各选项含义。

---

## 8. 变更影响范围

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `doc/pseudocodes/09_logging_module.md` | **新增** | 日志模块完整伪代码 (5 个章节) |
| `doc/pseudocodes/05_api_reference.md` | 修改 (3处) | 新增 §10 LogManager / 更新 LibraryConfig / 章节重编号 |
| `doc/pseudocodes/01_platform_layer.md` | 修改 (8处) | EventLoop 全部核心逻辑节点注入日志 |
| `doc/pseudocodes/02_session.md` | 修改 (9处) | Session 生命周期/收发/错误节点注入日志 |
| `doc/pseudocodes/03_server.md` | 修改 (7处) | Server 启停/会话管理/健康检测节点注入日志 |
| `doc/pseudocodes/04_client.md` | 修改 (8处) | Client 连接/断连/超时/重连节点注入日志 |
| `doc/pseudocodes/00_architecture_overview.md` | 修改 (3处) | 初始化流程/依赖图/扩展点 |
| `doc/pseudocodes/07_tech_stack.md` | 修改 (1处) | 设计模式 (新增 3 项) |
| `doc/pseudocodes/08_system_config.md` | 修改 (2处) | log_output 字段说明扩展 |
| `changelog/change_record_issue10.md` | **新增** | 本次修改记录 |

---

## 9. 需求验收

| Issue 要求 | 验收状态 | 说明 |
|-----------|---------|------|
| 分析全部文档，增加日志模块 | 通过 | `09_logging_module.md` 完整伪代码，5个章节 |
| 更新配置系统 | 通过 | `08_system_config.md` 已有 log_level/log_output 字段；`05_api_reference.md` 已更新 LibraryConfig |
| 更新技术栈 | 通过 | `07_tech_stack.md` 新增 3 种设计模式 |
| 核心逻辑节点加上日志 | 通过 | Session/Server/Client/EventLoop 核心逻辑节点全部注入 (32处) |
| 回调函数线程安全 | 通过 | 设计: mutex保护回调调用 + 原子变量级别过滤 + 锁外格式化 |
| SetLogCallback是库Public API | 通过 | `05_api_reference.md` §10 完整Public API文档 |

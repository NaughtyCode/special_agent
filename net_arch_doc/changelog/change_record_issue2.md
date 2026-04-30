# 修改记录 — Issue #2

## 基本信息

| 项目 | 内容 |
|------|------|
| 修改编号 | issue2 |
| 修改日期 | 2026-04-30 |
| 修改类型 | 文档优化 — 伪代码审查修复与表达增强 |
| 关联文档 | `doc/pseudocodes/` (全部6个文件) |
| 修改人 | SpecialArchAgent |

## 修改概述

对 `doc/pseudocodes/` 下的全部6个伪代码文件进行系统审查，修复发现的问题，并优化所有表述，使其具备更强、更普适、更灵活、更泛化的表达能力。

## 修改原则

1. **消除硬编码** — 将所有魔数替换为命名配置参数或可配置常量
2. **提升抽象层级** — 将具体实现细节（如 epoll/IOCP/eventfd）替换为抽象概念（如 EventLoop/IOBackend/WakeupChannel）
3. **增加扩展点** — 为关键组件添加策略模式/回调注入，支持自定义行为
4. **协议无关化** — 将 KCP 特定的类名/概念泛化为通用传输协议概念
5. **完善错误处理** — 补全原有的错误处理缺口，增加错误传播路径
6. **修复实际Bug** — 修正悬空指针、字段名不一致、初始化缺失等问题

## 文件变更清单

### 修改文件

| 序号 | 文件路径 | 变更说明 |
|------|----------|----------|
| 1 | `doc/pseudocodes/00_architecture_overview.md` | 全面重写 |
| 2 | `doc/pseudocodes/01_platform_layer.md` | 全面重写 |
| 3 | `doc/pseudocodes/02_kcp_session.md` | 全面重写 |
| 4 | `doc/pseudocodes/03_kcp_server.md` | 全面重写 |
| 5 | `doc/pseudocodes/04_kcp_client.md` | 全面重写 |
| 6 | `doc/pseudocodes/05_api_reference.md` | 全面重写 |

### 新增文件

| 序号 | 文件路径 | 变更说明 |
|------|----------|----------|
| 7 | `changelog/change_record_issue2.md` | 本修改记录 |

## 详细变更内容

### 1. 00_architecture_overview.md — 架构总览

**修复的问题：**
- 硬编码的 `"0.0.0.0":8888` → 可配置的 `config.listen_address`
- 硬编码的 `10ms` / `30s` 时间值 → `config.update_tick_ms` / `config.idle_timeout_ms`
- 数据发送流程之前缺少发送窗口检查和阻塞处理 → 新增 `SendResult::kBlocked` 路径
- 定时驱动流程增加了完整的状态机推动步骤描述
- 线程模型中的 `session.bound_thread` 之前不在 KCPSession 类定义中 → 重构为 Worker绑定

**增强的表达能力：**
- 四层架构增加了"可替换"描述，每一层都可注入定制实现
- 新增配置体系总览 (LibraryConfig / ServerConfig / ClientConfig / SessionConfig)
- 线程模型从2种扩展到4种：单线程 / 多线程Sticky(3种分配子策略) / 互斥锁
- 架构依赖图增加了明确的"扩展点"标注
- 超时检测从简单的二值判定升级为三级健康度评估 (Healthy/Idle/Stale)
- 新增 `ProtocolProfile` 预设概念 (Fast/Reliable/Balanced/Custom)

### 2. 01_platform_layer.md — 平台抽象层

**修复的问题：**
- IOContext 缺少 `wakeup_channel_` 初始化 → 在构造函数中通过 `impl_.CreateWakeupChannel()` 初始化
- `RegisterFd` 仅注册了 `EPOLLIN` 但 Run 循环也检查 `EPOLLOUT` → 使用 `IOMask` 位掩码统一管理
- Windows 路径的 `WaitForIOEvents` 为空 `...` → 补全为委托 `impl_.WaitForEvents()`
- `RecvResult.data` 类型为 `uint8_t*` 指向临时buffer → 添加生命周期文档说明，改为 `const uint8_t*`
- 所有Socket缓冲区硬编码 `256*1024` → 移入 `SocketConfig`
- `SendTo` 返回 `int` 但未区分阻塞和真实错误 → 改用 `std::expected<int, SocketError>`

**增强的表达能力：**
- `IOContext` → `EventLoop`（更通用的名称）
- 具体平台判断 `IF platform IS Linux` → Pimpl模式委托 `IOBackendImpl`
- 平台特定唤醒机制 (`eventfd`) → 抽象的 `WakeupChannel` 概念
- `UdpSocket` → `DatagramSocket`（支持UDP/UDPLite/Unix Domain Dgram）
- `ThreadPool` → `WorkerPool`（强调Worker概念，支持4种分配策略）
- 硬编码的 `65536` 缓冲区 → `configurable` + `std::vector` 动态分配
- 新增 `IEventHandler` 接口定义（之前缺漏）
- 定时器从仅支持 `uint32_t delay` 扩展为支持 `TimerHandle` 返回值
- TaskQueue 批量处理优化（swap后锁外执行）

### 3. 02_kcp_session.md — 协议层核心

**修复的问题：**
- KCP参数全部硬编码(`ikcp_nodelay(kcp_, 1, 10, 2, 1)`) → 通过 `Session::Config` 和 `ProtocolProfile` 配置
- `Send` 返回 `void` 导致发送失败无法感知 → 返回 `SendResult` 枚举
- `TryRecv` 每消息分配新 `vector` → 使用可复用 `recv_buffer_`
- 只有2个状态(无 `kClosing`)导致优雅关闭无法实现 → 新增 `kClosing` 状态
- 缺少错误传播机制 → 新增 `ErrorCallback` 和 `NotifyError()`
- 缺少状态变更通知 → 新增 `StateChangeCallback`
- 类名 `KCPSession` 与具体协议耦合 → 改为 `Session`（协议无关抽象）

**增强的表达能力：**
- 协议引擎从直接调用 KCP C API → 抽象为 `ProtocolEngine` 接口（可替换实现）
- `IsTimeout` 二值判断 → `EvaluateHealth` 三级健康评估
- 新增 `SessionStats` 运行时统计收集
- 新增 `GracefulShutdown()` 优雅关闭路径
- 配置支持 `ProtocolProfile` 预设 + `kCustom` 逐参数自定义
- 状态机新增从 kConnected → kClosing → kClosed 的优雅关闭路径
- 协议头解析泛化描述（`MIN_HEADER_SIZE` 而非硬编码24）

### 4. 03_kcp_server.md — 服务端抽象层

**修复的问题：**
- `recv_buffer_` 引用问题 — 统一使用 `recv_buf_` vector 而非固定数组
- `result.data_len` vs `result.len` 字段名不一致 → 统一为 `result.len`
- `OnReadable` 引用 `recv_buffer_` 但 `RecvFrom` 需要对 `recv_buf_.data()` 操作
- 超时检测直接在遍历中 erase → 改为两阶段：收集列表→批量删除
- 类名 `KcpServer` → `Server`（泛化）

**增强的表达能力：**
- Accept流程增加了 `routing_key` 抽象（不仅限于 `conv`）
- 新增 `EvictionPolicy` 枚举：kImmediateClose / kGracefulShutdown / kNotifyOnly
- 新增 `IdlePolicy` 枚举：kIgnore / kSendProbe / kNotify
- 新增 `EvictReason` 枚举区分不同驱逐原因
- 新增 `SessionEvictedHandler` 回调
- 会话驱逐流程增加了 `WireSessionEvents` 自动连接Session内部事件
- 新增 `max_sessions` 限制和防conv冲突的复合键方案
- 探活机制增加了 `SendProbe` 的独立描述

### 5. 04_kcp_client.md — 客户端抽象层

**修复的问题：**
- `socket_` 为裸指针 `UdpSocket*`，所有权不明确 → `std::unique_ptr<DatagramSocket>`
- `EnableAutoReconnect` 为空实现 `...` → 在 `DoConnect()`/`OnConnectTimeout()` 中实现完整重连逻辑
- `Connect` 同步返回 Session → 改为异步，通过 `ConnectSuccessHandler` / `ConnectFailureHandler` 回调
- 连接时无超时控制 → 新增 `connect_timeout_ms` 和超时定时器
- 类名 `KcpClient` → `Client`（泛化）

**增强的表达能力：**
- 重连策略从内建实现 → `ReconnectStrategy` 配置结构，支持4种策略（指数退避/固定间隔/自定义/无重连）
- 新增 `ConnectState` 的 `kReconnecting` 状态
- 新增 `ConnectError` 枚举（超时/拒绝/DNS失败/Socket错误/最大重试）
- DNS解析支持（通过 `DatagramSocket::Address` 字符串自动解析）
- 源验证增加了路由键验证，防止旧会话残留包干扰
- 新增完整的使用示例（含异步回调）

### 6. 05_api_reference.md — API参考

**修复的问题：**
- `RecvResult.data` 类型 `uint8_t*` → `const uint8_t*`
- 新增之前缺失的类型定义：`IEventHandler`, `TimerHandle`, `SessionStats`, `LibraryConfig`
- 新增之前缺失的配置结构：`Session::Config`, `Server::Config`, `Client::Config`, `SocketConfig`
- 所有枚举增加了完整的成员列表和说明
- KCP C API 的 `ikcp_nodelay`/`ikcp_wndsize`/`ikcp_setmtu` 补充了返回值说明

**增强的表达能力：**
- 类名全部泛化：`KCPSession→Session`, `KcpServer→Server`, `KcpClient→Client`
- `IOContext→EventLoop`, `UdpSocket→DatagramSocket`, `ThreadPool→WorkerPool`
- 回调类型从 `std::function` → `std::move_only_function`（支持move-only闭包）
- 新增 `std::expected` 返回错误信息而非吞掉错误
- 新增三级健康度评估API
- 新增运行时统计 `SessionStats`
- 新增 `GracefulShutdown` API
- 新增 `ProtocolProfile` 和 `Config::FromProfile` 工厂方法

## 问题修复统计

| 类别 | 数量 | 说明 |
|------|------|------|
| 硬编码值消除 | 20+ | 所有魔数替换为配置参数 |
| Bug修复 | 8 | 悬空指针、字段名不一致、初始化缺失、erase-in-loop等 |
| 缺失类型补充 | 5 | IEventHandler, TimerHandle, SessionStats, SocketError, LibraryConfig |
| 缺失API补充 | 12 | ErrorCallback, StateChangeCallback, GracefulShutdown, EvaluateHealth等 |
| 命名泛化 | 10+ | 所有KCP专有名称 → 通用概念 |
| 抽象层级提升 | 6 | IOContext→EventLoop, UdpSocket→DatagramSocket等 |
| 配置结构化 | 6 | 新增Config结构体聚合参数 |
| 错误处理完善 | 5 | SendResult, ConnectError, SocketError, SessionError, EvictReason |

## 影响分析

- **兼容性**: 所有类名和接口均有变化（泛化重命名），旧代码需要更新引用
- **架构收益**: 协议无关设计使得未来替换KCP为其他协议（QUIC/自定义）成本大幅降低
- **可测试性**: 新增的配置注入和回调机制便于单元测试中注入Mock
- **可运维性**: 新增的统计和健康度评估接口便于监控和故障诊断

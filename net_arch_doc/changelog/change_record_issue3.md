# Issue 3 修改记录

## 概述

基于 Issue 3 要求对所有 `doc/pseudocodes/` 伪代码文件进行第三轮深度审查与优化，修复表述不准确、架构缺陷和API不一致问题；新增高并发单元测试需求文档；进一步优化 Public API 设计。

---

## 1. 00_architecture_overview.md — 架构总览

### 1.1 拼写与命名修正
- **修正**: `CONNECTION_HEALTH` → `ConnectionHealth` (与Session类定义一致)
- **修正**: `PROTOCOL_PROFILE` → `ProtocolProfile` (与Session类定义一致)
- **修正**: 注释中 `Ice` → `Idle` (空闲状态英文拼写错误)
- **修正**: `kPending` → `kBlocked` (SendResult枚举值,与Session类中SendResult定义对齐)

### 1.2 配置结构完整性
- **新增**: `ServerConfig` 中补充 `stale_timeout_ms` 字段 (此前仅在健康检测函数参数中出现,但未纳入配置结构)
- **对齐**: `LibraryConfig` 的 `default_*` 字段命名统一为与 `Session::Config` 一致的后缀形式

### 1.3 数据流表述优化
- **修正**: 客户端连接流程中明确 `kConnecting` 状态语义: "在收到服务器首个响应ACK之前,状态保持为 kConnecting" (此前未明确此约束)
- **优化**: `DataReceiveFlow` 描述中补充 `FeedInput` 自动调用 `TryRecv` 的说明

---

## 2. 01_platform_layer.md — 平台抽象层

### 2.1 拼写修正
- **修正**: `处罚` → `触发` (TimerQueue注释: "触发已到期的定时器回调")

### 2.2 EventLoop 类型安全修复
- **修正**: `EventLoop::Run()` 中对 `GetNextTimeout()` 返回值处理 — 此前代码将 `std::optional<uint32_t>` 隐式当作原始 `int` 使用,现改为显式检查 `has_value()` 并提取 `value()`,无定时器时传 `std::nullopt` 给平台层以支持无限等待

### 2.3 DatagramSocket API 语义增强
- **修正**: `RecvFrom` 返回类型从 `std::optional<RecvResult>` 改为 `std::expected<std::optional<RecvResult>, SocketError>` — 区分三种结果:
  - 成功且有数据 → `RecvResult`
  - 成功但无数据 → `std::nullopt` (非阻塞正常)
  - 失败 → `SocketError` (如ICMP错误,不影响Socket继续使用)
- **重命名**: `SetWriteHandler` → `EnableWriteNotifications` (语义更准确: 启用/禁用可写通知)
- **新增**: `DisableWriteNotifications` 方法 (恢复为仅监听可读,减少不必要的事件触发)
- **新增**: `Address::operator==` 和 `operator!=` (Client中源地址验证需要)

### 2.4 WorkerPool 结构完善
- **新增**: 显式定义 `Worker` 内部结构体 (`thread`, `event_loop`, `session_count`),此前为隐式声明
- **修正**: `workers_[i].thread` 的 `std::thread` 构造中lambda正确捕获 `workers` 引用

### 2.5 Message 类简化
- **移除**: `DataBuffer` variant 过早优化 (设计决策: 在v1中统一使用 `std::vector<uint8_t>` 存储,后续版本按需引入零拷贝视图)

### 2.6 缓冲区语义修正
- **修正**: `recv_buffer_` 使用 `resize()` 而非 `reserve()` 初始化 — 确保 `data()` 可写入,`size()` 返回有效容量

---

## 3. 02_kcp_session.md — Session 传输协议层

### 3.1 Config 工厂方法完善
- **修正**: `Config::FromProfile()` 此前仅设置 `nodelay`/`update_interval_ms`/`fast_resend_threshold`/`flow_control_enabled` 4个字段,`mtu_bytes`/`send_window_packets` 等共6个字段使用未初始化的默认值。现工厂方法为所有10个字段填充预设默认值:
  - kFastMode: mtu=1400, send_window=128, recv_window=128, rx_buf=64KB, tx_buf=64KB, metrics=true
  - kReliableMode/kBalancedMode: 同上默认值 + 各自的行为参数

### 3.2 统计计数器时序修正
- **修正**: `Send()` 中 `stats_.total_bytes_sent` 和 `total_messages_sent` 仅在 `engine_.Send()` 返回 `kQueued` 后递增 (此前在调用前递增,若Send失败则统计不准确)

### 3.3 新增 Public API 方法
- **新增**: `SendHandshakePacket()` — 发送协议层握手首包 (Client连接时调用,触发服务端隐式Accept)
- **新增**: `SendProbePacket()` — 发送协议层探活包 (Server空闲检测时调用)
- **新增**: `ApplyConfig(config)` — 运行时更新协议配置 (仅允许在kIdle状态调用以确保安全)
- **新增**: `GetRemoteAddress()` — 获取远端地址 (用于日志/监控/连接识别)
- **新增**: `OnSendComplete(cb)` — 消息确认送达回调 (可选扩展,供应用层追踪发送完成)

### 3.4 生命周期安全增强
- **修正**: `Close()` 中新增 `CancelShutdownTimer()` 调用 — 防止GracefulShutdown的定时器在Close后仍触发
- **修正**: 析构函数中先取消shutdown定时器再FlushStats — 正确的资源释放顺序

### 3.5 构造初始化修正
- **修正**: `recv_buffer_.resize(config_.rx_buffer_init_bytes)` 确保接收缓冲区预分配并可写入

### 3.6 SessionStats 字段完善
- **新增**: `total_retransmissions` — 累计重传次数
- **新增**: `estimated_rtt_ms` — 当前估算RTT
- **新增**: `send_window_used` / `recv_window_used` — 窗口占用情况

---

## 4. 03_kcp_server.md — Server 服务端

### 4.1 迭代器访问修正 (关键Bug)
- **修正**: 全部 `it.second` → `it->second` (4处) — `std::unordered_map` 的迭代器使用 `->` 访问值,`.` 访问的是 `std::pair<Key,Value>` 的 `second` 成员。但由于 `it` 是迭代器而非引用,正确写法应为 `it->second` (等价于 `(*it).second`)

### 4.2 接收缓冲区修正
- **修正**: `recv_buf_(65536)` → `recv_buf_.resize(config_.recv_buf_init_bytes)` (构造函数中显式resize)
- **修正**: `RecvFrom(recv_buf_.data(), recv_buf_.capacity())` → `RecvFrom(recv_buf_.data(), recv_buf_.size())` (使用size而非capacity表达可用长度)
- **新增**: `recv_buf_init_bytes` 纳入 `Server::Config` (可配置,默认65536)

### 4.3 OnReadable 结构化重构
- **修正**: `recv_result.data` → `recv_result->data`, `recv_result.len` → `recv_result->len` (RecvResult现在是指针解引用)
- **修正**: `recv_result.sender` → `recv_result->sender`
- **新增**: 数据报长度不足时静默丢弃 (而非崩溃)
- **新增**: 显式会话上限检查和拒绝逻辑

### 4.4 WireSessionEvents 增强
- **新增**: `OnStateChange` 回调注册 — Session自行进入kClosed状态时自动触发驱逐清理
- **修正**: 回调使用 `PostTask` 投递 — 确保在EventLoop线程中安全操作sessions_
- **修正**: 闭包捕获 `conv` 而非 `session->GetConvId()` 的值 — 避免在回调执行时session可能已被销毁

### 4.5 会话驱逐逻辑修复
- **修正**: `RemoveSession` 中先取出 `shared_ptr` 副本 → 再从 `sessions_` 中 `erase` → 最后执行 `EvictSession` — 防止驱逐回调中间接导致重入时访问已擦除的迭代器
- **修正**: `EvictSession` 使用完全限定枚举名 (`EvictionPolicy::kImmediateClose` 等)

### 4.6 新增内容
- **新增**: `线程安全与并发说明` 章节 — 文档化Server的单EventLoop线程模型和跨线程操作Session的正确方式
- **新增**: `会话数量管理` 章节 — LRU驱逐策略伪代码
- **新增**: `AcceptFilter中间件链` 扩展点 — IP黑名单/Token验证等安全增强钩子
- **新增**: 复合键会话表方案 (`(conv, sender_ip, sender_port)`) 的文档说明

---

## 5. 04_kcp_client.md — Client 客户端

### 5.1 状态机架构修正 (关键)
- **修正**: `DoConnect()` 中移除了立即 `state_ = kConnected` 和 `success_handler_(session_)` 调用
  - **此前行为**: 创建Session后立即标记为Connected — 违反异步连接语义,无需服务器响应即声称已连接
  - **此后行为**: DoConnect仅发送握手,状态保持 `kConnecting`; 首次收到服务器有效响应时 `OnReadable` → `OnServerFirstResponse()` 才转入 `kConnected`
- **新增**: `OnServerFirstResponse()` — 取消超时定时器 + state→kConnected + 触发success_handler

### 5.2 重连逻辑修复
- **修正**: `Disconnect()` 中 `reconnect_strategy_.reset()` → `config_.reconnect.reset()` — `reconnect_strategy_` 不存在为独立成员变量,重连策略存储在 `config_.reconnect` (std::optional) 中
- **修正**: `OnConnectTimeout` 中先取消 `connect_timer_` 再调用 `NotifyConnectFailure` — 防止二次触发

### 5.3 接收缓冲区修正
- **修正**: `recv_buf_(65536)` → `recv_buf_.resize(config_.recv_buf_init_bytes)` + Config中新增 `recv_buf_init_bytes`
- **修正**: `recv_buf_.capacity()` → `recv_buf_.size()` (表达可用缓冲区长度)

### 5.4 闭包安全性修正
- **修正**: `MinimalClientExample` — 此前 `client` 以引用 `[&client]` 捕获到异步回调中。若回调在 `client` 析构后触发则悬挂引用。改为:
  - 使用 `std::shared_ptr<Client>` 管理生命周期
  - `on_success` 回调使用 `[client]` 值捕获 shared_ptr (延长生命周期)
  - `session->Send(data)` 直接使用回调参数 `session`,不捕获 `client`

### 5.5 错误处理增强
- **新增**: `WireSessionEvents` — Session错误自动触发重连逻辑
- **新增**: `OnStateChange` 回调 — 感知Session的kClosed状态变更
- **修正**: `NotifyConnectFailure` 中清理session (Close + reset)

### 5.6 连接状态管理增强
- **修正**: `Connect()` 中正确处理 `kReconnecting` 状态 (先Disconnect再重连)
- **修正**: `OnReadable` 中 `recv_result` 使用指针解引用 (`recv_result->data`)

---

## 6. 05_api_reference.md — API参考文档

### 6.1 Session API 完善
- **新增**: `SendHandshakePacket()` 方法文档
- **新增**: `SendProbePacket()` 方法文档
- **新增**: `ApplyConfig(Config config)` 方法文档
- **新增**: `GetRemoteAddress()` 方法文档
- **新增**: `OnSendComplete(SendCompleteCallback cb)` 方法文档
- **新增**: `SendCompleteCallback` 类型定义
- **新增**: `SessionStats` 完整字段定义 (含新增的 retransmissions/rtt/window)

### 6.2 DatagramSocket API 增强
- **修正**: `RecvFrom` 返回类型更新为 `std::expected<std::optional<RecvResult>, SocketError>`
- **新增**: `EnableWriteNotifications` / `DisableWriteNotifications` 方法
- **新增**: `Address::operator==` / `operator!=`
- **新增**: `SocketError` 枚举完整定义

### 6.3 Server API 完善
- **新增**: `recv_buf_init_bytes` 配置字段
- **修正**: 驱逐相关枚举使用完全限定名

### 6.4 Client API 完善
- **新增**: `recv_buf_init_bytes` 配置字段
- **修正**: `ClientState` 各状态的语义说明 (明确kConnecting含义)

### 6.5 新增 Section 11: ProtocolEngine 接口
- **新增**: 协议引擎抽象接口完整定义 — 为扩展点提供明确的接口契约
- **新增**: `ProtocolEngineFactory::Create` 工厂函数

### 6.6 新增 Section 12: 其他基础类型
- **新增**: `TimerHandle`, `AddressFamily`, `IOBackend` 等类型集中定义

---

## 7. 06_high_concurrency_tests.md — 高并发单元测试需求 (新文件)

新增12个测试需求章节,覆盖:

| 章节 | 内容 | 测试项数 |
|------|------|----------|
| 1. 基础设施 | 模拟时钟/网络模拟器/TSan/ASan/压力框架 | 4 |
| 2. TaskQueue | MPSC正确性/高竞争/批量消费/TryPop/有界背压 | 5 |
| 3. TimerQueue | 并发Add+Fire/Cancel+Fire/无效Cancel/重复定时器/惰性清理 | 6 |
| 4. WorkerPool | ModuloHash一致性/并发Dispatch/RoundRobin/LeastSessions/Shutdown/一致性哈希 | 6 |
| 5. Session | 跨线程Send/并发Send+Close/FeedInput+Update/高频Update/析构安全/窗口背压 | 6 |
| 6. Server | 高频会话创建/创建驱逐并发/健康检测收发并发/多Worker隔离/会话上限 | 5 |
| 7. Client | 超时重连锁/连接中Disconnect/重连中Disconnect/断连恢复/快速Connect-Disconnect循环/超时竞态/收发并发 | 7 |
| 8. DatagramSocket | 缓冲区满/空读/边缘触发完整性/地址冲突/无效地址 | 5 |
| 9. E2E集成 | 多Client→单Server/P2P对称/网络分区恢复/优雅关闭/24h稳定性 | 5 |
| 10. 内存安全 | Session循环创建销毁/Server长时间运行/定时器泄漏/回调闭包链/Socket RAII | 5 |
| 11. 性能回归 | EventLoop吞吐/TaskQueue延迟/Session吞吐/Server创建速率 | 4 |
| 12. 确定性仿真 | 重传时序/拥塞窗口/乱序重组/确定性回归套件 | 4 |

---

## 8. 跨文件一致性修正汇总

### 8.1 统一迭代器写法
`it->second` (非 `it.second`) — 修正全部 `03_kcp_server.md` 中4处错误

### 8.2 统一 RecvFrom 返回类型
所有文件: `std::expected<std::optional<RecvResult>, SocketError>` 替代旧的 `std::optional<RecvResult>`

### 8.3 统一缓冲区初始化模式
所有文件: `recv_buf_.resize(init_bytes)` + `RecvFrom(buf.data(), buf.size())` 替代 `vector(N)` + `.capacity()`

### 8.4 统一枚举使用风格
所有枚举引用使用完全限定名 (如 `SessionState::kIdle` 而非裸 `kIdle`)

### 8.5 统一 recv_buf_init_bytes 配置项
Server::Config 和 Client::Config 均新增此字段 (默认65536),替代硬编码

---

## 9. Public API 变更清单 (Issue 3 累计)

### 新增接口
| 类 | 方法 | 说明 |
|----|------|------|
| Session | `SendHandshakePacket()` | 发送协议层握手首包 |
| Session | `SendProbePacket()` | 发送协议层探活包 |
| Session | `ApplyConfig(Config)` | 运行时更新配置 |
| Session | `GetRemoteAddress()` | 获取远端地址 |
| Session | `OnSendComplete(cb)` | 发送完成回调注册 |
| DatagramSocket | `EnableWriteNotifications()` | 启用可写通知 (重命名自SetWriteHandler) |
| DatagramSocket | `DisableWriteNotifications()` | 关闭可写通知 |
| Address | `operator==` / `operator!=` | 地址比较运算符 |

### 返回类型变更
| 方法 | 旧类型 | 新类型 |
|------|--------|--------|
| `DatagramSocket::RecvFrom` | `std::optional<RecvResult>` | `std::expected<std::optional<RecvResult>, SocketError>` |

### 配置新增字段
| 结构 | 字段 | 类型 | 默认值 |
|------|------|------|--------|
| Server::Config | `recv_buf_init_bytes` | `size_t` | `65536` |
| Client::Config | `recv_buf_init_bytes` | `size_t` | `65536` |
| Session::Config | `enable_metrics` | `bool` | `true` |

---

## 10. 架构层面的关键修复

### 10.1 Client 异步连接语义
**问题**: `DoConnect()` 中创建Session后立即 state=kConnected 并触发 success_handler — 但这发生在收到服务器任何响应之前,违反了异步连接语义。

**修复**: 引入 `OnServerFirstResponse()` — 仅在 `OnReadable` 收到首个有效服务器响应后才转换到 kConnected。完整流程:
```
DoConnect → SendHandshake → (kConnecting) → OnReadable → FeedInput → OnServerFirstResponse → (kConnected) → success_handler
```

### 10.2 Session事件到端点的传播机制
**问题**: Server和Client需要感知Session的错误和关闭事件,但此前WireSessionEvents仅注册了OnError,缺少OnStateChange。

**修复**: 两端点均注册OnError和OnStateChange双回调,使用PostTask安全投递到EventLoop线程:
- OnError → EvictSession/Reconnect
- OnStateChange(kClosed) → 清理

### 10.3 迭代器生命周期安全
**问题**: `RemoveSession` 在 `EvictSession` 执行后使用 `it` 进行 `erase` — 若驱逐回调中间接触发对 `sessions_` 的修改,则迭代器可能已失效。

**修复**: 先取出 `shared_ptr` 副本 → erase → 在锁外执行 `EvictSession`。

### 10.4 闭包捕获安全性
**问题**: `MinimalClientExample` 中栈对象 `client` 被lambda以引用捕获 — 在异步回调执行时可能已析构。

**修复**: 示例代码改用 `shared_ptr<Client>` + 值捕获,回调中使用参数提供的 `session` 而非外部 `client`。

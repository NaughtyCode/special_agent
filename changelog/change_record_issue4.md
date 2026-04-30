# Issue 4 修改记录

## 概述

基于 Issue 4 要求对 `06_high_concurrency_tests.md`（高并发单元测试需求）和 `05_api_reference.md`（Public API参考）进行深度审查与修复。同时修复了 `03_kcp_server.md` 和 `04_kcp_client.md` 中 `RecvFrom` 返回值的错误处理逻辑。

---

## 1. 06_high_concurrency_tests.md — 高并发单元测试需求

### 1.1 术语与工具链描述修正

| 位置 | 修正前 | 修正后 | 原因 |
|------|--------|--------|------|
| 1.3 | `helgrind (valgrind)` | `Helgrind (Valgrind工具)` | 专有名词大写，明确Helgrind是Valgrind工具集的组成部分 |
| 1.3 | `CI中` | `CI流水线中` | 书写规范化 |
| 1.3 | 仅提及TSan | 分别说明TSan检测数据竞争、ASan检测内存错误、Helgrind检测锁顺序问题 | 工具职责分离表述 |

### 1.2 堆完整性验证工具修正

| 位置 | 修正前 | 修正后 |
|------|--------|--------|
| 3.1 | `heap_无损坏 (TSan验证)` | `堆数据结构无损坏: 操作后验证堆不变量 (父节点 ≤ 子节点)` + `TSan无数据竞争报告` |

**原因**: TSan检测数据竞争而非堆损坏。堆完整性应由断言/不变式检查验证，两者互补。

### 1.3 WorkerPool测试对齐

| 位置 | 修正前 | 修正后 | 原因 |
|------|--------|--------|------|
| 4.4 | `差值不超过配置阈值` | 移除阈值引用，改为`session_count分布趋于均匀` | WorkerPool无此配置项，测试应反映实际接口 |
| 4.6 | `由上层管理迁移` | `Session迁移需由上层 (如Server) 根据映射变更自行处理` | 明确WorkerPool不负责Session迁移，责任边界清晰 |

### 1.4 Session线程模型描述修正

| 位置 | 修正前 | 修正后 |
|------|--------|--------|
| 5.3 | `在正确线程上交替高频执行` | `在同一EventLoop线程上串行交替执行` |

**原因**: Session非线程安全，"正确线程"表述模糊。"同一EventLoop线程串行"明确所有操作在单一线程序列化执行。

### 1.5 shared_ptr生命周期描述修正

| 位置 | 修正前 | 修正后 |
|------|--------|--------|
| 5.5 | `直接从外部delete/重置shared_ptr` | `从外部重置/销毁shared_ptr (reset或离开作用域)` |

**原因**: `delete shared_ptr` 是错误表述，shared_ptr通过`reset()`或析构来释放。

### 1.6 Server测试与实现对齐

| 位置 | 修正前 | 修正后 | 原因 |
|------|--------|--------|------|
| 6.1 | 无 | 添加`使用模拟网络 (非真实Socket) 以实现可控速率` | 10K/s的创建速率在真实网络上不可达，必须使用模拟 |
| 6.2 | `如配置了上限驱逐` → `sessions_.size() <= max_sessions` | `sessions_.size()在达到max_sessions后不再增长 (新到达的包被静默丢弃)` | Server当前实现为达到上限时拒绝新包，非自动驱逐旧会话 |
| 6.4 | `每个Worker独立的Server+EventLoop` | 重新表述为WorkerPool分配模式：`相同conv的数据报始终路由到同一Worker` | 多Worker模式不要求独立Server实例，关键在路由一致性 |

### 1.7 边缘触发测试描述修正

| 位置 | 修正前 | 修正后 |
|------|--------|--------|
| 8.3 | `如果循环提前退出,剩余数据报不会触发新的事件通知 (边缘触发特征)` | `边缘触发要求彻底排空Socket recv缓冲区; 如果循环在排空前退出,剩余数据报将丢失` |

**原因**: 原文暗示"丢失"是预期行为，实为**使用者的错误**。边缘触发模式下未排空是bug，测试应验证正确排空行为。

### 1.8 ICMP错误路径描述修正

| 位置 | 修正前 | 修正后 |
|------|--------|--------|
| 8.5 | `在RecvFrom中返回kConnectionRefused` | `下一次RecvFrom调用可能返回SocketError::kConnectionRefused (通过std::expected的error通道)` |

**原因**: 澄清ICMP错误通过`std::expected`的error路径返回，而非通过`RecvResult`数据字段。

### 1.9 E2E测试API名称修正

| 位置 | 修正前 | 修正后 |
|------|--------|--------|
| 9.2 | `双方同时Connect和Listen` | `Peer-A绑定端口A并Start Server, Peer-B绑定端口B并Start Server; 然后互相Connect` |

**原因**: API中不存在`Listen`方法，Server通过`Start()`启动。

### 1.10 性能指标澄清

| 位置 | 修正前 | 修正后 |
|------|--------|--------|
| 11.1 | `满载 (10K Session) 每秒钟的Update+IO处理能力` | `满载(10K活跃Session)下EventLoop每周期处理能力(IO事件+定时器+Update)` |

### 1.11 乱序交付语义修正

| 位置 | 修正前 | 修正后 |
|------|--------|--------|
| 12.3 | `乱序包到达后消息立即可交付 (不等待)` | `当最后一个缺口分片到达时,完整消息立即交付给应用层 (TryRecv); 缺口未补齐前,PeekMessageSize()返回0或<0 (不完整)` |

**原因**: 仅当到达的分片填补了最后缺口时消息才可交付。任意乱序包到达不等于消息可交付。

### 1.12 新增附录A：测试优先级与依赖

新增附录定义P0~P3四级测试优先级和测试模块间依赖关系：
- P0 (阻断): 每次commit前 — 核心正确性 (MPSC/定时器/Session析构/内存泄漏)
- P1 (高): 每次PR前 — 线程安全与集成 (WorkerPool/Server/Client状态机/E2E优雅关闭)
- P2 (中): 每日构建 — 负载与稳定性
- P3 (低): 每周/发版前 — 性能回归/确定性仿真
- 依赖链: TaskQueue/TimerQueue → WorkerPool/DatagramSocket → Session → Server/Client → E2E

### 1.13 其他细节优化

- 1.1: 模拟时钟增加"同一AdvanceTime内先到期的先触发"语义说明
- 1.2: 网络模拟器增加"支持动态修改链路参数"要求
- 2.1: 明确生产者数N和任务数M的具体值 (N=4,8; M=100K)
- 2.2: 增加"随生产者数量增加吞吐量单调递增"验证条件
- 3.3: 增加`Cancel(0)`无效句柄测试
- 3.6: 增加"连续Cancel堆顶3次"的级联清理测试
- 5.6: 增加暂停Update模拟对端无响应的场景说明
- 7.1: 增加模拟时钟要求以保证退避时序可精确验证
- 7.2: 增加模拟时钟说明
- 9.5: 明确使用模拟时钟加速 (1模拟秒=1实际毫秒)
- 10.1: 增加LSan验证和RSS回归基线 (每10K次回归初始值±5%)
- 10.5: 增加move后fd标记为invalid的验证
- 12.4: 增加网络trace文件格式说明

---

## 2. 05_api_reference.md — Public API参考

### 2.1 C++标准版本声明修正

**修正前**: `所有API均为C++17标准`

**修正后**: `API设计面向现代C++ (C++17为基础,部分类型使用C++20/23标准库设施的polyfill或等效替代)`

**原因**: `std::span`(C++20)、`std::expected`(C++23)、`std::move_only_function`(C++23) 非C++17标准库。文档应诚实说明，并指出可使用polyfill（如`tl::expected`、`fu2::unique_function`、`gsl::span`）。

### 2.2 Send/SendComplete API不匹配修复

**问题**: `Send()`返回`SendResult` (kQueued/kBlocked)不含`message_id`，但`OnSendComplete`回调参数为`uint32_t message_id`。二者无法关联。

**修复**: 
- `Send()` 文档增加说明: "当前返回值为SendResult枚举,不含message_id; OnSendComplete回调中的message_id为协议引擎内部分配的序列号"
- `OnSendComplete` 文档增加说明: "此回调在引擎内部确认对端ACK时触发,与Send()返回值无直接关联"
- 建议应用层如需消息级确认，在Message载荷中携带业务id

### 2.3 EventLoop线程安全描述修正

**修正前**: `线程安全: Start/Stop线程安全, Register/Modify/Unregister必须在所属线程调用`

**修正后**: `线程安全: Stop可从任何线程调用; Run在调用线程阻塞执行; Register/Modify/Unregister必须在EventLoop所属线程调用`

**原因**: EventLoop无`Start`方法（只有`Run`/`Stop`）。`Run`阻塞在当前线程，`Stop`线程安全。

### 2.4 WorkerPool::Dispatch路由键类型修正

**修正前**: `void Dispatch(uint64_t routing_key, ...)`

**修正后**: `void Dispatch(uint32_t routing_key, ...)`

**原因**: Session的`conv`为`uint32_t`。`routing_key`类型应与之匹配，避免隐式转换和位宽不一致。

### 2.5 ParseResult类型定义补充

**问题**: `ProtocolEngine::Input()`返回`ParseResult`，但该类型在任何文件中均未定义。

**修复**: 在Section 11中补充`ParseResult`结构体完整定义:
```
STRUCT ParseResult:
    success: bool
    error: std::optional<SessionError>
    bytes_consumed: size_t
    STATIC FUNCTION Ok(consumed) / Err(e)
```

### 2.6 RecvMessage返回值语义文档化

**问题**: `RecvMessage`返回`int`，但正/零/负值的语义未说明。

**修复**: 补充完整文档: `>0=实际消息字节数, 0=无消息就绪, <0=错误`，并说明`max_len`应`>= PeekMessageSize()`。

### 2.7 移除重复类型定义

**移除**: Section 12中以下重复定义：
- `IOBackend` — 已在Section 4.1定义
- `AddressFamily` — 已移至Section 5.2 (DatagramSocket辅助类型)
- `TimerHandle` — 已在Section 9定义

**保留**: Section 12改名为"附录: 类型速查"，仅保留`TimerHandle`作为快速索引。

### 2.8 ApplyConfig前置条件矛盾修正

**修正前**: `前置条件: state_ == SessionState::kIdle (仅允许在未启动时修改)` + `说明: 运行时重新配置协议参数`

**修正后**: `前置条件: state_ == SessionState::kIdle (配置仅在Start前可修改)` + `说明: 设置协议参数...如需运行时调整,应在创建新Session时应用新Config`

**原因**: 实现中`IF state_ != kIdle: RETURN`直接拒绝非kIdle状态的修改。"运行时重新配置"表述与实现矛盾。

### 2.9 SendHandshakePacket/SendProbePacket可见性警告

**新增**: 两个方法增加应用层使用警告：
- `SendHandshakePacket`: "此方法通常由端点层(Client/Peer)在连接初始化时调用,应用层不应直接使用 — 误调用可能导致协议状态异常"
- `SendProbePacket`: "此方法通常由Server在空闲检测时调用,或由应用层在需要主动检测连接存活时调用"

### 2.10 Client::Send前置条件修正

**修正前**: `前置条件: state_ == ClientState::kConnected`

**修正后**: 移除"前置条件"措辞，改为: `state_ != kConnected时返回kBlocked (调用方应检查返回值或等待kConnected)`

**原因**: 实现中state_!=kConnected时返回kBlocked而非assert/异常。文档应描述实际行为而非误导性前置条件。

### 2.11 DatagramSocket线程安全描述修正

**修正前**: `所有操作必须在所属EventLoop线程执行`

**修正后**: `SendTo和RecvFrom的底层系统调用本身是线程安全的 (OS保证),但EventLoop注册操作 (SetReadHandler/EnableWriteNotifications等) 必须在EventLoop所属线程调用`

**原因**: POSIX `sendto`/`recvfrom` 是线程安全的系统调用。EventLoop的epoll/kqueue注册操作才必须在所属线程。

### 2.12 RecvFrom返回值处理指南

**新增**: 详细说明调用方应如何区分SocketError和nullopt两种无数据情况，附带代码示例。

### 2.13 API文档其他优化

- Section 1.11: 移除`GetRemoteAddress()`重复文档（已在1.11中列出）
- Section 5.2: `AddressFamily`从Section 12移至DatagramSocket辅助类型区（逻辑归属）
- Section 11: `ProtocolEngine::ResetBuffers`补充"通常在Close时调用"的上下文
- Section 11: `ProtocolEngineFactory::Create`补充扩展注册机制的用法说明
- 类头描述统一"线程安全"措辞格式

---

## 3. 03_kcp_server.md & 04_kcp_client.md — RecvFrom错误处理修复

### 问题

`DatagramSocket::RecvFrom`返回类型为 `std::expected<std::optional<RecvResult>, SocketError>`（三态），但Server和Client的`OnReadable`方法仅检查 `recv_result.has_value()`（即检查是否为expected类型），将SocketError和nullopt（无数据）两种不同情况混为一谈：

```cpp
// 修正前: 将SocketError误当作"无数据",直接BREAK
IF NOT recv_result.has_value():
    BREAK
```

这导致：
1. **ICMP错误（如端口不可达）** 被当作"缓冲区排空"，读取循环提前退出
2. 未能区分"暂时性Socket错误"和"正常无数据"
3. `recv_result->data`等字段访问需要通过两层解引用（expected→optional→RecvResult），原代码的`recv_result->data`写法在双重包装下不正确

### 修复

```cpp
// 修正后: 分三层处理
IF NOT recv_result.has_value():
    // SocketError → 记录日志,继续循环
    LOG_WARN("RecvFrom socket error: {}", ...)
    CONTINUE
IF NOT recv_result->has_value():
    // nullopt → 缓冲区排空,退出循环
    BREAK
// 提取RecvResult引用,后续使用result.data/result.len/result.sender
auto& result = recv_result.value().value()
```

### 影响文件
- `03_kcp_server.md`: `OnReadable()` — 修正SocketError/无数据的区分处理
- `04_kcp_client.md`: `OnReadable()` — 同上

---

## 4. 跨文件一致性检查清单

| 检查项 | 涉及文件 | 状态 |
|--------|----------|------|
| Send返回类型与OnSendComplete参数可关联性 | 05_api_reference, 02_kcp_session | 已文档化差异 |
| EventLoop线程安全描述 (Stop vs Start) | 05_api_reference | 已修正 |
| WorkerPool::Dispatch routing_key类型 | 05_api_reference, 07 (WorkerPool) | 已统一为uint32_t |
| RecvFrom三态返回值处理 | 03_server, 04_client, 05_api | 已修正 |
| ParseResult类型定义 | 05_api_reference | 已补充 |
| C++标准版本声明与实际特性对齐 | 05_api_reference | 已修正 |
| 重复类型定义清理 | 05_api_reference Section 12 | 已清理 |
| ApplyConfig前置条件与说明一致 | 05_api_reference, 02_kcp_session | 已修正 |
| Client::Send前置条件vs守卫行为 | 05_api_reference, 04_kcp_client | 已修正 |
| 乱序包交付语义 | 06_test_requirements 12.3 | 已修正 |
| Server max_sessions超越上限行为 | 06_test_requirements 6.2, 03_server | 已对齐 (拒绝而非驱逐) |

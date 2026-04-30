# API 详细参考文档

本文档列出所有核心接口的完整API定义，包含类/接口名、函数签名、返回值、参数类型和参数名。所有API均为C++17标准，使用 `std::optional`、`std::expected`、`std::move_only_function`、`std::span` 等现代C++特性。

---

## 1. Session 类

```
类名: Session
基类: std::enable_shared_from_this<Session>
头文件: session.h
描述: 传输协议会话抽象,管理单个连接的生命周期和数据收发,接口为协议无关设计
     线程安全: 非线程安全,所有操作必须在所属EventLoop线程执行
```

### 1.1 类型定义

| 类型名 | 定义 |
|--------|------|
| `MessageCallback` | `std::move_only_function<void(std::unique_ptr<Message>)>` |
| `ErrorCallback` | `std::move_only_function<void(SessionError)>` |
| `StateChangeCallback` | `std::move_only_function<void(SessionState old, SessionState new)>` |
| `SendCompleteCallback` | `std::move_only_function<void(uint32_t message_id)>` |

### 1.2 枚举

```
enum class SessionState {
    kIdle      = 0,  // 初始空闲,尚未Start
    kConnected = 1,  // 已连接,可收发数据
    kClosing   = 2,  // 正在优雅关闭 (等待对端确认)
    kClosed    = 3   // 已关闭,终态 (不可逆)
};

enum class SessionError {
    kProtocolError,   // 协议引擎解析/状态异常
    kSocketError,     // 底层Socket错误
    kTimeout,         // 连接超时
    kBufferOverflow,  // 接收缓冲区溢出
    kRemoteClose,     // 对端主动发送关闭通知
    kLocalClose       // 本地主动调用Close
};

enum class SendResult {
    kQueued  = 0,  // 数据已加入发送队列,等待协议引擎异步发送
    kBlocked = 1   // 状态不允许发送 (未连接/已关闭/发送窗口满)
};

enum class ConnectionHealth {
    kHealthy = 0,  // 正常通信中 (距上次收包 < idle_threshold)
    kIdle    = 1,  // 空闲 (idle_threshold <= 距上次收包 < stale_threshold)
    kStale   = 2   // 过期 (距上次收包 >= stale_threshold,应被驱逐)
};

enum class ProtocolProfile {
    kFastMode,      // 低延迟优先 (实时游戏/VoIP/即时交互)
    kReliableMode,  // 可靠性优先 (文件传输/数据同步/批量导入)
    kBalancedMode,  // 平衡模式 (通用RPC/消息推送)
    kCustom         // 用户逐参数自定义 (所有字段需手动设置)
};
```

### 1.3 配置结构

```
struct Session::Config {
    // === 协议预设 (选择后自动填充下列4项) ===
    ProtocolProfile profile = ProtocolProfile::kFastMode;

    // === 以下字段在kFast/kReliable/kBalanced模式下由FromProfile填充 ===
    int nodelay = 1;                    // 0=普通模式(RTO翻倍), 1=快速模式(RTO×1.5)
    int update_interval_ms = 10;        // 协议内部时钟周期(ms),Update()调用间隔
    int fast_resend_threshold = 2;      // 快速重传触发阈值 (跳过ACK次数)
    bool flow_control_enabled = false;  // 是否启用拥塞流控

    // === 以下字段对所有Profile生效,可独立覆盖 ===
    int mtu_bytes = 1400;                   // 最大传输单元(字节),含协议头
    int send_window_packets = 128;          // 发送窗口大小(包数)
    int recv_window_packets = 128;          // 接收窗口大小(包数)
    size_t rx_buffer_init_bytes = 64*1024;  // 接收缓冲区初始大小(字节)
    size_t tx_buffer_init_bytes = 64*1024;  // 发送缓冲区初始大小(字节)
    bool enable_metrics = true;             // 是否启用运行时统计收集

    // 工厂方法: 从Profile预设生成完整配置
    static Config FromProfile(ProtocolProfile profile);
};
```

### 1.4 构造函数

```
Session(
    uint32_t conv,                               // [in] 会话标识 (routing_key),全网唯一或(地址+conv)唯一
    EventLoop* event_loop,                       // [in] 绑定的EventLoop (生命周期由调用方保证)
    DatagramSocket* socket,                      // [in] 数据报Socket (借用,生命周期由调用方保证)
    DatagramSocket::Address remote_addr,         // [in] 远端地址 (发送目标/来源验证)
    Config config = Config::FromProfile(ProtocolProfile::kFastMode)  // [in] 会话协议配置
)
// 后置条件: state_ == kIdle, 协议引擎已创建, OutputCallback已注册
// 说明: 构造后需调用 Start() 方可收发数据
```

### 1.5 生命周期管理

```
void Start()
// 返回值: void
// 前置条件: state_ == SessionState::kIdle
// 后置条件: state_ == SessionState::kConnected
// 说明: 激活会话,此后可进行数据收发

void Close()
// 返回值: void
// 前置条件: 无限制 (幂等操作)
// 后置条件: state_ == SessionState::kClosed
// 说明: 立即关闭会话,清空缓冲区,通知对端,取消shutdown定时器

void GracefulShutdown(uint32_t timeout_ms = 5000)
// 返回值: void
// 参数: timeout_ms — [in] 优雅关闭超时(ms),超时后自动调用Close()
// 前置条件: state_ == SessionState::kConnected
// 后置条件: state_ == SessionState::kClosed (可能在timeout_ms后)
// 说明: 发送关闭通知→等待对端ACK确认→超时未确认则强制Close
```

### 1.6 数据发送

```
SendResult Send(const std::vector<uint8_t>& data)
// 返回值: SendResult — kQueued=已加入发送队列, kBlocked=阻塞
// 参数: data — [in] 待发送的用户数据 (拷贝到内部发送缓冲区)

SendResult Send(const uint8_t* data, size_t len)
// 返回值: SendResult
// 参数: data — [in] 数据指针 (不可为nullptr), len — [in] 数据长度 (必须>0)
// 前置条件: data != nullptr, len > 0
// 说明: 成功时更新 stats_.total_bytes_sent 和 total_messages_sent
```

### 1.7 协议层数据包发送

```
void SendHandshakePacket()
// 返回值: void
// 说明: 发送协议层握手首包,触发服务端的隐式Accept
//       由Client在DoConnect()中调用; Peer模式下也可由任一端调用

void SendProbePacket()
// 返回值: void
// 说明: 发送协议层探活包 (如KCP的WASK),对端自动回复确认
//       由Server在空闲检测时调用,或由上层应用主动触发
```

### 1.8 数据接收输入

```
void FeedInput(const uint8_t* data, size_t len)
// 返回值: void
// 参数: data — [in] 原始数据报载荷, len — [in] 数据长度(字节)
// 说明: 将底层数据报输入协议引擎解析
//       内部流程: 更新last_recv_time_ms_ → Engine.Input() → TryRecv() → 触发回调
//       解析错误时通过OnError回调通知
```

### 1.9 定时驱动

```
void Update(uint64_t now_ms)
// 返回值: void
// 参数: now_ms — [in] 当前时间戳(毫秒),由Clock::NowMs()获取
// 说明: 驱动协议引擎状态机 (重传判定/ACK发送/窗口更新/RTT估算)
//       应由EventLoop以 config_.update_interval_ms 为周期调用
//       引擎在Update中通过OutputCallback输出待发送数据包
```

### 1.10 回调注册

```
void OnMessage(MessageCallback cb)
// 参数: cb — [in] 收到完整用户消息时的回调 (在TryRecv中触发)

void OnError(ErrorCallback cb)
// 参数: cb — [in] 发生不可恢复错误时的回调

void OnStateChange(StateChangeCallback cb)
// 参数: cb — [in] 状态变更回调,参数为 (old_state, new_state)

void OnSendComplete(SendCompleteCallback cb)
// 参数: cb — [in] 单个消息完全确认送达时的回调 (可选扩展)
//       参数 message_id 为发送时返回的序列号
```

### 1.11 状态查询

```
uint32_t GetConvId() const
// 返回值: 会话标识 (routing_key)

SessionState GetState() const
// 返回值: 当前会话状态

uint64_t GetLastRecvTime() const
// 返回值: 最后一次收到有效数据的时间戳(ms)

DatagramSocket::Address GetRemoteAddress() const
// 返回值: 远端地址的副本

ConnectionHealth EvaluateHealth(
    uint64_t now_ms,
    uint32_t idle_threshold_ms = 15000,
    uint32_t stale_threshold_ms = 30000
) const
// 返回值: ConnectionHealth — 连接健康分级
// 参数:
//   now_ms              — [in] 当前时间(ms)
//   idle_threshold_ms   — [in] 空闲判定阈值,默认15s (超过则kIdle)
//   stale_threshold_ms  — [in] 过期判定阈值,默认30s (超过则kStale)

SessionStats GetStats() const
// 返回值: SessionStats — 运行时统计快照 (收发字节/包/消息数/重传次数/RTT等)

void ApplyConfig(Config config)
// 参数: config — [in] 新的会话配置
// 前置条件: state_ == SessionState::kIdle (仅允许在未启动时修改)
// 说明: 运行时重新配置协议参数 (如MTU/窗口大小)
```

---

## 2. Server 类

```
类名: Server
头文件: server.h
基类: IEventHandler
描述: 服务端端点,负责数据报监听、会话创建/路由/销毁、健康检测与驱逐
     线程安全: 所有操作在所属EventLoop线程执行
```

### 2.1 类型定义

```
using NewSessionHandler     = std::move_only_function<void(std::shared_ptr<Session>)>;
using SessionEvictedHandler = std::move_only_function<void(uint32_t conv, EvictReason)>;
using SessionMap            = std::unordered_map<uint32_t, std::shared_ptr<Session>>;
```

### 2.2 枚举

```
enum class ServerState {
    kStopped = 0,  // 未启动
    kRunning = 1   // 运行中 (监听Socket,接受会话)
};

enum class EvictReason {
    kTimedOut,      // 空闲超时 (stale)
    kRemoteClosed,  // 对端主动关闭
    kLocalClosed,   // 本地主动关闭
    kError          // 协议/Socket错误
};

enum class EvictionPolicy {
    kImmediateClose,    // 立即Close,不等待
    kGracefulShutdown,  // 尝试GracefulShutdown,超时后强制Close
    kNotifyOnly         // 仅通知上层,由上层决定 (不自动关闭)
};

enum class IdlePolicy {
    kIgnore,     // 忽略空闲
    kSendProbe,  // 发送协议层探活包
    kNotify      // 通知上层 (不自动处理)
};
```

### 2.3 配置结构

```
struct Server::Config {
    DatagramSocket::Address listen_address;               // 监听地址
    Session::Config session_config;                       // 新会话默认协议配置
    size_t max_sessions = 0;                              // 最大会话数 (0=不限制)
    uint32_t health_check_interval_ms = 1000;             // 健康检测周期
    uint32_t idle_timeout_ms = 15000;                     // 空闲超时 (超过则kIdle)
    uint32_t stale_timeout_ms = 30000;                    // 过期超时 (超过则kStale)
    EvictionPolicy eviction_policy = EvictionPolicy::kImmediateClose;
    IdlePolicy idle_policy = IdlePolicy::kSendProbe;
    DatagramSocket::SocketConfig socket_config = DatagramSocket::SocketConfig::Default();
    size_t recv_buf_init_bytes = 65536;                   // 接收缓冲区初始大小
};
```

### 2.4 构造函数

```
Server(EventLoop* event_loop, Config config)
// 参数: event_loop — [in] 事件循环 (生命周期由调用方保证)
//       config      — [in] 服务端配置 (包含监听地址/会话配置/驱逐策略等)
// 后置条件: state_ == ServerState::kStopped, Socket已创建并绑定
```

### 2.5 生命周期

```
void Start()
// 返回值: void
// 前置条件: state_ == ServerState::kStopped
// 后置条件: state_ == ServerState::kRunning
// 说明: 注册Socket可读事件,启动健康检测定时器

void Stop()
// 返回值: void
// 前置条件: 无
// 后置条件: state_ == ServerState::kStopped
// 说明: 取消定时器,驱逐所有现存会话
```

### 2.6 回调注册

```
void OnNewSession(NewSessionHandler handler)
// 参数: handler — [in] 新会话建立时的回调 (收到首包隐式Accept后触发)

void OnSessionEvicted(SessionEvictedHandler handler)
// 参数: handler — [in] 会话被驱逐时的回调 (参数: conv, reason)
```

### 2.7 会话管理

```
std::shared_ptr<Session> GetSession(uint32_t conv)
// 返回值: 会话的shared_ptr,不存在时返回nullptr

void RemoveSession(uint32_t conv, EvictReason reason)
// 参数: conv   — [in] 会话标识
//       reason — [in] 驱逐原因
// 说明: 先查找→取出→从表中移除→执行驱逐 (防止重入)

size_t GetSessionCount() const
// 返回值: 当前活跃会话数
```

### 2.8 IEventHandler实现

```
void OnReadable()
// 说明: Socket可读时循环接收数据报→解析routing_key→路由到已有Session或创建新Session
//       边缘触发模式下循环读取直到返回nullopt
```

---

## 3. Client 类

```
类名: Client
头文件: client.h
基类: IEventHandler
描述: 客户端端点,管理与服务器的单个会话连接,支持异步连接和多种重连策略
     线程安全: 所有操作在所属EventLoop线程执行
```

### 3.1 类型定义

```
using ConnectSuccessHandler = std::move_only_function<void(std::shared_ptr<Session>)>;
using ConnectFailureHandler = std::move_only_function<void(ConnectError)>;
```

### 3.2 枚举

```
enum class ClientState {
    kDisconnected  = 0,  // 未连接
    kConnecting    = 1,  // 已发送握手,等待服务器首次响应
    kConnected     = 2,  // 已收到服务器响应,可正常收发
    kReconnecting  = 3,  // 断连后等待重连
    kClosed        = 4   // 已关闭,终态
};

enum class ConnectError {
    kTimeout,             // 连接超时 (connect_timeout_ms内未收到响应)
    kRefused,             // 被服务器拒绝
    kDnsFailed,           // DNS解析失败
    kSocketError,         // Socket创建/绑定/IO错误
    kMaxRetriesExceeded   // 超过最大重连次数
};
```

### 3.3 配置结构

```
struct ReconnectStrategy {
    uint32_t initial_delay_ms = 1000;   // 初始重连间隔
    uint32_t max_delay_ms = 30000;      // 最大重连间隔 (封顶)
    float backoff_factor = 2.0;         // 退避因子 (每次乘以此值)
    uint32_t max_attempts = 5;          // 最大重试次数 (0=无限)
    uint32_t jitter_ms = 200;           // 随机抖动范围 (避免惊群)
};

struct Client::Config {
    DatagramSocket::Address remote_address;                       // 目标服务器地址
    Session::Config session_config;                               // Session协议配置
    std::optional<ReconnectStrategy> reconnect;                   // 重连策略 (nullopt=禁用)
    uint32_t connect_timeout_ms = 5000;                           // 连接超时(ms)
    DatagramSocket::Address local_bind_address = DatagramSocket::Address::Any();
    DatagramSocket::SocketConfig socket_config = DatagramSocket::SocketConfig::Default();
    size_t recv_buf_init_bytes = 65536;                           // 接收缓冲区初始大小
};
```

### 3.4 构造函数

```
Client(EventLoop* event_loop, Config config)
// 参数: event_loop — [in] 事件循环 (生命周期由调用方保证)
//       config      — [in] 客户端配置
// 后置条件: state_ == ClientState::kDisconnected, Socket已创建
```

### 3.5 连接管理

```
void Connect(
    ConnectSuccessHandler on_success = nullptr,
    ConnectFailureHandler on_failure = nullptr
)
// 说明: 异步连接,非阻塞立即返回
//       流程: 创建Session → 发送握手首包 → 等待服务器响应
//       成功: 收到服务器首次有效响应后回调on_success
//       失败: 超时且无重连或达到最大重试次数后回调on_failure

void Disconnect()
// 说明: 断开连接,取消重连,关闭并释放Session
// 后置条件: state_ == ClientState::kDisconnected
```

### 3.6 数据发送

```
SendResult Send(const std::vector<uint8_t>& data)
// 返回值: SendResult — kQueued=已加入队列, kBlocked=未连接或窗口满
// 参数: data — [in] 待发送数据

SendResult Send(const uint8_t* data, size_t len)
// 返回值: SendResult
// 参数: data — [in] 数据指针 (不可为nullptr), len — [in] 数据长度 (必须>0)
// 前置条件: state_ == ClientState::kConnected
```

### 3.7 状态查询

```
std::shared_ptr<Session> GetSession() const
// 返回值: 当前会话的shared_ptr,未连接时可能为nullptr

ClientState GetState() const
// 返回值: 当前客户端状态
```

### 3.8 IEventHandler实现

```
void OnReadable()
// 说明: Socket可读时循环接收数据报
//       验证: 源地址==remote_address AND routing_key匹配
//       通过验证后调用session->FeedInput()
//       首次收到有效响应时自动从kConnecting转为kConnected
```

---

## 4. EventLoop 类

```
类名: EventLoop
头文件: event_loop.h
描述: 跨平台IO事件循环抽象,统一封装epoll/IOCP/kqueue/poll
     线程安全: Start/Stop线程安全, Register/Modify/Unregister必须在所属线程调用
```

### 4.1 枚举与类型

```
enum class IOBackend {
    kAutoDetect,  // 自动选择当前平台最优IO模型
    kEpoll,       // Linux epoll
    kIocp,        // Windows IOCP
    kKqueue,      // macOS/BSD kqueue
    kPoll         // POSIX poll (通用回退方案)
};

enum class IOMask : uint8_t {
    kReadable      = 0x01,  // 可读事件
    kWritable      = 0x02,  // 可写事件
    kError         = 0x04,  // 错误事件
    kEdgeTriggered = 0x10   // 边缘触发 (推荐用于高性能场景)
};

struct EventDesc {
    uintptr_t fd_or_handle;      // 文件描述符 (POSIX) 或句柄 (Windows)
    // Platform platform_tag;    // 平台标记 (内部使用)
};
```

### 4.2 公有接口

```
EventLoop(IOBackend backend = IOBackend::kAutoDetect)
// 参数: backend — [in] IO后端选择,默认自动检测最优

void Run()
// 返回值: void
// 说明: 阻塞运行事件循环
//       每轮循环: IO事件等待 → 分派Handler → 触发到期定时器 → 执行异步任务
//       循环直到外部调用Stop()

void Stop()
// 返回值: void
// 说明: 停止事件循环,线程安全 (可从任何线程调用)
//       内部通过WakeUp()唤醒正在阻塞的Run()

void Register(EventDesc desc, IOMask mask, IEventHandler* handler)
// 参数: desc    — [in] 文件描述符或句柄
//       mask    — [in] 关注的事件位掩码 (可组合)
//       handler — [in] 事件回调接口 (生命周期由调用方保证)
// 说明: 注册文件描述符及其关注的事件类型

void Modify(EventDesc desc, IOMask new_mask)
// 参数: desc     — [in] 已注册的描述符
//       new_mask — [in] 新的事件掩码
// 说明: 修改已注册描述符的关注事件 (如添加/移除可写监听)

void Unregister(EventDesc desc)
// 参数: desc — [in] 已注册的描述符
// 说明: 取消注册,不再接收此描述符的事件通知

void PostTask(std::move_only_function<void()> task)
// 参数: task — [in] 可移动闭包
// 说明: 向EventLoop线程安全投递任务,常用于跨线程操作
//       内部Push到任务队列后WakeUp()唤醒事件循环

TimerHandle AddTimer(
    uint32_t delay_ms,
    std::move_only_function<void()> callback
)
// 返回值: TimerHandle — 定时器句柄 (用于取消)
// 参数: delay_ms — [in] 延迟时间(ms)
//       callback — [in] 到期时执行的回调 (一次性)
// 说明: 添加一次性定时器

TimerHandle AddPeriodicTimer(
    uint32_t interval_ms,
    std::move_only_function<void()> callback
)
// 返回值: TimerHandle
// 参数: interval_ms — [in] 周期间隔(ms)
//       callback    — [in] 每次到期时执行的回调
// 说明: 添加周期性定时器,每隔interval_ms重复触发

void CancelTimer(TimerHandle handle)
// 参数: handle — [in] 定时器句柄
// 说明: 取消指定定时器 (延迟删除: 标记取消,在下次Fire时跳过并清理)
```

---

## 5. DatagramSocket 类

```
类名: DatagramSocket
头文件: datagram_socket.h
描述: 非阻塞数据报Socket的RAII封装,抽象UDP/UDPLite/Unix Domain Dgram
     线程安全: 非线程安全,所有操作必须在所属EventLoop线程执行
```

### 5.1 公有接口

```
DatagramSocket(
    EventLoop* event_loop,
    Address bind_addr = Address::Any(),
    SocketConfig config = SocketConfig::Default()
)
// 参数: event_loop — [in] 事件循环 (用于Register)
//       bind_addr  — [in] 绑定地址 (Any()=任意地址随机端口)
//       config     — [in] Socket选项配置
// 后置条件: Socket已创建/绑定/设为非阻塞

std::expected<int, SocketError> SendTo(
    const uint8_t* data, size_t len, Address dest
)
// 返回值: std::expected<int, SocketError>
//         成功 → 发送字节数
//         失败 → SocketError (kWouldBlock表示发送缓冲区满,可等待可写事件)
// 参数: data — [in] 待发送数据指针
//       len  — [in] 数据长度
//       dest — [in] 目标地址

std::expected<std::optional<RecvResult>, SocketError> RecvFrom(
    uint8_t* buffer, size_t buffer_capacity
)
// 返回值: std::expected<std::optional<RecvResult>, SocketError>
//         成功且有数据  → RecvResult (含数据指针/长度/来源/时间戳)
//         成功但无数据  → std::nullopt (非阻塞模式正常,需等待下次可读事件)
//         失败          → SocketError (ICMP错误等不影响Socket继续使用)
// 参数: buffer          — [out] 接收缓冲区 (数据写入此处)
//       buffer_capacity — [in]  缓冲区可用容量
// 注意: RecvResult::data 指向传入的buffer,生命周期与buffer一致

void SetReadHandler(IEventHandler* handler)
// 参数: handler — [in] 事件处理器 (实现OnReadable/OnWritable/OnError)
// 说明: 向EventLoop注册此Socket的可读事件 (边缘触发模式)

void EnableWriteNotifications(IEventHandler* handler)
// 参数: handler — [in] 事件处理器
// 说明: 启用可写通知 (发送缓冲区从满→可用时通知)
//       仅在SendTo返回kWouldBlock后需要等待恢复时使用

void DisableWriteNotifications(IEventHandler* handler)
// 参数: handler — [in] 事件处理器
// 说明: 关闭可写通知 (恢复为仅监听可读,减少不必要的事件触发)
```

### 5.2 辅助类型

```
struct DatagramSocket::Address {
    std::string ip;        // IPv4/IPv6地址字符串 或 Unix Domain路径
    uint16_t port;         // 端口号 (Unix Domain时忽略)
    AddressFamily family;  // kIPv4 / kIPv6 / kUnixDomain

    bool operator==(const Address& other) const
    // 返回值: ip、port、family三者全部相等时为true

    bool operator!=(const Address& other) const
    // 返回值: !(*this == other)

    static Address Any()
    // 返回值: Address{"0.0.0.0", 0, kIPv4}
    // 说明: 绑定到任意地址随机端口

    static Address From(std::string ip, uint16_t port)
    // 返回值: 根据ip字符串自动检测AddressFamily的Address
    // 参数: ip   — [in] IPv4/IPv6地址字符串
    //       port — [in] 端口号
};

struct DatagramSocket::RecvResult {
    const uint8_t* data;    // 数据指针 (指向调用方RecvFrom的buffer参数)
    size_t len;             // 实际接收的数据字节数
    Address sender;         // 数据报来源地址
    uint64_t timestamp_ms;  // 接收时刻的时间戳 (用于RTT精确计算)
};

struct DatagramSocket::SocketConfig {
    bool reuse_addr = true;              // SO_REUSEADDR (快速重启,避免TIME_WAIT阻塞)
    uint32_t recv_buf_bytes = 256*1024;  // SO_RCVBUF (接收缓冲区大小)
    uint32_t send_buf_bytes = 256*1024;  // SO_SNDBUF (发送缓冲区大小)
    uint8_t dscp = 0;                    // DSCP/TOS QoS标记 (0=默认尽力而为)
    uint8_t ttl = 64;                    // TTL (单播跳数限制)

    static SocketConfig Default()
    // 返回值: 默认配置 (reuse_addr=true, buf=256KB, dscp=0, ttl=64)
};

enum class SocketError {
    kWouldBlock,        // 操作会阻塞 (非阻塞模式正常,调用方应等待事件)
    kConnectionRefused, // ICMP端口不可达 (目标无监听进程)
    kAccessDenied,      // 权限不足 (如绑定特权端口<1024)
    kInvalidArg,        // 参数无效
    kSyscallFailed      // 其他系统调用失败 (检查errno)
};
```

---

## 6. IEventHandler 接口

```
class IEventHandler {
public:
    virtual void OnReadable() = 0;
    // 描述符可读时调用 (边缘触发: 需循环读取直到EAGAIN)

    virtual void OnWritable() { }
    // 描述符可写时调用 (发送缓冲区从满→可用)
    // 默认空实现: 大多数场景仅关注可读事件

    virtual void OnError(int error_code) { }
    // 描述符异常时调用 (如ICMP错误)
    // 参数: error_code — 平台相关错误码
    // 默认空实现: 大多数错误已在RecvFrom/SendTo返回值中体现

    virtual ~IEventHandler() = default;
};
```

---

## 7. WorkerPool 类

```
类名: WorkerPool
头文件: worker_pool.h
描述: 固定大小的工作线程池,每个Worker绑定独立的EventLoop
     支持多种Session→Worker分配策略,同一Session粘滞在同一Worker
```

### 7.1 枚举

```
enum class DispatchStrategy {
    kModuloHash,      // hash(routing_key) % N (默认,适合均匀分布)
    kConsistentHash,  // 一致性哈希环 (适合动态增减Worker)
    kRoundRobin,      // 轮询 (原子计数器递增)
    kLeastSessions    // 最少会话优先 (适合不均匀负载)
};
```

### 7.2 公有接口

```
WorkerPool(
    size_t num_workers = 0,                                   // 0=自动检测CPU核心数
    DispatchStrategy strategy = DispatchStrategy::kModuloHash
)
// 参数: num_workers — [in] Worker线程数 (0=hardware_concurrency)
//       strategy    — [in] 分配策略
// 后置条件: 所有Worker线程已启动,各自的EventLoop::Run()正在运行

void Dispatch(uint64_t routing_key, std::move_only_function<void()> task)
// 参数: routing_key — [in] 路由键 (通常为Session的conv)
//       task        — [in] 待投递任务
// 说明: 根据routing_key和策略选择目标Worker,调用其EventLoop::PostTask()
//       线程安全: 可从任何线程调用

void Shutdown()
// 说明: 依次停止所有Worker的EventLoop并join线程
//       阻塞直到所有Worker线程退出
```

---

## 8. TaskQueue 类

```
类名: TaskQueue
头文件: task_queue.h
描述: 线程安全FIFO任务队列 (多生产者-单消费者)
     默认实现: std::mutex + std::condition_variable + std::queue
     可替换为: 无锁MPSC队列 / 优先级队列 / 有界队列 (背压控制)
```

### 8.1 公有接口

```
void Push(std::move_only_function<void()> task)
// 参数: task — [in] 可移动闭包
// 说明: 线程安全地入队 (多生产者),入队后notify_one

std::move_only_function<void()> Pop()
// 返回值: 队列头部任务
// 说明: 阻塞等待直到队列非空,取出并返回 (单消费者)

std::optional<std::move_only_function<void()>> TryPop()
// 返回值: 队列头部任务,队列为空时返回std::nullopt
// 说明: 非阻塞版本,立即返回

void ExecuteAll()
// 说明: 批量消费: 加锁→交换到本地队列→解锁→在锁外执行所有任务
//       减少锁竞争,适合在EventLoop主循环末尾调用
```

---

## 9. TimerQueue 类

```
类名: TimerQueue
头文件: timer_queue.h
描述: 基于小顶堆的定时器管理器 (可替换为分层时间轮)
     支持一次性/周期性定时器,延迟删除 (标记取消)
     所有操作线程安全
```

### 9.1 公有接口

```
using TimerHandle = uint64_t;   // 定时器唯一标识

TimerHandle Add(
    uint32_t delay_or_interval_ms,
    std::move_only_function<void()> callback,
    bool repeat
)
// 返回值: TimerHandle — 定时器句柄 (用于取消)
// 参数: delay_or_interval_ms — [in] 延迟/间隔时间(ms)
//       callback              — [in] 到期时执行的回调
//       repeat                — [in] true=周期性, false=一次性
// 说明: 线程安全,返回唯一句柄

void Cancel(TimerHandle id)
// 参数: id — [in] 定时器句柄
// 说明: 延迟删除: 标记取消,在下次GetNextTimeout或FireExpired时惰性清理
//       保证: Cancel后回调不会再被触发

std::optional<uint32_t> GetNextTimeout()
// 返回值: 距最近定时器到期的剩余时间(ms)
//         std::nullopt = 无待触发定时器 (EventLoop可无限等待)
// 说明: 内部惰性清理堆顶已取消条目

void FireExpired(uint64_t now_ms)
// 参数: now_ms — [in] 当前时间(ms)
// 说明: 执行所有已到期的定时器回调
//       一次性定时器: 执行后移除
//       周期性定时器: 更新到期时间后重新入堆
//       已取消的: 跳过并清理
// 注意: 回调在持有锁时执行,如回调可能耗时,应改为投递到TaskQueue
```

---

## 10. 基础类型与工具

```
// 时钟
namespace Clock {
    uint64_t NowMs();   // 返回当前wall-clock时间戳(毫秒),单调递增
    uint64_t NowUs();   // 微秒精度 (用于精确RTT计算)
}

// 运行时统计
struct SessionStats {
    uint64_t total_bytes_sent;         // 累计发送字节数
    uint64_t total_bytes_recv;         // 累计接收字节数
    uint64_t total_messages_sent;      // 累计发送消息数
    uint64_t total_messages_recv;      // 累计接收消息数
    uint64_t total_packets_sent;       // 累计发送包数
    uint64_t total_packets_recv;       // 累计接收包数
    uint64_t total_retransmissions;    // 累计重传次数
    uint32_t estimated_rtt_ms;         // 当前估计RTT (ms)
    uint32_t send_window_used;         // 当前发送窗口占用 (包数)
    uint32_t recv_window_used;         // 当前接收窗口占用 (包数)
    uint64_t created_at_ms;            // Session创建时间戳
    uint64_t last_activity_ms;         // 最后活动时间戳
};

// 全局库配置
struct LibraryConfig {
    IOBackend io_backend = IOBackend::kAutoDetect;  // IO后端选择
    bool enable_metrics = true;                      // 是否启用全局指标收集
    // ... 预留: 日志级别、内存分配器、断言处理器等
};

// Message — 从传输层完整接收的用户消息
class Message {
public:
    Message(const uint8_t* buf, size_t len, uint32_t sid);

    const uint8_t* Data() const;                       // 只读数据指针
    size_t Size() const;                               // 数据长度(字节)
    std::span<const uint8_t> AsSpan() const;           // C++20 span视图 (零拷贝)
    std::string_view AsStringView() const;             // 字符串视图 (零拷贝)
    std::vector<uint8_t> TakeBytes();                  // 移动取出所有权 (跨线程传递)

    uint32_t session_id;                               // 来源会话ID
    uint64_t receive_time_ms;                          // 接收时间戳
};
```

---

## 11. ProtocolEngine 接口 (扩展点参考)

```
// ============================================================
// 描述: 协议引擎抽象接口 — 实现此接口即可替换底层传输协议
//       默认实现: KCP (ikcp_* API封装)
//       可替换: 自定义可靠UDP / QUIC-like / Mock引擎
// ============================================================

CLASS ProtocolEngine:
    // 输出回调: 引擎产生的底层数据包通过此回调发出
    VIRTUAL FUNCTION SetOutputCallback(
        cb: std::move_only_function<void(const uint8_t* data, size_t len)>
    ) -> void = 0

    // 输入原始数据报到引擎
    VIRTUAL FUNCTION Input(data: const uint8_t*, len: size_t) -> ParseResult = 0

    // 发送用户数据
    VIRTUAL FUNCTION Send(data: const uint8_t*, len: size_t) -> SendResult = 0

    // 驱动引擎状态机
    VIRTUAL FUNCTION Update(now_ms: uint64_t) -> void = 0

    // 取出完整用户消息
    VIRTUAL FUNCTION PeekMessageSize() -> int = 0
    VIRTUAL FUNCTION RecvMessage(buffer: uint8_t*, max_len: size_t) -> int = 0

    // 发送协议层命令包
    VIRTUAL FUNCTION SendHandshake() -> void = 0     // 握手包
    VIRTUAL FUNCTION SendProbe() -> void = 0         // 探活包
    VIRTUAL FUNCTION NotifyClose() -> void = 0       // 关闭通知
    VIRTUAL FUNCTION SendShutdownNotification() -> void = 0  // 优雅关闭通知

    // 配置与重置
    VIRTUAL FUNCTION ApplyConfig(config: Session::Config) -> void = 0
    VIRTUAL FUNCTION ResetBuffers() -> void = 0       // 清空收发缓冲

    VIRTUAL ~ProtocolEngine() = default

// 工厂函数
namespace ProtocolEngineFactory {
    std::unique_ptr<ProtocolEngine> Create(Session::Config config);
    // 默认实现: 创建KCP引擎实例,封装ikcp_create/ikcp_setoutput等
    // 扩展: 可通过注册自定义工厂来支持其他协议实现
}
```

## 12. 其他基础类型

```
// 定时器句柄
using TimerHandle = uint64_t;   // 0=无效句柄, >0=有效

// 地址族
enum class AddressFamily {
    kIPv4,
    kIPv6,
    kUnixDomain
};

// IO后端选择
enum class IOBackend {
    kAutoDetect,  // 运行时自动检测平台最优IO模型
    kEpoll,       // Linux epoll (推荐)
    kIocp,        // Windows I/O Completion Port
    kKqueue,      // macOS / FreeBSD kqueue
    kPoll         // POSIX poll (通用性最好,性能最差)
};
```

# API 详细参考文档

本文档列出所有核心接口的完整API定义，包含类/接口名、函数签名、返回值、参数类型和参数名。API设计面向现代C++ (C++17为基础,部分类型使用C++20/23标准库设施的polyfill或等效替代: `std::optional`为C++17, `std::span`和`std::expected`可使用等效第三方库或编译器内置, `std::move_only_function`可使用等效的`fu2::unique_function`等)。

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

enum class EngineType {
    kEngineKCP  = 0,  // KCP协议引擎 (默认,轻量级可靠UDP,无内置加密)
    kEngineQUIC = 1   // QUIC协议引擎 (基于UDP,内置TLS 1.3加密,支持连接迁移/0-RTT/多路复用)
};
```

### 1.3 配置结构

```
struct Session::Config {
    // === 协议引擎选择 ===
    EngineType engine_type = EngineType::kEngineKCP;  // 默认使用KCP引擎, 可选kEngineQUIC

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
// 说明: 成功时更新 stats_.total_bytes_sent 和 total_messages_sent
//       如需追踪单个消息的送达,使用 OnSendComplete 回调

SendResult Send(const uint8_t* data, size_t len)
// 返回值: SendResult
// 参数: data — [in] 数据指针 (不可为nullptr), len — [in] 数据长度 (必须>0)
// 前置条件: data != nullptr, len > 0
// 说明: 成功时更新 stats_.total_bytes_sent 和 total_messages_sent
// 注意: 当前返回值为SendResult枚举,不含message_id;
//       OnSendComplete回调中的message_id为协议引擎内部分配的序列号,
//       用于内部追踪; 应用层如需消息级确认,建议在Message载荷中携带业务id
```

### 1.7 协议层数据包发送

```
void SendHandshakePacket()
// 返回值: void
// 说明: 发送协议层握手首包,触发服务端的隐式Accept
//       此方法通常由端点层(Client/Peer)在连接初始化时调用,
//       应用层不应直接使用 — 误调用可能导致协议状态异常

void SendProbePacket()
// 返回值: void
// 说明: 发送协议层探活包 (如KCP的WASK命令字 / QUIC的PING帧),对端自动回复确认
//       此方法通常由Server在空闲检测时调用,或由应用层在需要主动
//       检测连接存活时调用 (如: 长时间无业务数据后主动探活)
```

### 1.8 数据接收输入

```
void FeedInput(const uint8_t* data, size_t len)
// 返回值: void
// 参数: data — [in] 原始数据报载荷, len — [in] 数据长度(字节)
// 说明: 将底层数据报输入协议引擎解析
//       内部流程: 更新last_recv_time_ms_ → Engine.Input() → TryRecv() → 触发回调
//       解析错误时通过OnError回调通知,错误类型见SessionError枚举
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
// 参数: cb — [in] 单个消息完全确认送达时的回调 (可选扩展,用于追踪发送完成)
//       参数 message_id 为协议引擎内部分配的消息序列号
//       注意: 此回调在引擎内部确认对端ACK时触发,与Send()返回值无直接关联
//       典型用途: 应用层在Message载荷中携带业务id,在此回调中确认送达
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
// 前置条件: state_ == SessionState::kIdle (配置仅在Start前可修改)
// 说明: 设置协议参数 (MTU/窗口大小/流控开关等)
//       如需运行时调整,应在创建新Session时应用新Config
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
// 说明: Socket可读时循环接收数据报→区分SocketError和nullopt→
//       解析routing_key→路由到已有Session或创建新Session
//       边缘触发模式下循环读取直到返回nullopt (无更多数据)
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
//       流程: 断开旧连接(如有) → 创建Session → 发送握手首包 → 等待服务器响应
//       成功: 收到服务器首次有效响应后回调on_success
//       失败: 超时且无重连或达到最大重试次数后回调on_failure
// 注意: 每次Connect调用会覆盖上一次注册的handler (最后一个Connect生效)
//       重复Connect时旧连接自动Disconnect

void Disconnect()
// 说明: 断开连接,取消所有重连定时器,关闭并释放Session
// 后置条件: state_ == ClientState::kDisconnected
// 幂等: 重复调用安全
```

### 3.6 数据发送

```
SendResult Send(const std::vector<uint8_t>& data)
// 返回值: SendResult — kQueued=已加入队列, kBlocked=当前不可发送
// 参数: data — [in] 待发送数据
// 说明: state_ != kConnected时返回kBlocked (调用方应检查返回值或等待kConnected)

SendResult Send(const uint8_t* data, size_t len)
// 返回值: SendResult
// 参数: data — [in] 数据指针 (不可为nullptr), len — [in] 数据长度 (必须>0)
// 说明: state_ != kConnected时返回kBlocked,调用方负责重试或丢弃
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
// 说明: Socket可读时循环接收数据报→区分SocketError和nullopt→
//       验证源地址和routing_key→通过后调用session->FeedInput()
//       首次收到有效响应时自动从kConnecting转为kConnected并触发success_handler
```

---

## 4. EventLoop 类

```
类名: EventLoop
头文件: event_loop.h
描述: 跨平台IO事件循环抽象,统一封装epoll(Linux/Android)/IOCP(Windows)/kqueue(macOS/BSD/iOS)/poll(回退)
     线程安全: Stop可从任何线程调用; Run在调用线程阻塞执行;
              Register/Modify/Unregister必须在EventLoop所属线程调用
```

### 4.1 枚举与类型

```
enum class IOBackend {
    kAutoDetect,  // 自动选择当前平台最优IO模型
    kEpoll,       // Linux/Android epoll
    kIocp,        // Windows IOCP
    kKqueue,      // macOS/BSD/iOS kqueue
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
    // Platform platform_tag;    // 平台标记 (内部使用,调用方无需设置)
};
```

### 4.2 公有接口

```
EventLoop(IOBackend backend = IOBackend::kAutoDetect)
// 参数: backend — [in] IO后端选择,默认自动检测最优

void Run()
// 返回值: void
// 说明: 阻塞运行事件循环 (在调用线程阻塞,直到Stop()被调用)
//       每轮循环: IO事件等待 → 分派Handler → 触发到期定时器 → 执行异步任务

void Stop()
// 返回值: void
// 说明: 停止事件循环,线程安全 (可从任何线程调用)
//       内部通过WakeUp()唤醒正在阻塞的Run()

void Register(EventDesc desc, IOMask mask, IEventHandler* handler)
// 参数: desc    — [in] 文件描述符或句柄
//       mask    — [in] 关注的事件位掩码 (可组合,如 kReadable | kEdgeTriggered)
//       handler — [in] 事件回调接口 (生命周期由调用方保证,需在Unregister前有效)
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
//       内部Push到任务队列后WakeUp()唤醒事件循环 (如当前正在阻塞等待IO)

TimerHandle AddTimer(
    uint32_t delay_ms,
    std::move_only_function<void()> callback
)
// 返回值: TimerHandle — 定时器句柄 (用于取消,0为无效句柄)
// 参数: delay_ms — [in] 延迟时间(ms)
//       callback — [in] 到期时执行的回调 (一次性触发)
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
// 参数: handle — [in] 定时器句柄 (0=无效,直接忽略)
// 说明: 取消指定定时器 (延迟删除: 标记取消,在下次Fire时跳过并清理)
```

---

## 5. DatagramSocket 类

```
类名: DatagramSocket
头文件: datagram_socket.h
描述: 非阻塞数据报Socket的RAII封装,抽象UDP/UDPLite/Unix Domain Dgram
     线程安全: SendTo和RecvFrom的底层系统调用本身是线程安全的 (OS保证),
             但EventLoop注册操作 (SetReadHandler/EnableWriteNotifications等)
             必须在EventLoop所属线程调用
```

### 5.1 公有接口

```
DatagramSocket(
    EventLoop* event_loop,
    Address bind_addr = Address::Any(),
    SocketConfig config = SocketConfig::Default()
)
// 参数: event_loop — [in] 事件循环 (用于后续Register操作)
//       bind_addr  — [in] 绑定地址 (Any()=任意地址随机端口)
//       config     — [in] Socket选项配置
// 后置条件: Socket已创建/绑定/设为非阻塞模式
// 异常: 创建或绑定失败时抛出std::runtime_error

std::expected<int, SocketError> SendTo(
    const uint8_t* data, size_t len, Address dest
)
// 返回值: std::expected<int, SocketError>
//         成功 → 实际发送字节数
//         失败 → SocketError (kWouldBlock表示发送缓冲区满,需等待可写事件后重试)
// 参数: data — [in] 待发送数据指针
//       len  — [in] 数据长度
//       dest — [in] 目标地址

std::expected<std::optional<RecvResult>, SocketError> RecvFrom(
    uint8_t* buffer, size_t buffer_capacity
)
// 返回值: std::expected<std::optional<RecvResult>, SocketError>
//         成功且有数据  → std::optional包含RecvResult
//         成功但无数据  → std::optional为nullopt (非阻塞模式正常,需等待下次可读事件)
//         Socket错误    → std::unexpected(SocketError)
// 参数: buffer          — [out] 接收缓冲区 (数据写入此处)
//       buffer_capacity — [in]  缓冲区可用容量 (应等于buffer的size())
// 注意: RecvResult::data 指向传入的buffer,生命周期与buffer一致
// 调用方应区分SocketError和nullopt两种情况:
//   - nullopt: 无就绪数据,继续等待下次OnReadable (正常流程)
//   - SocketError: 记录日志,通常可继续使用Socket (ICMP错误不影响后续操作)

void SetReadHandler(IEventHandler* handler)
// 参数: handler — [in] 事件处理器 (实现OnReadable/OnWritable/OnError)
// 说明: 向EventLoop注册此Socket的可读事件 (边缘触发模式)
//       必须在EventLoop线程调用

void EnableWriteNotifications(IEventHandler* handler)
// 参数: handler — [in] 事件处理器
// 说明: 启用可写通知 (发送缓冲区从满→可用时通知)
//       仅在SendTo返回kWouldBlock后需要等待恢复时使用
//       必须在EventLoop线程调用

void DisableWriteNotifications(IEventHandler* handler)
// 参数: handler — [in] 事件处理器
// 说明: 关闭可写通知 (恢复为仅监听可读,减少不必要的事件触发)
//       必须在EventLoop线程调用
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

enum class AddressFamily {
    kIPv4,
    kIPv6,
    kUnixDomain
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
    // 描述符可读时调用 (边缘触发: 需循环读取直到EAGAIN/EWOULDBLOCK)

    virtual void OnWritable() { }
    // 描述符可写时调用 (发送缓冲区从满→可用)
    // 默认空实现: 大多数场景仅关注可读事件

    virtual void OnError(int error_code) { }
    // 描述符异常时调用 (如ICMP错误)
    // 参数: error_code — 平台相关错误码 (Windows: WSAError, POSIX: errno)
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
    kRoundRobin,      // 轮询 (原子计数器递增,不依赖routing_key)
    kLeastSessions    // 最少会话优先 (适合负载不均匀场景)
};
```

### 7.2 公有接口

```
WorkerPool(
    size_t num_workers = 0,                                   // 0=自动检测CPU核心数
    DispatchStrategy strategy = DispatchStrategy::kModuloHash
)
// 参数: num_workers — [in] Worker线程数 (0=std::thread::hardware_concurrency)
//       strategy    — [in] 分配策略
// 后置条件: 所有Worker线程已启动,各自的EventLoop::Run()正在运行

void Dispatch(uint32_t routing_key, std::move_only_function<void()> task)
// 参数: routing_key — [in] 路由键 (通常为Session的conv, uint32_t)
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
// 说明: 线程安全地入队 (多生产者),入队后notify_one唤醒消费者

std::move_only_function<void()> Pop()
// 返回值: 队列头部任务
// 说明: 阻塞等待直到队列非空,取出并返回 (仅单消费者线程调用)

std::optional<std::move_only_function<void()>> TryPop()
// 返回值: 队列头部任务,队列为空时返回std::nullopt
// 说明: 非阻塞版本,立即返回 (通常用于批量消费前的快速检查)

void ExecuteAll()
// 说明: 批量消费: 加锁→交换到本地队列→解锁→在锁外执行所有任务
//       减少锁竞争 (单次加锁处理全部积压),适合在EventLoop主循环末尾调用
```

---

## 9. TimerQueue 类

```
类名: TimerQueue
头文件: timer_queue.h
描述: 基于小顶堆的定时器管理器 (可替换为分层时间轮)
     支持一次性/周期性定时器,延迟删除 (标记取消)
     所有公开操作线程安全
```

### 9.1 公有接口

```
using TimerHandle = uint64_t;   // 定时器唯一标识, 0=无效句柄

TimerHandle Add(
    uint32_t delay_or_interval_ms,
    std::move_only_function<void()> callback,
    bool repeat
)
// 返回值: TimerHandle — 定时器句柄 (用于取消, >0的有效值)
// 参数: delay_or_interval_ms — [in] 延迟/间隔时间(ms)
//       callback              — [in] 到期时执行的回调
//       repeat                — [in] true=周期性重复, false=一次性
// 说明: 线程安全,返回唯一句柄

void Cancel(TimerHandle id)
// 参数: id — [in] 定时器句柄 (0=无效,直接忽略; 已取消的句柄幂等)
// 说明: 延迟删除: 标记取消,在下次GetNextTimeout或FireExpired时惰性清理
//       保证: Cancel返回后,对应回调不会再被触发

std::optional<uint32_t> GetNextTimeout()
// 返回值: 距最近定时器到期的剩余时间(ms)
//         std::nullopt = 无待触发定时器 (EventLoop可无限等待IO事件)
// 说明: 内部惰性清理堆顶已取消条目 (确保返回的是有效定时器的到期时间)

void FireExpired(uint64_t now_ms)
// 参数: now_ms — [in] 当前时间戳(ms)
// 说明: 执行所有到期时刻 <= now_ms 的定时器回调
//       一次性: 执行后移除
//       周期性: 执行后更新expire_time为 now_ms + interval_ms 并重新入堆
//       已取消: 跳过并清理canceled_集合中的记录
// 注意: 回调在持有锁时执行,如回调可能耗时,应改为在回调中PostTask异步执行
```

---

## 10. LogManager 类

```
类名: LogManager
头文件: log_manager.h
描述: 全局日志管理器,提供线程安全的日志回调注册和分级输出
     支持编译期级别裁剪和运行时级别过滤
     所有静态方法线程安全,是库的Public API
```

### 10.1 日志级别

```
enum class LogManager::Level : uint8_t {
    kTrace = 0,  // 追踪级 (最详细,仅开发调试,Release构建默认裁剪)
    kDebug = 1,  // 调试级 (开发环境)
    kInfo  = 2,  // 信息级 (生产环境默认,记录关键业务事件)
    kWarn  = 3,  // 警告级 (非预期但可恢复的情况)
    kError = 4,  // 错误级 (操作失败,需关注)
    kFatal = 5   // 致命级 (不可恢复,通常随后退出进程)
};
```

### 10.2 回调类型

```
using LogManager::LogCallback = std::move_only_function<void(
    Level level,              // 日志级别
    const char* file,         // 源文件名 (__FILE__)
    int line,                 // 行号 (__LINE__)
    const char* function,     // 函数名 (__FUNCTION__ / __func__)
    const std::string& message // 格式化后的日志消息
)>;
// 线程安全要求: 回调可能从多个线程并发调用,
//             LogManager内部已对回调调用加锁,
//             回调实现无需自行处理同步
```

### 10.3 Public API

```
static void SetLogCallback(LogCallback cb)
// 参数: cb — [in] 日志回调函数,传入nullptr则禁用日志输出
// 说明: 线程安全,可从任何线程调用
//       重复调用会替换之前注册的回调
//       回调在LogManager内部锁保护下被调用,回调实现无需自行加锁
// 注意: 回调中不应:
//         a. 再次调用SetLogCallback (会导致死锁)
//         b. 执行长时间阻塞操作 (会阻塞所有日志输出)
//         c. 抛出异常 (会被捕获并忽略,但日志消息丢失)

static std::optional<LogCallback> GetLogCallback()
// 返回值: 当前注册的回调副本; std::nullopt表示未设置回调
// 说明: 返回的是回调的值副本 (std::move_only_function不可拷贝,以optional包装);
//       调用方获得独立的回调副本,可在锁外安全调用;
//       该副本的生命周期与LogManager内部状态解耦,不存在悬空指针风险
// 注意: 此接口用于检查/包装已有回调; 频繁调用会产生move_only_function的移动开销

static void SetLevel(Level level)
// 参数: level — [in] 最低输出级别,默认kInfo
// 说明: 低于此级别的日志消息被丢弃
//       线程安全: 可从任何线程调用,原子操作

static Level GetLevel()
// 返回值: 当前运行时日志级别
// 说明: 原子读取,可从任何线程调用

static bool IsLevelEnabled(Level level)
// 返回值: true=该级别日志将被输出
// 说明: 用于调用方在构造日志消息前进行快速检查,避免不必要的格式化开销
```

### 10.4 内部日志输出

```
static void Log(
    Level level,
    const char* file,
    int line,
    const char* function,
    const char* fmt,
    ...   // printf风格变参 → 内部格式化为std::string
)
// 说明: 通常不直接调用,由LOG_*宏封装
//       线程安全: 内部对回调访问加锁
//       流程: 运行时级别过滤(无锁原子读取) → 格式化消息(锁外) → 调用回调(持锁)
//       如果级别为kFatal,可选触发用户注册的fatal handler
```

### 10.5 日志宏 (编译期裁剪)

```cpp
// 编译期最低日志级别 (CMake/构建系统可覆盖)
#ifndef LOG_COMPILE_MIN_LEVEL
    #ifdef NDEBUG
        #define LOG_COMPILE_MIN_LEVEL  LogManager::Level::kInfo   // Release: 裁剪TRACE/DEBUG
    #else
        #define LOG_COMPILE_MIN_LEVEL  LogManager::Level::kTrace  // Debug: 保留全部
    #endif
#endif

#define LOG_TRACE(fmt, ...)  // 追踪级 (Release中编译器完全移除,零运行时开销)
#define LOG_DEBUG(fmt, ...)  // 调试级 (Release中编译器完全移除)
#define LOG_INFO(fmt, ...)   // 信息级 (生产环境默认输出)
#define LOG_WARN(fmt, ...)   // 警告级
#define LOG_ERROR(fmt, ...)  // 错误级
#define LOG_FATAL(fmt, ...)  // 致命级
// 所有宏自动注入 __FILE__, __LINE__, __FUNCTION__
// 编译期级别检查: 低于LOG_COMPILE_MIN_LEVEL的宏调用被编译器完全消除
```

### 10.6 使用示例

```cpp
// 注册回调 (应用层在库初始化阶段调用)
LogManager::SetLogCallback([](LogManager::Level level,
                               const char* file, int line,
                               const char* func,
                               const std::string& msg) {
    fprintf(stderr, "[%d] [%s] %s:%d %s\n",
            static_cast<int>(level), func, file, line, msg.c_str());
});

// 设置运行时级别
LogManager::SetLevel(LogManager::Level::kDebug);

// 使用日志宏
LOG_INFO("Network library initialized, backend={}", io_backend_name);
LOG_DEBUG("Session {}: send_window={}", conv, send_window);
LOG_ERROR("Session {}: error={}", conv, ErrorToString(error));
```

---

## 11. 基础类型与工具

```
// 时钟
namespace Clock {
    uint64_t NowMs();   // 返回当前wall-clock时间戳(毫秒),单调递增保证
    uint64_t NowUs();   // 返回微秒时间戳 (用于精确RTT计算和性能测量)
}

// 运行时统计 (所有计数器为单调递增)
struct SessionStats {
    uint64_t total_bytes_sent;         // 累计发送字节数
    uint64_t total_bytes_recv;         // 累计接收字节数
    uint64_t total_messages_sent;      // 累计发送消息数 (Send调用次数)
    uint64_t total_messages_recv;      // 累计接收消息数 (OnMessage触发次数)
    uint64_t total_packets_sent;       // 累计发送包数 (含重传/ACK/探活)
    uint64_t total_packets_recv;       // 累计接收包数 (所有入站数据报)
    uint64_t total_retransmissions;    // 累计重传次数
    uint32_t estimated_rtt_ms;         // 当前平滑RTT估计值 (ms)
    uint32_t send_window_used;         // 当前发送窗口占用 (包数)
    uint32_t recv_window_used;         // 当前接收窗口占用 (包数)
    uint64_t created_at_ms;            // Session创建时刻 (Clock::NowMs)
    uint64_t last_activity_ms;         // 最后活动时刻 (收发任一方向)
};

// 全局库配置
struct LibraryConfig {
    IOBackend io_backend = IOBackend::kAutoDetect;  // IO后端选择
    bool enable_metrics = true;                      // 是否启用全局指标收集
    std::string log_level = "info";                  // 运行时日志级别 ("trace"/"debug"/"info"/"warn"/"error")
    std::string log_output = "stdout";               // 日志输出目标 ("stdout"/"stderr"/"callback"/文件路径)
    std::string metrics_output;                      // 指标输出目标 (空=不输出)
    int max_worker_threads = 0;                      // 最大工作线程数 (0=硬件并发数)
};

// Message — 从传输层完整接收的用户消息
class Message {
public:
    Message(const uint8_t* buf, size_t len, uint32_t sid);

    const uint8_t* Data() const;                       // 只读数据指针
    size_t Size() const;                               // 数据长度(字节)
    std::span<const uint8_t> AsSpan() const;           // span视图 (零拷贝,需C++20或polyfill)
    std::string_view AsStringView() const;             // 字符串视图 (零拷贝, C++17)
    std::vector<uint8_t> TakeBytes();                  // 移动取出所有权 (跨线程传递,避免拷贝)
                                                     // 注意: 调用后Message内部data_为空,
                                                     // 后续Data()/Size()/AsSpan()/AsStringView()返回空/0

    uint32_t session_id;                               // 来源会话ID (routing_key)
    uint64_t receive_time_ms;                          // 接收时间戳 (Clock::NowMs)
};
```

---

## 12. ProtocolEngine 接口 (扩展点参考)

```
// ============================================================
// 描述: 协议引擎抽象接口 — 实现此接口即可替换底层传输协议
//       默认实现: KCP (ikcp_* C API封装)
//       第二实现: QUIC (基于UDP的多路复用安全传输,内置TLS 1.3加密)
//       可替换为: 自定义可靠UDP / Mock引擎 (测试用)
// ============================================================

// 解析结果: 引擎Input()的返回值
STRUCT ParseResult:
    success: bool             // true=解析成功, false=发生错误
    error: std::optional<SessionError>  // 失败时的错误类型,成功时为nullopt
    bytes_consumed: size_t    // 此次Input消耗的字节数

    STATIC FUNCTION Ok(consumed: size_t) -> ParseResult:
        result = ParseResult{}
        result.success = true
        result.error = std::nullopt
        result.bytes_consumed = consumed
        RETURN result

    STATIC FUNCTION Err(e: SessionError) -> ParseResult:
        result = ParseResult{}
        result.success = false
        result.error = e
        result.bytes_consumed = 0
        RETURN result

CLASS ProtocolEngine:
    // -------------------- 生命周期回调 --------------------

    // 注册输出回调: 引擎产生的底层数据包通过此回调发出
    // Session在构造时注册,将数据包导向DatagramSocket::SendTo
    VIRTUAL FUNCTION SetOutputCallback(
        cb: std::move_only_function<void(const uint8_t* data, size_t len)>
    ) -> void = 0

    // -------------------- 数据输入 --------------------

    // 将原始数据报输入引擎进行解析
    // 引擎内部根据命令字路由: DATA→插入接收缓冲, ACK→确认发送包, PROBE→回复探测
    VIRTUAL FUNCTION Input(
        data: const uint8_t*, len: size_t
    ) -> ParseResult = 0

    // -------------------- 数据发送 --------------------

    // 将用户数据加入发送队列 (拷贝到引擎内部发送缓冲区)
    // 实际发送在Update中根据窗口和MTU分段发出
    VIRTUAL FUNCTION Send(data: const uint8_t*, len: size_t) -> SendResult = 0

    // -------------------- 定时驱动 --------------------

    VIRTUAL FUNCTION Update(now_ms: uint64_t) -> void = 0
    // 参数: now_ms — [in] 当前时间戳(ms)
    // 内部: 检查RTO→标记重传→快速重传判定→发送待发数据→更新RTT→流控状态更新

    // -------------------- 消息取出 --------------------

    VIRTUAL FUNCTION PeekMessageSize() -> int = 0
    // 返回值: >0 = 下一条完整用户消息的字节数
    //          0 = 当前无完整消息就绪 (等待更多数据)
    //         <0 = 内部错误

    VIRTUAL FUNCTION RecvMessage(
        buffer: uint8_t*, max_len: size_t
    ) -> int = 0
    // 返回值: >0 = 实际拷贝到buffer的消息字节数
    //          0 = 无消息 (应先用PeekMessageSize检查)
    //         <0 = 错误
    // 参数: buffer  — [out] 消息写入目标
    //       max_len — [in]  buffer可用容量 (应 >= PeekMessageSize())

    // -------------------- 协议命令包 --------------------

    VIRTUAL FUNCTION SendHandshake() -> void = 0
    // 发送握手首包:
    //   KCP: 空数据包 (用于触发服务端隐式Accept)
    //   QUIC: Initial包 (包含TLS 1.3 ClientHello, 触发加密握手)

    VIRTUAL FUNCTION SendProbe() -> void = 0
    // 发送探活包:
    //   KCP: WASK命令字 (对端自动回复WINS)
    //   QUIC: PING帧 (对端自动回复PONG或携带数据的ACK)

    VIRTUAL FUNCTION NotifyClose() -> void = 0
    // 构建并发送关闭通知包

    VIRTUAL FUNCTION SendShutdownNotification() -> void = 0
    // 构建并发送优雅关闭通知,区别于NotifyClose:
    // NotifyClose用于立即关闭; SendShutdownNotification用于GracefulShutdown流程

    // -------------------- 配置与重置 --------------------

    VIRTUAL FUNCTION ApplyConfig(config: Session::Config) -> void = 0
    // 将Session::Config中的参数应用到协议引擎 (MTU/窗口/nodelay/流控等)

    VIRTUAL FUNCTION ResetBuffers() -> void = 0
    // 清空引擎内部的收发缓冲区 (丢弃未发送数据和未交付消息)
    // 通常在Close时调用

    VIRTUAL ~ProtocolEngine() = default

// 工厂函数
namespace ProtocolEngineFactory {
    std::unique_ptr<ProtocolEngine> Create(Session::Config config);
    // 根据Config中的engine_type字段选择协议引擎:
    //   kEngineKCP  → 创建KCP引擎实例 (封装ikcp_create/ikcp_setoutput/ikcp_nodelay/ikcp_wndsize等)
    //   kEngineQUIC → 创建QUIC引擎实例 (封装TLS 1.3握手/流控/连接迁移等)
    // 扩展: 可通过注册自定义工厂函数来支持其他协议引擎实现
    // 用法: 在库初始化时调用 RegisterFactory("my_protocol", myFactoryFunction)
}
```

---

## 附录: 类型速查

```
// TimerHandle — 定时器句柄
using TimerHandle = uint64_t;   // 0=无效句柄 (由EventLoop和TimerQueue共用)
```

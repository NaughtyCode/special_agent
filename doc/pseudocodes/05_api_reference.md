# API 详细参考文档

本文档列出所有核心接口的完整API定义，包含类/接口名、函数签名、返回值、参数类型和参数名。

---

## 1. Session 类

```
类名: Session
基类: std::enable_shared_from_this<Session>
头文件: session.h
描述: 传输协议会话抽象,管理单个连接的生命周期和数据收发,接口为协议无关设计
```

### 1.1 类型定义

| 类型名 | 定义 |
|--------|------|
| `MessageCallback` | `std::move_only_function<void(std::unique_ptr<Message>)>` |
| `ErrorCallback` | `std::move_only_function<void(SessionError)>` |
| `StateChangeCallback` | `std::move_only_function<void(SessionState old, SessionState new)>` |

### 1.2 枚举

```
enum class SessionState {
    kIdle      = 0,  // 初始空闲,尚未Start
    kConnected = 1,  // 已连接,可收发数据
    kClosing   = 2,  // 正在优雅关闭
    kClosed    = 3   // 已关闭,终态
};

enum class SessionError {
    kProtocolError,   // 协议层解析/状态异常
    kSocketError,     // 底层Socket错误
    kTimeout,         // 连接超时
    kBufferOverflow,  // 接收缓冲区溢出
    kRemoteClose,     // 对端主动关闭
    kLocalClose       // 本地主动关闭
};

enum class SendResult {
    kQueued  = 0,  // 数据已加入发送队列
    kBlocked = 1   // 发送窗口满,需等待
};

enum class ConnectionHealth {
    kHealthy = 0,  // 正常通信
    kIdle    = 1,  // 空闲 (无数据交换,但未超时)
    kStale   = 2   // 过期 (超过超时阈值)
};

enum class ProtocolProfile {
    kFastMode,      // 低延迟优先 (游戏/VoIP/实时交互)
    kReliableMode,  // 可靠性优先 (文件传输/数据同步)
    kBalancedMode,  // 平衡模式 (通用场景)
    kCustom         // 用户逐参数自定义
};
```

### 1.3 配置结构

```
struct Session::Config {
    ProtocolProfile profile = ProtocolProfile::kFastMode;
    int nodelay = 1;                    // 0=普通模式, 1=快速模式
    int update_interval_ms = 10;        // 协议内部时钟周期
    int fast_resend_threshold = 2;      // 快速重传触发阈值
    bool flow_control_enabled = false;  // 是否启用流控
    int mtu_bytes = 1400;              // 最大传输单元
    int send_window_packets = 128;     // 发送窗口(包数)
    int recv_window_packets = 128;     // 接收窗口(包数)
    size_t rx_buffer_init_bytes = 64*1024;  // 接收缓冲初始大小
    size_t tx_buffer_init_bytes = 64*1024;  // 发送缓冲初始大小

    static Config FromProfile(ProtocolProfile profile);
};
```

### 1.4 构造函数

```
Session(
    uint32_t conv,                              // [in] 会话ID,唯一标识
    EventLoop* event_loop,                      // [in] 绑定的EventLoop
    DatagramSocket* socket,                     // [in] 数据报Socket (借用)
    DatagramSocket::Address remote_addr,        // [in] 远端地址
    Config config = Config::FromProfile(kFastMode)  // [in] 会话配置
)
// 说明: 创建Session实例,初始化协议引擎并应用配置
```

### 1.5 生命周期管理

```
void Start()
// 返回值: void
// 前置条件: state_ == kIdle
// 后置条件: state_ == kConnected

void Close()
// 返回值: void
// 前置条件: 无限制 (幂等)
// 后置条件: state_ == kClosed
// 说明: 立即关闭,不等待对端确认

void GracefulShutdown(uint32_t timeout_ms = 5000)
// 返回值: void
// 参数: timeout_ms — [in] 优雅关闭超时(ms),超时后强制Close
// 前置条件: state_ == kConnected
// 后置条件: state_ == kClosed
// 说明: 发送关闭通知→等待对端ACK→超时后强制关闭
```

### 1.6 数据发送

```
SendResult Send(const std::vector<uint8_t>& data)
// 返回值: SendResult — kQueued=加入队列, kBlocked=窗口满
// 参数: data — [in] 待发送数据

SendResult Send(const uint8_t* data, size_t len)
// 返回值: SendResult
// 参数: data — [in] 数据指针, len — [in] 数据长度
// 前置条件: data != nullptr, len > 0
```

### 1.7 数据接收输入

```
void FeedInput(const uint8_t* data, size_t len)
// 返回值: void
// 参数: data — [in] 原始数据报, len — [in] 数据长度
// 说明: 将底层数据报输入协议引擎解析,更新last_recv_time,
//       完成后自动调用TryRecv
```

### 1.8 定时驱动

```
void Update(uint64_t now_ms)
// 返回值: void
// 参数: now_ms — [in] 当前时间戳(毫秒)
// 说明: 驱动协议引擎状态机 (重传/ACK/窗口更新)
//       应由EventLoop以config_.update_interval_ms周期调用
```

### 1.9 回调注册

```
void OnMessage(MessageCallback cb)
// 参数: cb — [in] 收到完整用户消息时的回调

void OnError(ErrorCallback cb)
// 参数: cb — [in] 发生不可恢复错误时的回调

void OnStateChange(StateChangeCallback cb)
// 参数: cb — [in] 状态变更时的回调 (old_state, new_state)
```

### 1.10 状态查询

```
uint32_t GetConvId() const;
SessionState GetState() const;
uint64_t GetLastRecvTime() const;

ConnectionHealth EvaluateHealth(
    uint64_t now_ms,
    uint32_t idle_threshold_ms = 15000,
    uint32_t stale_threshold_ms = 30000
) const;
// 返回值: ConnectionHealth — 连接健康分级
// 参数:
//   now_ms              — [in] 当前时间(ms)
//   idle_threshold_ms   — [in] 空闲判定阈值,默认15s
//   stale_threshold_ms  — [in] 过期判定阈值,默认30s

SessionStats GetStats() const;
// 返回值: SessionStats — 运行时统计 (收发字节/包/消息数等)
```

---

## 2. Server 类

```
类名: Server
头文件: server.h
描述: 服务端端点,负责数据报监听、会话管理、健康检测
```

### 2.1 类型定义

```
using NewSessionHandler = std::move_only_function<void(std::shared_ptr<Session>)>;
using SessionEvictedHandler = std::move_only_function<void(uint32_t conv, EvictReason)>;
using SessionMap = std::unordered_map<uint32_t, std::shared_ptr<Session>>;
```

### 2.2 枚举

```
enum class ServerState { kStopped = 0, kRunning = 1 };
enum class EvictReason { kTimedOut, kRemoteClosed, kLocalClosed, kError };
enum class EvictionPolicy { kImmediateClose, kGracefulShutdown, kNotifyOnly };
enum class IdlePolicy { kIgnore, kSendProbe, kNotify };
```

### 2.3 配置结构

```
struct Server::Config {
    DatagramSocket::Address listen_address;
    Session::Config session_config;
    size_t max_sessions = 0;
    uint32_t health_check_interval_ms = 1000;
    uint32_t idle_timeout_ms = 15000;
    uint32_t stale_timeout_ms = 30000;
    EvictionPolicy eviction_policy = kImmediateClose;
    IdlePolicy idle_policy = kSendProbe;
    DatagramSocket::SocketConfig socket_config = ...;
};
```

### 2.4 构造函数

```
Server(EventLoop* event_loop, Config config)
// 参数: event_loop — [in] 事件循环, config — [in] 服务端配置
```

### 2.5 生命周期

```
void Start()
// 前置条件: state_ == kStopped, 后置条件: state_ == kRunning

void Stop()
// 前置条件: 无, 后置条件: state_ == kStopped
```

### 2.6 回调注册

```
void OnNewSession(NewSessionHandler handler)
void OnSessionEvicted(SessionEvictedHandler handler)
```

### 2.7 会话管理

```
std::shared_ptr<Session> GetSession(uint32_t conv)
void RemoveSession(uint32_t conv, EvictReason reason)
size_t GetSessionCount() const
```

### 2.8 I/O事件处理

```
void OnReadable()  // 实现 IEventHandler 接口
// 说明: Socket可读时循环接收数据报,路由到对应Session或创建新Session
```

---

## 3. Client 类

```
类名: Client
头文件: client.h
描述: 客户端端点,管理与服务器的单个会话连接
```

### 3.1 类型定义

```
using ConnectSuccessHandler = std::move_only_function<void(std::shared_ptr<Session>)>;
using ConnectFailureHandler = std::move_only_function<void(ConnectError)>;
```

### 3.2 枚举

```
enum class ClientState {
    kDisconnected = 0, kConnecting = 1, kConnected = 2,
    kReconnecting = 3, kClosed = 4
};
enum class ConnectError {
    kTimeout, kRefused, kDnsFailed, kSocketError, kMaxRetriesExceeded
};
```

### 3.3 配置结构

```
struct ReconnectStrategy {
    uint32_t initial_delay_ms = 1000;
    uint32_t max_delay_ms = 30000;
    float backoff_factor = 2.0;
    uint32_t max_attempts = 5;
    uint32_t jitter_ms = 200;
};

struct Client::Config {
    DatagramSocket::Address remote_address;
    Session::Config session_config;
    std::optional<ReconnectStrategy> reconnect;
    uint32_t connect_timeout_ms = 5000;
    DatagramSocket::Address local_bind_address = ...;
    DatagramSocket::SocketConfig socket_config = ...;
};
```

### 3.4 构造函数

```
Client(EventLoop* event_loop, Config config)
```

### 3.5 连接管理

```
void Connect(
    ConnectSuccessHandler on_success = nullptr,
    ConnectFailureHandler on_failure = nullptr
)
// 说明: 异步连接,成功/失败通过回调通知

void Disconnect()
// 说明: 断开连接,取消重连
```

### 3.6 数据发送

```
SendResult Send(const std::vector<uint8_t>& data)
SendResult Send(const uint8_t* data, size_t len)
```

### 3.7 状态查询

```
std::shared_ptr<Session> GetSession() const
ClientState GetState() const
```

### 3.8 I/O事件处理

```
void OnReadable()  // 实现 IEventHandler
// 说明: 验证数据报来源和conv,通过后FeedInput
```

---

## 4. EventLoop 类

```
类名: EventLoop
头文件: event_loop.h
描述: 跨平台IO事件循环抽象,统一封装epoll/IOCP/kqueue/poll
```

### 4.1 公有接口

```
EventLoop(IOBackend backend = kAutoDetect)
// 参数: backend — [in] IO后端选择

void Run()
// 阻塞运行事件循环,循环顺序: IO事件→定时器→异步任务

void Stop()
// 停止事件循环,线程安全

void Register(EventDesc desc, IOMask mask, IEventHandler* handler)
// 参数: desc — [in] 文件描述符/句柄, mask — [in] 关注事件位掩码,
//       handler — [in] 事件回调接口

void Modify(EventDesc desc, IOMask new_mask)
// 修改已注册描述符的关注事件

void Unregister(EventDesc desc)
// 取消注册

void PostTask(std::move_only_function<void()> task)
// 投递闭包任务到EventLoop线程执行,线程安全

TimerHandle AddTimer(
    uint32_t delay_ms,
    std::move_only_function<void()> callback
)
// 返回值: TimerHandle — 定时器句柄
// 说明: 添加一次性定时器

TimerHandle AddPeriodicTimer(
    uint32_t interval_ms,
    std::move_only_function<void()> callback
)
// 返回值: TimerHandle
// 说明: 添加周期性定时器

void CancelTimer(TimerHandle handle)
// 取消指定定时器 (延迟删除,安全)
```

---

## 5. DatagramSocket 类

```
类名: DatagramSocket
头文件: datagram_socket.h
描述: 非阻塞数据报Socket的RAII封装,抽象UDP/UDPLite等
```

### 5.1 公有接口

```
DatagramSocket(
    EventLoop* event_loop,
    Address bind_addr = Address::Any(),
    SocketConfig config = SocketConfig::Default()
)
// 参数: event_loop — [in] 事件循环,
//       bind_addr — [in] 绑定地址,
//       config — [in] Socket配置

std::expected<int, SocketError> SendTo(
    const uint8_t* data, size_t len, Address dest
)
// 返回值: std::expected<int, SocketError> — 成功返回发送字节数,
//         失败(如 kWouldBlock)返回错误码

std::optional<RecvResult> RecvFrom(
    uint8_t* buffer, size_t buffer_capacity
)
// 返回值: std::optional<RecvResult> — 收到数据时返回结果,
//         无数据时返回 nullopt
// 注意: RecvResult.data 指向传入的buffer,生命周期与buffer一致

void SetReadHandler(IEventHandler* handler)
// 将Socket注册到EventLoop以接收可读通知
```

### 5.2 辅助类型

```
struct DatagramSocket::Address {
    std::string ip;           // IP地址或Unix Domain路径
    uint16_t port;            // 端口号
    AddressFamily family;     // kIPv4 / kIPv6 / kUnixDomain

    static Address Any();     // 0.0.0.0:0 (任意地址)
    static Address From(std::string ip, uint16_t port);
};

struct DatagramSocket::RecvResult {
    const uint8_t* data;      // 数据指针 (指向调用方buffer)
    size_t len;               // 数据长度
    Address sender;           // 来源地址
    uint64_t timestamp_ms;    // 接收时间戳
};

struct DatagramSocket::SocketConfig {
    bool reuse_addr = true;
    uint32_t recv_buf_bytes = 256*1024;
    uint32_t send_buf_bytes = 256*1024;
    uint8_t dscp = 0;
    uint8_t ttl = 64;
};

enum class SocketError {
    kWouldBlock,       // 操作会阻塞 (非阻塞模式正常)
    kConnectionRefused,// ICMP拒绝 (目标不可达)
    kAccessDenied,     // 权限不足
    kInvalidArg,       // 参数无效
    kSyscallFailed     // 其他系统调用失败
};
```

---

## 6. IEventHandler 接口

```
class IEventHandler {
public:
    virtual void OnReadable() = 0;
    virtual void OnWritable() { }
    virtual void OnError(int error_code) { }
    virtual ~IEventHandler() = default;
};
```

---

## 7. WorkerPool 类

```
类名: WorkerPool
头文件: worker_pool.h
描述: 工作线程池,每个Worker绑定独立EventLoop,支持多种分配策略
```

### 7.1 公有接口

```
WorkerPool(
    size_t num_workers = 0,                              // 0=CPU核心数
    DispatchStrategy strategy = DispatchStrategy::kModuloHash
)

void Dispatch(
    uint64_t routing_key,
    std::move_only_function<void()> task
)
// 说明: 根据routing_key和策略选择Worker,投递任务

void Shutdown()

enum class DispatchStrategy {
    kModuloHash, kConsistentHash, kRoundRobin, kLeastSessions
};
```

---

## 8. TaskQueue 类

```
类名: TaskQueue
头文件: task_queue.h
描述: 线程安全FIFO任务队列 (多生产者-单消费者)

void Push(std::move_only_function<void()> task)
std::move_only_function<void()> Pop()
std::optional<std::move_only_function<void()>> TryPop()
void ExecuteAll()   // 批量消费,减少锁竞争
```

---

## 9. TimerQueue 类

```
类名: TimerQueue
头文件: timer_queue.h
描述: 基于小顶堆的定时器管理器

using TimerHandle = uint64_t;

TimerHandle Add(
    uint32_t delay_or_interval_ms,
    std::move_only_function<void()> callback,
    bool repeat
)

void Cancel(TimerHandle id)
std::optional<uint32_t> GetNextTimeout()    // 返回最近定时间隔,空=无限
void FireExpired(uint64_t now_ms)           // 执行已到期定时器
```

---

## 10. 基础类型

```
// 时间戳与时钟
namespace Clock {
    uint64_t NowMs();    // 返回当前wall-clock时间戳(毫秒)
    uint64_t NowUs();    // 微秒精度 (用于精确RTT)
}

// 运行时统计
struct SessionStats {
    uint64_t total_bytes_sent;
    uint64_t total_bytes_recv;
    uint64_t total_messages_sent;
    uint64_t total_messages_recv;
    uint64_t total_packets_sent;
    uint64_t total_packets_recv;
    uint64_t total_retransmissions;
    uint32_t estimated_rtt_ms;
    uint32_t send_window_used;    // 当前发送窗口占用(包数)
    uint32_t recv_window_used;    // 当前接收窗口占用(包数)
    uint64_t created_at_ms;
    uint64_t last_activity_ms;
};

struct LibraryConfig {
    IOBackend io_backend = kAutoDetect;   // kEpoll / kIocp / kKqueue / kPoll
    bool enable_metrics = true;
    // ... 其他全局配置
};
```

---

## 11. KCP C API (底层依赖参考)

Session 内部以 KCP 为默认协议引擎实现,以下是其底层 C API 供参考:

```
ikcpcb* ikcp_create(IUINT32 conv, void* user)
// 返回: KCP实例指针, NULL=失败

void ikcp_release(ikcpcb* kcp)

void ikcp_setoutput(ikcpcb* kcp,
    int (*output)(const char* buf, int len, ikcpcb* kcp, void* user))

int ikcp_send(ikcpcb* kcp, const char* buffer, int len)
// 返回: 0=成功, <0=失败

int ikcp_input(ikcpcb* kcp, const char* data, long size)
// 返回: 0=成功, <0=失败

void ikcp_update(ikcpcb* kcp, IUINT32 current)

int ikcp_recv(ikcpcb* kcp, char* buffer, int len)
// 返回: >0=消息长度, 0=无完整消息, <0=错误

int ikcp_peeksize(const ikcpcb* kcp)
// 返回: >0=下一条消息长度, 0=无消息, <0=错误

int ikcp_nodelay(ikcpcb* kcp, int nodelay, int interval, int resend, int nc)
// 返回: 0=成功

int ikcp_wndsize(ikcpcb* kcp, int sndwnd, int rcvwnd)
// 返回: 0=成功

int ikcp_setmtu(ikcpcb* kcp, int mtu)
// 返回: 0=成功
```

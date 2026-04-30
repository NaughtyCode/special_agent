# API 详细参考文档

本文档列出所有核心类的完整API,包含类名、函数签名、返回值、参数类型和参数名。

---

## 1. KCPSession 类

```
类名: KCPSession
基类: std::enable_shared_from_this<KCPSession>
头文件: kcp_session.h
描述: KCP协议会话核心封装,管理单个KCP连接的生命周期和数据收发
```

### 1.1 类型定义

| 类型名 | 定义 |
|--------|------|
| `MessageCallback` | `std::function<void(std::unique_ptr<Message>)>` |

### 1.2 枚举

```
enum class SessionState {
    kIdle      = 0,  // 初始空闲状态,尚未Start
    kConnected = 1,  // 已连接,可收发数据
    kClosed    = 2   // 已关闭
};
```

### 1.3 构造函数

```
KCPSession(
    uint32_t conv,              // [in] 会话ID,唯一标识一个KCP连接
    IOContext* io_ctx,          // [in] IO上下文,用于投递异步任务
    UdpSocket* socket,          // [in] UDP Socket,用于底层数据传输
    std::string remote_ip,      // [in] 远端IP地址
    uint16_t remote_port        // [in] 远端端口号
)
// 返回值: 无 (构造函数)
// 异常: std::runtime_error — ikcp_create失败时抛出
// 说明: 创建KCPSession实例,初始化KCP协议栈并配置为快速模式
```

### 1.4 析构函数

```
~KCPSession()
// 返回值: 无
// 说明: 释放KCP实例(ikcp_release),清理所有资源
```

### 1.5 禁用拷贝

```
KCPSession(const KCPSession&) = delete
// 说明: 禁止拷贝构造,保证会话唯一性

KCPSession& operator=(const KCPSession&) = delete
// 说明: 禁止拷贝赋值,保证会话唯一性
```

### 1.6 生命周期管理

```
void Start()
// 返回值: void
// 参数: 无
// 前置条件: state_ == SessionState::kIdle
// 后置条件: state_ == SessionState::kConnected
// 说明: 启动会话,更新最后收包时间为当前时间

void Close()
// 返回值: void
// 参数: 无
// 前置条件: 无限制 (幂等操作)
// 后置条件: state_ == SessionState::kClosed
// 说明: 关闭会话,清空接收缓冲区。多次调用安全。
```

### 1.7 数据发送

```
void Send(const std::vector<uint8_t>& data)
// 返回值: void
// 参数:
//   data — [in] const std::vector<uint8_t>&  待发送的用户数据
// 前置条件: state_ == SessionState::kConnected
// 说明: 将用户数据提交给KCP进行可靠传输,内部调用ikcp_send
//       若未连接则静默忽略

void Send(const uint8_t* data, size_t len)
// 返回值: void
// 参数:
//   data — [in] const uint8_t*  待发送数据的原始指针
//   len  — [in] size_t          数据长度(字节)
// 前置条件: data != nullptr, len > 0, state_ == kConnected
// 说明: 重载版本,支持原始指针+长度方式发送
```

### 1.8 数据接收输入

```
void FeedInput(const uint8_t* data, size_t len)
// 返回值: void
// 参数:
//   data — [in] const uint8_t*  从UDP Socket收到的原始数据
//   len  — [in] size_t          数据长度(字节)
// 前置条件: data != nullptr, len > 0
// 说明: 将底层UDP数据包喂给KCP协议解析,内部调用ikcp_input
//       同时更新last_recv_time_,用于超时检测
//       处理完后自动调用TryRecv()尝试组装完整用户消息
```

### 1.9 定时驱动

```
void Update(uint32_t current_ms)
// 返回值: void
// 参数:
//   current_ms — [in] uint32_t  当前系统时间(毫秒)
// 说明: 驱动KCP内部状态机,内部调用ikcp_update
//       负责: 超时重传检测、快速重传判断、ACK包发送、拥塞窗口更新
//       应由Platform Layer以固定频率(10ms)调用
```

### 1.10 回调设置

```
void SetMessageCallback(MessageCallback cb)
// 返回值: void
// 参数:
//   cb — [in] MessageCallback  收到完整用户消息时的回调函数
//        签名: void(std::unique_ptr<Message>)
// 说明: 设置消息接收回调,当KCP成功组装出完整用户消息时触发
```

### 1.11 状态查询

```
uint32_t GetConvId() const
// 返回值: uint32_t — 当前会话的conv ID
// 参数: 无

SessionState GetState() const
// 返回值: SessionState — 当前会话状态 (kIdle/kConnected/kClosed)
// 参数: 无

uint64_t GetLastRecvTime() const
// 返回值: uint64_t — 最后一次收到数据包的时间(毫秒时间戳)
// 参数: 无

bool IsTimeout(uint64_t now, uint32_t timeout_ms = 30000) const
// 返回值: bool — true=已超时, false=未超时
// 参数:
//   now        — [in] uint64_t  当前时间(毫秒)
//   timeout_ms — [in] uint32_t  超时阈值(毫秒),默认30000(30秒)
// 说明: 检查距离上次收包是否超过指定阈值
```

### 1.12 私有静态方法

```
static int OnKcpOutput(const char* buf, int len, ikcpcb* kcp, void* user)
// 返回值: int — 实际发送的字节数,负数表示错误
// 参数:
//   buf  — [in] const char*  KCP输出的底层数据包缓冲区
//   len  — [in] int          数据包长度(字节)
//   kcp  — [in] ikcpcb*      触发回调的KCP实例
//   user — [in] void*        用户指针(KCPSession的this指针)
// 说明: KCP输出回调,当KCP准备好待发送的底层数据包时触发
//       内部通过user恢复KCPSession引用,调用UdpSocket发送
```

### 1.13 私有方法

```
void TryRecv()
// 返回值: void
// 参数: 无
// 说明: 尝试从KCP接收完整用户消息
//       循环调用ikcp_peeksize预查大小 + ikcp_recv获取消息
//       收到完整消息后触发message_callback_
```

---

## 2. Message 类

```
类名: Message
头文件: message.h
描述: 封装从KCP层接收到的完整用户消息
```

### 2.1 公有成员变量

```
std::vector<uint8_t> data
// 描述: 消息的原始字节数据

uint32_t session_id
// 描述: 来源会话ID (即KCPSession的conv)

uint64_t receive_time
// 描述: 收到此消息的时间戳(毫秒)
```

### 2.2 构造函数

```
Message(const uint8_t* buf, size_t len, uint32_t sid)
// 参数:
//   buf — [in] const uint8_t*  消息数据指针
//   len — [in] size_t          消息数据长度
//   sid — [in] uint32_t        来源会话ID
// 说明: 拷贝构造消息数据,记录接收时间
```

### 2.3 成员函数

```
std::string_view AsStringView() const
// 返回值: std::string_view — 数据的string_view视图(零拷贝)
// 参数: 无

size_t Size() const
// 返回值: size_t — 消息数据长度(字节)
// 参数: 无

const uint8_t* Data() const
// 返回值: const uint8_t* — 消息数据原始指针
// 参数: 无
```

---

## 3. KcpServer 类

```
类名: KcpServer
头文件: kcp_server.h
描述: KCP服务端,负责UDP端口监听、会话创建/查找/销毁、超时检测
```

### 3.1 类型定义

```
using NewSessionHandler = std::function<void(std::shared_ptr<KCPSession>)>
// 描述: 新会话到达时的回调类型

using SessionMap = std::unordered_map<uint32_t, std::shared_ptr<KCPSession>>
// 描述: 会话映射表类型,键为conv_id
```

### 3.2 枚举

```
enum class ServerState {
    kStopped = 0,  // 已停止
    kRunning = 1   // 运行中
};
```

### 3.3 构造函数

```
KcpServer(
    IOContext* io_ctx,               // [in] IO上下文,关联事件循环
    std::string ip,                  // [in] 监听IP地址 (如 "0.0.0.0")
    uint16_t port,                   // [in] 监听端口号
    uint32_t timeout_ms = 30000,     // [in] 超时阈值(ms),默认30000
    uint32_t check_interval_ms = 1000 // [in] 超时检测间隔(ms),默认1000
)
// 说明: 创建服务端实例,创建UDP Socket并绑定到指定地址
```

### 3.4 析构函数

```
~KcpServer()
// 说明: 自动调用Stop()关闭所有会话
```

### 3.5 生命周期管理

```
void Start()
// 返回值: void
// 参数: 无
// 前置条件: state_ == kStopped
// 后置条件: state_ == kRunning
// 说明: 启动服务器,将UDP Socket注册到IOContext,启动超时检测定时器

void Stop()
// 返回值: void
// 参数: 无
// 前置条件: 无 (幂等)
// 后置条件: state_ == kStopped
// 说明: 停止服务器,取消定时器,关闭并移除所有会话
```

### 3.6 回调设置

```
void SetNewSessionHandler(NewSessionHandler handler)
// 返回值: void
// 参数:
//   handler — [in] NewSessionHandler  新会话到达回调
//             签名: void(std::shared_ptr<KCPSession>)
// 说明: 设置当有新客户端连接时的回调,在Accept流程创建KCPSession后触发
```

### 3.7 会话管理

```
void RemoveSession(uint32_t conv)
// 返回值: void
// 参数:
//   conv — [in] uint32_t  会话ID
// 说明: 主动关闭并移除指定会话

std::shared_ptr<KCPSession> GetSession(uint32_t conv)
// 返回值: std::shared_ptr<KCPSession> — 会话指针,不存在时返回nullptr
// 参数:
//   conv — [in] uint32_t  会话ID

size_t GetSessionCount() const
// 返回值: size_t — 当前活跃会话数
// 参数: 无
```

### 3.8 I/O事件处理

```
void OnReadable()
// 返回值: void
// 参数: 无
// 说明: 实现IEventHandler接口,UDP Socket可读时由IOContext回调
//       从Socket循环读取数据,解析conv,查找/创建会话并调用FeedInput
```

### 3.9 私有方法

```
void CheckTimeout()
// 返回值: void
// 参数: 无
// 说明: 由定时器周期性触发,遍历所有会话检查超时并清理
```

---

## 4. KcpClient 类

```
类名: KcpClient
头文件: kcp_client.h
描述: KCP客户端,管理与服务器的单个会话连接
```

### 4.1 枚举

```
enum class ClientState {
    kDisconnected = 0,  // 未连接
    kConnecting   = 1,  // 连接中
    kConnected    = 2,  // 已连接
    kClosed       = 3   // 已关闭
};
```

### 4.2 构造函数

```
KcpClient(IOContext* io_ctx)
// 参数:
//   io_ctx — [in] IOContext*  IO上下文
// 说明: 创建客户端实例,创建UDP Socket(端口由OS自动分配),
//       初始化conv生成器(基于当前时间戳)
```

### 4.3 析构函数

```
~KcpClient()
// 说明: 自动调用Disconnect()断开连接
```

### 4.4 连接管理

```
std::shared_ptr<KCPSession> Connect(
    std::string server_ip,     // [in] 服务器IP地址
    uint16_t server_port       // [in] 服务器端口
)
// 返回值: std::shared_ptr<KCPSession> — 创建的会话对象
// 参数:
//   server_ip   — [in] std::string  服务器IP
//   server_port — [in] uint16_t     服务器端口
// 说明: 向指定服务器发起连接
//       1. 如果已有连接则先断开
//       2. 生成唯一conv_id
//       3. 创建KCPSession并Start
//       4. 注册Socket到IOContext
//       5. 发送首个握手数据包
//       6. 状态 → kConnected

void Disconnect()
// 返回值: void
// 参数: 无
// 说明: 断开与服务器的连接,关闭Session
```

### 4.5 数据发送

```
void Send(const std::vector<uint8_t>& data)
// 返回值: void
// 参数:
//   data — [in] const std::vector<uint8_t>&  待发送数据
// 前置条件: state_ == kConnected 且 session_ != nullptr
// 说明: 发送数据到服务器(通过KCPSession)

void Send(const uint8_t* data, size_t len)
// 返回值: void
// 参数:
//   data — [in] const uint8_t*  数据指针
//   len  — [in] size_t          数据长度
// 前置条件: data != nullptr, len > 0, 已连接
// 说明: 重载版本,原始指针发送
```

### 4.6 状态查询

```
std::shared_ptr<KCPSession> GetSession() const
// 返回值: std::shared_ptr<KCPSession> — 当前会话对象
// 参数: 无

ClientState GetState() const
// 返回值: ClientState — 当前连接状态
// 参数: 无
```

### 4.7 I/O事件处理

```
void OnReadable()
// 返回值: void
// 参数: 无
// 说明: 实现IEventHandler,UDP Socket可读时回调
//       验证数据来源IP/Port和conv,通过后FeedInput
```

### 4.8 重连支持

```
void EnableAutoReconnect(
    int max_retries,               // [in] 最大重试次数
    uint32_t retry_interval_ms     // [in] 重试间隔(毫秒)
)
// 返回值: void
// 说明: 启用自动重连,断线后按指定策略自动重试
```

---

## 5. IOContext 类

```
类名: IOContext
头文件: io_context.h
描述: 事件循环核心,封装epoll(IOCP),管理I/O事件、定时器和异步任务
```

### 5.1 公有接口

```
IOContext()
// 说明: 构造函数,创建epoll实例(Linux)或IOCP完成端口(Windows)

~IOContext()
// 说明: 析构函数,停止事件循环,释放系统资源

void Run()
// 返回值: void
// 参数: 无
// 说明: 启动事件循环(阻塞),循环处理I/O事件→定时器→异步任务

void Stop()
// 返回值: void
// 参数: 无
// 说明: 停止事件循环,Run()将在当前迭代后返回

void PostTask(std::function<void()> task)
// 返回值: void
// 参数:
//   task — [in] std::function<void()>  待执行的异步任务
// 说明: 投递任务到IO线程执行,线程安全

void RegisterFd(int fd, IEventHandler* handler)
// 返回值: void
// 参数:
//   fd      — [in] int              要监听的文件描述符
//   handler — [in] IEventHandler*   事件回调接口指针
// 说明: 注册文件描述符读就绪事件到epoll/IOCP

void UnregisterFd(int fd)
// 返回值: void
// 参数:
//   fd — [in] int  要取消监听的文件描述符

TimerId AddTimer(
    uint32_t delay_ms,               // [in] 延迟时间(毫秒)
    std::function<void()> callback,  // [in] 到期回调
    bool repeat = false              // [in] 是否重复,默认false
)
// 返回值: TimerId — 定时器唯一标识,用于取消
// 说明: 添加定时器,delay_ms后触发callback

void CancelTimer(TimerId timer_id)
// 返回值: void
// 参数:
//   timer_id — [in] TimerId  要取消的定时器ID
// 说明: 取消指定定时器(延迟删除)
```

---

## 6. UdpSocket 类

```
类名: UdpSocket
头文件: udp_socket.h
描述: 非阻塞UDP Socket的RAII封装
```

### 6.1 公有接口

```
UdpSocket(IOContext* io_ctx, std::string ip, uint16_t port)
// 参数:
//   io_ctx — [in] IOContext*  IO上下文
//   ip     — [in] std::string 绑定IP
//   port   — [in] uint16_t    绑定端口(0=系统分配)
// 说明: 创建非阻塞UDP Socket,设置地址复用,增大收发缓冲区

~UdpSocket()
// 说明: 关闭Socket

int SendTo(const uint8_t* data, size_t len, 
           std::string remote_ip, uint16_t remote_port)
// 返回值: int — 实际发送字节数,<0表示错误
// 参数:
//   data        — [in] const uint8_t*  数据缓冲区
//   len         — [in] size_t          数据长度
//   remote_ip   — [in] std::string     远端IP
//   remote_port — [in] uint16_t        远端端口
// 说明: 非阻塞发送,立即返回

std::optional<RecvResult> RecvFrom(uint8_t* buffer, size_t buffer_size)
// 返回值: std::optional<RecvResult> — 有数据时返回RecvResult,无数据时nullopt
// 参数:
//   buffer      — [out] uint8_t*  接收缓冲区
//   buffer_size — [in]  size_t    缓冲区大小
// 说明: 非阻塞接收,无数据时返回nullopt

void EnableRead(IEventHandler* handler)
// 返回值: void
// 参数:
//   handler — [in] IEventHandler*  可读事件回调
// 说明: 注册到IOContext,当Socket可读时触发handler->OnReadable()
```

### 6.2 辅助结构体

```
struct RecvResult {
    uint8_t* data;           // 接收到的数据指针
    size_t len;              // 数据长度
    std::string remote_ip;   // 发送方IP
    uint16_t remote_port;    // 发送方端口
};
```

---

## 7. ThreadPool 类

```
类名: ThreadPool
头文件: thread_pool.h
描述: 固定大小线程池,每线程绑定独立IOContext
```

### 7.1 公有接口

```
ThreadPool(size_t num_threads = 0)
// 参数:
//   num_threads — [in] size_t  线程数,0=使用硬件并发数
// 说明: 创建num_threads个IOContext和工作线程

~ThreadPool()
// 说明: 自动调用Shutdown()

void Shutdown()
// 返回值: void
// 参数: 无
// 说明: 停止所有IOContext,join所有线程

void PostToThread(uint32_t conv_id, std::function<void()> task)
// 返回值: void
// 参数:
//   conv_id — [in] uint32_t                会话ID,用于哈希选择目标线程
//   task    — [in] std::function<void()>   待投递的任务
// 说明: 按conv_id取模,将任务投递到对应IO线程的任务队列

IOContext* GetIOContext(size_t index)
// 返回值: IOContext* — 指定索引的IO上下文
// 参数:
//   index — [in] size_t  线程索引
```

---

## 8. TaskQueue 类

```
类名: TaskQueue
头文件: task_queue.h
描述: 线程安全FIFO任务队列,支持多生产者-单消费者
```

### 8.1 公有接口

```
void Push(std::function<void()> task)
// 返回值: void
// 参数:
//   task — [in] std::function<void()>  待执行任务
// 说明: 线程安全地添加任务到队尾,并通知等待线程

std::function<void()> Pop()
// 返回值: std::function<void()> — 队首任务
// 参数: 无
// 说明: 阻塞等待并取出队首任务

std::optional<std::function<void()>> TryPop()
// 返回值: std::optional<...> — 有任务时返回任务,队列空时nullopt
// 参数: 无
// 说明: 非阻塞尝试取出队首任务

void ExecuteAll()
// 返回值: void
// 参数: 无
// 说明: 批量执行队列中的所有待处理任务
```

---

## 9. KCP C API (底层依赖)

以下为 KCP 原生 C API,在 KCPSession 内部调用:

```
// 创建KCP实例
ikcpcb* ikcp_create(IUINT32 conv, void* user)
// 参数: conv — 会话ID, user — 用户数据指针
// 返回: KCP实例指针,失败返回NULL

// 释放KCP实例
void ikcp_release(ikcpcb* kcp)
// 参数: kcp — KCP实例指针

// 设置输出回调 (KCP输出底层数据包时调用)
void ikcp_setoutput(ikcpcb* kcp, 
    int (*output)(const char* buf, int len, ikcpcb* kcp, void* user))
// 参数: kcp — KCP实例, output — 回调函数指针

// 发送用户数据 (提交给KCP可靠传输)
int ikcp_send(ikcpcb* kcp, const char* buffer, int len)
// 参数: kcp — KCP实例, buffer — 数据, len — 长度
// 返回: 0成功, <0失败

// 输入底层数据包 (解析协议,提取ACK,重组数据)
int ikcp_input(ikcpcb* kcp, const char* data, long size)
// 参数: kcp — KCP实例, data — 原始包数据, size — 长度
// 返回: 0成功, <0失败

// 驱动KCP状态机 (定时调用,处理超时/重传/ACK)
void ikcp_update(ikcpcb* kcp, IUINT32 current)
// 参数: kcp — KCP实例, current — 当前时间戳(毫秒)

// 接收完整用户消息
int ikcp_recv(ikcpcb* kcp, char* buffer, int len)
// 参数: kcp — KCP实例, buffer — 接收缓冲, len — 缓冲大小
// 返回: >0=消息长度, 0=无完整消息, <0=错误

// 预查下一条完整消息的大小
int ikcp_peeksize(const ikcpcb* kcp)
// 参数: kcp — KCP实例
// 返回: >0=消息长度, 0=无完整消息, <0=错误

// 配置快速模式
int ikcp_nodelay(ikcpcb* kcp, int nodelay, int interval, int resend, int nc)
// 参数:
//   kcp      — KCP实例
//   nodelay  — 0=禁用, 1=启用快速模式
//   interval — 内部刷新间隔(ms),与ikcp_update调用频率一致
//   resend   — 触发快速重传的ACK跳过次数(典型值: 2)
//   nc       — 0=正常流控, 1=关闭流控
// 返回: 0成功

// 设置窗口大小
int ikcp_wndsize(ikcpcb* kcp, int sndwnd, int rcvwnd)
// 参数: kcp — KCP实例, sndwnd — 发送窗口(包数), rcvwnd — 接收窗口(包数)
// 返回: 0成功

// 设置MTU
int ikcp_setmtu(ikcpcb* kcp, int mtu)
// 参数: kcp — KCP实例, mtu — 最大传输单元(字节)
// 返回: 0成功
```

# Client — 客户端抽象层伪代码

`Client` 提供通用的客户端连接与会话管理，通过组合 `Session` 实现CS架构的客户端。设计为端点抽象：同样接口可复用于对等端(Peer)模式。

---

## 1. Client 完整伪代码

```
// ============================================================
// 类名: Client
// 描述: 通用客户端端点,管理与服务器的连接会话
//       核心职责:
//       1. 创建到指定目标的Session并管理其生命周期
//       2. 提供发送便捷接口和重连策略
//       3. 管理连接状态和异步回调
// ============================================================
CLASS Client:
    // -------------------- 类型别名 --------------------
    USING ConnectSuccessHandler = std::move_only_function<void(std::shared_ptr<Session>)>
    USING ConnectFailureHandler = std::move_only_function<void(ConnectError)>

    ENUM ClientState:
        kDisconnected = 0
        kConnecting   = 1
        kConnected    = 2
        kReconnecting = 3
        kClosed       = 4

    ENUM ConnectError:
        kTimeout          // 连接超时
        kRefused          // 被服务器拒绝
        kDnsFailed        // DNS解析失败
        kSocketError      // Socket创建/绑定失败
        kMaxRetriesExceeded // 超过最大重连次数

    // -------------------- 数据结构 --------------------
    STRUCT ReconnectStrategy:
        initial_delay_ms: uint32_t = 1000     // 初始重连间隔
        max_delay_ms: uint32_t = 30000        // 最大重连间隔
        backoff_factor: float = 2.0           // 退避因子
        max_attempts: uint32_t = 5            // 最大重试次数 (0=无限)
        jitter_ms: uint32_t = 200             // 随机抖动 (避免惊群)

    STRUCT Config:
        remote_address: DatagramSocket::Address
        session_config: Session::Config               // Session配置
        reconnect: std::optional<ReconnectStrategy>    // 重连策略 (nullopt=禁用)
        connect_timeout_ms: uint32_t = 5000            // 连接超时
        local_bind_address: DatagramSocket::Address = DatagramSocket::Address::Any()
        socket_config: DatagramSocket::SocketConfig = DatagramSocket::SocketConfig::Default()

    // -------------------- 构造与析构 --------------------
    CONSTRUCTOR Client(
            event_loop: EventLoop*,
            config: Config
    ):
        event_loop_ = event_loop
        config_     = std::move(config)
        state_      = kDisconnected
        socket_     = std::make_unique<DatagramSocket>(
            event_loop, config_.local_bind_address, config_.socket_config)
        routing_key_counter_ = Clock::NowMs() & 0xFFFFFFFF  // 起始序列

    DESTRUCTOR ~Client():
        Disconnect()

    // 禁止拷贝,允许移动
    Client(const Client&) = delete
    Client& operator=(const Client&) = delete
    Client(Client&&) = default
    Client& operator=(Client&&) = default

    // -------------------- 连接管理 --------------------

    // 异步连接 (非阻塞,结果通过回调返回)
    FUNCTION Connect(
            on_success: ConnectSuccessHandler = nullptr,
            on_failure: ConnectFailureHandler = nullptr
    ) -> void:
        IF state_ != kDisconnected AND state_ != kClosed:
            Disconnect()

        state_ = kConnecting
        success_handler_ = std::move(on_success)
        failure_handler_ = std::move(on_failure)
        retry_count_ = 0

        DoConnect()

    // 执行具体连接逻辑
    PRIVATE FUNCTION DoConnect() -> void:
        // 生成唯一routing_key
        conv_ = routing_key_counter_++

        // 创建Session实例
        session_ = std::make_shared<Session>(
            conv_,
            event_loop_,
            socket_.get(),
            config_.remote_address,
            config_.session_config
        )
        session_.Start()

        // 注册Socket可读事件 (接收服务器响应)
        socket_.SetReadHandler(this)

        // 连接超时定时器
        connect_timer_ = event_loop_.AddTimer(
            config_.connect_timeout_ms,
            [this](){ OnConnectTimeout() }
        )

        // 发送首包 (隐式握手)
        // 协议层会自动构建一个初始数据包 (可能仅包含协议头)
        session_.SendHandshakePacket()

        state_ = kConnected
        IF success_handler_:
            success_handler_(session_)

    // 连接超时处理
    PRIVATE FUNCTION OnConnectTimeout() -> void:
        IF state_ != kConnecting:
            RETURN
        IF !config_.reconnect.has_value():
            NotifyConnectFailure(ConnectError::kTimeout)
            RETURN

        // 尝试重连
        strategy = config_.reconnect.value()
        IF strategy.max_attempts > 0 AND retry_count_ >= strategy.max_attempts:
            NotifyConnectFailure(ConnectError::kMaxRetriesExceeded)
            RETURN

        retry_count_++
        delay = MIN(
            strategy.initial_delay_ms * POW(strategy.backoff_factor, retry_count_ - 1),
            strategy.max_delay_ms
        )
        // 添加随机抖动
        jitter = RandomRange(0, strategy.jitter_ms)
        delay += jitter

        state_ = kReconnecting
        event_loop_.AddTimer(delay, [this]():
            IF session_:
                session_.Close()
                session_.reset()
            DoConnect()
        )

    // 断开连接
    FUNCTION Disconnect() -> void:
        IF state_ == kDisconnected OR state_ == kClosed:
            RETURN
        IF connect_timer_.IsValid():
            event_loop_.CancelTimer(connect_timer_)
        reconnect_strategy_.reset()
        retry_count_ = 0
        IF session_:
            session_.Close()
            session_.reset()
        state_ = kDisconnected

    // -------------------- 数据发送 --------------------

    FUNCTION Send(data: const std::vector<uint8_t>&) -> SendResult:
        IF state_ != kConnected OR session_ IS nullptr:
            RETURN SendResult::kBlocked
        RETURN session_.Send(data)

    FUNCTION Send(data: const uint8_t*, len: size_t) -> SendResult:
        IF state_ != kConnected OR session_ IS nullptr:
            RETURN SendResult::kBlocked
        RETURN session_.Send(data, len)

    // -------------------- I/O: 数据报到达处理 --------------------

    FUNCTION OnReadable() -> void:
        WHILE true:
            recv_result = socket_.RecvFrom(recv_buf_.data(), recv_buf_.capacity())
            IF NOT recv_result.has_value():
                BREAK

            // 源验证: 仅处理来自目标服务器的数据报
            IF recv_result.sender != config_.remote_address:
                CONTINUE

            // 路由键验证: 仅处理本会话的数据报
            IF recv_result.len >= 4:
                pkt_conv = ReadBigEndianU32(recv_result.data, 0)
                IF pkt_conv != conv_:
                    CONTINUE     // 旧会话残留包,忽略

            IF session_ != nullptr:
                session_.FeedInput(recv_result.data, recv_result.len)

    // -------------------- 状态查询 --------------------

    FUNCTION GetSession() -> std::shared_ptr<Session>:
        RETURN session_

    FUNCTION GetState() -> ClientState:
        RETURN state_

    // -------------------- 私有 --------------------

    PRIVATE FUNCTION NotifyConnectFailure(error: ConnectError) -> void:
        state_ = kDisconnected
        IF failure_handler_: failure_handler_(error)

    PRIVATE MEMBER event_loop_: EventLoop*
    PRIVATE MEMBER config_: Config
    PRIVATE MEMBER state_: ClientState = kDisconnected
    PRIVATE MEMBER socket_: std::unique_ptr<DatagramSocket>  // Client持有Socket所有权
    PRIVATE MEMBER session_: std::shared_ptr<Session>
    PRIVATE MEMBER conv_: uint32_t = 0
    PRIVATE MEMBER routing_key_counter_: uint64_t
    PRIVATE MEMBER connect_timer_: TimerHandle
    PRIVATE MEMBER success_handler_: ConnectSuccessHandler
    PRIVATE MEMBER failure_handler_: ConnectFailureHandler
    PRIVATE MEMBER retry_count_: uint32_t = 0
    PRIVATE MEMBER recv_buf_: std::vector<uint8_t>(65536)
```

---

## 2. 连接时序图

```
// ============================================================
// 描述: 客户端和服务端的完整交互时序
// ============================================================

FUNCTION ConnectionSequence():
    // ── 客户端 ──
    // 1. Client.Connect() → DoConnect()
    //    - 分配 routing_key (如 conv=12345)
    //    - 创建 Session(conv=12345)
    //    - session.Start() → kConnected
    //    - 启动 connect_timeout 定时器
    //    - 发送握手首包 → 网络

    // ── 网络 ──
    // 2. 数据报从客户端到达服务器

    // ── 服务端 ──
    // 3. Server.OnReadable()
    //    - 解析 routing_key = 12345
    //    - sessions_.find(12345) → MISS
    //    - 创建 Session(conv=12345)
    //    - session.Start() + FeedInput(首包)
    //    - sessions_[12345] = session
    //    - 触发 new_session_handler_

    // ── 服务端响应 (可选: ACK + 业务数据) ──
    // 4. 服务端 Session 通过 Update 驱动发出 ACK
    //    和/或服务端应用层调用 session.Send(response)

    // ── 客户端收到响应 ──
    // 5. Client.OnReadable()
    //    - 源地址验证 ✓ → conv验证 ✓
    //    - session.FeedInput(response)
    //    - 如果有完整用户消息 → 触发 message_callback

    // ── 连接已建立 ──
    // 6. 双向通信正常进行
    //    - 关闭 connect_timeout 定时器
    //    - 双方自由收发数据
```

---

## 3. 重连策略详解

```
// ============================================================
// 描述: 可配置的重连策略
// ============================================================

// --------------------------------------------------
// 3.1 指数退避 (默认推荐)
// --------------------------------------------------
FUNCTION ExponentialBackoffStrategy():
    // 延迟序列: 1s → 2s → 4s → 8s → 16s → 30s (封顶) → ...
    // 每轮附加随机抖动 (±200ms), 避免多个客户端同时重连 (惊群效应)
    // 适用: 临时网络故障后恢复

// --------------------------------------------------
// 3.2 固定间隔
// --------------------------------------------------
FUNCTION FixedIntervalStrategy(interval_ms: uint32_t):
    // 每次以固定间隔重试,直到成功或达到最大次数
    // 适用: 已知恢复时间的场景 (如服务端计划重启)

// --------------------------------------------------
// 3.3 自定义策略
// --------------------------------------------------
FUNCTION CustomReconnectStrategy(user_policy_fn):
    // 用户提供回调,每次断连时调用,返回值决定是否重试及等待时间
    // user_policy_fn(retry_count, last_error) → std::optional<uint32_t>
    //   返回 uint32_t = 等待N ms后重试
    //   返回 nullopt  = 放弃重连
    // 适用: 根据错误类型动态决策 (如DNS失败不重试, 网络抖动重试)

// --------------------------------------------------
// 3.4 无重连
// --------------------------------------------------
FUNCTION NoReconnectStrategy():
    // ReconnectStrategy 设为 nullopt
    // 断连即进入 kDisconnected,立即通知失败
    // 适用: 非持久连接场景 (如请求-响应模式)
```

---

## 4. 最小使用示例

```
// ============================================================
// 描述: 最小化的客户端使用流程
// ============================================================

FUNCTION MinimalClientExample():
    event_loop = EventLoop::Create()

    client = Client(event_loop, Client::Config{
        .remote_address = DatagramSocket::Address::From("127.0.0.1", 8888),
        .reconnect = ExponentialBackoff(),
        .connect_timeout_ms = 5000
    })

    client.Connect(
        // 连接成功
        [](std::shared_ptr<Session> session):
            session.OnMessage([](std::unique_ptr<Message> msg):
                LOG("Received: {} bytes", msg.Size())
            )

            // 发送数据
            client.Send(std::vector<uint8_t>{'H','e','l','l','o'})
        ,
        // 连接失败
        [](ConnectError err):
            LOG("Connection failed: {}", int(err))
    )

    event_loop.Run()
```

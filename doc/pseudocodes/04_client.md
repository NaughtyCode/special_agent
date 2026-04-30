# Client — 客户端抽象层伪代码

`Client` 提供通用的客户端连接与会话管理，通过组合 `Session` 实现CS架构的客户端。设计为端点抽象：同样接口可复用于对等端(Peer)模式。

---

## 1. Client 完整伪代码

```
// ============================================================
// 类名: Client
// 描述: 通用客户端端点,管理与服务器的单个连接会话
//       核心职责:
//       1. 创建到指定目标的Session并管理其生命周期
//       2. 提供发送便捷接口和可配置重连策略
//       3. 管理异步连接状态和回调通知
//       线程安全: 所有操作在所属EventLoop线程执行,无需内部锁
// ============================================================
CLASS Client:
    // -------------------- 类型别名 --------------------
    USING ConnectSuccessHandler = std::move_only_function<void(std::shared_ptr<Session>)>
    USING ConnectFailureHandler = std::move_only_function<void(ConnectError)>

    ENUM ClientState:
        kDisconnected  = 0   // 未连接
        kConnecting    = 1   // 已发送握手,等待服务器首次响应
        kConnected     = 2   // 已收到服务器响应,可正常收发
        kReconnecting  = 3   // 断连后正在等待重连
        kClosed        = 4   // 已关闭,终态

    ENUM ConnectError:
        kTimeout            // 连接超时 (connect_timeout_ms内未收到服务器响应)
        kRefused            // 被服务器拒绝 (收到拒绝通知)
        kDnsFailed          // DNS解析失败
        kSocketError        // Socket创建/绑定失败
        kMaxRetriesExceeded // 超过最大重连次数

    // -------------------- 数据结构 --------------------
    STRUCT ReconnectStrategy:
        initial_delay_ms: uint32_t = 1000    // 初始重连间隔
        max_delay_ms: uint32_t = 30000       // 最大重连间隔 (封顶值)
        backoff_factor: float = 2.0          // 退避因子 (每次乘以该值)
        max_attempts: uint32_t = 5           // 最大重试次数 (0=无限重试)
        jitter_ms: uint32_t = 200            // 随机抖动范围 (避免惊群效应)

    STRUCT Config:
        remote_address: DatagramSocket::Address                    // 目标服务器地址
        session_config: Session::Config                            // Session协议配置
        reconnect: std::optional<ReconnectStrategy>                // 重连策略 (nullopt=禁用重连)
        connect_timeout_ms: uint32_t = 5000                        // 连接超时 (ms)
        local_bind_address: DatagramSocket::Address = DatagramSocket::Address::Any()
        socket_config: DatagramSocket::SocketConfig = DatagramSocket::SocketConfig::Default()
        recv_buf_init_bytes: size_t = 65536                        // 接收缓冲区初始大小

    // -------------------- 构造与析构 --------------------
    CONSTRUCTOR Client(
            event_loop: EventLoop*,
            config: Config
    ):
        event_loop_ = event_loop
        config_     = std::move(config)
        state_      = ClientState::kDisconnected
        socket_     = std::make_unique<DatagramSocket>(
            event_loop, config_.local_bind_address, config_.socket_config)
        routing_key_counter_ = Clock::NowMs() & 0xFFFFFFFF   // 用当前时间作为起始序列
        recv_buf_.resize(config_.recv_buf_init_bytes)        // 预分配接收缓冲区

    DESTRUCTOR ~Client():
        Disconnect()
        // socket_ unique_ptr 自动析构 (RAII关闭fd)

    // 禁止拷贝,允许移动 (Socket所有权唯一)
    Client(const Client&) = delete
    Client& operator=(const Client&) = delete
    Client(Client&&) = default
    Client& operator=(Client&&) = default

    // -------------------- 连接管理 --------------------

    // 异步连接 (非阻塞,结果通过回调通知)
    FUNCTION Connect(
            on_success: ConnectSuccessHandler = nullptr,
            on_failure: ConnectFailureHandler = nullptr
    ) -> void:
        LOG_INFO("Client: connecting to {}:{}",
                 config_.remote_address.ip, config_.remote_address.port)

        // 如果当前有活跃连接,先断开
        IF state_ != ClientState::kDisconnected AND state_ != ClientState::kClosed:
            Disconnect()

        state_ = ClientState::kConnecting
        success_handler_ = std::move(on_success)
        failure_handler_ = std::move(on_failure)
        retry_count_ = 0

        DoConnect()

    // 执行具体连接逻辑 (创建Session,发送握手,等待响应)
    PRIVATE FUNCTION DoConnect() -> void:
        // 生成唯一routing_key (会话标识)
        conv_ = static_cast<uint32_t>(routing_key_counter_++)

        // 创建Session实例并启动
        session_ = std::make_shared<Session>(
            conv_,
            event_loop_,
            socket_.get(),
            config_.remote_address,
            config_.session_config
        )
        session_->Start()    // kIdle → kConnected (Session内部状态)

        // 注册Session事件回调
        WireSessionEvents(session_)

        // 注册Socket可读事件 (接收服务器响应)
        socket_->SetReadHandler(this)

        // 启动连接超时定时器
        connect_timer_ = event_loop_.AddTimer(
            config_.connect_timeout_ms,
            [this](){ OnConnectTimeout() }
        )

        // 发送握手首包 (触发服务器的隐式Accept)
        LOG_DEBUG("Client: created session conv={}, sending handshake", conv_)
        session_->SendHandshakePacket()

        // 注意: state_ 保持 kConnecting,不在此处设为 kConnected
        // 必须收到服务器首次有效响应后才进入 kConnected (参见 OnReadable)

    // 收到服务器首次响应: 连接正式建立
    PRIVATE FUNCTION OnServerFirstResponse() -> void:
        IF state_ != ClientState::kConnecting: RETURN

        // 取消连接超时定时器
        IF connect_timer_.IsValid():
            event_loop_.CancelTimer(connect_timer_)

        state_ = ClientState::kConnected
        LOG_INFO("Client: connection established to {}:{}, conv={}",
                 config_.remote_address.ip, config_.remote_address.port, conv_)

        IF success_handler_:
            success_handler_(session_)

    // 连接超时处理
    PRIVATE FUNCTION OnConnectTimeout() -> void:
        IF state_ != ClientState::kConnecting:
            RETURN    // 已经连接成功或已断开,忽略

        IF NOT config_.reconnect.has_value():
            // 无重连策略: 直接通知失败
            LOG_ERROR("Client: connect failed to {}:{}, timeout",
                      config_.remote_address.ip, config_.remote_address.port)
            event_loop_.CancelTimer(connect_timer_)
            NotifyConnectFailure(ConnectError::kTimeout)
            RETURN

        // 指数退避重连
        strategy = config_.reconnect.value()
        IF strategy.max_attempts > 0 AND retry_count_ >= strategy.max_attempts:
            LOG_ERROR("Client: max retries exceeded ({}) to {}:{}",
                      strategy.max_attempts,
                      config_.remote_address.ip, config_.remote_address.port)
            event_loop_.CancelTimer(connect_timer_)
            NotifyConnectFailure(ConnectError::kMaxRetriesExceeded)
            RETURN

        retry_count_++
        LOG_WARN("Client: connection timeout to {}:{}, retry {}/{}",
                 config_.remote_address.ip, config_.remote_address.port,
                 retry_count_, strategy.max_attempts)
        delay = MIN(
            strategy.initial_delay_ms * POW(strategy.backoff_factor, retry_count_ - 1),
            strategy.max_delay_ms
        )
        jitter = RandomRange(0, strategy.jitter_ms)
        delay += jitter

        state_ = ClientState::kReconnecting

        // 清理当前失败的Session
        IF session_:
            session_->Close()
            session_.reset()

        // 延迟后重试
        event_loop_.AddTimer(delay, [this]():
            IF state_ == ClientState::kReconnecting:
                state_ = ClientState::kConnecting
                DoConnect()
        )

    // 断开连接
    FUNCTION Disconnect() -> void:
        IF state_ == ClientState::kDisconnected OR state_ == ClientState::kClosed:
            RETURN

        LOG_INFO("Client: disconnected from {}:{}",
                 config_.remote_address.ip, config_.remote_address.port)

        // 取消连接超时定时器 (生命周期安全: 防止悬空指针回调)
        IF connect_timer_.IsValid():
            event_loop_.CancelTimer(connect_timer_)

        // 清除重连配置以停止重连循环
        config_.reconnect.reset()
        retry_count_ = 0

        // 关闭并释放Session
        IF session_:
            session_->Close()
            session_.reset()

        state_ = ClientState::kDisconnected

    // -------------------- 数据发送 --------------------

    FUNCTION Send(data: const std::vector<uint8_t>&) -> SendResult:
        IF state_ != ClientState::kConnected OR session_ IS nullptr:
            RETURN SendResult::kBlocked
        RETURN session_->Send(data)

    FUNCTION Send(data: const uint8_t*, len: size_t) -> SendResult:
        IF state_ != ClientState::kConnected OR session_ IS nullptr:
            RETURN SendResult::kBlocked
        RETURN session_->Send(data, len)

    // -------------------- IEventHandler 实现: 数据报到达处理 --------------------

    FUNCTION OnReadable() -> void:
        consecutive_errors = 0
        WHILE true:
            recv_result = socket_.RecvFrom(recv_buf_.data(), recv_buf_.size())
            IF NOT recv_result.has_value():
                // SocketError (如ICMP不可达): 记录日志,继续循环
                // Socket错误不影响Socket继续使用,不应中断读取循环
                // 但连续过多错误说明Socket可能已损坏,中止循环防止忙等
                consecutive_errors += 1
                LOG_WARN("RecvFrom socket error: {}", static_cast<int>(recv_result.error()))
                IF consecutive_errors >= kMaxConsecutiveRecvErrors:
                    LOG_ERROR("Too many consecutive RecvFrom errors ({}), breaking read loop",
                              consecutive_errors)
                    BREAK
                CONTINUE
            consecutive_errors = 0   // 成功读取时重置计数器
            IF NOT recv_result->has_value():
                BREAK      // nullopt: Socket接收缓冲区已排空,无更多就绪数据报

            // 提取接收结果 (已通过双检)
            auto& result = recv_result.value().value()

            // 源地址验证: 仅处理来自目标服务器的数据报 (防窃听/注入)
            IF result.sender != config_.remote_address:
                CONTINUE

            // 路由键验证: 仅处理属于本会话的数据报
            // 过路包 (旧会话残留/路由错误) 直接丢弃
            IF result.len >= 4:
                pkt_conv = ReadBigEndianU32(result.data, 0)
                IF pkt_conv != conv_:
                    CONTINUE

            IF session_ != nullptr:
                session_->FeedInput(result.data, result.len)

                // 首次收到有效服务器响应 → 连接正式建立
                IF state_ == ClientState::kConnecting:
                    OnServerFirstResponse()

    // -------------------- 状态查询 --------------------

    FUNCTION GetSession() -> std::shared_ptr<Session>:
        RETURN session_

    FUNCTION GetState() -> ClientState:
        RETURN state_

    // -------------------- 私有辅助 --------------------

    PRIVATE FUNCTION WireSessionEvents(session: std::shared_ptr<Session>) -> void:
        // 注册Session错误回调: 将协议/Socket错误传播到重连逻辑
        session->OnError([this](SessionError e):
            IF state_ == ClientState::kConnected:
                // 已建立的连接断开 → 尝试重连
                IF config_.reconnect.has_value():
                    // 清理当前Session并进入重连流程
                    IF session_:
                        session_->Close()
                        session_.reset()
                    // 通过PostTask异步发起重连(避免在Session回调中修改自身状态)
                    event_loop_.PostTask([this]():
                        DoConnect()   // 直接创建新Session并发起连接
                    )
                ELSE:
                    NotifyConnectFailure(ConnectError::kSocketError)
        )

        // 注册Session状态变更回调
        session->OnStateChange([this](SessionState old_state, SessionState new_state):
            IF new_state == SessionState::kClosed:
                IF state_ == ClientState::kConnected:
                    state_ = ClientState::kDisconnected
        )

    PRIVATE FUNCTION NotifyConnectFailure(error: ConnectError) -> void:
        LOG_ERROR("Client: connect failed to {}:{}, error={}",
                  config_.remote_address.ip, config_.remote_address.port,
                  ConnectErrorToString(error))
        state_ = ClientState::kDisconnected
        IF session_:
            session_->Close()
            session_.reset()
        IF failure_handler_:
            failure_handler_(error)

    // -------------------- 成员变量 --------------------
    PRIVATE MEMBER event_loop_: EventLoop*
    PRIVATE MEMBER config_: Config
    PRIVATE MEMBER state_: ClientState = ClientState::kDisconnected
    PRIVATE MEMBER socket_: std::unique_ptr<DatagramSocket>   // Client持有Socket所有权
    PRIVATE MEMBER session_: std::shared_ptr<Session>
    PRIVATE MEMBER conv_: uint32_t = 0                         // 当前会话的routing_key
    PRIVATE MEMBER routing_key_counter_: uint64_t              // 单调递增的routing_key分配器
    PRIVATE MEMBER connect_timer_: TimerHandle                 // 连接超时定时器句柄
    PRIVATE MEMBER success_handler_: ConnectSuccessHandler
    PRIVATE MEMBER failure_handler_: ConnectFailureHandler
    PRIVATE MEMBER retry_count_: uint32_t = 0
    PRIVATE MEMBER recv_buf_: std::vector<uint8_t>             // 接收缓冲区 (resize后size=可用长度)
```

---

## 2. 连接时序图

```
// ============================================================
// 描述: 客户端和服务端的完整异步连接时序
// ============================================================

FUNCTION ConnectionSequence():
    // ── 阶段1: 客户端发起连接 ──
    // Client.Connect() → DoConnect()
    //   - 分配 routing_key (如 conv=12345)
    //   - 创建 Session(conv=12345)
    //   - session.Start() → Session内部状态: kIdle → kConnected
    //   - 启动 connect_timeout 定时器
    //   - 发送握手首包 (SendHandshakePacket) → 网络
    //   - Client状态: kConnecting (等待服务器响应)

    // ── 阶段2: 网络传输 ──
    // 数据报从客户端经UDP到达服务器

    // ── 阶段3: 服务端接收 ──
    // Server.OnReadable()
    //   - 解析 routing_key = 12345
    //   - sessions_.find(12345) → MISS (首次到达)
    //   - 创建 Session(conv=12345, remote_addr=客户端地址)
    //   - session.Start() + session.FeedInput(首包)
    //   - sessions_[12345] = session
    //   - 触发 new_session_handler_ (通知应用层)

    // ── 阶段4: 服务端响应 ──
    // 服务端协议引擎通过Update周期驱动发出ACK (确认收到客户端首包)
    // 和/或服务端应用层调用 session.Send(response) 发送业务数据

    // ── 阶段5: 客户端收到响应 → 连接建立 ──
    // Client.OnReadable()
    //   - 源地址验证 ✓ (sender == remote_address)
    //   - conv验证 ✓ (pkt_conv == conv_)
    //   - session.FeedInput(response)
    //   - 检测 state_ == kConnecting → OnServerFirstResponse():
    //       * 取消 connect_timeout 定时器
    //       * state_ = kConnected
    //       * 触发 success_handler_(session_)
    //   - 后续: TryRecv() → 如有完整用户消息 → 触发 message_callback

    // ── 阶段6: 双向通信 ──
    // 双方自由收发数据,协议引擎持续处理ACK/重传/流控
```

---

## 3. 重连策略详解

```
// ============================================================
// 描述: 可配置的重连策略及选择指南
// ============================================================

// --------------------------------------------------
// 3.1 指数退避 (默认推荐)
// --------------------------------------------------
FUNCTION ExponentialBackoffStrategy():
    // 延迟序列: 1s → 2s → 4s → 8s → 16s → 30s (封顶) → 30s → ...
    // 每轮附加随机抖动 (±jitter_ms范围),避免多个客户端同时重连 (惊群效应)
    // 公式: delay = min(initial × factor^(retry-1), max) + random(0, jitter)
    // 适用: 临时网络故障后自动恢复 (大多数场景)

// --------------------------------------------------
// 3.2 固定间隔
// --------------------------------------------------
FUNCTION FixedIntervalStrategy(interval_ms: uint32_t):
    // 每次以固定间隔重试,直到成功或达到max_attempts
    // 实现: backoff_factor=1.0, initial_delay_ms=max_delay_ms=interval_ms
    // 适用: 已知恢复时间的场景 (如服务端计划重启,预期N秒后恢复)

// --------------------------------------------------
// 3.3 自定义策略 (扩展点)
// --------------------------------------------------
FUNCTION CustomReconnectStrategy(user_policy_fn):
    // 用户提供策略回调,每次断连时调用,返回值决定是否重试及等待时间
    // 回调签名: user_policy_fn(retry_count, last_error) → std::optional<uint32_t>
    //   - 返回 uint32_t = 等待N ms后重试
    //   - 返回 nullopt  = 放弃重连
    // 适用: 根据错误类型动态决策
    //   示例: DNS失败不重试(直接报错), 网络超时重试
    //   示例: 根据当前时间决定 (如业务低峰期延长重试间隔)

// --------------------------------------------------
// 3.4 无重连
// --------------------------------------------------
FUNCTION NoReconnectStrategy():
    // Config::reconnect = std::nullopt
    // 超时或断连即进入 kDisconnected,立即通知失败
    // 适用: 请求-响应模式 / 非持久连接 / 上层自行管理重连
```

---

## 4. 使用示例

```
// ============================================================
// 描述: 最小化的客户端使用流程 (修正了闭包捕获安全性)
// ============================================================

FUNCTION MinimalClientExample():
    event_loop = EventLoop(IOBackend::kAutoDetect)

    client_config = Client::Config{
        .remote_address     = DatagramSocket::Address::From("127.0.0.1", 8888),
        .reconnect          = ReconnectStrategy{
            .initial_delay_ms = 1000,
            .max_delay_ms     = 30000,
            .backoff_factor   = 2.0,
            .max_attempts     = 5
        },
        .connect_timeout_ms = 5000
    }

    // 使用shared_ptr管理Client,以便在回调中安全捕获
    client = std::make_shared<Client>(&event_loop, client_config)

    client->Connect(
        // 连接成功回调: session由Client持有,参数传递引用
        [client](std::shared_ptr<Session> session):
            session->OnMessage([](std::unique_ptr<Message> msg):
                LOG("Received: {} bytes", msg->Size())
            )

            // 发送数据 (session为参数,无需捕获client)
            data = std::vector<uint8_t>{'H','e','l','l','o'}
            session->Send(data)
        ,
        // 连接失败回调: 仅使用错误码,无需捕获外部状态
        [](ConnectError err):
            LOG("Connection failed: {}", static_cast<int>(err))
    )

    event_loop.Run()
    // 注意: 生产环境应在Run()返回后清理client
```

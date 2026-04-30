# Server — 服务端抽象层伪代码

`Server` 提供通用的服务端监听与会话管理能力，通过组合 `Session` 和平台层实现CS架构的服务端。设计为角色无关的端点抽象：同样接口可用于对等端(Peer)模式。

---

## 1. Server 完整伪代码

```
// ============================================================
// 类名: Server
// 描述: 通用服务端端点,负责监听数据报端口并管理所有客户端会话
//       核心职责:
//       1. 监听数据报端口,接收所有来源的入站数据包
//       2. 管理 Session 的创建/路由/销毁
//       3. 执行连接健康度检测和过期会话驱逐
//       4. 提供会话级事件钩子,支持中间件链
//       线程安全: 所有操作在所属EventLoop线程执行,无需内部锁
// ============================================================
CLASS Server:
    // -------------------- 常量 --------------------
    CONST kMaxConsecutiveRecvErrors: int = 16   // 连续RecvFrom错误上限 (防止Socket损坏导致忙等)
                                                 // 与Client::kMaxConsecutiveRecvErrors独立定义,
                                                 // 二者使用场景相同 (循环读取中防死循环)

    // -------------------- 类型别名 --------------------
    USING NewSessionHandler     = std::move_only_function<void(std::shared_ptr<Session>)>
    USING SessionEvictedHandler = std::move_only_function<void(uint32_t conv, EvictReason)>
    // 注意: 当前使用uint32_t作为会话键,不同来源使用相同conv值时会产生冲突
    // 缓解方案: 使用复合键 std::tuple<uint32_t, std::string, uint16_t> (conv, sender_ip, sender_port)
    // 或服务端在首次响应中分配新的服务端conv,建立conv映射表以避免冲突
    USING SessionMap            = std::unordered_map<uint32_t, std::shared_ptr<Session>>

    ENUM ServerState:
        kStopped = 0
        kRunning = 1

    ENUM EvictReason:
        kTimedOut      // 空闲超时
        kRemoteClosed  // 对端主动关闭
        kLocalClosed   // 本地主动关闭
        kError         // 协议/Socket错误

    ENUM EvictionPolicy:
        kImmediateClose    // 立即关闭,不等待对端确认
        kGracefulShutdown  // 尝试优雅关闭,超时后强制
        kNotifyOnly        // 仅通知上层,上层决定关闭方式

    ENUM IdlePolicy:
        kIgnore     // 忽略空闲,不做任何处理
        kSendProbe  // 发送协议层探活包
        kNotify     // 仅通知上层,由上层决定处理方式

    STRUCT Config:
        listen_address: DatagramSocket::Address
        session_config: Session::Config               // 新Session的默认协议配置
        max_sessions: size_t = 0                      // 最大会话数 (0=不限制)
        health_check_interval_ms: uint32_t = 1000     // 健康检测周期间隔
        idle_timeout_ms: uint32_t = 15000             // 空闲判定阈值 (超过则进入kIdle)
        stale_timeout_ms: uint32_t = 30000            // 过期判定阈值 (超过则进入kStale)
        eviction_policy: EvictionPolicy = EvictionPolicy::kImmediateClose
        idle_policy: IdlePolicy = IdlePolicy::kSendProbe
        socket_config: DatagramSocket::SocketConfig = DatagramSocket::SocketConfig::Default()
        recv_buf_init_bytes: size_t = 65536           // 接收缓冲区初始大小

    // -------------------- 构造与析构 --------------------
    CONSTRUCTOR Server(
            event_loop: EventLoop*,
            config: Config
    ):
        event_loop_ = event_loop
        config_     = std::move(config)
        state_      = ServerState::kStopped
        socket_     = DatagramSocket(event_loop, config_.listen_address, config_.socket_config)
        recv_buf_.resize(config_.recv_buf_init_bytes)   // 预分配接收缓冲区

    DESTRUCTOR ~Server():
        Stop()
        // socket_ 成员自动析构 (RAII关闭fd)

    // 禁止拷贝 (Socket和会话表不可共享)
    Server(const Server&) = delete
    Server& operator=(const Server&) = delete

    // -------------------- 生命周期 --------------------

    FUNCTION Start() -> void:
        IF state_ == ServerState::kRunning: RETURN
        state_ = ServerState::kRunning

        LOG_INFO("Server started: listening on {}:{}",
                 config_.listen_address.ip, config_.listen_address.port)

        // 注册Socket可读事件: 数据报到达时回调 OnReadable()
        socket_.SetReadHandler(this)

        // 启动周期性Session协议驱动定时器 (驱动所有Session的协议状态机)
        // 周期: Session::Config::update_interval_ms (默认10ms)
        // 这是协议引擎正常工作的必要条件:
        //   - 驱动数据发送 (窗口内数据分片发出)
        //   - 驱动重传判定 (RTO超时/快速重传)
        //   - 驱动ACK发送和RTT估算
        //   - 驱动流控状态更新 (如启用)
        drive_timer_ = event_loop_.AddPeriodicTimer(
            config_.session_config.update_interval_ms,
            [this](){ DriveAllSessions() }
        )

        // 启动周期性健康检测定时器
        health_timer_ = event_loop_.AddPeriodicTimer(
            config_.health_check_interval_ms,
            [this](){ RunHealthCheck() }
        )

    FUNCTION Stop() -> void:
        IF state_ == ServerState::kStopped: RETURN
        state_ = ServerState::kStopped

        LOG_INFO("Server stopped: {} sessions active at shutdown",
                 sessions_.size())

        // 取消健康检测定时器和协议驱动定时器 (生命周期安全: 在清理会话前取消)
        event_loop_.CancelTimer(health_timer_)
        event_loop_.CancelTimer(drive_timer_)

        // 根据驱逐策略处理所有现存会话
        FOR EACH (conv, session) IN sessions_:
            EvictSession(session, EvictReason::kLocalClosed)
        sessions_.clear()

    // -------------------- 回调注册 --------------------

    FUNCTION OnNewSession(handler: NewSessionHandler) -> void:
        new_session_handler_ = std::move(handler)

    FUNCTION OnSessionEvicted(handler: SessionEvictedHandler) -> void:
        session_evicted_handler_ = std::move(handler)

    // -------------------- IEventHandler 实现: 数据报到达处理 --------------------

    FUNCTION OnReadable() -> void:
        // 边缘触发模式: 循环读取直到Socket缓冲区排空
        // 连续错误计数器: 防止持久性Socket错误导致无限循环
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

            // 提取接收结果 (已通过has_value和nullopt检查)
            auto& result = recv_result.value().value()

            // 解析协议头部获取会话标识 (routing_key)
            // conv是KCP的概念,QUIC使用Connection ID,泛化为routing_key以支持多协议
            routing_key = ExtractRoutingKey(result.data, result.len)
            IF NOT routing_key.has_value():
                CONTINUE   // 无效数据包 (长度不足),静默丢弃

            // 路由到已有Session或隐式创建新Session
            it = sessions_.find(routing_key.value())
            IF it != sessions_.end():
                // 命中已有会话: 直接输入数据
                it->second->FeedInput(result.data, result.len)
            ELSE:
                // 未命中: 隐式Accept — 收到首包即创建会话
                IF config_.max_sessions > 0 AND
                   sessions_.size() >= config_.max_sessions:
                    // 达到最大会话数上限,静默丢弃 (也可配置为驱逐最旧会话)
                    CONTINUE

                session = std::make_shared<Session>(
                    routing_key.value(),
                    event_loop_,
                    &socket_,
                    result.sender,
                    config_.session_config
                )
                session->Start()
                session->FeedInput(result.data, result.len)

                // 注册Session内部事件,向上层传播
                WireSessionEvents(session)

                sessions_[routing_key.value()] = session

                LOG_INFO("Server: new session accepted, conv={}, from={}",
                         routing_key.value(), result.sender.ToString())
                LOG_DEBUG("Server: session count now {}/{}",
                          sessions_.size(), config_.max_sessions)

                IF new_session_handler_:
                    new_session_handler_(session)

    // -------------------- 会话管理 --------------------

    FUNCTION GetSession(conv: uint32_t) -> std::shared_ptr<Session>:
        it = sessions_.find(conv)
        IF it != sessions_.end():
            RETURN it->second
        RETURN nullptr

    FUNCTION RemoveSession(conv: uint32_t, reason: EvictReason) -> void:
        it = sessions_.find(conv)
        IF it != sessions_.end():
            session = it->second     // 持有shared_ptr副本,确保EvictSession期间有效
            sessions_.erase(it)       // 先从表中移除
            EvictSession(session, reason)  // 再执行驱逐 (顺序重要: 防止重入)

    FUNCTION GetSessionCount() -> size_t:
        RETURN sessions_.size()

    FUNCTION GetEventLoop() -> EventLoop*:
        RETURN event_loop_

    // -------------------- 会话协议驱动 --------------------

    PRIVATE FUNCTION DriveAllSessions() -> void:
        now = Clock::NowMs()
        FOR EACH (conv, session) IN sessions_:
            session->Update(now)
        // 协议引擎在Update中通过OutputCallback输出:
        //   新数据发送 / 重传 / ACK确认 / 探活响应 / WINS窗口更新
        // OutputCallback已由Session构造时绑定到socket_->SendTo

    // -------------------- 健康检测 --------------------

    PRIVATE FUNCTION RunHealthCheck() -> void:
        now = Clock::NowMs()
        stale_conv_list = std::vector<uint32_t>()   // 收集过期会话ID,批量处理

        idle_count = 0
        FOR EACH (conv, session) IN sessions_:
            health = session->EvaluateHealth(
                now, config_.idle_timeout_ms, config_.stale_timeout_ms)

            SWITCH health:
                CASE ConnectionHealth::kStale:
                    stale_conv_list.push_back(conv)
                CASE ConnectionHealth::kIdle:
                    idle_count += 1
                    IF config_.idle_policy == IdlePolicy::kSendProbe:
                        session->SendProbePacket()    // 主动发送协议层探活包
                    ELSE IF config_.idle_policy == IdlePolicy::kNotify:
                        // 预留: 通知上层应用空闲事件
                        // IF idle_handler_: idle_handler_(conv)

        LOG_DEBUG("Server health check: {} sessions, {} idle, {} stale",
                  sessions_.size(), idle_count, stale_conv_list.size())

        // 批量驱逐过期会话 (通过RemoveSession集中处理,避免重复erase+evict逻辑)
        FOR EACH conv IN stale_conv_list:
            LOG_WARN("Server: session conv={} timed out (stale), evicting", conv)
            RemoveSession(conv, EvictReason::kTimedOut)

    // -------------------- 私有辅助 --------------------

    PRIVATE FUNCTION EvictSession(
            session: std::shared_ptr<Session>,
            reason: EvictReason
    ) -> void:
        LOG_INFO("Server: evicting session conv={}, reason={}",
                 session->GetConvId(), EvictReasonToString(reason))

        SWITCH config_.eviction_policy:
            CASE EvictionPolicy::kImmediateClose:
                session->Close()
            CASE EvictionPolicy::kGracefulShutdown:
                session->GracefulShutdown(/*timeout_ms=*/5000)
            CASE EvictionPolicy::kNotifyOnly:
                // 不主动关闭,由上层应用根据reason自行处理

        IF session_evicted_handler_:
            session_evicted_handler_(session->GetConvId(), reason)

    // 将Session的内部事件连接到Server的驱逐逻辑
    // 生命周期说明: lambda捕获的this (Server*) 的生命期必须长于Session
    // 在Stop()中先清理sessions_再析构Server,保证此前提成立
    PRIVATE FUNCTION WireSessionEvents(session: std::shared_ptr<Session>) -> void:
        conv = session->GetConvId()

        // 错误事件 → 驱逐 (远程关闭或协议错误)
        session->OnError([this, conv](SessionError e):
            EvictReason reason = (e == SessionError::kRemoteClose)
                ? EvictReason::kRemoteClosed
                : EvictReason::kError
            // 通过PostTask确保在EventLoop线程中执行
            event_loop_->PostTask([this, conv, reason]():
                RemoveSession(conv, reason)
            )
        )

        // 状态变更事件 → 会话自行进入kClosed时触发清理
        session->OnStateChange([this, conv](SessionState old_state, SessionState new_state):
            IF new_state == SessionState::kClosed:
                event_loop_->PostTask([this, conv]():
                    RemoveSession(conv, EvictReason::kLocalClosed)
                )
        )

    // 从数据报头部提取路由键 (协议相关,取决于协议引擎类型)
    CONST MIN_HEADER_SIZE: size_t = 24   // KCP最小头部24字节 (conv+cmd+frag+wnd+ts+sn+una+len)
                                         // QUIC最小1字节但由ProtocolEngine::ExtractRoutingKey处理
    PRIVATE FUNCTION ExtractRoutingKey(
            data: const uint8_t*, len: size_t
    ) -> std::optional<uint32_t>:
        // KCP:  conv 位于偏移0, 4字节大端无符号整数; 最小头部24字节
        // QUIC: Connection ID提取逻辑根据引擎类型不同:
        //   - 长头 (Initial/Handshake): HeaderForm(1) + Reserved(2) + Version(4) +
        //     DCIL(1) + DCID(variable) + SCIL(1) + SCID(variable),取SCID哈希
        //   - 短头 (1-RTT): HeaderForm(1) + CID(variable),取CID哈希
        // 为确保协议无关,当engine_type为kEngineQUIC时应调用
        // ProtocolEngine::ExtractRoutingKey(data, len) 以委托协议特定解析
        IF len < MIN_HEADER_SIZE: RETURN std::nullopt
        IF config_.session_config.engine_type == EngineType::kEngineQUIC:
            // QUIC的Connection ID提取逻辑复杂(长头/短头格式不同),委托ProtocolEngine静态方法解析
            // 注意: ProtocolEngine::ExtractRoutingKey是静态方法,不依赖引擎实例;
            //       定义在 protocol_engine.h 中,各引擎实现提供对应重载
            RETURN ProtocolEngine::ExtractRoutingKey(data, len)
        // KCP (默认): conv位于偏移0,4字节大端无符号整数
        RETURN ReadBigEndianU32(data, 0)

    // -------------------- 成员变量 --------------------
    PRIVATE MEMBER event_loop_: EventLoop*
    PRIVATE MEMBER config_: Config
    PRIVATE MEMBER state_: ServerState = ServerState::kStopped
    PRIVATE MEMBER socket_: DatagramSocket                          // RAII管理的Socket
    PRIVATE MEMBER sessions_: SessionMap                            // conv → Session映射
    PRIVATE MEMBER new_session_handler_: NewSessionHandler
    PRIVATE MEMBER session_evicted_handler_: SessionEvictedHandler
    PRIVATE MEMBER health_timer_: TimerHandle = 0                   // 健康检测定时器句柄
    PRIVATE MEMBER drive_timer_: TimerHandle = 0                    // 协议驱动定时器句柄
    PRIVATE MEMBER recv_buf_: std::vector<uint8_t>                  // 接收缓冲区 (resize后size=可用长度)
```

---

## 2. Accept 流程详解 (应用层握手)

```
// ============================================================
// 描述: 基于数据报的隐式连接建立 (无连接传输层的"握手")
// ============================================================

FUNCTION AcceptFlowDescription(server: Server):
    // 由于基于数据报(Datagram)的协议没有内核态连接状态,
    // 服务端采用"收到首包即建立会话"的隐式握手模型

    // 完整流程:
    // 1. Socket收到数据报
    raw_datagram = socket_.RecvFrom()

    // 2. 提取路由键 (协议头中的会话标识字段)
    routing_key = ExtractRoutingKey(raw_datagram)

    // 3. 路由决策:
    //    HIT  → 已有会话 → FeedInput (正常数据路径)
    //    MISS → 新会话   → CreateSession + Start + FeedInput + WireSessionEvents
    //
    // 设计考量 (基于数据报的无连接特性):
    //   a. conv冲突: 不同来源可能使用相同conv值
    //      缓解方案: 使用 (conv, sender_ip, sender_port) 复合键作为会话索引
    //         SESSION_KEY = std::tuple<uint32_t, std::string, uint16_t>
    //      或: 服务端在首次响应中分配新的服务端conv,建立conv映射表
    //   b. 防御伪造: 可在应用层添加cookie/token验证环节
    //      (如: 客户端首包携带服务端预先签发的token)
    //   c. 慢速客户端: 收到首包但不发送后续数据 → 依赖健康检测的stale超时驱逐

    // 安全增强: 可插拔的AcceptFilter中间件链
    // server.AddAcceptFilter([](const DatagramSocket::Address& src, span<const uint8_t> first_pkt) -> bool {
    //     // 返回false拒绝此会话 (如IP黑名单检查)
    //     return !IsBlacklisted(src.ip);
    // });
```

---

## 3. 定时任务与会话维护

```
// ============================================================
// 描述: 服务端周期任务
// ============================================================

// --------------------------------------------------
// 3.1 驱动所有Session的协议状态机
// --------------------------------------------------
FUNCTION DriveAllSessions(server: Server, now_ms: uint64_t):
    FOR EACH (conv, session) IN server.sessions_:
        session->Update(now_ms)
    // 此调用可集成到EventLoop的定时器中
    // 推荐: 与健康检测共用同一周期定时器以降低定时器开销
    // Update频率应等于 Session::Config::update_interval_ms 的最小公倍数

// --------------------------------------------------
// 3.2 会话驱逐策略对比
// --------------------------------------------------
FUNCTION EvictionPolicyComparison(session, policy: EvictionPolicy):
    SWITCH policy:
        CASE EvictionPolicy::kImmediateClose:
            // 最快回收资源,直接关闭不等待
            session->Close()
            // 注意: 对端无法收到通知,下次通信时才会发现对端已不可达
            // 适合: 资源受限场景,或确信对端已不可达

        CASE EvictionPolicy::kGracefulShutdown:
            // 最友好的方式: 先发送CLOSE通知,等待对端ACK确认
            // 缺点: 需要额外状态追踪和超时处理,资源回收延迟
            // 适合: 需要保证对端感知连接关闭的场景
            session->GracefulShutdown(timeout_ms=5000)

        CASE EvictionPolicy::kNotifyOnly:
            // 最灵活: 应用层完全控制关闭行为
            // 应用层可在回调中: 保存状态、尝试重连、记录日志等
            // 适合: 需要自定义驱逐逻辑的复杂业务场景

// --------------------------------------------------
// 3.3 探活机制
// --------------------------------------------------
FUNCTION SendProbe(session: std::shared_ptr<Session>):
    // 向空闲Session发送协议层探活包
    // 协议引擎将构建并发送探活数据包:
    //   KCP:  WASK命令字,对端自动回复WINS
    //   QUIC: PING帧,对端自动回复PONG或携带数据的ACK
    // 完成一次心跳往返,本端在后续FeedInput中会更新last_recv_time_ms_
    session->SendProbePacket()

// --------------------------------------------------
// 3.4 会话数量管理
// --------------------------------------------------
FUNCTION SessionCapacityManagement(server: Server):
    // 当会话数接近max_sessions时,可选策略:
    //   a. 拒绝新会话 (默认: 静默丢弃)
    //   b. 驱逐最旧/最不活跃的会话 (LRU驱逐)
    //   c. 通知上层,由应用层决策
    //
    // LRU驱逐伪代码:
    // IF sessions_.size() >= max_sessions_:
    //     oldest_conv = FindLeastRecentlyActive(sessions_)
    //     RemoveSession(oldest_conv, EvictReason::kLocalClosed)
    //     // 然后正常创建新会话
```

---

## 4. 线程安全与并发说明

```
// ============================================================
// 描述: Server的线程模型与并发安全保证
// ============================================================

FUNCTION ServerThreadSafetyModel():
    // Server设计为单EventLoop线程运行:
    //   - OnReadable() 由EventLoop在IO线程回调
    //   - RunHealthCheck() 由定时器在IO线程触发
    //   - 所有sessions_操作在同一线程串行执行
    //
    // 因此: sessions_ (std::unordered_map) 无需额外同步
    //
    // 跨线程操作Session (如应用层从其他线程Send):
    //   必须通过 EventLoop::PostTask 投递到Session所属的EventLoop线程
    //   示例:
    //     server.GetEventLoop()->PostTask([session, data](){
    //         session->Send(data);
    //     });
    //
    // 多Worker模式: 每个Worker拥有独立的EventLoop+Server实例
    //   不同的routing_key被Dispatch到不同Worker → 各Worker独立运作
    //   Session粘滞在分配到的Worker线程,无跨线程访问
```

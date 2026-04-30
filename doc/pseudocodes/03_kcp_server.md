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
// ============================================================
CLASS Server:
    // -------------------- 类型别名 --------------------
    USING NewSessionHandler   = std::move_only_function<void(std::shared_ptr<Session>)>
    USING SessionEvictedHandler = std::move_only_function<void(uint32_t conv, EvictReason)>
    USING SessionMap = std::unordered_map<uint32_t, std::shared_ptr<Session>>

    ENUM ServerState:
        kStopped = 0
        kRunning = 1

    ENUM EvictReason:
        kTimedOut     // 空闲超时
        kRemoteClosed // 对端主动关闭
        kLocalClosed  // 本地主动关闭
        kError        // 协议/Socket错误

    ENUM EvictionPolicy:
        kImmediateClose   // 立即关闭,不通知
        kGracefulShutdown // 尝试优雅关闭,超时后强制
        kNotifyOnly       // 仅通知上层,上层决定是否关闭

    ENUM IdlePolicy:
        kIgnore           // 忽略空闲
        kSendProbe        // 发送探活包
        kNotify           // 通知上层

    STRUCT Config:
        listen_address: DatagramSocket::Address
        session_config: Session::Config              // 新Session的默认配置
        max_sessions: size_t = 0                     // 最大会话数 (0=不限制)
        health_check_interval_ms: uint32_t = 1000    // 健康检测周期
        idle_timeout_ms: uint32_t = 15000            // 空闲超时
        stale_timeout_ms: uint32_t = 30000           // 过期超时
        eviction_policy: EvictionPolicy = kImmediateClose
        idle_policy: IdlePolicy = kSendProbe
        socket_config: DatagramSocket::SocketConfig = DatagramSocket::SocketConfig::Default()

    // -------------------- 构造与析构 --------------------
    CONSTRUCTOR Server(
            event_loop: EventLoop*,
            config: Config
    ):
        event_loop_ = event_loop
        config_     = std::move(config)
        state_      = kStopped
        socket_     = DatagramSocket(event_loop, config_.listen_address, config_.socket_config)

    DESTRUCTOR ~Server():
        Stop()

    // 禁止拷贝
    Server(const Server&) = delete
    Server& operator=(const Server&) = delete

    // -------------------- 生命周期 --------------------

    FUNCTION Start() -> void:
        IF state_ == kRunning: RETURN
        state_ = kRunning

        // Socket就绪 → 接收所有入站数据报
        socket_.SetReadHandler(this)

        // 启动周期健康检测
        health_timer_ = event_loop_.AddPeriodicTimer(
            config_.health_check_interval_ms,
            [this](){ RunHealthCheck() }
        )

    FUNCTION Stop() -> void:
        IF state_ == kStopped: RETURN
        state_ = kStopped

        event_loop_.CancelTimer(health_timer_)

        // 根据驱逐策略处理所有现存会话
        FOR EACH (conv, session) IN sessions_:
            EvictSession(session, EvictReason::kLocalClosed)
        sessions_.clear()

    // -------------------- 回调注册 --------------------

    FUNCTION OnNewSession(handler: NewSessionHandler) -> void:
        new_session_handler_ = std::move(handler)

    FUNCTION OnSessionEvicted(handler: SessionEvictedHandler) -> void:
        session_evicted_handler_ = std::move(handler)

    // -------------------- I/O: 数据报到达处理 --------------------

    FUNCTION OnReadable() -> void:
        // 循环读取,直到Socket缓冲区排空 (边缘触发要求)
        WHILE true:
            recv_result = socket_.RecvFrom(recv_buf_.data(), recv_buf_.capacity())
            IF NOT recv_result.has_value():
                BREAK

            // 解析协议头部获取会话标识 (conv是KCP的概念,泛化为routing_key)
            routing_key = ExtractRoutingKey(recv_result.data, recv_result.len)
            IF NOT routing_key.has_value():
                CONTINUE    // 无效数据包,丢弃

            // 路由: 在会话表中查找或创建
            it = sessions_.find(routing_key.value())
            IF it != sessions_.end():
                // 命中: 路由到已有Session
                it.second.FeedInput(recv_result.data, recv_result.len)
            ELSE:
                // 未命中: 创建新Session (隐式Accept)
                IF config_.max_sessions > 0 AND
                   sessions_.size() >= config_.max_sessions:
                    // 达到最大会话数,根据策略处理: 拒绝/驱逐最旧/静默丢弃
                    CONTINUE

                session = std::make_shared<Session>(
                    routing_key.value(),
                    event_loop_,
                    &socket_,
                    recv_result.sender,
                    config_.session_config
                )
                session.Start()
                session.FeedInput(recv_result.data, recv_result.len)

                // 注册Session内部事件,向上层传播
                WireSessionEvents(session)

                sessions_[routing_key.value()] = session

                IF new_session_handler_:
                    new_session_handler_(session)

    // -------------------- 会话管理 --------------------

    FUNCTION GetSession(conv: uint32_t) -> std::shared_ptr<Session>:
        it = sessions_.find(conv)
        IF it != sessions_.end(): RETURN it.second
        RETURN nullptr

    FUNCTION RemoveSession(conv: uint32_t, reason: EvictReason) -> void:
        it = sessions_.find(conv)
        IF it != sessions_.end():
            EvictSession(it.second, reason)
            sessions_.erase(it)

    FUNCTION GetSessionCount() -> size_t:
        RETURN sessions_.size()

    // -------------------- 健康检测 --------------------

    PRIVATE FUNCTION RunHealthCheck() -> void:
        now = Clock::NowMs()
        stale_conv_list = std::vector<uint32_t>()   // 收集后批量处理

        FOR EACH (conv, session) IN sessions_:
            health = session.EvaluateHealth(
                now, config_.idle_timeout_ms, config_.stale_timeout_ms)

            SWITCH health:
                CASE kStale:
                    stale_conv_list.push_back(conv)
                CASE kIdle:
                    IF config_.idle_policy == kSendProbe:
                        SendProbe(session)   // 主动探活
                    ELSE IF config_.idle_policy == kNotify:
                        // 通知上层,由上层决定

        FOR EACH conv IN stale_conv_list:
            it = sessions_.find(conv)
            IF it != sessions_.end():
                EvictSession(it.second, EvictReason::kTimedOut)
                sessions_.erase(it)

    // -------------------- 私有辅助 --------------------

    PRIVATE FUNCTION EvictSession(
            session: std::shared_ptr<Session>,
            reason: EvictReason
    ) -> void:
        SWITCH config_.eviction_policy:
            CASE kImmediateClose:
                session.Close()
            CASE kGracefulShutdown:
                session.GracefulShutdown(/*timeout_ms=*/5000)
            CASE kNotifyOnly:
                // 不主动关闭,由上层处理

        IF session_evicted_handler_:
            session_evicted_handler_(session.GetConvId(), reason)

    PRIVATE FUNCTION WireSessionEvents(session: std::shared_ptr<Session>) -> void:
        // 将Session的错误/关闭事件连接到Server的驱逐逻辑
        session.OnError([this, conv = session.GetConvId()](SessionError e):
            IF e == SessionError::kRemoteClose:
                RemoveSession(conv, EvictReason::kRemoteClosed)
            ELSE:
                RemoveSession(conv, EvictReason::kError)
        )

    PRIVATE FUNCTION ExtractRoutingKey(
            data: const uint8_t*, len: size_t
    ) -> std::optional<uint32_t>:
        // 从协议头固定偏移提取会话标识
        // KCP: conv 位于偏移0, 4字节大端
        // 其他协议可能有不同偏移或更复杂的提取逻辑
        IF len < 4: RETURN std::nullopt
        RETURN ReadBigEndianU32(data, 0)

    // -------------------- 成员变量 --------------------
    PRIVATE MEMBER event_loop_: EventLoop*
    PRIVATE MEMBER config_: Config
    PRIVATE MEMBER state_: ServerState = kStopped
    PRIVATE MEMBER socket_: DatagramSocket
    PRIVATE MEMBER sessions_: SessionMap
    PRIVATE MEMBER new_session_handler_: NewSessionHandler
    PRIVATE MEMBER session_evicted_handler_: SessionEvictedHandler
    PRIVATE MEMBER health_timer_: TimerHandle
    PRIVATE MEMBER recv_buf_: std::vector<uint8_t>(65536)  // 可配置大小
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

    // 流程:
    // 1. Socket收到数据报
    raw_datagram = socket_.RecvFrom()

    // 2. 提取路由键 (协议头中的会话标识)
    routing_key = ExtractRoutingKey(raw_datagram)

    // 3. 路由决策:
    //    HIT  → 已有会话 → FeedInput(正常数据路径)
    //    MISS → 新会话   → CreateSession + Start + FeedInput
    //
    // 注意: 由于数据报没有"握手"步骤,
    // 需要在应用层/协议层处理:
    //   a. conv冲突: 不同来源使用相同conv → 会话表应使用 (conv, sender) 复合键
    //      或由服务端在首次响应中分配新conv (conv映射)
    //   b. 防御伪造: 可在应用层添加cookie/token验证环节

    // 改进方案: 复合键会话表
    // SESSION_KEY = std::tuple<conv, sender_ip, sender_port>
    // 或: 服务端分配不透明token → 客户端后续包携带token
```

---

## 3. 定时任务

```
// ============================================================
// 描述: 服务端周期任务
// ============================================================

// --------------------------------------------------
// 3.1 驱动所有Session的协议状态机
// --------------------------------------------------
FUNCTION DriveAllSessions(server: Server, now_ms: uint64_t):
    FOR EACH (conv, session) IN server.sessions_:
        session.Update(now_ms)
    // 此调用可集成到EventLoop的定时器中,与健康检测同一周期执行

// --------------------------------------------------
// 3.2 会话驱逐策略对比
// --------------------------------------------------
FUNCTION EvictionPolicyComparison(session, policy: EvictionPolicy):
    SWITCH policy:
        CASE kImmediateClose:
            // 最快回收资源,但对端可能不知道连接已断开
            session.Close()
            // 对端只能在下次通信时发现 (收包被忽略或ICMP拒绝)

        CASE kGracefulShutdown:
            // 最友好的方式: 先发送CLOSE通知,等待对端ACK
            // 缺点: 需要额外状态追踪和超时处理
            session.GracefulShutdown(timeout_ms=5000)

        CASE kNotifyOnly:
            // 最灵活: 应用层可定制驱逐行为
            // 例如: 应用层可能想先保存状态,再手动关闭
            app_callback(session)

// --------------------------------------------------
// 3.3 探活机制
// --------------------------------------------------
FUNCTION SendProbe(session: std::shared_ptr<Session>):
    // 向空闲Session发送协议层探活包
    // 以KCP为例: 发送WASK (窗口探测) 命令字包
    // 对端收到后会回复WINS,即完成一次心跳往返
    // 许多协议引擎内置了探活支持,只需触发即可
    session.SendProbePacket()
```

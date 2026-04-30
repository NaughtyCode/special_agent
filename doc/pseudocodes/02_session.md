# Session — 传输协议层核心伪代码

`Session` 是整个网络库的核心协议抽象，封装底层传输协议引擎，管理连接生命周期、数据收发和可靠性保证。接口设计为协议无关，便于替换为任意可靠传输协议实现。

---

## 1. Session 完整伪代码

```
// ============================================================
// 类名: Session
// 描述: 传输协议会话抽象 (协议无关接口)
//       继承 std::enable_shared_from_this<Session>,使Session可
//       在回调/异步闭包中安全持有自身引用
// ============================================================
CLASS Session : PUBLIC std::enable_shared_from_this<Session>:
    // -------------------- 类型别名 --------------------
    USING MessageCallback     = std::move_only_function<void(std::unique_ptr<Message>)>
    USING ErrorCallback       = std::move_only_function<void(SessionError)>
    USING StateChangeCallback = std::move_only_function<void(SessionState, SessionState)>
    USING SendCompleteCallback = std::move_only_function<void(uint32_t message_id)>

    // -------------------- 枚举类型 --------------------
    ENUM SessionState:
        kIdle      = 0    // 初始空闲,尚未Start
        kConnected = 1    // 已连接,可收发数据
        kClosing   = 2    // 正在优雅关闭
        kClosed    = 3    // 已关闭,终态

    ENUM SessionError:
        kProtocolError    // 协议引擎解析/状态异常
        kSocketError      // 底层Socket错误
        kTimeout          // 连接超时
        kBufferOverflow   // 接收缓冲区溢出
        kRemoteClose      // 对端主动发送关闭通知
        kLocalClose       // 本地主动关闭

    ENUM SendResult:
        kQueued  = 0      // 数据已加入发送队列
        kBlocked = 1      // 状态不允许发送(未连接/已关闭)或发送窗口满

    ENUM ConnectionHealth:
        kHealthy = 0      // 正常通信中
        kIdle    = 1      // 空闲 (无数据交互但未达到超时)
        kStale   = 2      // 过期 (超过超时阈值)

    ENUM ProtocolProfile:
        kFastMode       // 低延迟优先 (实时游戏/VoIP/即时交互)
        kReliableMode   // 可靠性优先 (文件传输/数据同步)
        kBalancedMode   // 平衡模式 (通用RPC/消息推送)
        kCustom         // 用户逐参数自定义

    // -------------------- 配置结构 --------------------
    STRUCT Config:
        // 协议预设 (选择预设后自动填充下列4项,也可在kCustom下逐项设置)
        profile: ProtocolProfile = ProtocolProfile::kFastMode
        nodelay: int = 1                 // 0=普通模式(RTO翻倍), 1=快速模式(RTO×1.5)
        update_interval_ms: int = 10     // 协议内部时钟周期(ms)
        fast_resend_threshold: int = 2   // 快速重传触发阈值(ACK跳过次数)
        flow_control_enabled: bool = false  // 是否启用拥塞流控
        // 以下字段对所有Profile生效,可独立覆盖:
        mtu_bytes: int = 1400            // 最大传输单元(字节)
        send_window_packets: int = 128   // 发送窗口(包数)
        recv_window_packets: int = 128   // 接收窗口(包数)
        rx_buffer_init_bytes: size_t = 64*1024  // 接收缓冲初始大小
        tx_buffer_init_bytes: size_t = 64*1024  // 发送缓冲初始大小
        enable_metrics: bool = true      // 是否启用运行时统计

        // 工厂方法: 从Profile预设生成配置,mtu/窗口/缓冲使用默认值
        STATIC FUNCTION FromProfile(profile: ProtocolProfile) -> Config:
            config = Config{}
            config.profile = profile
            SWITCH profile:
                CASE kFastMode:
                    config.nodelay = 1
                    config.update_interval_ms = 10
                    config.fast_resend_threshold = 2
                    config.flow_control_enabled = false
                CASE kReliableMode:
                    config.nodelay = 0
                    config.update_interval_ms = 100
                    config.fast_resend_threshold = 0
                    config.flow_control_enabled = true
                CASE kBalancedMode:
                    config.nodelay = 1
                    config.update_interval_ms = 20
                    config.fast_resend_threshold = 2
                    config.flow_control_enabled = true
                CASE kCustom:
                    // 由用户手动设置各字段
            RETURN config

    // -------------------- 构造与析构 --------------------
    CONSTRUCTOR Session(
            conv: uint32_t,
            event_loop: EventLoop*,
            socket: DatagramSocket*,
            remote_addr: DatagramSocket::Address,
            config: Config = Config::FromProfile(kFastMode)
    ):
        conv_            = conv
        event_loop_      = event_loop
        socket_          = socket
        remote_addr_     = std::move(remote_addr)
        config_          = config
        last_recv_time_ms_ = Clock::NowMs()
        recv_buffer_.resize(config_.rx_buffer_init_bytes)

        // 创建协议引擎 (可注入: KCP / 自定义 / Mock)
        engine_ = ProtocolEngineFactory::Create(config_)

        // 注册引擎输出回调: 引擎产生的底层数据包 → Socket发出
        engine_.SetOutputCallback([this](const uint8_t* buf, size_t len):
            socket_.SendTo(buf, len, remote_addr_)
        )

        engine_.ApplyConfig(config_)

    DESTRUCTOR ~Session():
        // 取消未完成的shutdown定时器
        IF shutdown_timer_.IsValid():
            event_loop_.CancelTimer(shutdown_timer_)
        // 如启用统计,在析构前将最终快照写入MetricsSink
        IF config_.enable_metrics AND stats_.total_packets_recv > 0:
            FlushStats()

    // 禁止拷贝,允许移动
    Session(const Session&) = delete
    Session& operator=(const Session&) = delete
    Session(Session&&) = default
    Session& operator=(Session&&) = default

    // -------------------- 生命周期 --------------------

    FUNCTION Start() -> void:
        IF state_ != kIdle: RETURN
        TransitionState(kConnected)

    // 立即关闭: 通知对端 + 清空缓冲区 + 进入终态
    FUNCTION Close() -> void:
        IF state_ == kClosed: RETURN
        CancelShutdownTimer()
        TransitionState(kClosed)
        engine_.NotifyClose()
        engine_.ResetBuffers()

    // 优雅关闭: 通知对端 → 等待ACK确认 → 超时后强制Close
    FUNCTION GracefulShutdown(timeout_ms: uint32_t = 5000) -> void:
        IF state_ != kConnected: RETURN
        TransitionState(kClosing)
        engine_.SendShutdownNotification()
        shutdown_timer_ = event_loop_.AddTimer(timeout_ms, [this]():
            IF state_ == kClosing:
                Close()
        )

    // -------------------- 数据发送 --------------------

    FUNCTION Send(data: const std::vector<uint8_t>&) -> SendResult:
        RETURN Send(data.data(), data.size())

    FUNCTION Send(data: const uint8_t*, len: size_t) -> SendResult:
        IF state_ != kConnected:
            RETURN SendResult::kBlocked
        result = engine_.Send(data, len)
        IF result == SendResult::kQueued:
            stats_.total_bytes_sent += len
            stats_.total_messages_sent += 1
        RETURN result

    // 发送协议层握手包 (由Client在连接初始化时调用)
    FUNCTION SendHandshakePacket() -> void:
        engine_.SendHandshake()

    // 发送协议层探活包 (由Server在空闲检测时调用)
    FUNCTION SendProbePacket() -> void:
        engine_.SendProbe()

    // -------------------- 数据接收 --------------------

    FUNCTION FeedInput(data: const uint8_t*, len: size_t) -> void:
        IF state_ == kClosed: RETURN
        last_recv_time_ms_ = Clock::NowMs()
        stats_.total_packets_recv += 1
        stats_.total_bytes_recv += len

        parse_result = engine_.Input(data, len)
        IF parse_result.HasError():
            NotifyError(parse_result.error)
            RETURN

        // 引擎Input后可能已有完整用户消息就绪 → 尝试取出
        TryRecv()

    // -------------------- 定时驱动 --------------------

    FUNCTION Update(now_ms: uint64_t) -> void:
        IF state_ == kClosed: RETURN
        engine_.Update(now_ms)
        // 引擎Update自动通过OutputCallback输出: 新数据/重传/ACK/探活/WINS等

    // -------------------- 回调注册 --------------------

    FUNCTION OnMessage(cb: MessageCallback) -> void:
        message_callback_ = std::move(cb)

    FUNCTION OnError(cb: ErrorCallback) -> void:
        error_callback_ = std::move(cb)

    FUNCTION OnStateChange(cb: StateChangeCallback) -> void:
        state_change_callback_ = std::move(cb)

    FUNCTION OnSendComplete(cb: SendCompleteCallback) -> void:
        send_complete_callback_ = std::move(cb)

    // -------------------- 状态与统计查询 --------------------

    FUNCTION GetConvId() -> uint32_t:
        RETURN conv_

    FUNCTION GetState() -> SessionState:
        RETURN state_

    FUNCTION GetLastRecvTime() -> uint64_t:
        RETURN last_recv_time_ms_

    FUNCTION GetRemoteAddress() -> DatagramSocket::Address:
        RETURN remote_addr_

    FUNCTION EvaluateHealth(
            now_ms: uint64_t,
            idle_threshold_ms: uint32_t = 15000,
            stale_threshold_ms: uint32_t = 30000
    ) -> ConnectionHealth:
        elapsed = now_ms - last_recv_time_ms_
        IF elapsed >= stale_threshold_ms:
            RETURN ConnectionHealth::kStale
        IF elapsed >= idle_threshold_ms:
            RETURN ConnectionHealth::kIdle
        RETURN ConnectionHealth::kHealthy

    FUNCTION GetStats() -> SessionStats:
        RETURN stats_

    // 运行时更新配置 (仅允许在kIdle状态调用以确保安全)
    FUNCTION ApplyConfig(config: Config) -> void:
        IF state_ != kIdle: RETURN
        config_ = config
        engine_.ApplyConfig(config_)

    // -------------------- 私有 --------------------

    PRIVATE:
        FUNCTION TransitionState(new_state: SessionState) -> void:
            old = state_
            state_ = new_state
            IF state_change_callback_:
                state_change_callback_(old, new_state)

        FUNCTION TryRecv() -> void:
            // 循环取出引擎中所有已就绪的完整用户消息
            WHILE true:
                peek_size = engine_.PeekMessageSize()
                IF peek_size <= 0: BREAK
                recv_buffer_.resize(MAX(recv_buffer_.size(), size_t(peek_size)))
                recv_len = engine_.RecvMessage(recv_buffer_.data(), peek_size)
                IF recv_len > 0:
                    stats_.total_messages_recv += 1
                    IF message_callback_:
                        msg = std::make_unique<Message>(
                            recv_buffer_.data(), size_t(recv_len), conv_)
                        message_callback_(std::move(msg))
                ELSE IF recv_len == 0:
                    BREAK
                ELSE:
                    NotifyError(SessionError::kProtocolError)
                    BREAK

        FUNCTION NotifyError(error: SessionError) -> void:
            IF error_callback_: error_callback_(error)

        FUNCTION CancelShutdownTimer() -> void:
            IF shutdown_timer_.IsValid():
                event_loop_.CancelTimer(shutdown_timer_)
                shutdown_timer_ = TimerHandle::Invalid()

        FUNCTION FlushStats() -> void:
            MetricsSink::Write("session", conv_, stats_)
            // ...

    PRIVATE MEMBER engine_: std::unique_ptr<ProtocolEngine>
    PRIVATE MEMBER conv_: uint32_t
    PRIVATE MEMBER state_: SessionState = kIdle
    PRIVATE MEMBER message_callback_: MessageCallback
    PRIVATE MEMBER error_callback_: ErrorCallback
    PRIVATE MEMBER state_change_callback_: StateChangeCallback
    PRIVATE MEMBER send_complete_callback_: SendCompleteCallback
    PRIVATE MEMBER socket_: DatagramSocket*
    PRIVATE MEMBER remote_addr_: DatagramSocket::Address
    PRIVATE MEMBER last_recv_time_ms_: uint64_t
    PRIVATE MEMBER event_loop_: EventLoop*
    PRIVATE MEMBER config_: Config
    PRIVATE MEMBER stats_: SessionStats
    PRIVATE MEMBER recv_buffer_: std::vector<uint8_t>
    PRIVATE MEMBER shutdown_timer_: TimerHandle
```

---

## 2. 协议数据包处理流程 (协议无关)

```
// ============================================================
// 描述: 协议引擎层数据包处理流转
// ============================================================

// --------------------------------------------------
// 2.1 发送管线: 用户消息 → 分段 → 网络
// --------------------------------------------------
FUNCTION SendPipeline(session: Session, user_data: span<const uint8_t>):
    // 步骤1: Session.Send() → 状态检查 → Engine.Send()
    // 步骤2: Engine将用户数据拷贝到内部发送缓冲区
    // 步骤3: Engine根据MTU将数据切分为传输单元 (segment/frame)
    //   每个单元 = [协议头(变长)] + [用户数据分片]
    //   以KCP为例: 头部24字节 =
    //     conv(4) + cmd(1) + frag(1) + wnd(2) +
    //     ts(4) + sn(4) + una(4) + len(4)
    // 步骤4: 分段加入发送队列
    // 步骤5: Update()时:
    //   a. 检查发送窗口 → 窗口内分段通过OutputCallback输出
    //   b. 记录每分段的sn和发送时间 (用于后续重传判定)
    // 步骤6: OutputCallback → Socket.SendTo

// --------------------------------------------------
// 2.2 接收管线: 网络 → 重组 → 用户消息
// --------------------------------------------------
FUNCTION RecvPipeline(session: Session, raw_datagram: span<const uint8_t>):
    // 步骤1: EventLoop → Socket.RecvFrom → Session.FeedInput
    // 步骤2: FeedInput → Engine.Input(raw_datagram)
    //   Engine解析协议头,根据命令字(cmd)路由:
    //     DATA   → 按sn插入接收缓冲,检查是否可组装完整消息
    //     ACK    → 标记对应sn已确认送达,更新发送窗口,检查快速重传
    //     PROBE  → 回复探测响应(WINS)
    //     CLOSE  → 触发远程关闭通知 → NotifyError(kRemoteClose)
    //   处理UNA: 累积确认 → 连续小于UNA的sn全部标记为已确认
    // 步骤3: FeedInput → TryRecv() → Engine.RecvMessage()
    //   检查接收缓冲是否按序排列出一条完整用户消息
    //   如有 → 组装返回 → 触发OnMessage回调

// --------------------------------------------------
// 2.3 协议头解析 (以KCP为例,Engine可替换)
// --------------------------------------------------
FUNCTION ParseHeader(data: span<const uint8_t>) -> std::optional<Header>:
    MIN_HEADER_SIZE = 24  // 此值由协议引擎类型决定,此处以KCP为例
    IF data.size() < MIN_HEADER_SIZE:
        RETURN std::nullopt

    RETURN Header{
        .conv     = ReadBigEndianU32(data, 0),   // 会话标识
        .cmd      = data[4],                     // 命令字
        .frag_id  = data[5],                     // 分片标识
        .recv_wnd = ReadBigEndianU16(data, 6),   // 对端窗口通告
        .ts       = ReadBigEndianU32(data, 8),   // 发送方时间戳
        .sn       = ReadBigEndianU32(data, 12),  // 序列号
        .una      = ReadBigEndianU32(data, 16),  // 累积确认号
        .len      = ReadBigEndianU32(data, 20)   // 有效载荷长度
    }
```

---

## 3. Session 生命周期状态机

```
// ============================================================
// 描述: Session 状态转移图 (含优雅关闭路径)
// ============================================================

//                    Start()       ┌───────────┐
//    ┌─────────┐ ───────────────▶  │ kConnected │
//    │  kIdle   │                  └─────┬─────┘
//    └────┬────┘                        │
//         │                    GracefulShutdown()
//         │                   ┌───────▼────────┐
//         │                   │   kClosing      │
//         │                   └───┬───┬─────────┘
//         │          Close()      │   │ Close() (超时)
//         │                       │   │
//         ▼                       ▼   ▼
//    ┌──────────────────────────────────┐
//    │            kClosed (终态)          │
//    └──────────────────────────────────┘

FUNCTION SessionLifecycleDescription(session: Session):
    // kIdle → kConnected: Start()被调用,激活会话
    // kIdle → kClosed:   未启动即关闭 (如Client构造后因错误放弃)
    //
    // kConnected (主工作状态):
    //   允许: Send / FeedInput / Update / TryRecv
    //   → GracefulShutdown() → kClosing
    //   → Close() → kClosed
    //   → 远程关闭通知 / 外部驱逐 → Close() → kClosed
    //
    // kClosing (过渡状态):
    //   允许: FeedInput(接收ACK), Update(发送ACK)
    //   禁止: Send(拒绝新数据)
    //   → 收到对端关闭ACK → Close() → kClosed
    //   → GracefulShutdown超时 → Close() → kClosed
    //
    // kClosed (终态):
    //   所有操作冪等返回/忽略
    //   等待析构释放引擎和缓冲区资源
    //   统计快照可在此阶段读取
```

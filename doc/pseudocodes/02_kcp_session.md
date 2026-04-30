# Session — 传输协议层核心伪代码

`Session` 是整个网络库的核心协议抽象，封装底层传输协议实例，管理连接生命周期、数据收发和可靠性保证。虽以KCP为主要实现，但接口设计为协议无关，便于替换为其他可靠传输协议。

---

## 1. Session 完整伪代码

```
// ============================================================
// 类名: Session
// 描述: 传输协议会话抽象 (协议无关接口)
//       继承 std::enable_shared_from_this,使Session可在
//       回调/异步闭包中安全持有自身引用
// ============================================================
CLASS Session : PUBLIC std::enable_shared_from_this<Session>:
    // -------------------- 类型别名 --------------------
    // 消息回调: 协议层组装出完整用户消息时触发
    USING MessageCallback   = std::move_only_function<void(std::unique_ptr<Message>)>
    // 错误回调: 协议层发生不可恢复错误时触发
    USING ErrorCallback     = std::move_only_function<void(SessionError)>
    // 状态变更回调: 会话状态变化时触发 (可用于连接/断开通知)
    USING StateChangeCallback = std::move_only_function<void(SessionState, SessionState)>

    // -------------------- 枚举类型 --------------------
    ENUM SessionState:
        kIdle      = 0    // 初始空闲,尚未Start
        kConnected = 1    // 已连接,数据可收发
        kClosing   = 2    // 正在执行优雅关闭
        kClosed    = 3    // 已关闭

    ENUM SessionError:
        kProtocolError    // 协议层解析/状态异常
        kSocketError      // 底层Socket错误
        kTimeout          // 连接超时
        kBufferOverflow   // 接收缓冲区溢出
        kRemoteClose      // 对端主动关闭
        kLocalClose       // 本地主动关闭

    ENUM SendResult:
        kQueued  = 0      // 数据已加入发送队列
        kBlocked = 1      // 发送窗口满,需等待

    ENUM ConnectionHealth:
        kHealthy = 0      // 正常通信
        kIdle    = 1      // 空闲 (无数据交换,但未超时)
        kStale   = 2      // 过期 (超过超时阈值)

    // -------------------- 配置结构 --------------------
    STRUCT Config:
        // 协议预设Profile (快速设置)
        profile: ProtocolProfile = ProtocolProfile::kFastMode
        // 或逐项覆盖 (kCustom模式下生效)
        nodelay: int = 1                 // 0=普通模式, 1=快速模式
        update_interval_ms: int = 10     // 协议内部时钟周期
        fast_resend_threshold: int = 2   // 快速重传触发阈值
        flow_control_enabled: bool = false  // 是否启用流控
        mtu_bytes: int = 1400            // 最大传输单元
        send_window_packets: int = 128   // 发送窗口(包数)
        recv_window_packets: int = 128   // 接收窗口(包数)
        rx_buffer_init_bytes: size_t = 64*1024  // 接收缓冲初始大小
        tx_buffer_init_bytes: size_t = 64*1024  // 发送缓冲初始大小

        // 从预设Profile获取默认配置
        STATIC FUNCTION FromProfile(profile: ProtocolProfile) -> Config:
            SWITCH profile:
                CASE kFastMode:
                    RETURN Config{
                        .nodelay = 1, .update_interval_ms = 10,
                        .fast_resend_threshold = 2, .flow_control_enabled = false
                    }
                CASE kReliableMode:
                    RETURN Config{
                        .nodelay = 0, .update_interval_ms = 100,
                        .fast_resend_threshold = 0, .flow_control_enabled = true
                    }
                CASE kBalancedMode:
                    RETURN Config{
                        .nodelay = 1, .update_interval_ms = 20,
                        .fast_resend_threshold = 2, .flow_control_enabled = true
                    }

    ENUM ProtocolProfile:
        kFastMode       // 低延迟优先 (游戏/VoIP)
        kReliableMode   // 可靠性优先 (文件传输)
        kBalancedMode   // 平衡模式 (通用场景)
        kCustom         // 用户逐参数自定义

    // -------------------- 成员变量 --------------------
    PRIVATE MEMBER engine_: std::unique_ptr<ProtocolEngine> // 协议引擎 (Pimpl,可替换)
    PRIVATE MEMBER conv_: uint32_t                          // 会话ID
    PRIVATE MEMBER state_: SessionState = kIdle             // 当前状态
    PRIVATE MEMBER message_callback_: MessageCallback        // 消息回调
    PRIVATE MEMBER error_callback_: ErrorCallback            // 错误回调
    PRIVATE MEMBER state_change_callback_: StateChangeCallback // 状态变更回调
    PRIVATE MEMBER socket_: DatagramSocket*                  // 绑定Socket
    PRIVATE MEMBER remote_addr_: DatagramSocket::Address     // 远端地址
    PRIVATE MEMBER last_recv_time_ms_: uint64_t              // 最后收包时间
    PRIVATE MEMBER event_loop_: EventLoop*                   // 绑定EventLoop
    PRIVATE MEMBER config_: Config                           // 会话配置
    PRIVATE MEMBER stats_: SessionStats                      // 运行时统计

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

        // 创建协议引擎 (以KCP为例,可替换为其他实现)
        engine_ = CreateProtocolEngine(config)
        // 引擎创建时可指定: KCP / 自定义协议 / Mock (测试用)

        // 将Session自身注入引擎的输出回调
        engine_.SetOutputCallback([this](const uint8_t* buf, size_t len):
            // 引擎产生待发送的底层数据包 → 经Socket发出
            socket_.SendTo(buf, len, remote_addr_)
        )

        // 应用配置参数到引擎
        engine_.ApplyConfig(config)

    DESTRUCTOR ~Session():
        // 协议引擎的释放由unique_ptr自动完成
        // 如需统计上报,可在此处Flush
        IF stats_.total_packets_recv > 0:
            // 将最终统计写入MetricsSink (如果启用)
            FlushStats()

    // 禁止拷贝,运行移动
    Session(const Session&) = delete
    Session& operator=(const Session&) = delete
    Session(Session&&) = default
    Session& operator=(Session&&) = default

    // -------------------- 生命周期管理 --------------------

    FUNCTION Start() -> void:
        IF state_ != kIdle:
            RETURN
        TransitionState(kConnected)
        last_recv_time_ms_ = Clock::NowMs()

    // 普通关闭: 立即终止
    FUNCTION Close() -> void:
        IF state_ == kClosed:
            RETURN
        TransitionState(kClosed)
        // 通知对端 (通过引擎的关闭通知机制)
        engine_.NotifyClose()
        engine_.ResetBuffers()

    // 优雅关闭: 先发送FIN通知,等待对端确认后再关闭
    FUNCTION GracefulShutdown(timeout_ms: uint32_t = 5000) -> void:
        IF state_ != kConnected:
            RETURN
        old_state = kConnected
        TransitionState(kClosing)
        // 发送优雅关闭请求
        engine_.SendShutdownNotification()
        // 启动超时定时器,超时后强制Close
        shutdown_timer_ = event_loop_.AddTimer(timeout_ms, [this]():
            IF state_ == kClosing:
                Close()
        )

    // -------------------- 数据发送 --------------------

    FUNCTION Send(data: const std::vector<uint8_t>&) -> SendResult:
        IF state_ != kConnected:
            RETURN SendResult::kBlocked
        stats_.total_bytes_sent += data.size()
        stats_.total_messages_sent += 1
        RETURN engine_.Send(data.data(), data.size())

    FUNCTION Send(data: const uint8_t*, len: size_t) -> SendResult:
        IF state_ != kConnected:
            RETURN SendResult::kBlocked
        stats_.total_bytes_sent += len
        stats_.total_messages_sent += 1
        RETURN engine_.Send(data, len)

    // -------------------- 数据接收输入 --------------------

    FUNCTION FeedInput(data: const uint8_t*, len: size_t) -> void:
        IF state_ == kClosed:
            RETURN
        last_recv_time_ms_ = Clock::NowMs()
        stats_.total_packets_recv += 1
        stats_.total_bytes_recv += len

        // 将数据报输入协议引擎进行解析
        parse_result = engine_.Input(data, len)
        IF parse_result.HasError():
            NotifyError(parse_result.error)
            RETURN

        // 尝试从引擎取出完整用户消息
        TryRecv()

    // -------------------- 定时驱动 --------------------

    FUNCTION Update(now_ms: uint64_t) -> void:
        IF state_ == kClosed:
            RETURN
        engine_.Update(now_ms)
        // 引擎Update内部会自动通过OutputCallback输出待发送数据包
        // (包括新数据、重传数据、ACK等)

    // -------------------- 回调注册 --------------------

    FUNCTION OnMessage(cb: MessageCallback) -> void:
        message_callback_ = std::move(cb)

    FUNCTION OnError(cb: ErrorCallback) -> void:
        error_callback_ = std::move(cb)

    FUNCTION OnStateChange(cb: StateChangeCallback) -> void:
        state_change_callback_ = std::move(cb)

    // -------------------- 状态与统计查询 --------------------

    FUNCTION GetConvId() -> uint32_t:
        RETURN conv_

    FUNCTION GetState() -> SessionState:
        RETURN state_

    FUNCTION GetLastRecvTime() -> uint64_t:
        RETURN last_recv_time_ms_

    FUNCTION EvaluateHealth(now_ms: uint64_t,
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

    // -------------------- 私有方法 --------------------

    PRIVATE:
        FUNCTION TransitionState(new_state: SessionState) -> void:
            old_state = state_
            state_ = new_state
            IF state_change_callback_:
                state_change_callback_(old_state, new_state)

        FUNCTION TryRecv() -> void:
            // 循环从引擎中取出所有已就绪的完整用户消息
            WHILE true:
                peek_size = engine_.PeekMessageSize()
                IF peek_size <= 0:
                    BREAK
                // 使用可复用缓冲区 (避免每消息分配)
                recv_buffer_.resize(peek_size)
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
            IF error_callback_:
                error_callback_(error)

        FUNCTION FlushStats() -> void:
            // 将stats_提交到全局MetricsSink
            ...

        MEMBER recv_buffer_: std::vector<uint8_t>  // 可复用接收缓冲
```

---

## 2. 协议数据包处理流程

```
// ============================================================
// 描述: 协议层数据包处理流转 (协议无关描述)
// ============================================================

// --------------------------------------------------
// 2.1 发送管线: 用户消息 → 分段 → 网络包
// --------------------------------------------------
FUNCTION SendPipeline(session: Session, user_data: span<const uint8_t>):
    // 步骤1: 应用层调用 Send → 引擎 Send
    result = session.Send(user_data)

    // 步骤2: 引擎内部处理
    //   a. 将用户数据写入发送缓冲区
    //   b. 根据MTU将数据切分为传输单元 (segment/frame)
    //     每个传输单元 = [协议头(变长)] + [用户数据分片]
    //     以KCP为例: 协议头24字节 +
    //       conv(4) + cmd(1) + frag(1) + wnd(2) +
    //       ts(4) + sn(4) + una(4) + len(4)

    // 步骤3: 在下一次Update()调用时
    //   a. 检查发送窗口可用空间
    //   b. 将窗口内的传输单元通过OutputCallback输出
    //   c. 为每个发出的传输单元记录序列号和发送时间 (用于重传判定)

    // 步骤4: OutputCallback → Socket.SendTo → 网络

// --------------------------------------------------
// 2.2 接收管线: 网络包 → 重组 → 用户消息
// --------------------------------------------------
FUNCTION RecvPipeline(session: Session, raw_packet: span<const uint8_t>):
    // 步骤1: EventLoop通知 → Socket.RecvFrom → Session.FeedInput
    session.FeedInput(raw_packet.data(), raw_packet.size())

    // 步骤2: FeedInput → 引擎 Input
    //   引擎解析协议头,根据命令字路由:
    //     DATA包 → 插入接收缓冲区,按序列号排序
    //     ACK包  → 确认已送达的发送单元,更新发送窗口
    //     PING包 → 回复PONG (探活机制)
    //     CLOSE包→ 触发远程关闭通知
    //   处理UNA信息: 更新已确认的连续序列号

    // 步骤3: FeedInput → TryRecv → 引擎 RecvMessage
    //   检查接收缓冲区是否有按序排列的完整用户消息
    //   如有: 组装返回,触发MessageCallback

// --------------------------------------------------
// 2.3 协议头解析 (以KCP为例,可替换)
// --------------------------------------------------
FUNCTION ParseProtocolHeader(data: span<const uint8_t>) -> std::optional<Header>:
    MIN_HEADER_SIZE = 24  // KCP最小头部; 其他协议可能有不同值

    IF data.size() < MIN_HEADER_SIZE:
        RETURN std::nullopt

    header = Header{
        .conv     = ReadBigEndianU32(data, 0),   // 会话标识
        .cmd      = data[4],                     // 命令字
        .frag_id   = data[5],                     // 分片标识
        .recv_wnd  = ReadBigEndianU16(data, 6),   // 接收窗口通告
        .timestamp = ReadBigEndianU32(data, 8),   // 发送方时间戳
        .seq_num   = ReadBigEndianU32(data, 12),  // 序列号
        .una       = ReadBigEndianU32(data, 16),  // 累积确认号
        .payload_len = ReadBigEndianU32(data, 20) // 有效载荷长度
    }
    RETURN header
```

---

## 3. Session 生命周期状态机

```
// ============================================================
// 描述: Session 状态转移图 (含优雅关闭路径)
// ============================================================

// 状态转移:
//
//                  Start()        ┌───────────┐
//    ┌─────────┐ ───────────────▶ │ kConnected │
//    │  kIdle   │                 └─────┬─────┘
//    └─────────┘                       │
//         │                  GracefulShutdown()
//         │                 ┌───────▼────────┐  timeout/ack ┌────────┐
//         │                 │   kClosing      │─────────────▶│kClosed │
//         │                 └───────┬────────┘               └────────┘
//         │                         │ Close()
//         │        Close()          ▼
//         └─────────────────▶ ┌────────┐
//                             │kClosed │
//                             └────────┘

FUNCTION SessionLifecycleDescription(session: Session):
    // kIdle: 初始创建,尚未激活
    //   → Start() → kConnected
    //   → Close() → kClosed (可以直接销毁未启动的Session)

    // kConnected: 正常工作状态
    //   可执行: Send / FeedInput / Update / TryRecv
    //   → GracefulShutdown() → kClosing
    //   → Close() → kClosed
    //   → 外部触发 (超时/错误) → kClosed

    // kClosing: 优雅关闭中
    //   可执行: FeedInput (接收最后的ACK/数据)
    //   可执行: Update (发送最后的ACK)
    //   不可执行: Send (拒绝新数据)
    //   → 收到对端ACK确认 / 超时 → Close() → kClosed

    // kClosed: 终态
    //   所有操作冪等返回/忽略
    //   等待析构释放引擎资源
    //   统计信息可在此阶段读取
```

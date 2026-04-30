# 架构总览 — 通用可配置KCP网络库

## 1. 设计目标

构建一个 **易用、高性能、跨平台、支持CS与P2P架构** 的网络库，以KCP协议为核心可替换传输层，提供低延迟、高可靠的传输能力，同时通过参数化配置适配从实时游戏到IoT数据上报等多种场景。

## 2. 分层架构 (可替换层次设计)

```
┌──────────────────────────────────────────────────────────────┐
│               User Application Layer (应用层)                  │
│   任意业务逻辑: 消息编解码、连接编排、自定义协议扩展              │
├──────────────────────────────────────────────────────────────┤
│              Abstraction Layer (抽象层)                        │
│   Server / Client / Peer (角色无关的端点抽象)                   │
│   SessionManager (会话生命周期管理器, 支持自定义驱逐策略)         │
│   ConnectionPool (连接池, 支持多路复用)                          │
├──────────────────────────────────────────────────────────────┤
│             Transport Protocol Layer (传输协议层)               │
│   Session (协议会话抽象, 可替换为KCP/TCP/QUIC等)                 │
│     - 生命周期管理 (Start / Close / GracefulShutdown)          │
│     - 数据收发 (Send / FeedInput / TryRecv)                    │
│     - 状态驱动 (Update)                                       │
│     - 回调管理 (OutputCallback / MessageCallback / ErrorCallback)│
│     - 统计收集 (Statistics)                                    │
├──────────────────────────────────────────────────────────────┤
│              Platform Layer (平台抽象层)                         │
│   EventLoop (epoll / IOCP / kqueue 统一抽象)                   │
│   ThreadScheduler (线程调度器, 支持多种分配策略)                 │
│   TimerService (定时器服务)                                    │
│   DatagramSocket (数据报Socket抽象, 支持UDP/UDPLite/RAW)        │
│   TaskQueue (无锁/有锁可配置任务队列)                            │
└──────────────────────────────────────────────────────────────┘
```

## 3. 数据流总览 (伪代码)

```
// ============================================================
// 文件名: architecture_overview.pseudo
// 描述: 整体数据流与控制流,所有参数均为可配置项
// ============================================================

// --------------------------------------------------
// 3.1 库初始化与全局配置
// --------------------------------------------------
FUNCTION LibraryInitialize(config: LibraryConfig):
    // 全局配置: 日志级别、内存分配器、平台选择策略等
    // 所有层级的默认参数均可在此统一指定,逐层覆盖
    LibraryConfig DEFAULT:
        .io_backend           = AUTO_DETECT         // 自动选择最优IO模型
        .default_mtu           = 1400               // 默认MTU,可按链路调整
        .default_send_window   = 128                // 默认发送窗口(包数)
        .default_recv_window   = 128                // 默认接收窗口(包数)
        .default_update_tick_ms = 10                // 默认驱动时钟周期
        .default_timeout_ms    = 30000              // 默认超时阈值
        .socket_rcvbuf_bytes   = 256 * 1024         // Socket接收缓冲
        .socket_sndbuf_bytes   = 256 * 1024         // Socket发送缓冲
        .max_worker_threads    = CPU_CORE_COUNT      // 最大工作线程数
        .enable_metrics        = true               // 是否启用指标收集

// --------------------------------------------------
// 3.2 服务端启动流程 (泛化)
// --------------------------------------------------
FUNCTION ServerStart(config: ServerConfig):
    // 步骤1: 创建事件循环 (IO后端可替换)
    event_loop = EventLoop::Create(config.io_backend)

    // 步骤2: 创建Server端点,绑定地址
    server = Server(event_loop, config.listen_address)
    server.SetSessionConfig(config.session_config)    // 注入会话级配置
    server.SetEvictionPolicy(config.eviction_policy)  // 注入驱逐策略

    // 步骤3: 注册事件处理器链 (责任链模式,可插拔)
    server.OnNewSession(FUNCTION(session):
        session.OnMessage(FUNCTION(msg):
            ApplicationLogic.ProcessMessage(msg)
        )
        session.OnError(FUNCTION(error):
            ApplicationLogic.HandleError(session, error)
        )
    )

    // 步骤4: 启动监听
    server.Start()

    // 步骤5: 进入事件循环
    event_loop.Run()

// --------------------------------------------------
// 3.3 客户端连接流程 (泛化)
// --------------------------------------------------
FUNCTION ClientConnect(config: ClientConfig):
    event_loop = EventLoop::Create(config.io_backend)

    client = Client(event_loop)
    client.SetSessionConfig(config.session_config)
    client.SetReconnectStrategy(ExponentialBackoff{
        .initial_delay_ms = 1000,
        .max_delay_ms     = 30000,
        .max_attempts     = 5,
        .backoff_factor   = 2.0
    })

    // Connect返回的是一个异步句柄,可在回调中获得Session
    client.Connect(config.remote_address,
        // 成功回调
        FUNCTION(session):
            session.OnMessage(FUNCTION(msg):
                ApplicationLogic.ProcessMessage(msg)
            )
        ,
        // 失败回调
        FUNCTION(error):
            ApplicationLogic.HandleConnectFailed(error)
    )

    event_loop.Run()

// --------------------------------------------------
// 3.4 数据发送流程 (应用层→网络) — 完整管线
// --------------------------------------------------
FUNCTION DataSendFlow(session, user_data):
    // 步骤1: 应用层调用 Send(user_data)
    // 步骤2: Session检查状态和流控窗口
    //    IF send_window_full: 返回 kPending / 加入发送等待队列
    // 步骤3: Session调用协议层 send(user_data)
    // 步骤4: 协议层根据MTU分段为传输单元 (segment/frame)
    // 步骤5: 分段加入发送队列,等待下次Update时发送
    // 步骤6: Update()驱动时:
    //    a. 检查发送窗口 → 将窗口内分段通过OutputCallback输出
    //    b. OutputCallback → Socket.SendTo(network)

    result = session.Send(user_data)
    IF result == SendResult::kQueued:
        // 数据已加入发送缓冲,等待协议层异步发送
        // 可通过 session.OnSendComplete() 注册发送完成回调
        pass
    ELSE IF result == SendResult::kBlocked:
        // 发送窗口满或缓冲区满,需等待
        // 应用层可选择: 丢弃 / 阻塞等待 / 加入应用层队列

// --------------------------------------------------
// 3.5 数据接收流程 (网络→应用层) — 完整管线
// --------------------------------------------------
FUNCTION DataReceiveFlow(session):
    // 步骤1: EventLoop监听到Socket可读事件
    // 步骤2: Socket读取原始数据报
    // 步骤3: 根据数据报头部的conv/cmd等字段路由到对应Session
    // 步骤4: Session将数据报输入协议层进行解析
    // 步骤5: 协议层内部处理: 头部解析→ACK处理→乱序缓存→按序重组
    // 步骤6: 如果有完整用户消息组装完毕:
    //    - 触发MessageCallback → 用户回调
    //    - 更新统计计数器 (bytes_recv, packets_recv, messages_recv)
    // 步骤7: 如果协议层有ACK需要发送:
    //    - 在下次Update时通过OutputCallback输出ACK包

    // 数据流路径汇总:
    // Socket.Read() → Session.FeedInput() → Protocol.Input()
    //   → [内部重组] → Session.TryRecv() → MessageCallback

// --------------------------------------------------
// 3.6 定时驱动流程 (协议状态机推进)
// --------------------------------------------------
FUNCTION TimerDriveFlow(event_loop, sessions):
    // 定时器以可配置的时钟周期 (默认与协议内部interval对齐) 触发
    // 每个时钟周期内,遍历所有活跃Session:
    //   session.Update(current_time)
    //   协议层Update内部处理:
    //     a. 检查发送队列中超时的分段 → 标记重传
    //     b. 检查快速重传条件 (重复ACK计数 >= 阈值)
    //     c. 将待发送分段(含重传)通过OutputCallback输出
    //     d. 更新RTO/RTT估算
    //     e. 更新拥塞/流控状态

    timer_id = event_loop.AddPeriodicTimer(
        config.update_tick_ms,
        FUNCTION():
            now = Clock::NowMs()
            FOR EACH session IN active_sessions:
                session.Update(now)
    )

// --------------------------------------------------
// 3.7 超时与连接健康管理
// --------------------------------------------------
FUNCTION ConnectionHealthCheck(server, config):
    // 周期性扫描所有会话,评估连接健康度:
    //   - Ice (空闲时间) = now - last_recv_time
    //   - 分级判定:
    //       Ice < warning_threshold   → HEALTHY  (正常)
    //       Ice >= warning_threshold  → IDLE     (空闲,可发送探活)
    //       Ice >= timeout_threshold  → STALE    (过期,触发清理)
    //
    // 可配置的清理动作:
    //   eviction_policy: { IMMEDIATE_CLOSE | GRACEFUL_SHUTDOWN | NOTIFY_ONLY }
    
    timer_id = event_loop.AddPeriodicTimer(
        config.health_check_interval_ms,
        FUNCTION():
            now = Clock::NowMs()
            FOR EACH (id, session) IN server.sessions_:
                health = session.EvaluateHealth(now)
                IF health == CONNECTION_HEALTH::kStale:
                    server.HandleStaleSession(session, config.eviction_policy)
                ELSE IF health == CONNECTION_HEALTH::kIdle:
                    server.HandleIdleSession(session, config.idle_policy)

// --------------------------------------------------
// 3.8 协议配置模式
// --------------------------------------------------
FUNCTION ConfigureProtocol(session, profile: ProtocolProfile):
    // 协议参数不再硬编码,而是通过预设Profile或自定义参数配置
    // 预定义Profile:
    ProtocolProfile FAST_MODE = {
        .nodelay       = 1,        // 快速模式
        .interval_ms   = 10,       // 内部时钟周期
        .fast_resend   = 2,        // 快速重传触发阈值
        .flow_control  = false     // 关闭流控
    }
    ProtocolProfile RELIABLE_MODE = {
        .nodelay       = 0,        // 普通模式
        .interval_ms   = 100,      // 大时钟周期,降低CPU开销
        .fast_resend   = 0,        // 禁用快速重传
        .flow_control  = true      // 启用流控,公平共享带宽
    }
    ProtocolProfile CUSTOM_MODE = {
        // 用户自定义,逐参数调整
        .nodelay       = user_config.nodelay,
        .interval_ms   = user_config.interval_ms,
        .fast_resend   = user_config.fast_resend,
        .flow_control  = user_config.enable_flow_control
    }

    session.ApplyProfile(profile)
```

## 4. 核心模块依赖关系与扩展点

```
                    ┌──────────────────┐
                    │   Application     │
                    └────────┬─────────┘
                             │ 依赖接口 (不依赖具体实现)
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
       ┌────────────┐ ┌────────────┐ ┌──────────────┐
       │  Server    │ │  Client    │ │ Message/Types│
       │ (端点抽象)  │ │ (端点抽象)  │ │ (通用数据类型) │
       └─────┬──────┘ └─────┬──────┘ └──────────────┘
             │               │
             │ 管理           │ 持有
             ▼               ▼
       ┌──────────────────────────────────┐
       │       Session (协议会话抽象)        │
       │    (可选 enable_shared_from_this)   │
       │    扩展点: 可替换底层协议实现         │
       └────────────────┬─────────────────┘
                        │ 委托
       ┌────────────────┼─────────────────┐
       ▼                ▼                 ▼
   ┌──────────┐  ┌──────────────┐  ┌──────────────┐
   │ Protocol │  │ DatagramSocket│  │  TaskQueue   │
   │ Engine   │  │ (可替换传输层) │  │ (线程安全队列) │
   │(KCP/自研)│  └──────────────┘  └──────────────┘
   └──────────┘

   关键扩展点:
   1. Protocol Engine  — 可替换为任意可靠传输协议
   2. DatagramSocket   — 可替换为UDPLite、RAW Socket、甚至模拟层
   3. TaskQueue        — 可替换为无锁队列、优先级队列等
   4. TimerService     — 可替换为高精度定时器或时间轮
```

## 5. 线程模型 (多策略可配置)

```
// ============================================================
// 5.1 单线程EventLoop模式 (推荐用于简单场景)
// ============================================================
// 一个线程运行一个EventLoop,管理所有Session
// 优点: 零锁开销,逻辑简单; 适用: 连接数 < 1000
FUNCTION SingleThreadModel():
    event_loop = EventLoop::Create()
    // 所有IO事件、定时器、Session操作在同一线程执行
    event_loop.Run()  // 单线程阻塞运行

// ============================================================
// 5.2 多线程Sticky模式 (推荐用于高并发)
// ============================================================
// 每个Worker线程运行独立EventLoop,Session按键哈希粘滞到固定线程
// 优点: 无需锁,水平扩展; 适用: 连接数 > 1000
FUNCTION MultiThreadStickyModel(sessions, num_workers):
    workers = ARRAY OF WorkerThread[num_workers]
    FOR EACH worker IN workers:
        worker.Start()  // 每个Worker在自己的EventLoop中运行

    // Session→Worker 映射策略 (可替换)
    FUNCTION AssignSession(session, routing_key):
        index = HASH(routing_key) MOD num_workers
        // 备选策略: 轮询(RoundRobin)、最少连接(LeastConnection)、
        //          一致性哈希(ConsistentHash)、指定亲和性(Affinity)
        workers[index].BindSession(session)

    // 跨线程操作: 通过目标Worker的TaskQueue投递闭包
    FUNCTION Dispatch(session, task):
        worker = session.GetBoundWorker()
        worker.PostTask(task)  // 线程安全的消息传递

// ============================================================
// 5.3 互斥锁模式 (兼容模式,不推荐)
// ============================================================
// 所有Session共享一个EventLoop,用mutex保护共享状态
// 优点: 实现简单; 缺点: 锁竞争限制吞吐,空转消耗CPU
// 仅用于遗留系统集成或开发调试阶段
FUNCTION MutexBasedModel():
    // 对Session的所有公共操作内部加锁
    // 使用 std::shared_mutex 实现读多写少优化
    // 注意: 需防范死锁和优先级反转
```

## 6. 配置体系总览

```
// ============================================================
// 分层配置结构,支持逐层覆盖
// ============================================================

STRUCT LibraryConfig:        // 库级全局配置
    .io_backend               // IO后端选择: kAutoDetect / kEpoll / kIocp / kKqueue
    .allocator                // 内存分配器: 默认使用std::allocator,可替换为池分配器
    .log_sink                 // 日志输出: 控制台/文件/自定义回调
    .metrics_sink             // 指标输出: 无/Prometheus/自定义回调

STRUCT ServerConfig:          // 服务端配置
    .listen_address           // 监听地址
    .session_config           // 会话级协议配置 (见下)
    .eviction_policy          // 驱逐策略: kImmediate / kGraceful / kNotifyOnly
    .health_check_interval_ms // 健康检测间隔
    .idle_timeout_ms          // 空闲超时
    .max_sessions             // 最大会话数 (0=不限制)

STRUCT ClientConfig:          // 客户端配置
    .remote_address           // 远端地址
    .session_config           // 会话级协议配置
    .reconnect_strategy       // 重连策略: 固定间隔/指数退避/自定义
    .connect_timeout_ms       // 连接超时
    .local_bind_address       // 本地绑定地址 (可选,默认OS分配)

STRUCT SessionConfig:         // 会话级协议配置
    .protocol_profile         // 协议预设: kFastMode / kReliableMode / kCustom
    .mtu_bytes                // MTU
    .send_window_packets      // 发送窗口(包数)
    .recv_window_packets      // 接收窗口(包数)
    .update_tick_ms           // Update驱动周期
    // 以下仅在 kCustom 模式下生效:
    .nodelay_enabled          // 是否启用快速模式
    .fast_resend_threshold    // 快速重传触发阈值
    .flow_control_enabled     // 是否启用流控
    .rx_buffer_initial_bytes  // 接收缓冲初始大小
    .tx_buffer_initial_bytes  // 发送缓冲初始大小
```

# 架构总览 — 通用可配置网络库

## 1. 设计目标

构建一个 **易用、高性能、跨平台、支持CS与P2P架构** 的网络库，以可替换传输协议为核心，提供低延迟、高可靠的传输能力，同时通过 JSON 配置文件 + 分层参数化配置体系适配从实时游戏到IoT数据上报等多种场景。系统启动时读取 JSON 配置文件初始化全库参数,支持环境变量和命令行覆盖。

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
│   Session (协议会话抽象, 可替换实现)                             │
│     - 生命周期管理 (Start / Close / GracefulShutdown)          │
│     - 数据收发 (Send / FeedInput / TryRecv)                    │
│     - 状态驱动 (Update)                                       │
│     - 回调管理 (OnMessage / OnError / OnStateChange)           │
│     - 统计收集 (GetStats)                                      │
├──────────────────────────────────────────────────────────────┤
│              Platform Layer (平台抽象层)                         │
│   EventLoop (epoll / IOCP / kqueue / poll 统一抽象)            │
│   WorkerPool (线程调度器, 支持多种分配策略)                      │
│   TimerQueue (定时器服务, 小顶堆/时间轮可替换)                    │
│   DatagramSocket (数据报Socket抽象, 支持UDP/UDPLite/RAW)        │
│   TaskQueue (有锁/无锁可配置任务队列)                            │
└──────────────────────────────────────────────────────────────┘
```

## 3. 数据流总览 (伪代码)

```
// ============================================================
// 文件名: architecture_overview.pseudo
// 描述: 整体数据流与控制流,所有参数均为可配置项
// ============================================================

// --------------------------------------------------
// 3.1 库初始化与全局配置 (基于JSON配置文件)
// --------------------------------------------------
FUNCTION LibraryInitialize(config_file_path: string = "netlib_config.json"):
    // 步骤1: 创建ConfigurationManager并加载JSON配置文件
    //        配置来源优先级: 内置默认值 → JSON文件 → 环境变量 → 命令行
    config_mgr = ConfigurationManager()
    IF NOT config_mgr.LoadFromFile(config_file_path):
        LOG_FATAL("Failed to load configuration from {}", config_file_path)
        RETURN false

    // 步骤2: 应用命令行覆盖 (最高优先级)
    //        如: ./server --server.listen_port=9000 --session_defaults.mtu_bytes=1200
    config_mgr.ApplyCmdLineOverrides(ParseCommandLine())

    // 步骤3: 获取最终配置快照 (线程安全,不可变)
    config = config_mgr.GetConfig()

    // 步骤4: 根据配置创建IO后端 (自动检测或显式指定)
    //        config->library.io_backend: "auto"/"epoll"/"iocp"/"kqueue"/"poll"
    event_loop = EventLoop(ParseIOBackend(config->library.io_backend))

    // 步骤5: 创建WorkerPool (如配置多线程模式)
    //        config->worker_pool.num_workers: 0=硬件并发数
    IF config->worker_pool.num_workers > 1 OR config->worker_pool.num_workers == 0:
        worker_pool = WorkerPool(
            config->worker_pool.num_workers,
            ParseDispatchStrategy(config->worker_pool.dispatch_strategy)
        )

    // 步骤6: 注册运行时配置重载 (SIGHUP或管理接口触发)
    //        仅修改可热更新的参数 (日志级别/超时阈值等)
    //        io_backend/端口等需重启生效
    SignalHandler::OnSIGHUP([&config_mgr]():
        config_mgr.Reload(config_file_path)
    )

    // 配置覆盖示例 — 各层参数均可被JSON/环境变量/命令行覆盖:
    //   library.io_backend             = "auto" / "epoll" / "iocp" / "kqueue" / "poll"
    //   library.default_engine_type     = "kcp" / "quic"
    //   library.log_level              = "trace" / "debug" / "info" / "warn" / "error"
    //   session_defaults.mtu_bytes     = 500~9000 (默认1400)
    //   session_defaults.send_window   = 4~1024 (默认128)
    //   server.max_sessions            = 0~UINT32_MAX (0=不限制)
    //   socket_defaults.recv_buf_bytes = 4096~INT_MAX (默认256KB)
    //   worker_pool.num_workers        = 0~512 (0=硬件并发数)

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
            ApplicationLogic.HandleSessionError(session, error)
        )
        session.OnStateChange(FUNCTION(old_state, new_state):
            ApplicationLogic.HandleStateChange(session, old_state, new_state)
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

    // Connect是异步的: 成功/失败通过回调通知
    // 在收到服务器首个响应ACK之前,状态保持为 kConnecting
    client.Connect(config.remote_address,
        FUNCTION(session):    // 成功: 服务器已响应,会话已建立
            session.OnMessage(FUNCTION(msg):
                ApplicationLogic.ProcessMessage(msg)
            )
        ,
        FUNCTION(error):      // 失败: 超时/拒绝/DNS失败等
            ApplicationLogic.HandleConnectFailed(error)
    )

    event_loop.Run()

// --------------------------------------------------
// 3.4 数据发送流程 (应用层→网络) — 完整管线
// --------------------------------------------------
FUNCTION DataSendFlow(session, user_data):
    // 步骤1: 应用层调用 Send(user_data)
    // 步骤2: Session检查状态: state_ != kConnected → 返回 kBlocked
    // 步骤3: Session委托协议引擎 send(user_data)
    // 步骤4: 协议引擎根据MTU将用户数据分段为传输单元 (segment)
    //   每个传输单元 = [协议头(变长)] + [用户数据分片]
    // 步骤5: 分段加入发送队列
    // 步骤6: 下次Update()时:
    //    a. 检查发送窗口余量 → 窗口内分段通过OutputCallback输出
    //    b. OutputCallback → Socket.SendTo → 网络
    //    c. 记录各分段的序列号和发送时间 (用于RTO/重传判定)
    // 步骤7: Update后若发送成功,统计计数器更新在引擎回调中进行
    //    (bytes_sent, messages_sent 在引擎确认交付后递增)

    result = session.Send(user_data)
    IF result == SendResult::kQueued:
        // 数据已加入发送缓冲,等待协议引擎异步发送
        // 可通过 session.OnSendComplete() 注册发送完成回调 (可选扩展)
    ELSE IF result == SendResult::kBlocked:
        // 状态非kConnected或发送窗口满
        // 应用层可选: 丢弃 / 阻塞等待 / 加入应用层重试队列

// --------------------------------------------------
// 3.5 数据接收流程 (网络→应用层) — 完整管线
// --------------------------------------------------
FUNCTION DataReceiveFlow(session):
    // 步骤1: EventLoop监听到Socket可读事件
    // 步骤2: Socket读取原始数据报 → 得到发送方地址和载荷
    // 步骤3: 端点(Object)根据数据报头的routing_key路由到对应Session
    // 步骤4: Session.FeedInput() → 协议引擎.Input()
    //   协议引擎内部: 头部解析→ACK信息处理→按序插入接收缓冲→乱序重组
    // 步骤5: FeedInput末尾自动调用 TryRecv()
    //   如果协议引擎有完整用户消息就绪:
    //     a. 组装为Message对象
    //     b. 触发 OnMessage 回调
    //     c. 更新统计 (bytes_recv, messages_recv)

    // 数据流单行汇总:
    // Socket.Read() → Session.FeedInput() → Engine.Input()
    //   → [内部重组] → Session.TryRecv() → OnMessage(Message)

// --------------------------------------------------
// 3.6 定时驱动流程 (协议状态机推进)
// --------------------------------------------------
FUNCTION TimerDriveFlow(event_loop, sessions):
    // 定时器以配置的时钟周期 (默认与协议内部interval对齐) 周期性触发
    // 每个时钟周期遍历所有活跃Session,调用:
    //   session.Update(now_ms)
    //
    // 协议引擎Update内部处理 (按顺序):
    //   a. 遍历发送队列,检查各分段的RTO超时 → 标记重传
    //   b. 检查快速重传条件 (重复ACK计数 >= fast_resend_threshold)
    //   c. 将待发送分段(新数据+重传+ACK)通过OutputCallback输出
    //   d. 更新RTO/RTT估算值
    //   e. 更新拥塞/流控状态 (如启用)

    event_loop.AddPeriodicTimer(
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
    // 周期性扫描所有会话,进行三级健康评估:
    //   空闲时长 = now - session.GetLastRecvTime()
    //   判定逻辑:
    //     空闲时长 < idle_timeout_ms        → kHealthy (正常通信)
    //     idle_timeout_ms <= 空闲时长 < stale_timeout_ms → kIdle (空闲,发送探活)
    //     空闲时长 >= stale_timeout_ms      → kStale  (过期,触发驱逐)

    event_loop.AddPeriodicTimer(
        config.health_check_interval_ms,
        FUNCTION():
            now = Clock::NowMs()
            stale_list = []
            FOR EACH (id, session) IN server.sessions_:
                health = session.EvaluateHealth(now,
                    config.idle_timeout_ms, config.stale_timeout_ms)
                IF health == ConnectionHealth::kStale:
                    stale_list.push_back(id)
                ELSE IF health == ConnectionHealth::kIdle:
                    server.HandleIdleSession(session, config.idle_policy)

            // 批量清理过期会话 (避免遍历中修改Map)
            FOR EACH conv IN stale_list:
                server.EvictSession(conv, EvictReason::kTimedOut)

// --------------------------------------------------
// 3.8 协议配置模式
// --------------------------------------------------
FUNCTION ConfigureProtocol(session, profile: ProtocolProfile):
    // 通过预设Profile或逐参数自定义来配置协议行为
    // 推荐使用FromProfile工厂方法获取预设 → 再按需覆盖个别字段
    // 可选协议引擎: KCP (kEngineKCP, 默认) / QUIC (kEngineQUIC)

    // 预定义Profile示例:
    //   kFastMode:     nodelay=1, interval=10, resend=2, fc=false
    //   kReliableMode: nodelay=0, interval=100, resend=0, fc=true
    //   kBalancedMode: nodelay=1, interval=20, resend=2, fc=true
    //   kCustom:       用户直接设置Config各字段

    config = Session::Config::FromProfile(profile)
    // 在预设基础上微调 (可选):
    config.engine_type = EngineType::kEngineQUIC  // 切换为QUIC协议引擎
    config.mtu_bytes = 1200  // 覆盖MTU以适配特定链路
    session.ApplyConfig(config)
```

## 4. 核心模块依赖关系与扩展点

```
                    ┌──────────────────┐
                    │ ConfigurationMgr │ ← 启动时加载JSON配置
                    │ (系统配置管理器)  │
                    └────────┬─────────┘
                             │ 初始化时注入各层配置
                    ┌────────┴─────────┐
                    │   Application     │
                    └────────┬─────────┘
                             │ 仅依赖公开接口
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
       ┌────────────┐ ┌────────────┐ ┌──────────────┐
       │  Server    │ │  Client    │ │ Message/Types│
       │ (端点抽象)  │ │ (端点抽象)  │ │ (通用数据类型) │
       └─────┬──────┘ └─────┬──────┘ └──────────────┘
             │               │
             │ 创建/管理      │ 创建/持有
             ▼               ▼
       ┌──────────────────────────────────┐
       │       Session (协议会话抽象)        │
       │    (可选 enable_shared_from_this)   │
       │    扩展点: 可替换底层协议引擎实现      │
       └────────────────┬─────────────────┘
                        │ 委托
       ┌────────────────┼─────────────────┐
       ▼                ▼                 ▼
   ┌──────────┐  ┌──────────────┐  ┌──────────────┐
   │ Protocol │  │ DatagramSocket│  │  TaskQueue   │
   │ Engine   │  │ (可替换传输层) │  │ (线程安全队列) │
   └──────────┘  └──────────────┘  └──────────────┘

   关键扩展点:
   0. ConfigurationMgr — 从JSON文件加载全库配置,支持环境变量/命令行覆盖和热重载
   1. Protocol Engine  — 实现统一接口即可替换为任意可靠传输协议 (内置KCP和QUIC两种实现)
   2. DatagramSocket   — 适配UDPLite/RAW Socket/模拟测试层
   3. TaskQueue        — 可替换为无锁MPSC队列/优先级队列/有界队列
   4. TimerService     — 可替换为高精度定时器/分层时间轮
   5. IOBackend        — 可替换为epoll(Linux/Android)/IOCP(Windows)/kqueue(macOS/BSD/iOS)/poll(回退)
   6. JSON Parser      — 可替换为nlohmann/json / simdjson / rapidjson (配置解析层)
```

## 5. 线程模型 (多策略可配置)

```
// ============================================================
// 5.1 单线程EventLoop模式 (推荐用于连接数 < 1000 的场景)
// ============================================================
// 一个线程运行一个EventLoop,管理所有Session
// 优点: 零锁开销,逻辑简单,调试方便; 缺点: 不能利用多核
FUNCTION SingleThreadModel():
    event_loop = EventLoop::Create()
    event_loop.Run()  // 单线程阻塞运行,所有操作串行化

// ============================================================
// 5.2 多线程Worker模式 (推荐用于高并发,连接数 > 1000)
// ============================================================
// N个Worker线程各运行独立EventLoop,Session按键哈希粘滞到固定Worker
// 同一Session的所有操作在同一Worker线程执行 → 无需锁
// 跨Worker操作通过目标Worker的TaskQueue投递闭包
FUNCTION MultiThreadWorkerModel(num_workers):
    workers = ARRAY OF WorkerThread[num_workers]
    FOR EACH worker IN workers:
        worker.Start()

    // Session→Worker 分配策略 (可插拔):
    DispatchStrategy OPTIONS:
        kModuloHash      // hash(routing_key) % N (默认,适合均匀分布)
        kConsistentHash   // 一致性哈希 (适合动态增减Worker)
        kRoundRobin       // 轮询
        kLeastSessions    // 最少会话优先

// ============================================================
// 5.3 互斥锁模式 (仅用于遗留系统兼容或开发调试)
// ============================================================
// 所有Session共享一个EventLoop和一把大锁
// 优点: 实现简单; 缺点: 锁竞争限制吞吐,无法利用多核
// 不建议在生产环境使用
```

## 6. 配置体系总览

```
// ============================================================
// 分层配置结构,支持逐层覆盖: Library → Endpoint → Session
// ============================================================

STRUCT LibraryConfig:        // 库级全局配置
    .io_backend               // kAutoDetect / kEpoll(Linux/Android) / kIocp(Windows) / kKqueue(macOS/BSD/iOS) / kPoll(回退)
    .default_engine_type       // EngineType                默认协议引擎 (kEngineKCP / kEngineQUIC)
    .allocator                // 可替换内存分配器
    .log_sink                 // 日志输出目标
    .metrics_sink             // 指标输出目标 (Prometheus/自定义)

STRUCT ServerConfig:          // 服务端配置
    .listen_address           // DatagramSocket::Address  监听地址
    .session_config           // Session::Config          新会话默认配置
    .eviction_policy          // EvictionPolicy           驱逐策略
    .idle_policy              // IdlePolicy               空闲处理策略
    .health_check_interval_ms // uint32_t                 健康检测周期
    .idle_timeout_ms          // uint32_t                 空闲判定阈值
    .stale_timeout_ms         // uint32_t                 过期判定阈值
    .max_sessions             // size_t                   最大会话数 (0=不限制)

STRUCT ClientConfig:          // 客户端配置
    .remote_address           // DatagramSocket::Address  目标地址
    .session_config           // Session::Config          会话配置
    .reconnect                // std::optional<ReconnectStrategy>  重连策略
    .connect_timeout_ms       // uint32_t                 连接超时
    .local_bind_address       // DatagramSocket::Address  本地绑定地址

STRUCT Session::Config:       // 会话级协议配置
    .engine_type              // EngineType               协议引擎选择 (kEngineKCP / kEngineQUIC)
    .profile                  // ProtocolProfile          预设选择
    // --- 仅kCustom模式逐项生效,否则由FromProfile填充 ---
    .nodelay                  // int                      快速模式开关
    .update_interval_ms       // int                      内部时钟周期
    .fast_resend_threshold    // int                      快速重传阈值
    .flow_control_enabled     // bool                     流控开关
    // --- 以下字段对所有Profile生效,可独立覆盖 ---
    .mtu_bytes                // int                      最大传输单元
    .send_window_packets      // int                      发送窗口(包数)
    .recv_window_packets      // int                      接收窗口(包数)
    .rx_buffer_init_bytes     // size_t                   接收缓冲初始大小
    .tx_buffer_init_bytes     // size_t                   发送缓冲初始大小
```

# System Configuration Module (系统配置模块)

系统配置模块负责集中管理所有可伸缩参数,提供从 JSON 配置文件加载、解析、验证到初始化各层组件的完整配置管线。支持分层覆盖、环境变量覆盖、命令行覆盖和运行时热更新。

---

## 1. ConfigurationManager 完整伪代码

```
// ============================================================
// 类名: ConfigurationManager
// 描述: 系统配置管理器,负责加载/解析/验证JSON配置文件,
//       并将配置分发到 Library / Server / Client / Session 各层
//       线程安全: Load/Parse阶段为单线程 (启动阶段),
//               Reload为线程安全 (原子交换shared_ptr)
// ============================================================
CLASS ConfigurationManager:
    // -------------------- 类型别名 --------------------
    USING ConfigPtr = std::shared_ptr<const SystemConfig>
    USING ValidationError = std::string
    USING ValidationWarnings = std::vector<std::string>

    // -------------------- 配置来源优先级 --------------------
    ENUM ConfigSource:
        kDefault   = 0   // 内置默认值 (最低优先级)
        kFile      = 1   // JSON配置文件
        kEnvVar    = 2   // 环境变量覆盖 (如 NETLIB_SERVER_MAX_SESSIONS=5000)
        kCmdLine   = 3   // 命令行参数覆盖 (最高优先级)

    // -------------------- 系统配置总成 --------------------
    STRUCT SystemConfig:
        library: LibraryConfig                 // 库级全局配置
        socket_defaults: SocketConfig          // Socket默认配置
        session_defaults: SessionDefaultsConfig // Session默认配置
        server: ServerEndpointConfig           // 服务端配置 (可选,仅Server使用)
        client: ClientEndpointConfig           // 客户端配置 (可选,仅Client使用)
        worker_pool: WorkerPoolConfig          // Worker线程池配置

    // Library级配置
    STRUCT LibraryConfig:
        io_backend: string = "auto"            // "auto" / "epoll" / "iocp" / "kqueue" / "poll"
        default_engine_type: string = "kcp"    // "kcp" / "quic"
        enable_metrics: bool = true            // 是否启用全局指标收集
        log_level: string = "info"             // "trace" / "debug" / "info" / "warn" / "error"
        log_output: string = "stdout"          // "stdout" / "stderr" / "callback" / 文件路径
        metrics_output: string = ""            // 指标输出目标 (空=不输出, "prometheus://:9090"等)
        max_worker_threads: int = 0            // 最大工作线程数 (0=硬件并发数)

    // Socket默认配置
    STRUCT SocketConfig:
        reuse_addr: bool = true                // SO_REUSEADDR
        recv_buf_bytes: int = 262144           // SO_RCVBUF (256KB)
        send_buf_bytes: int = 262144           // SO_SNDBUF (256KB)
        dscp: int = 0                          // DSCP/TOS QoS标记 (0=默认)
        ttl: int = 64                          // TTL

    // Session默认配置 (新Session的初始配置模板)
    STRUCT SessionDefaultsConfig:
        engine_type: string = "kcp"            // 协议引擎: "kcp" / "quic"
        profile: string = "fast"               // 协议预设: "fast" / "reliable" / "balanced" / "custom"
        nodelay: int = 1                       // 快速模式: 0=RTO翻倍, 1=RTO×1.5
        update_interval_ms: int = 10           // 协议内部时钟周期(ms)
        fast_resend_threshold: int = 2         // 快速重传阈值
        flow_control_enabled: bool = false     // 拥塞流控开关
        mtu_bytes: int = 1400                  // 最大传输单元(字节)
        send_window_packets: int = 128         // 发送窗口(包数)
        recv_window_packets: int = 128         // 接收窗口(包数)
        rx_buffer_init_bytes: int = 65536      // 接收缓冲初始大小(64KB)
        tx_buffer_init_bytes: int = 65536      // 发送缓冲初始大小(64KB)
        enable_metrics: bool = true            // 会话级指标收集

    // 服务端端点配置
    STRUCT ServerEndpointConfig:
        enabled: bool = false                  // 是否启用Server端点
        listen_ip: string = "0.0.0.0"         // 监听IP
        listen_port: int = 8888                // 监听端口
        address_family: string = "ipv4"        // "ipv4" / "ipv6"
        max_sessions: int = 0                  // 最大会话数 (0=不限制)
        health_check_interval_ms: int = 1000   // 健康检测周期(ms)
        idle_timeout_ms: int = 15000           // 空闲判定阈值(ms)
        stale_timeout_ms: int = 30000          // 过期驱逐阈值(ms)
        eviction_policy: string = "immediate"  // "immediate" / "graceful" / "notify_only"
        idle_policy: string = "probe"          // "ignore" / "probe" / "notify"
        recv_buf_init_bytes: int = 65536       // 接收缓冲区初始大小

    // 客户端端点配置
    STRUCT ClientEndpointConfig:
        enabled: bool = false                  // 是否启用Client端点
        remote_ip: string = "127.0.0.1"       // 目标服务器地址
        remote_port: int = 8888                // 目标服务器端口
        address_family: string = "ipv4"        // "ipv4" / "ipv6"
        local_bind_ip: string = "0.0.0.0"     // 本地绑定地址
        local_bind_port: int = 0               // 本地绑定端口 (0=随机)
        connect_timeout_ms: int = 5000         // 连接超时(ms)
        recv_buf_init_bytes: int = 65536       // 接收缓冲区初始大小
        reconnect: ReconnectConfig             // 重连配置

    // 重连策略配置
    STRUCT ReconnectConfig:
        enabled: bool = true                   // 是否启用重连
        initial_delay_ms: int = 1000           // 初始重连间隔
        max_delay_ms: int = 30000              // 最大重连间隔
        backoff_factor: float = 2.0            // 退避因子
        max_attempts: int = 5                  // 最大重试次数 (0=无限)
        jitter_ms: int = 200                   // 随机抖动范围

    // Worker线程池配置
    STRUCT WorkerPoolConfig:
        num_workers: int = 0                   // Worker线程数 (0=硬件并发数)
        dispatch_strategy: string = "modulo"   // "modulo" / "consistent_hash" / "round_robin" / "least_sessions"

    // -------------------- 构造 --------------------
    CONSTRUCTOR ConfigurationManager():
        config_ = std::make_shared<SystemConfig>()   // 初始化为默认值
        ApplyDefaults()

    // -------------------- 加载管线 --------------------

    // 主入口: 从JSON文件加载配置 (启动阶段调用)
    // 返回值: true=加载成功, false=解析/验证失败
    FUNCTION LoadFromFile(file_path: const std::string&) -> bool:
        // 步骤1: 读取文件内容
        file_content = ReadFileAll(file_path)
        IF file_content.empty():
            LOG_ERROR("Configuration file not found or empty: {}", file_path)
            RETURN false

        // 步骤2: JSON解析
        json_root = ParseJSON(file_content)
        IF NOT json_root.has_value():
            LOG_ERROR("JSON parse error: {}", json_root.error())
            RETURN false

        // 步骤3: 分层反序列化
        new_config = std::make_shared<SystemConfig>()
        ApplyDefaults()   // 先填充默认值

        IF NOT DeserializeLibrary(json_root["library"], new_config->library):
            RETURN false
        IF NOT DeserializeSocketDefaults(json_root["socket_defaults"], new_config->socket_defaults):
            RETURN false
        IF NOT DeserializeSessionDefaults(json_root["session_defaults"], new_config->session_defaults):
            RETURN false
        IF NOT DeserializeServer(json_root["server"], new_config->server):
            RETURN false
        IF NOT DeserializeClient(json_root["client"], new_config->client):
            RETURN false
        IF NOT DeserializeWorkerPool(json_root["worker_pool"], new_config->worker_pool):
            RETURN false

        // 步骤4: 语义验证
        warnings = Validate(new_config)
        FOR EACH w IN warnings:
            LOG_WARN("Config validation: {}", w)
        IF HasBlockingErrors(new_config):
            LOG_ERROR("Configuration validation failed with blocking errors")
            RETURN false

        // 步骤5: 环境变量覆盖 (优先级高于JSON文件)
        ApplyEnvOverrides(new_config)

        // 步骤6: 原子替换 (线程安全)
        std::atomic_store(&config_, new_config)
        LOG_INFO("Configuration loaded successfully from {}", file_path)
        RETURN true

    // 从内存中的JSON字符串加载 (用于单元测试/嵌入式场景)
    FUNCTION LoadFromString(json_string: const std::string&) -> bool:
        // 流程同LoadFromFile,跳过文件读取步骤
        // ...

    // -------------------- 配置读取 --------------------

    // 获取当前系统配置 (线程安全,返回不可变快照)
    FUNCTION GetConfig() -> ConfigPtr:
        RETURN std::atomic_load(&config_)

    // 便捷访问: 获取库级配置
    FUNCTION GetLibraryConfig() -> const LibraryConfig&:
        RETURN GetConfig()->library

    // 便捷访问: 获取Session默认配置 (用于构造新Session)
    FUNCTION GetSessionDefaults() -> const SessionDefaultsConfig&:
        RETURN GetConfig()->session_defaults

    // 便捷访问: 获取服务端配置
    FUNCTION GetServerConfig() -> const ServerEndpointConfig&:
        RETURN GetConfig()->server

    // 便捷访问: 获取客户端配置
    FUNCTION GetClientConfig() -> const ClientEndpointConfig&:
        RETURN GetConfig()->client

    // 便捷访问: 获取WorkerPool配置
    FUNCTION GetWorkerPoolConfig() -> const WorkerPoolConfig&:
        RETURN GetConfig()->worker_pool

    // -------------------- 反序列化 (JSON → 类型化配置) --------------------

    PRIVATE FUNCTION DeserializeLibrary(json: JsonValue, out: LibraryConfig&) -> bool:
        IF json IS null: RETURN true   // 整个section缺失,使用默认值
        IF NOT json.IsObject(): RETURN false

        IF json.Has("io_backend"):
            out.io_backend = json["io_backend"].AsString()
        IF json.Has("default_engine_type"):
            out.default_engine_type = json["default_engine_type"].AsString()
        IF json.Has("enable_metrics"):
            out.enable_metrics = json["enable_metrics"].AsBool()
        IF json.Has("log_level"):
            out.log_level = json["log_level"].AsString()
        IF json.Has("log_output"):
            out.log_output = json["log_output"].AsString()
        IF json.Has("metrics_output"):
            out.metrics_output = json["metrics_output"].AsString()
        IF json.Has("max_worker_threads"):
            out.max_worker_threads = json["max_worker_threads"].AsInt()
        RETURN true

    PRIVATE FUNCTION DeserializeSocketDefaults(json: JsonValue, out: SocketConfig&) -> bool:
        IF json IS null: RETURN true
        IF NOT json.IsObject(): RETURN false
        // 逐字段反序列化 (仅覆盖JSON中存在的键,保留默认值)
        IF json.Has("reuse_addr"):
            out.reuse_addr = json["reuse_addr"].AsBool()
        IF json.Has("recv_buf_bytes"):
            out.recv_buf_bytes = json["recv_buf_bytes"].AsInt()
        IF json.Has("send_buf_bytes"):
            out.send_buf_bytes = json["send_buf_bytes"].AsInt()
        IF json.Has("dscp"):
            out.dscp = json["dscp"].AsInt()
        IF json.Has("ttl"):
            out.ttl = json["ttl"].AsInt()
        RETURN true

    PRIVATE FUNCTION DeserializeSessionDefaults(json: JsonValue, out: SessionDefaultsConfig&) -> bool:
        // 结构同上,逐字段反序列化...
        IF json IS null: RETURN true
        IF NOT json.IsObject(): RETURN false
        IF json.Has("engine_type"):
            out.engine_type = json["engine_type"].AsString()
        IF json.Has("profile"):
            out.profile = json["profile"].AsString()
        IF json.Has("nodelay"):
            out.nodelay = json["nodelay"].AsInt()
        IF json.Has("update_interval_ms"):
            out.update_interval_ms = json["update_interval_ms"].AsInt()
        IF json.Has("fast_resend_threshold"):
            out.fast_resend_threshold = json["fast_resend_threshold"].AsInt()
        IF json.Has("flow_control_enabled"):
            out.flow_control_enabled = json["flow_control_enabled"].AsBool()
        IF json.Has("mtu_bytes"):
            out.mtu_bytes = json["mtu_bytes"].AsInt()
        IF json.Has("send_window_packets"):
            out.send_window_packets = json["send_window_packets"].AsInt()
        IF json.Has("recv_window_packets"):
            out.recv_window_packets = json["recv_window_packets"].AsInt()
        IF json.Has("rx_buffer_init_bytes"):
            out.rx_buffer_init_bytes = json["rx_buffer_init_bytes"].AsInt()
        IF json.Has("tx_buffer_init_bytes"):
            out.tx_buffer_init_bytes = json["tx_buffer_init_bytes"].AsInt()
        IF json.Has("enable_metrics"):
            out.enable_metrics = json["enable_metrics"].AsBool()
        RETURN true

    // DeserializeServer / DeserializeClient / DeserializeWorkerPool 同理
    // ...

    // -------------------- 验证 --------------------

    FUNCTION Validate(config: SystemConfigPtr) -> ValidationWarnings:
        warnings = ValidationWarnings{}

        // 验证规则 (仅列举关键规则,实际实现包含更多):
        // 1. IOBackend有效性
        IF config->library.io_backend NOT IN {"auto", "epoll", "iocp", "kqueue", "poll"}:
            warnings.Push("Invalid io_backend: " + config->library.io_backend)

        // 2. 协议引擎有效性
        IF config->session_defaults.engine_type NOT IN {"kcp", "quic"}:
            warnings.Push("Invalid engine_type: " + config->session_defaults.engine_type)

        // 3. ProtocolProfile有效性
        IF config->session_defaults.profile NOT IN {"fast", "reliable", "balanced", "custom"}:
            warnings.Push("Invalid profile: " + config->session_defaults.profile)

        // 4. MTU范围检查
        IF config->session_defaults.mtu_bytes < 500 OR config->session_defaults.mtu_bytes > 9000:
            warnings.Push("MTU out of range (500-9000): " + ToString(config->session_defaults.mtu_bytes))

        // 5. 端口号范围检查
        IF config->server.enabled AND
           (config->server.listen_port < 0 OR config->server.listen_port > 65535):
            warnings.Push("Invalid server port: " + ToString(config->server.listen_port))

        // 6. 超时逻辑一致性
        IF config->server.idle_timeout_ms >= config->server.stale_timeout_ms:
            warnings.Push("idle_timeout_ms must be < stale_timeout_ms")

        // 7. 退避因子逻辑检查
        IF config->client.reconnect.enabled AND config->client.reconnect.backoff_factor <= 1.0:
            warnings.Push("backoff_factor should be > 1.0 for exponential backoff")

        // 8. 窗口大小与MTU逻辑一致性
        IF config->session_defaults.send_window_packets < 4:
            warnings.Push("send_window_packets too small (< 4), may cause throughput issues")

        // 9. QUIC引擎约束
        IF config->session_defaults.engine_type == "quic" AND
           config->library.io_backend == "iocp":
            // QUIC需要TLS库,检查是否在Windows上配置了TLS后端
            // 此警告提醒用户确认TLS库可用性
            warnings.Push("QUIC on Windows requires BoringSSL or compatible TLS backend")

        RETURN warnings

    // 阻塞性错误检查 (导致加载失败)
    PRIVATE FUNCTION HasBlockingErrors(config: SystemConfigPtr) -> bool:
        // - 文件解析失败 (已在Deserialize阶段返回false)
        // - Server和Client同时启用但共享同一端口 (> 1个绑定冲突)
        // - 必填字段缺失 (如Server enabled但未配置listen_port)
        // 此处仅举例:
        IF config->server.enabled AND config->client.enabled:
            IF config->server.listen_port == config->client.remote_port AND
               config->server.listen_ip == config->client.remote_ip:
                LOG_ERROR("Server and Client cannot share the same address:port")
                RETURN true
        RETURN false

    // -------------------- 环境变量覆盖 --------------------

    PRIVATE FUNCTION ApplyEnvOverrides(config: SystemConfigPtr) -> void:
        // 环境变量命名规范: NETLIB_<SECTION>_<FIELD>
        // 示例:
        //   NETLIB_LIBRARY_LOG_LEVEL=debug
        //   NETLIB_SERVER_MAX_SESSIONS=5000
        //   NETLIB_SESSION_DEFAULTS_MTU_BYTES=1200
        //   NETLIB_CLIENT_RECONNECT_MAX_ATTEMPTS=10

        // 遍历所有环境变量,匹配 NETLIB_ 前缀,按Section.Field覆盖
        // 类型转换: 字符串 → 根据字段类型自动转换 (int/float/bool/string)
        FOR EACH (name, value) IN GetEnvironmentVariables():
            IF NOT name.StartsWith("NETLIB_"): CONTINUE
            path = name.Substring(7)   // 去掉 "NETLIB_" 前缀
            // 解析 path: "LIBRARY_LOG_LEVEL" → section="library", field="log_level"
            ApplyOverrideByPath(config, path, value)

    // -------------------- 运行时重载 --------------------

    // 运行时重新加载配置文件 (不重启进程)
    // 注意: 部分配置需重建组件才能生效 (如io_backend, num_workers)
    //       标记为"需重启"的字段在重载时被忽略并产生警告
    FUNCTION Reload(file_path: const std::string&) -> bool:
        success = LoadFromFile(file_path)
        IF success:
            // 通知各组件配置已变更 (观察者模式)
            NotifyConfigChanged()
        RETURN success

    // 注册配置变更回调 (用于组件在配置重载后调整行为)
    FUNCTION OnConfigChanged(cb: std::move_only_function<void(const SystemConfig&)>):
        config_change_callbacks_.Push(std::move(cb))

    PRIVATE FUNCTION NotifyConfigChanged() -> void:
        snapshot = GetConfig()
        FOR EACH cb IN config_change_callbacks_:
            cb(*snapshot)

    // -------------------- 成员变量 --------------------
    PRIVATE MEMBER config_: std::shared_ptr<const SystemConfig>   // 原子访问的当前配置
    PRIVATE MEMBER config_change_callbacks_: std::vector<std::move_only_function<void(const SystemConfig&)>>
    PRIVATE MEMBER default_config_applied_: bool = false
```

---

## 2. JSON 配置文件完整示例

```json
// ============================================================
// 文件名: netlib_config.json
// 描述: 系统配置文件示例,包含所有可伸缩参数及其默认值
//       所有字段均为可选,缺失时使用代码内置默认值
// ============================================================
{
    // ========================================
    // 库级全局配置 (LibraryConfig)
    // ========================================
    "library": {
        "io_backend": "auto",
        "default_engine_type": "kcp",
        "enable_metrics": true,
        "log_level": "info",
        "log_output": "stdout",
        //   "stdout" = 标准输出, "stderr" = 标准错误,
        //   "callback" = 通过LogManager::SetLogCallback注册的回调,
        //   "/var/log/netlib.log" = 文件路径
        "metrics_output": "",
        "max_worker_threads": 0
    },

    // ========================================
    // Socket默认配置 (SocketConfig)
    // 所有端点(Socket)的默认选项,可被端点级覆盖
    // ========================================
    "socket_defaults": {
        "reuse_addr": true,
        "recv_buf_bytes": 262144,
        "send_buf_bytes": 262144,
        "dscp": 0,
        "ttl": 64
    },

    // ========================================
    // Session默认配置 (SessionDefaultsConfig)
    // 新建Session时的初始协议参数,可被代码逐Session覆盖
    // ========================================
    "session_defaults": {
        "engine_type": "kcp",
        "profile": "fast",
        "nodelay": 1,
        "update_interval_ms": 10,
        "fast_resend_threshold": 2,
        "flow_control_enabled": false,
        "mtu_bytes": 1400,
        "send_window_packets": 128,
        "recv_window_packets": 128,
        "rx_buffer_init_bytes": 65536,
        "tx_buffer_init_bytes": 65536,
        "enable_metrics": true
    },

    // ========================================
    // 服务端端点配置 (ServerEndpointConfig)
    // ========================================
    "server": {
        "enabled": true,
        "listen_ip": "0.0.0.0",
        "listen_port": 8888,
        "address_family": "ipv4",
        "max_sessions": 0,
        "health_check_interval_ms": 1000,
        "idle_timeout_ms": 15000,
        "stale_timeout_ms": 30000,
        "eviction_policy": "immediate",
        "idle_policy": "probe",
        "recv_buf_init_bytes": 65536
    },

    // ========================================
    // 客户端端点配置 (ClientEndpointConfig)
    // ========================================
    "client": {
        "enabled": false,
        "remote_ip": "127.0.0.1",
        "remote_port": 8888,
        "address_family": "ipv4",
        "local_bind_ip": "0.0.0.0",
        "local_bind_port": 0,
        "connect_timeout_ms": 5000,
        "recv_buf_init_bytes": 65536,

        // 重连策略 (ReconnectConfig)
        "reconnect": {
            "enabled": true,
            "initial_delay_ms": 1000,
            "max_delay_ms": 30000,
            "backoff_factor": 2.0,
            "max_attempts": 5,
            "jitter_ms": 200
        }
    },

    // ========================================
    // Worker线程池配置 (WorkerPoolConfig)
    // ========================================
    "worker_pool": {
        "num_workers": 0,
        "dispatch_strategy": "modulo"
    }
}
```

---

## 3. 按场景的配置Profile示例

### 3.1 低延迟游戏服务器 (局域网)

```json
{
    "library": {
        "io_backend": "epoll"
    },
    "session_defaults": {
        "engine_type": "kcp",
        "profile": "fast",
        "nodelay": 1,
        "update_interval_ms": 5,
        "fast_resend_threshold": 1,
        "flow_control_enabled": false,
        "mtu_bytes": 1400,
        "send_window_packets": 256,
        "recv_window_packets": 256
    },
    "server": {
        "enabled": true,
        "listen_port": 7777,
        "max_sessions": 1000,
        "idle_timeout_ms": 10000,
        "stale_timeout_ms": 20000
    }
}
```

### 3.2 公网移动游戏服务器 (高延迟、需要加密)

```json
{
    "library": {
        "default_engine_type": "quic"
    },
    "session_defaults": {
        "engine_type": "quic",
        "profile": "balanced",
        "nodelay": 1,
        "update_interval_ms": 20,
        "fast_resend_threshold": 2,
        "flow_control_enabled": true,
        "mtu_bytes": 1200,
        "send_window_packets": 128
    },
    "server": {
        "enabled": true,
        "listen_port": 443,
        "max_sessions": 50000,
        "idle_timeout_ms": 30000,
        "stale_timeout_ms": 60000,
        "eviction_policy": "graceful",
        "idle_policy": "probe"
    },
    "worker_pool": {
        "num_workers": 8,
        "dispatch_strategy": "consistent_hash"
    }
}
```

### 3.3 批量数据同步 (可靠性优先)

```json
{
    "session_defaults": {
        "engine_type": "kcp",
        "profile": "reliable",
        "nodelay": 0,
        "update_interval_ms": 100,
        "fast_resend_threshold": 0,
        "flow_control_enabled": true,
        "mtu_bytes": 1400,
        "send_window_packets": 512,
        "recv_window_packets": 512
    },
    "client": {
        "enabled": true,
        "remote_ip": "10.0.0.100",
        "remote_port": 9000,
        "connect_timeout_ms": 30000,
        "reconnect": {
            "enabled": false
        }
    }
}
```

---

## 4. 配置加载启动流程

```
// ============================================================
// 描述: 系统启动时的配置加载与组件初始化时序
// ============================================================

FUNCTION SystemStartupSequence():
    // 步骤1: 创建ConfigurationManager (此时仅有默认配置)
    config_mgr = ConfigurationManager()

    // 步骤2: 解析命令行参数 (提取 --config 路径)
    cmdline = ParseCommandLine()
    config_file_path = cmdline.Get("--config", "netlib_config.json")

    // 步骤3: 加载JSON配置文件
    IF NOT config_mgr.LoadFromFile(config_file_path):
        LOG_ERROR("Failed to load configuration, exiting")
        RETURN EXIT_FAILURE

    // 步骤4: 命令行覆盖 (最高优先级)
    //   示例: ./server --server.listen_port=9000 --session_defaults.mtu_bytes=1200
    config_mgr.ApplyCmdLineOverrides(cmdline)

    // 步骤5: 获取最终配置
    config = config_mgr.GetConfig()

    // 步骤6: 根据配置创建各层组件
    //   6a. 创建EventLoop (IO后端根据 config->library.io_backend)
    event_loop = EventLoop(ParseIOBackend(config->library.io_backend))

    //   6b. 创建WorkerPool (线程数根据 config->worker_pool)
    IF config->worker_pool.num_workers > 1:
        worker_pool = WorkerPool(
            config->worker_pool.num_workers,
            ParseDispatchStrategy(config->worker_pool.dispatch_strategy)
        )

    //   6c. 创建Server端点 (如启用)
    IF config->server.enabled:
        server = Server(event_loop, ServerConfigFromSystemConfig(config))

    //   6d. 创建Client端点 (如启用)
    IF config->client.enabled:
        client = Client(event_loop, ClientConfigFromSystemConfig(config))

    // 步骤7: 注册配置变更回调 (用于运行时重载)
    config_mgr.OnConfigChanged([&](const SystemConfig& new_cfg):
        // 仅更新可热更新的参数:
        //   - 日志级别 (log_level)
        //   - 健康检测周期 (health_check_interval_ms)
        //   - 空闲/过期超时 (idle_timeout_ms / stale_timeout_ms)
        //   - 驱逐策略 (eviction_policy)
        // 标记"需重启"的参数被忽略:
        //   - io_backend
        //   - listen_port
        //   - num_workers
        server.ApplyHotReloadConfig(new_cfg)
    )

    // 步骤8: 进入事件循环
    event_loop.Run()
    RETURN EXIT_SUCCESS
```

---

## 5. 配置优先级与覆盖规则

```
// ============================================================
// 描述: 多层配置覆盖规则 (优先级从低到高)
// ============================================================

// 优先级层级:
//   1. 代码内置默认值 (最低)
//   2. JSON配置文件 (netlib_config.json)
//   3. 环境变量覆盖 (NETLIB_* 前缀)
//   4. 命令行参数覆盖 (--section.field=value, 最高)
//
// 覆盖语义:
//   - 标量值 (int/float/bool/string): 完全替换
//   - 嵌套对象 (如reconnect): 逐字段Merge (非整体替换)
//     JSON中的reconnect.enabled=true 不影响其他未指定的reconnect字段
//
// 示例: Session MTU的最终值确定过程
//   内置默认:                mtu_bytes = 1400
//   JSON覆盖:                mtu_bytes = 1300  (JSON文件中设置)
//   环境变量覆盖:             无 NETLIB_SESSION_DEFAULTS_MTU_BYTES 设置
//   命令行覆盖:               ./server --session_defaults.mtu_bytes=1200
//   最终生效值:               mtu_bytes = 1200
```

---

## 6. 配置热更新分类

| 分类 | 字段示例 | 重载行为 |
|------|---------|---------|
| **即时生效** | `log_level`, `enable_metrics` | 立即应用到运行中组件 |
| **周期性生效** | `health_check_interval_ms`, `idle_timeout_ms`, `stale_timeout_ms` | 在下一个检测周期开始时生效 |
| **新建Session生效** | `session_defaults.*`, `socket_defaults.*` | 仅影响此后创建的Session,已有Session不受影响 |
| **需重启生效** | `io_backend`, `listen_port`, `num_workers` | 运行时重载时忽略,需重启进程才能生效 |

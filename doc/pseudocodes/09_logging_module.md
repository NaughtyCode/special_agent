# Logging Module (日志模块)

日志模块提供线程安全的、可外部注入回调的日志系统,支持分级输出、运行时级别过滤、编译期级别裁剪和格式化消息。核心设计原则: 热路径零开销 (编译期级别裁剪) + 回调线程安全 + 库级生命周期管理。

---

## 1. LogManager 完整伪代码

```
// ============================================================
// 类名: LogManager
// 描述: 全局日志管理器,提供线程安全的日志回调注册和分级输出
//       支持编译期级别裁剪 (Release模式默认裁剪TRACE/DEBUG)
//       所有静态方法线程安全
// 头文件: log_manager.h (Public API)
// ============================================================
CLASS LogManager:
    // -------------------- 日志级别 --------------------
    ENUM Level: uint8_t
        kTrace = 0   // 追踪级 (最详细,仅开发调试)
        kDebug = 1   // 调试级 (开发环境)
        kInfo  = 2   // 信息级 (生产环境默认,记录关键业务事件)
        kWarn  = 3   // 警告级 (非预期但可恢复的情况)
        kError = 4   // 错误级 (操作失败,需关注)
        kFatal = 5   // 致命级 (不可恢复,通常随后退出进程)

    // -------------------- 日志回调类型 --------------------
    // 线程安全要求: 回调可能从多个线程并发调用,
    //              LogManager内部已对回调调用加锁,
    //              回调实现无需自行处理同步
    USING LogCallback = std::move_only_function<void(
        Level level,                         // 日志级别
        const char* file,                    // 源文件名 (__FILE__)
        int line,                            // 行号 (__LINE__)
        const char* function,                // 函数名 (__FUNCTION__ / __func__)
        const std::string& message           // 格式化后的日志消息
    )>

    // -------------------- 回调注册 (Public API) --------------------

    // 设置全局日志回调 (线程安全,可从任何线程调用)
    // 参数: cb — [in] 日志回调函数,传入nullptr则禁用日志输出
    // 说明: 重复调用会替换之前注册的回调
    //       回调在LogManager内部锁保护下被调用,回调实现无需自行加锁
    //       回调中不应:
    //         a. 再次调用SetLogCallback (会导致死锁)
    //         b. 执行长时间阻塞操作 (会阻塞所有日志输出)
    //         c. 抛出异常 (会被捕获并忽略,但日志消息丢失)
    STATIC FUNCTION SetLogCallback(cb: LogCallback) -> void:
        LOCK(callback_mutex_):
            IF cb:
                // 使用shared_ptr包装以实现GetLogCallback的共享访问语义
                // (std::move_only_function不可拷贝,通过shared_ptr间接持有)
                log_callback_ = std::make_shared<LogCallback>(std::move(cb))
            ELSE:
                log_callback_.reset()

    // 获取当前注册的日志回调 (用于调试/组合/装饰)
    // 返回值: 回调的副本; nullopt表示未设置回调
    // 注意: std::move_only_function不可拷贝; 此接口通过shared_ptr包装实现共享所有权,
    //       返回的副本与内部回调共享同一底层可调用对象,在锁外安全调用
    //       使用shared_ptr包装而非直接返回引用,避免锁释放后回调被替换导致的悬空指针
    STATIC FUNCTION GetLogCallback() -> std::optional<LogCallback>:
        LOCK(callback_mutex_):
            IF NOT log_callback_.has_value():
                RETURN std::nullopt
            // 返回的是shared_ptr<LogCallback>解引用后的副本;
            // 原始shared_ptr保留在log_callback_中,后续日志仍可使用
            // 调用方获得的LogCallback独立于LogManager内部状态
            RETURN *log_callback_  // shared_ptr解引用,返回LogCallback的副本
        // 实现说明: log_callback_应为std::shared_ptr<LogCallback>以支持此语义;
        // 若LogCallback本身不可拷贝,可改用std::shared_ptr<std::function<...>>包装

    // -------------------- 运行时级别过滤 --------------------

    // 设置全局最低日志级别 (低于此级别的日志消息被丢弃)
    // 参数: level — [in] 最低输出级别,默认kInfo
    // 线程安全: 可从任何线程调用
    // 说明: 不影响编译期裁剪 (Setting低于编译期裁剪级别的Log仍被编译器移除)
    STATIC FUNCTION SetLevel(level: Level) -> void:
        atomic_level_.store(level, std::memory_order_relaxed)

    // 获取当前运行时日志级别
    STATIC FUNCTION GetLevel() -> Level:
        RETURN atomic_level_.load(std::memory_order_relaxed)

    // 检查给定级别是否应输出
    STATIC FUNCTION IsLevelEnabled(level: Level) -> bool:
        RETURN level >= GetLevel()

    // -------------------- 核心日志输出 --------------------

    // 内部日志格式化与输出 (通常不直接调用,由LOG_*宏封装)
    // 线程安全: 内部对回调访问加锁
    STATIC FUNCTION Log(
            level: Level,
            file: const char*,
            line: int,
            function: const char*,
            fmt: const char*,
            ...   // printf风格变参 → 内部格式化为std::string
    ) -> void:
        // 步骤1: 运行时级别过滤 (快速路径,无锁原子读取)
        IF NOT IsLevelEnabled(level):
            RETURN

        // 步骤2: 格式化消息 (锁外执行,避免长时间持锁)
        message = FormatString(fmt, ...)   // printf风格→std::string; 定义在 utils/string_format.h 中
                                           // 实现可使用 vsnprintf 或 fmt::format 库

        // 步骤3: 调用回调 (持锁保护)
        LOCK(callback_mutex_):
            IF log_callback_ != nullptr:
                (*log_callback_)(level, file, line, function, message)

        // 步骤4: 致命级别后可选处理 (锁外执行,避免Flush重入锁导致死锁)
        IF level == Level::kFatal:
            // 刷新日志缓冲确保fatal消息不丢失 (Flush内部独立获取锁)
            Flush()
            // 调用应用注册的fatal handler (如果存在)
            // 注意: fatal_handler_注册和调用由专用fatal_mutex_保护
            IF fatal_handler_:
                fatal_handler_(file, line, function, message)

    // 冲刷日志 (确保所有已写入的日志被输出)
    STATIC FUNCTION Flush() -> void:
        // 如果日志回调内部有缓冲区,此处触发冲刷
        // 对于无缓冲回调 (stdout/stderr),此为空操作
        LOCK(callback_mutex_):
            // 回调本身可能持有内部缓冲区 (如FILE*),flush语义由回调实现决定
            // LogManager不直接flush文件描述符,而是依赖回调内的fflush/fsync
            // 如需强制落盘,应用层应在注册回调时自行处理flush逻辑

    // -------------------- 私有成员 --------------------
    PRIVATE:
        // 使用shared_ptr包装move_only_function以实现:
        //   - SetLogCallback: 原子替换callback (shared_ptr赋值)
        //   - GetLogCallback: 返回独立副本 (shared_ptr解引用)
        //   - Log(): 在锁内检查非空后通过shared_ptr调用 (无需optional::has_value)
        STATIC MEMBER log_callback_: std::shared_ptr<LogCallback>
        STATIC MEMBER callback_mutex_: std::mutex                  // 保护log_callback_的读写
        STATIC MEMBER atomic_level_: std::atomic<Level> = Level::kInfo  // 无锁读取的运行时级别
```

---

## 2. 日志宏定义 (编译期裁剪)

```
// ============================================================
// 描述: 日志宏封装,自动注入 __FILE__ / __LINE__ / __FUNCTION__
//       通过编译期宏 LOG_COMPILE_MIN_LEVEL 实现发行版裁剪
//       热路径宏 (LOG_TRACE / LOG_DEBUG) 在Release构建中
//       被编译器完全消除 (零运行时开销)
// ============================================================

// 编译期最低日志级别 (CMake/构建系统可覆盖)
#ifndef LOG_COMPILE_MIN_LEVEL
    #ifdef NDEBUG
        #define LOG_COMPILE_MIN_LEVEL  LogManager::Level::kInfo   // Release: 裁剪TRACE和DEBUG
    #else
        #define LOG_COMPILE_MIN_LEVEL  LogManager::Level::kTrace  // Debug: 保留全部
    #endif
#endif   // LOG_COMPILE_MIN_LEVEL guard

// 编译期级别检查: 低于裁剪级别的Log调用被编译器完全移除
#define LOG_IS_COMPILE_ENABLED(level) \
    (static_cast<int>(level) >= static_cast<int>(LOG_COMPILE_MIN_LEVEL))

// ── 追踪 (仅开发调试,Release构建中完全移除) ──
// 使用 do { if constexpr (...) { ... } } while(0) 确保:
//   a. 宏在任何上下文中可安全使用 (if/else/while)
//   b. if constexpr 在C++17编译期完全移除低于裁剪级别的日志调用
//   c. 调用的函数参数 (如昂贵的格式化) 在编译期完全求值前被消除
#define LOG_TRACE(fmt, ...) \
    do { if constexpr (LOG_IS_COMPILE_ENABLED(LogManager::Level::kTrace)) { \
        LogManager::Log(LogManager::Level::kTrace, \
                        __FILE__, __LINE__, __FUNCTION__, fmt, ##__VA_ARGS__); \
    } } while(0)

// ── 调试 (开发环境) ──
#define LOG_DEBUG(fmt, ...) \
    do { if constexpr (LOG_IS_COMPILE_ENABLED(LogManager::Level::kDebug)) { \
        LogManager::Log(LogManager::Level::kDebug, \
                        __FILE__, __LINE__, __FUNCTION__, fmt, ##__VA_ARGS__); \
    } } while(0)

// ── 信息 (生产环境默认,关键业务事件) ──
#define LOG_INFO(fmt, ...) \
    do { if constexpr (LOG_IS_COMPILE_ENABLED(LogManager::Level::kInfo)) { \
        LogManager::Log(LogManager::Level::kInfo, \
                        __FILE__, __LINE__, __FUNCTION__, fmt, ##__VA_ARGS__); \
    } } while(0)

// ── 警告 (非预期但可恢复) ──
#define LOG_WARN(fmt, ...) \
    do { if constexpr (LOG_IS_COMPILE_ENABLED(LogManager::Level::kWarn)) { \
        LogManager::Log(LogManager::Level::kWarn, \
                        __FILE__, __LINE__, __FUNCTION__, fmt, ##__VA_ARGS__); \
    } } while(0)

// ── 错误 (操作失败,需关注) ──
#define LOG_ERROR(fmt, ...) \
    do { if constexpr (LOG_IS_COMPILE_ENABLED(LogManager::Level::kError)) { \
        LogManager::Log(LogManager::Level::kError, \
                        __FILE__, __LINE__, __FUNCTION__, fmt, ##__VA_ARGS__); \
    } } while(0)

// ── 致命 (不可恢复,通常随后退出) ──
#define LOG_FATAL(fmt, ...) \
    do { if constexpr (LOG_IS_COMPILE_ENABLED(LogManager::Level::kFatal)) { \
        LogManager::Log(LogManager::Level::kFatal, \
                        __FILE__, __LINE__, __FUNCTION__, fmt, ##__VA_ARGS__); \
    } } while(0)
```

---

## 3. 使用示例

### 3.1 基础用法 — 注册回调

```
// ============================================================
// 描述: 应用层在库初始化阶段注册日志回调
// ============================================================

// 简单控制台输出 (线程安全: LogManager内部已加锁)
LogManager::SetLogCallback([](LogManager::Level level,
                               const char* file, int line,
                               const char* func,
                               const std::string& msg):
    // 格式化时间戳
    auto now = std::chrono::system_clock::now()
    auto time = std::chrono::system_clock::to_time_t(now)

    // 输出到stderr
    fprintf(stderr, "[%s] [%s] %s:%d (%s) %s\n",
            LevelToString(level),               // "INFO"/"WARN"/"ERROR"...
            ctime(&time),                       // 时间戳
            file, line, func, msg.c_str())
)

// 设置运行时最低级别
LogManager::SetLevel(LogManager::Level::kDebug)

// 正常使用日志宏
LOG_INFO("Network library initialized, backend={}, workers={}",
         io_backend_name, num_workers)
LOG_DEBUG("Session {}: send_window={}, recv_window={}",
          conv, send_window, recv_window)
LOG_TRACE("Raw packet: {} bytes from {}", len, sender.ToString())
```

### 3.2 文件日志输出

```
// 写入文件 (线程安全: 文件写入在LogManager锁保护下串行化)
FILE* log_file = fopen("netlib.log", "a")
LogManager::SetLogCallback([log_file](LogManager::Level level,
                                       const char* file, int line,
                                       const char* func,
                                       const std::string& msg):
    fprintf(log_file, "[%d] [%s] %s:%d %s\n",
            static_cast<int>(level), func, file, line, msg.c_str())
    fflush(log_file)   // 立即落盘,避免丢失
)
```

### 3.3 组合回调 (多路输出)

```
// 同时输出到控制台和文件 (利用装饰器模式)
auto console_sink = CreateConsoleSink()
auto file_sink = CreateFileSink("netlib.log")
auto udp_sink = CreateUDPSink("logserver:9999")   // 远程日志

LogManager::SetLogCallback([console_sink, file_sink, udp_sink](
        LogManager::Level level, const char* file, int line,
        const char* func, const std::string& msg):
    // 注意: 这些Sink的Write方法内部不应再调用LOG_*宏 (避免递归)
    console_sink.Write(level, file, line, func, msg)
    file_sink.Write(level, file, line, func, msg)
    IF level >= LogManager::Level::kError:
        udp_sink.Write(level, file, line, func, msg)  // 仅错误级别远程上报
)
```

---

## 4. 核心逻辑节点日志注入点

### 4.1 Session 生命周期

```
// ── 状态转换 ──
FUNCTION TransitionState(new_state):
    LOG_INFO("Session conv={}: {} -> {}",
             conv_, StateToString(old_state), StateToString(new_state))

// ── 构造与析构 ──
CONSTRUCTOR Session(...):
    LOG_DEBUG("Session created: conv={}, remote={}",
              conv_, remote_addr_.ToString())

DESTRUCTOR ~Session():
    LOG_DEBUG("Session destroyed: conv={}, total_sent={}, total_recv={}",
              conv_, stats_.total_bytes_sent, stats_.total_bytes_recv)

// ── 启动与关闭 ──
FUNCTION Start():
    LOG_INFO("Session conv={} started", conv_)

FUNCTION Close():
    LOG_INFO("Session conv={} closed (immediate)", conv_)

FUNCTION GracefulShutdown(timeout_ms):
    LOG_INFO("Session conv={}: graceful shutdown initiated, timeout={}ms",
             conv_, timeout_ms)

// ── 数据收发 ──
FUNCTION Send(data, len):
    result = engine_.Send(data, len)
    IF result == SendResult::kBlocked:
        LOG_WARN("Session conv={}: send blocked (state={}, window_used={})",
                 conv_, StateToString(state_), stats_.send_window_used)
    ELSE:
        LOG_TRACE("Session conv={}: sent {} bytes, total_sent={}",
                  conv_, len, stats_.total_bytes_sent)

FUNCTION FeedInput(data, len):
    LOG_TRACE("Session conv={}: received {} bytes from network", conv_, len)

// ── 错误 ──
FUNCTION NotifyError(error):
    LOG_ERROR("Session conv={}: error={}", conv_, ErrorToString(error))
```

### 4.2 Server 生命周期

```
// ── 启动与停止 ──
FUNCTION Start():
    LOG_INFO("Server started: listening on {}:{}",
             config_.listen_address.ip, config_.listen_address.port)

FUNCTION Stop():
    LOG_INFO("Server stopped: {} sessions active at shutdown",
             sessions_.size())

// ── 会话管理 ──
FUNCTION OnReadable() → 创建新Session:
    LOG_INFO("Server: new session accepted, conv={}, from={}",
             routing_key, result.sender.ToString())
    LOG_DEBUG("Server: session count now {}/{}",
              sessions_.size(), config_.max_sessions)

FUNCTION EvictSession(session, reason):
    LOG_INFO("Server: evicting session conv={}, reason={}",
             session->GetConvId(), EvictReasonToString(reason))

FUNCTION RunHealthCheck():
    LOG_DEBUG("Server health check: {} sessions, {} idle, {} stale",
              sessions_.size(), idle_count, stale_conv_list.size())
    FOR EACH conv IN stale_conv_list:
        LOG_WARN("Server: session conv={} timed out (stale), evicting", conv)
```

### 4.3 Client 生命周期

```
// ── 连接管理 ──
FUNCTION Connect():
    LOG_INFO("Client: connecting to {}:{}",
             config_.remote_address.ip, config_.remote_address.port)

FUNCTION DoConnect():
    LOG_DEBUG("Client: created session conv={}, sending handshake", conv_)

FUNCTION OnServerFirstResponse():
    LOG_INFO("Client: connection established to {}:{}, conv={}",
             config_.remote_address.ip, config_.remote_address.port, conv_)

FUNCTION Disconnect():
    LOG_INFO("Client: disconnected from {}:{}",
             config_.remote_address.ip, config_.remote_address.port)

// ── 超时与重连 ──
FUNCTION OnConnectTimeout():
    LOG_WARN("Client: connection timeout to {}:{}, retry {}/{}",
             config_.remote_address.ip, config_.remote_address.port,
             retry_count_, strategy.max_attempts)

// ── 错误 ──
FUNCTION NotifyConnectFailure(error):
    LOG_ERROR("Client: connect failed to {}:{}, error={}",
              config_.remote_address.ip, config_.remote_address.port,
              ConnectErrorToString(error))
```

### 4.4 EventLoop 生命周期

```
// ── 事件循环 ──
FUNCTION Run():
    LOG_INFO("EventLoop: started (backend={})", BackendToString(backend_))
    // ... 循环 ...
    LOG_INFO("EventLoop: stopped")

// ── IO事件 ──
FUNCTION Register(desc, mask, handler):
    LOG_DEBUG("EventLoop: registered fd={}, mask={:x}", desc.fd_or_handle, mask)

FUNCTION Unregister(desc):
    LOG_DEBUG("EventLoop: unregistered fd={}", desc.fd_or_handle)

// ── 定时器 ──
FUNCTION AddTimer(delay_ms, ...):
    LOG_TRACE("EventLoop: timer added, delay={}ms, handle={}", delay_ms, handle)

FUNCTION CancelTimer(handle):
    LOG_TRACE("EventLoop: timer canceled, handle={}", handle)

// ── 错误 ──
FUNCTION OnError(event):
    LOG_WARN("EventLoop: IO error on fd={}, code={}", event.fd, event.error_code)
```

---

## 5. 线程安全设计

```
// ============================================================
// 描述: LogManager的线程安全保证
// ============================================================

// 安全保证:
//   1. SetLogCallback — 互斥锁保护,可从任何线程安全调用
//   2. SetLevel / GetLevel — 原子操作,可从任何线程安全调用
//   3. Log — 原子读取级别 + 互斥锁调用回调,多线程可并发调用
//   4. 回调调用 — 在互斥锁保护下串行化,回调实现无需自行加锁
//
// 注意:
//   1. 回调内不应长时间阻塞 (会阻塞所有线程的日志输出)
//   2. 回调内不应调用 LogManager 的 SetLogCallback (会导致死锁)
//   3. 回调内不应调用 LOG_* 宏 (会导致递归,除非回调本身不输出到日志系统)
//
// 性能:
//   - 运行时级别过滤: 无锁原子读取 (fast path)
//   - 消息格式化: 锁外执行 (避免格式化耗时影响回调调用延迟)
//   - 回调调用: 互斥锁保护 (确保回调实现的线程安全)
//   - 编译期裁剪: LOG_TRACE/LOG_DEBUG在Release中完全移除 (零开销)
```

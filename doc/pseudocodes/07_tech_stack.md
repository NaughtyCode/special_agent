# 技术栈信息

本文档基于 `doc/pseudocodes/` 目录下全部伪代码文件的表述,整理出该 CS 架构游戏网络库的完整技术栈信息。

---

## 1. 编程语言与标准

| 项目 | 选型 | 说明 |
|------|------|------|
| **核心语言** | C++17 | 最低标准要求 |
| **异步回调类型** | `std::move_only_function<void()>` | C++23 标准库设施,可使用 `fu2::unique_function` 作为 polyfill |
| **结果类型** | `std::expected<T, E>` | C++23 标准库设施,可使用 `tl::expected` 作为 polyfill |
| **零拷贝视图** | `std::span<const uint8_t>` | C++20 标准库设施,可使用 `gsl::span` 或 `tl::span` 作为 polyfill |
| **可选值** | `std::optional<T>` | C++17 标准库原生支持 |
| **字符串视图** | `std::string_view` | C++17 标准库原生支持 |
| **智能指针** | `std::shared_ptr<T>` / `std::unique_ptr<T>` | C++11+ |
| **原子操作** | `std::atomic<T>` | C++11+ |
| **线程** | `std::thread` | C++11+ |
| **硬件并发** | `std::thread::hardware_concurrency()` | C++11+ |

---

## 2. 平台与操作系统支持

| 平台 | IO 模型 | 唤醒机制 |
|------|---------|---------|
| **Linux** | epoll | eventfd |
| **Android** | epoll (Linux 内核) | eventfd 或 pipe |
| **Windows** | IOCP (I/O Completion Port) | PostQueuedCompletionStatus |
| **macOS / BSD** | kqueue | pipe 或 kqueue user event |
| **iOS** | kqueue (Darwin 内核) | pipe 或 kqueue user event |
| **通用回退** | POSIX poll | pipe |

- 平台自动检测: `IOBackend::kAutoDetect` → `PlatformDetect::BestAvailable()`:
  ```
  // PlatformDetect 伪代码 (编译期平台识别)
  namespace PlatformDetect {
      IOBackend BestAvailable():
          #if defined(__linux__) || defined(__ANDROID__)
              return IOBackend::kEpoll
          #elif defined(_WIN32)
              return IOBackend::kIocp
          #elif defined(__APPLE__) || defined(__FreeBSD__) || defined(__OpenBSD__) || defined(__NetBSD__) || defined(__DragonFly__)
              return IOBackend::kKqueue  // NetBSD/DragonFly BSD同样支持kqueue, 避免回退到性能较差的poll
          #else
              return IOBackend::kPoll      // 通用POSIX回退
          #endif
  }
  ```
- 也可手动指定后端: `kEpoll` (Linux/Android) / `kIocp` (Windows) / `kKqueue` (macOS/BSD/iOS) / `kPoll` (回退)
- Android 通过 NDK 编译,使用 Linux 内核的 epoll 和 eventfd 机制
- iOS 通过 Xcode 编译,使用 Darwin 内核的 kqueue 机制 (与 macOS 相同)

### 移动平台特殊考量

| 考量点 | 说明 |
|--------|------|
| **网络切换** | 移动设备频繁切换网络 (WiFi ↔ 蜂窝),IP 地址可能改变;应用层需感知网络变更并触发重连 |
| **应用生命周期** | iOS/Android 应用可进入后台/前台,后台时网络 Socket 可能被 OS 暂停或关闭;需在生命周期回调中管理会话的暂停/恢复/重连 |
| **省电优化** | 移动平台对后台网络活动有严格限制;建议在应用进入后台时降低健康检测频率和协议 Update 频率,或将长连接切换为低功耗心跳模式 |
| **NDK 编译** | Android 通过 NDK 交叉编译 C++ 代码,需支持 armeabi-v7a / arm64-v8a / x86_64 等多 ABI |
| **Xcode 集成** | iOS 通过 Xcode 构建,需配置 Framework 或静态库目标,支持 arm64 (真机) 和 x86_64 (模拟器) |
| **IPv6 就绪** | iOS 应用提交 App Store 要求支持 IPv6-only 网络;库的 `AddressFamily::kIPv6` 和地址解析需完整支持 |
| **蜂窝网络特征** | 蜂窝网络延迟波动大 (50-500ms)、丢包率高;协议配置应支持高延迟网络下的适应性调参 (增大 RTO 下限,启用流控) |

---

## 3. IO 模型与事件驱动

| 组件 | 选型 | 说明 |
|------|------|------|
| **事件循环** | EventLoop (统一抽象) | 封装 epoll(Linux/Android)/IOCP(Windows)/kqueue(macOS/BSD/iOS)/poll(回退), Pimpl 惯用法隐藏平台差异 |
| **触发模式** | 边缘触发 (Edge-Triggered) | `EPOLLET` / `kEdgeTriggered`,推荐用于高性能场景 |
| **Socket 类型** | 非阻塞数据报 (SOCK_DGRAM) | 支持 UDP / UDPLite / Unix Domain Dgram / RAW |
| **Socket API** | POSIX `sendto` / `recvfrom` | `MSG_DONTWAIT` 标志确保非阻塞 |
| **IP 协议** | IPv4 / IPv6 / Unix Domain | `AddressFamily::kIPv4` / `kIPv6` / `kUnixDomain` |
| **QoS 支持** | DSCP / TOS | `SocketConfig::dscp` 字段 |
| **TTL 配置** | `SocketConfig::ttl` | 默认 64 |
| **Socket 选项** | SO_REUSEADDR / SO_RCVBUF / SO_SNDBUF | 默认缓冲 256KB |

---

## 4. 传输协议

| 层级 | 选型 | 说明 |
|------|------|------|
| **默认协议引擎** | KCP | 通过 `ikcp_*` C API 封装 (`ikcp_create` / `ikcp_setoutput` / `ikcp_nodelay` / `ikcp_wndsize`);轻量级可靠UDP,适合低延迟游戏场景 |
| **第二协议引擎** | QUIC | 基于 UDP 的多路复用安全传输协议;内置 TLS 1.3 加密;支持 0-RTT 握手、连接迁移 (IP 切换不断连)、无队头阻塞的多流复用 |
| **协议引擎接口** | ProtocolEngine (抽象接口) | 可替换为任意可靠传输协议实现 (自定义可靠UDP / Mock 等) |
| **引擎选择** | `Session::Config::engine_type` | `kEngineKCP` (0,默认) / `kEngineQUIC` (1),构造时通过 `ProtocolEngineFactory::Create()` 创建对应引擎 |
| **工厂注册** | ProtocolEngineFactory | 支持运行时注册自定义协议引擎工厂函数 (`RegisterFactory`) |
| **协议预设** | Fast / Reliable / Balanced / Custom | 通过 `Session::Config::FromProfile()` 工厂方法生成 |

### KCP vs QUIC 选型指南

| 维度 | KCP | QUIC |
|------|-----|------|
| **传输层** | 基于 UDP,自定义可靠性 | 基于 UDP,IETF 标准 (RFC 9000) |
| **加密** | 无内置加密 (需应用层自行加密) | 强制 TLS 1.3 加密 (防窃听/篡改) |
| **握手延迟** | 0-RTT (无握手,首包即创建会话) | 0-RTT / 1-RTT (0-RTT 需预共享密钥) |
| **多路复用** | 单流 (不区分流ID) | 多流 (Stream ID 隔离,无队头阻塞) |
| **连接迁移** | 不支持 (IP 变更需重新握手) | 支持 (Connection ID 不变,IP 切换自动恢复) |
| **拥塞控制** | 固定窗口 (可配置) | 可插拔拥塞算法 (NewReno / Cubic / BBR) |
| **头部开销** | 24 字节 (固定) | 1-25+ 字节 (短头: 1B type + 0-20B CID + 1-4B PN; 长头: 1B type + 4B version + DCIL+DCID+SCIL+SCID + 1-4B PN) |
| **实现复杂度** | 低 (~2000 行 C) | 高 (需 TLS 库集成,~数万行) |
| **适用场景** | 局域网/私有网游戏,低延迟优先 | 公网/移动端游戏,需要安全加密和连接迁移 |
| **外部依赖** | 仅 ikcp.c/ikcp.h (无其他依赖) | TLS 库 (如 BoringSSL / OpenSSL / PicoTLS) |

### 协议配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| MTU | 1400 字节 | 最大传输单元,含协议头 |
| 发送窗口 | 128 包 | 飞行中未确认的最大包数 |
| 接收窗口 | 128 包 | 接收端可缓存的乱序包数 |
| 内部时钟周期 | 10 ms | Update() 调用间隔 |
| 快速重传阈值 | 2 | 收到此数量的重复 ACK 时立即重传 |
| NoDelay | 1 (Fast 模式) | 0=RTO 翻倍, 1=RTO × 1.5 |
| 流控 | false (Fast 模式) | 拥塞窗口控制开关 |
| 收发缓冲初始大小 | 64 KB | 动态扩容 |

---

## 5. 线程模型

| 模式 | 适用场景 | 同步策略 |
|------|---------|---------|
| **单线程 EventLoop** | 连接数 < 1000 | 零锁,所有操作在同一线程串行执行 |
| **多线程 Worker Pool** | 连接数 > 1000,高并发 | 每 Worker 独立 EventLoop,Session 按 routing_key 粘滞到固定 Worker |
| **互斥锁模式** | 遗留兼容/调试 | 全局锁,不推荐生产使用 |

### WorkerPool 分配策略

| 策略 | 算法 | 适用场景 |
|------|------|---------|
| **kModuloHash** | `hash(routing_key) % N` | 默认,均匀分布 |
| **kConsistentHash** | 一致性哈希环 | 需动态增减 Worker |
| **kRoundRobin** | 原子计数器轮询 | 与 routing_key 无关的均匀分配 |
| **kLeastSessions** | 最少会话优先 | 负载不均匀场景 |

### 跨线程安全机制

- 同一 Session 的所有操作在同一 EventLoop 线程串行执行 (无内部锁)
- 跨线程操作通过 `EventLoop::PostTask(task)` 投递闭包到目标线程
- `EventLoop::Stop()` 可从任何线程安全调用,通过 `WakeUp()` 唤醒阻塞中的 `Run()`
- `WorkerPool::Dispatch()` 线程安全,可从任何线程调用

---

## 6. 数据结构与算法

| 组件 | 数据结构 | 可替换方案 |
|------|---------|-----------|
| **TimerQueue** | `std::priority_queue` (小顶堆) | 分层时间轮 (Hierarchical Timing Wheel) |
| **TaskQueue** | `std::queue` + `std::mutex` + `std::condition_variable` | 无锁 MPSC 队列 / 优先级队列 / 有界队列 (背压) |
| **Session 路由表** | `std::unordered_map<uint32_t, shared_ptr<Session>>` | — |
| **WorkerPool 分配** | 取模哈希 / 一致性哈希环 / 原子计数器 | — |
| **接收缓冲** | `std::vector<uint8_t>` (动态扩容) | — |
| **消息封装** | `Message` 类 (持 `std::vector<uint8_t>` + 元数据) | — |
| **定时器延迟删除** | `std::unordered_set<TimerHandle>` 标记取消 + 惰性清理 | — |
| **配置存储** | `ConfigurationManager` + `SystemConfig` (JSON → 类型化结构体) | 支持 JSON/TOML/YAML 解析器替换 |

---

## 7. 配置体系

### 7.1 配置分级

```
SystemConfig (根)
  ├── LibraryConfig (库级全局)
  │     ├── io_backend / default_engine_type
  │     ├── log_level / log_output / metrics_output
  │     └── max_worker_threads / enable_metrics
  ├── SocketConfig (Socket 默认配置)
  │     └── reuse_addr / recv_buf_bytes / send_buf_bytes / dscp / ttl
  ├── SessionDefaultsConfig (Session 默认配置)
  │     ├── engine_type / profile
  │     └── 全部协议参数 (MTU/窗口/nodelay/流控等)
  ├── ServerEndpointConfig (Server 端点)
  │     ├── listen_ip / listen_port / max_sessions
  │     ├── 健康检测与驱逐策略参数
  │     └── idle_policy / eviction_policy
  ├── ClientEndpointConfig (Client 端点)
  │     ├── remote_ip / remote_port / connect_timeout_ms
  │     └── ReconnectConfig (重连策略)
  └── WorkerPoolConfig (线程池)
        └── num_workers / dispatch_strategy
```

### 7.2 配置来源优先级 (从低到高)

```
1. 代码内置默认值
      ↓ (JSON 覆盖)
2. netlib_config.json 配置文件
      ↓ (环境变量覆盖)
3. NETLIB_<SECTION>_<FIELD> 环境变量
      ↓ (命令行覆盖)
4. --section.field=value 命令行参数 (最高)
```

### 7.3 配置热更新分类

| 分类 | 生效时机 | 字段示例 |
|------|---------|---------|
| **即时生效** | 立即应用 | `log_level`, `enable_metrics` |
| **周期性生效** | 下个检测周期 | `health_check_interval_ms`, `idle_timeout_ms` |
| **新建Session生效** | 此后创建的 Session | `session_defaults.*`, `socket_defaults.*` |
| **需重启生效** | 进程重启后 | `io_backend`, `listen_port`, `num_workers` |

---

## 8. 设计模式

| 模式 | 应用位置 | 说明 |
|------|---------|------|
| **Pimpl (Pointer to Implementation)** | `EventLoop::impl_` (IOBackendImpl) | 隐藏平台相关 IO 实现细节 |
| **工厂方法** | `Config::FromProfile()` / `Address::From()` / `ProtocolEngineFactory::Create()` | 参数化对象创建 |
| **策略模式** | `DispatchStrategy` / `EvictionPolicy` / `IdlePolicy` / `ReconnectStrategy` | 可替换的行为策略 |
| **观察者模式** | `OnMessage` / `OnError` / `OnStateChange` / `OnNewSession` / `OnSessionEvicted` | 事件回调通知 |
| **责任链模式** | Server 事件处理器链 (`OnNewSession` → 注册 Session 回调) | 可插拔的中间件处理 |
| **RAII** | `DatagramSocket` (fd 管理) / `Session` (引擎+定时器) / `TimerHandle` | 自动资源管理 |
| **接口隔离** | `IEventHandler` / `ProtocolEngine` | 纯虚接口,支持注入和替换 |
| **幂等设计** | `Close()` / `Stop()` / `Cancel()` | 重复调用安全,终态不可逆 |
| **延迟删除** | `TimerQueue::Cancel()` / `EventLoop::CancelTimer()` | 标记取消 + 惰性清理,避免回调中删除自身的 ABA 问题 |
| **批量消费** | `TaskQueue::ExecuteAll()` / `Server::RunHealthCheck()` | swap 到本地后锁外执行,减少锁竞争 |
| **快照不可变** | `ConfigurationManager::GetConfig()` 返回 `shared_ptr<const>` | 多线程读配置无需锁,原子交换指针 |
| **分层反序列化** | `ConfigurationManager::DeserializeLibrary/Server/Client/...` | 逐 Section 反序列化,未出现的 key 保留默认值 |
| **环境注入** | `ApplyEnvOverrides` / `ApplyCmdLineOverrides` | 外部环境注入配置,实现 12-factor app 原则 |
| **回调注入** | `LogManager::SetLogCallback` | 日志输出回调由外部设置,库不依赖具体日志框架 |
| **编译期裁剪** | `LOG_COMPILE_MIN_LEVEL` + `LOG_TRACE`/`LOG_DEBUG` 宏 | Release构建中TRACE/DEBUG级别被编译器完全移除,热路径零开销 |
| **双级过滤** | 编译期宏 + 运行时原子变量 | 编译期裁剪不输出级别,运行时原子读取无锁过滤剩余级别 |

---

## 9. 构建与测试工具链

### 编译器与构建

| 项目 | 说明 |
|------|------|
| **编译优化级别** | 性能测试使用 Release 编译 (-O2/-O3) |
| **CI 集成** | CI 流水线自动执行测试分级 |

### 测试基础设施

| 工具 | 用途 |
|------|------|
| **模拟时钟 (SimulatedClock)** | 消除真实时间不确定性,精确控制协议超时/重传/定时器行为;支持 `AdvanceTime(delta_ms)` |
| **网络模拟器 (NetworkSimulator)** | 单进程内模拟延迟/丢包/乱序/重复;确定性伪随机 (固定种子可复现);支持动态修改链路参数 |
| **确定性仿真套件** | 预录制网络 trace 文件,回放时逐帧逐字节比对行为一致性 |

### 代码质量与安全工具

| 工具 | 检测内容 | 触发时机 |
|------|---------|---------|
| **ThreadSanitizer (TSan)** | 数据竞争、未同步的共享变量访问 | CI 流水线,所有并发测试 |
| **AddressSanitizer (ASan)** | use-after-free、堆/栈缓冲区溢出、内存泄漏 | CI 流水线 |
| **LeakSanitizer (LSan)** | 可达/间接内存泄漏 | 伴随 ASan 运行 |
| **Helgrind (Valgrind 工具)** | 锁顺序问题、潜在死锁 | 可选,CI 中可配置 |
| **RSS 回归检测** | 每 10K 次循环后 RSS 回归初始值 ±5% | 内存泄漏测试 |

### 性能测试指标

| 指标 | 说明 |
|------|------|
| **EventLoop 空载吞吐量** | 无 IO/定时器/任务 时的每秒循环次数 |
| **EventLoop 满载吞吐量** | 10K 活跃 Session 下每秒处理能力 |
| **TaskQueue 延迟** | P50/P95/P99 端到端延迟 (Push → 执行) |
| **Session Send 吞吐量** | 不同 MTU/窗口组合下的 Mbps |
| **Server 会话创建速率** | 每秒可创建并完成初始化的 Session 数 |

### 测试优先级分级

| 等级 | 执行频率 | 范围 |
|------|---------|------|
| **P0 (阻断)** | 每次 commit | 核心正确性: MPSC/定时器并发/Session 析构/内存泄漏 |
| **P1 (高)** | 每次 PR | 线程安全与集成: WorkerPool/Server/Client 状态机/E2E 优雅关闭 |
| **P2 (中)** | 每日构建 | 负载与稳定性: 高频创建/跨线程收发/网络分区恢复 |
| **P3 (低)** | 每周/发版前 | 性能回归与确定性仿真 |

---

## 10. 外部依赖

| 依赖 | 用途 | 备注 |
|------|------|------|
| **KCP (ikcp.c/ikcp.h)** | 默认协议引擎 (kEngineKCP) | C API,通过 `ProtocolEngine` 接口封装;轻量级,无额外依赖 |
| **QUIC 库 (可选)** | 第二协议引擎 (kEngineQUIC) | 需集成 TLS 库;如 BoringSSL (推荐)/OpenSSL (Linux/Android)/PicoTLS (嵌入式)/SecureTransport (iOS/macOS 原生) |
| **POSIX Socket API** | 跨平台网络 IO | Linux/Android/macOS/BSD/iOS 原生,Windows 通过 IOCP 适配 |
| **C++ 标准库** | 容器/线程/原子/智能指针/函数对象 | STL containers, threading, atomics, type traits |
| **第三方 polyfill (可选)** | 弥补 C++17 与 C++20/23 差距 | `tl::expected` / `fu2::unique_function` / `gsl::span` |
| **JSON 解析库** | JSON 配置文件解析 | 推荐 `nlohmann/json` (header-only, C++17 友好) 或 `simdjson` (高性能,零拷贝解析) |

---

## 11. 库级全局配置与配置体系分层

系统配置通过 `ConfigurationManager` 集中管理,从 JSON 文件加载并分发到各层。详见 `08_system_config.md`。

```
// 配置来源优先级 (低 → 高):
//   内置默认值 → JSON文件 → 环境变量(NETLIB_*) → 命令行(--section.field=value)

// 配置分层结构:
SystemConfig
  ├── LibraryConfig           // io_backend / engine_type / log_level / max_workers
  ├── SocketConfig             // reuse_addr / buffer sizes / dscp / ttl
  ├── SessionDefaultsConfig    // 协议参数模板 (MTU/窗口/nodelay/流控)
  ├── ServerEndpointConfig     // 监听地址 / 健康检测 / 驱逐策略
  ├── ClientEndpointConfig     // 目标地址 / 重连策略 / 连接超时
  └── WorkerPoolConfig         // 线程数 / 分配策略
```

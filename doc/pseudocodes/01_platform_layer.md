# Platform Layer (平台抽象层) 伪代码

平台层负责封装操作系统资源，向上层提供与具体IO模型和线程模型无关的统一异步接口。所有组件均支持注入和替换。

---

## 1. EventLoop — 统一事件循环

```
// ============================================================
// 类名: EventLoop
// 描述: 跨平台IO事件循环抽象
//       封装 epoll(Linux/Android) / IOCP(Windows) / kqueue(macOS/BSD/iOS)
//       统一接口,调用方无需关心底层IO模型差异
// ============================================================
CLASS EventLoop:
    // -------------------- 嵌套类型 --------------------
    // IO事件掩码 (位标志,可组合)
    FLAGS IOMask:
        kReadable      = 0x01   // 可读事件
        kWritable      = 0x02   // 可写事件
        kError         = 0x04   // 错误事件
        kEdgeTriggered = 0x10   // 边缘触发 (推荐用于高性能场景)

    // 统一的事件描述符 (跨平台句柄抽象)
    STRUCT EventDesc:
        fd_or_handle: uintptr_t              // 文件描述符或句柄
        platform_tag: Platform               // 平台标记

    // -------------------- 构造与析构 --------------------
    CONSTRUCTOR EventLoop(backend: IOBackend = kAutoDetect):
        // 自动选择当前平台最优IO模型
        // 也可手动指定: kEpoll / kIocp / kKqueue / kPoll (回退方案)
        // 平台映射: Linux/Android → kEpoll, Windows → kIocp,
        //          macOS/iOS → kKqueue, 通用回退 → kPoll
        SELECT backend:
            CASE kEpoll:
                impl_ = CREATE EpollImpl()
            CASE kIocp:
                impl_ = CREATE IocpImpl()
            CASE kKqueue:
                impl_ = CREATE KqueueImpl()
            CASE kPoll:
                impl_ = CREATE PollImpl()     // POSIX poll 作为通用回退
            CASE kAutoDetect:
                impl_ = PlatformDetect::BestAvailable()

        // 创建内部唤醒通道 (用于跨线程唤醒阻塞中的事件循环)
        // 各平台实现:
        //   Linux/Android → eventfd
        //   macOS/BSD/iOS → pipe 或 kqueue user event
        //   Windows → PostQueuedCompletionStatus
        wakeup_channel_ = impl_.CreateWakeupChannel()

    DESTRUCTOR ~EventLoop():
        Stop()
        impl_.Reset()

    // -------------------- 生命周期管理 --------------------

    // 启动事件循环 (阻塞调用,直到外部调用Stop)
    FUNCTION Run() -> void:
        state_ = kRunning
        LOG_INFO("EventLoop: started (backend={})", BackendToString(impl_.GetBackend()))
        // BackendToString: 将IOBackend枚举转为字符串 ("epoll"/"iocp"/"kqueue"/"poll")
        // 定义在 platform/io_backend_utils.cpp 中
        WHILE state_ == kRunning:
            // 步骤1: 获取最近定时器剩余时间作为IO等待上限
            //   std::nullopt 表示无定时器 → 可无限等待,直到IO事件到达
            timeout_opt = timer_queue_.GetNextTimeout()

            // 步骤2: 等待IO事件就绪 (委托给平台实现)
            event_batch = impl_.WaitForEvents(timeout_opt, kMaxEventsPerBatch)

            // 步骤3: 分派就绪事件到注册的Handler
            FOR EACH event IN event_batch:
                handler = STATIC_CAST<IEventHandler*>(event.user_context)
                IF handler IS nullptr:
                    CONTINUE
                IF event.mask HAS kReadable:
                    handler.OnReadable()
                IF event.mask HAS kWritable:
                    handler.OnWritable()
                IF event.mask HAS kError:
                    LOG_WARN("EventLoop: IO error on fd={}, code={}",
                             event.fd_or_handle, event.error_code)
                    handler.OnError(event.error_code)

            // 步骤4: 触发已到期的定时器回调
            timer_queue_.FireExpired(Clock::NowMs())

            // 步骤5: 批量执行投递的异步任务
            pending_tasks_.ExecuteAll()

        LOG_INFO("EventLoop: stopped")
    // 停止事件循环 (线程安全,可从任何线程调用)
    FUNCTION Stop() -> void:
        state_ = kStopped
        WakeUp()  // 如果Run正在阻塞等待IO,立即唤醒以退出循环

    // -------------------- IO事件管理 --------------------

    // 注册文件描述符/句柄及其关注的事件类型
    // handler的生命周期由调用方管理,必须保证在Unregister前有效
    FUNCTION Register(
            desc: EventDesc,
            mask: IOMask,
            handler: IEventHandler*
    ) -> void:
        LOG_DEBUG("EventLoop: registered fd={}, mask={:x}", desc.fd_or_handle, mask)
        impl_.Register(desc, mask, handler)

    // 修改已注册描述符的关注事件掩码
    FUNCTION Modify(desc: EventDesc, new_mask: IOMask) -> void:
        impl_.Modify(desc, new_mask)

    // 取消注册 (不再接收此描述符的事件通知)
    FUNCTION Unregister(desc: EventDesc) -> void:
        LOG_DEBUG("EventLoop: unregistered fd={}", desc.fd_or_handle)
        impl_.Unregister(desc)

    // -------------------- 任务投递 --------------------

    // 向EventLoop线程安全地投递一个可移动闭包
    // 常用于: 跨线程操作Session / 延迟执行 / 异步回调通知
    FUNCTION PostTask(task: std::move_only_function<void()>) -> void:
        pending_tasks_.Push(std::move(task))
        WakeUp()  // 如果EventLoop正在阻塞,唤醒它以立即处理任务

    // -------------------- 定时器管理 --------------------

    // 添加一次性定时器,到时后执行callback一次
    FUNCTION AddTimer(
            delay_ms: uint32_t,
            callback: std::move_only_function<void()>
    ) -> TimerHandle:
        handle = timer_queue_.Add(delay_ms, std::move(callback), /*repeat=*/false)
        LOG_TRACE("EventLoop: timer added, delay={}ms, handle={}", delay_ms, handle)
        RETURN handle

    // 添加周期性定时器,每隔interval_ms重复执行callback
    FUNCTION AddPeriodicTimer(
            interval_ms: uint32_t,
            callback: std::move_only_function<void()>
    ) -> TimerHandle:
        handle = timer_queue_.Add(interval_ms, std::move(callback), /*repeat=*/true)
        LOG_TRACE("EventLoop: periodic timer added, interval={}ms, handle={}", interval_ms, handle)
        RETURN handle

    // 取消定时器 (延迟删除: 仅标记取消,在下次Fire时跳过并清理)
    FUNCTION CancelTimer(handle: TimerHandle) -> void:
        LOG_TRACE("EventLoop: timer canceled, handle={}", handle)
        timer_queue_.Cancel(handle)

    // -------------------- 私有 --------------------
    PRIVATE FUNCTION WakeUp() -> void:
        // 向wakeup_channel_写入标记,唤醒正在阻塞的WaitForEvents调用
        impl_.WakeUp(wakeup_channel_)

    PRIVATE MEMBER impl_: std::unique_ptr<IOBackendImpl>  // 平台实现 (Pimpl惯用法)
    PRIVATE MEMBER state_: RunState = kStopped
    PRIVATE MEMBER pending_tasks_: TaskQueue               // 异步任务队列
    PRIVATE MEMBER timer_queue_: TimerQueue                // 定时器队列
    PRIVATE MEMBER wakeup_channel_: WakeupHandle           // 唤醒通道句柄
```

---

## 2. DatagramSocket — 数据报Socket抽象

```
// ============================================================
// 类名: DatagramSocket
// 描述: 非阻塞数据报Socket的RAII封装
//       适配UDP/UDPLite/Unix Domain Dgram,统一为Datagram语义
// ============================================================
CLASS DatagramSocket:
    // -------------------- 嵌套类型 --------------------

    // 协议无关的地址表示
    STRUCT Address:
        ip: std::string         // IPv4/IPv6地址字符串 或 Unix Domain路径
        port: uint16_t          // 端口 (Unix Domain时忽略)
        family: AddressFamily   // kIPv4 / kIPv6 / kUnixDomain

        OPERATOR ==(other: Address) -> bool:
            RETURN ip == other.ip AND port == other.port AND family == other.family

        OPERATOR !=(other: Address) -> bool:
            RETURN NOT (*this == other)

        STATIC FUNCTION Any() -> Address:
            addr = Address{}
            addr.ip = "0.0.0.0"
            addr.port = 0
            addr.family = kIPv4
            RETURN addr

        STATIC FUNCTION From(ip: string, port: uint16_t) -> Address:
            addr = Address{}
            addr.ip = ip
            addr.port = port
            addr.family = DetectFamily(ip)
            RETURN addr

        // 返回人类可读的地址表示: "ip:port" 或 "unix:/path" (Unix Domain)
        FUNCTION ToString() -> std::string:
            IF family == AddressFamily::kUnixDomain:
                RETURN "unix:" + ip
            RETURN ip + ":" + std::to_string(port)

        // 从平台原生sockaddr结构转换为Address (平台相关实现)
        STATIC FUNCTION FromSystem(sa: const sockaddr*, addr_len: socklen_t) -> Address:
            // 实现位于 platform/<os>/address_utils.cpp:
            //   - IPv4: 提取sin_addr→ip, sin_port→port (ntohs)
            //   - IPv6: 提取sin6_addr→ip, sin6_port→port (ntohs)
            //   - Unix: 提取sun_path→ip, family=kUnixDomain
            // 根据sa_family分派: AF_INET / AF_INET6 / AF_UNIX

    // 接收结果: 数据指针指向调用方传入的缓冲区
    // 调用方必须在RecvResult生命周期内保持buffer有效
    STRUCT RecvResult:
        data: const uint8_t*      // 数据指针 (生命周期与RecvFrom的buffer一致)
        len: size_t               // 实际接收的数据字节数
        sender: Address           // 数据报来源地址
        timestamp_ms: uint64_t    // 接收时刻的时间戳 (用于RTT精确计算)

    // -------------------- 配置结构 --------------------
    STRUCT SocketConfig:
        reuse_addr: bool = true               // SO_REUSEADDR (快速重启)
        recv_buf_bytes: uint32_t = 256*1024   // SO_RCVBUF
        send_buf_bytes: uint32_t = 256*1024   // SO_SNDBUF
        dscp: uint8_t = 0                     // DSCP/TOS (QoS标记, 0=默认)
        ttl: uint8_t = 64                     // TTL

        STATIC FUNCTION Default() -> SocketConfig:
            RETURN SocketConfig{}

    // -------------------- 构造与析构 --------------------
    CONSTRUCTOR DatagramSocket(
            event_loop: EventLoop*,
            bind_addr: Address = Address::Any(),
            config: SocketConfig = SocketConfig::Default()
    ):
        event_loop_ = event_loop
        config_ = config

        // 创建数据报Socket,设为非阻塞模式
        fd_ = ::socket(bind_addr.family.ToSystem(), SOCK_DGRAM, 0)
        IF fd_ < 0:
            THROW std::runtime_error("socket() failed")
        SetNonBlocking(fd_, true)

        // 通用Socket选项 (从config读取,无硬编码)
        SetReuseAddress(fd_, config_.reuse_addr)
        SetRecvBufferSize(fd_, config_.recv_buf_bytes)
        SetSendBufferSize(fd_, config_.send_buf_bytes)
        // 可选: 设置TOS/DSCP、TTL、MULTICAST_LOOP 等

        Bind(fd_, bind_addr)

    DESTRUCTOR ~DatagramSocket():
        IF fd_ IS VALID:
            ::close(fd_)

    // 禁止拷贝,允许移动
    DatagramSocket(const DatagramSocket&) = delete
    DatagramSocket& operator=(const DatagramSocket&) = delete
    DatagramSocket(DatagramSocket&& other) = default
    DatagramSocket& operator=(DatagramSocket&& other) = default

    // -------------------- 数据收发 --------------------

    // 非阻塞发送,立即返回发送字节数或错误码
    FUNCTION SendTo(
            data: const uint8_t*,    // [in] 待发送数据
            len: size_t,             // [in] 数据长度
            dest: Address            // [in] 目标地址
    ) -> std::expected<int, SocketError>:
        // 非阻塞发送: POSIX使用MSG_DONTWAIT标志,Windows使用已设置的
        // 非阻塞模式 (ioctlsocket FIONBIO); 平台适配由PlatformDetect在
        // 编译期选择正确的发送标志或调用方式,SendTo对外保持统一语义
        sent = ::sendto(fd_, data, len, PLATFORM_SEND_FLAGS,
                        dest.ToSystemSockaddr(), dest.SizeOfSockaddr())
        IF sent >= 0:
            RETURN sent
        IF IS_WOULD_BLOCK_ERROR():
            RETURN std::unexpected(SocketError::kWouldBlock)
        RETURN std::unexpected(SocketError::FromErrno(GetLastSocketError()))

    // 非阻塞接收,无数据时返回 nullopt, Socket错误时返回错误码
    // 注意: 需先调用 buffer.resize(capacity) 确保 capacity() == size()
    FUNCTION RecvFrom(
            buffer: uint8_t*,        // [out] 接收缓冲区
            buffer_capacity: size_t  // [in]  缓冲区可用容量
    ) -> std::expected<std::optional<RecvResult>, SocketError>:
        sender_addr: sockaddr_storage
        addr_len: socklen_t = sizeof(sender_addr)
        // 非阻塞接收: 平台适配标志由PLATFORM_RECV_FLAGS统一处理
        // (POSIX: MSG_DONTWAIT, Windows: 已设非阻塞模式)
        n = ::recvfrom(fd_, buffer, buffer_capacity, PLATFORM_RECV_FLAGS,
                       CAST(sockaddr*, &sender_addr), &addr_len)
        IF n > 0:
            result = RecvResult{}
            result.data          = buffer
            result.len           = size_t(n)
            result.sender        = Address::FromSystem(&sender_addr, addr_len)  // sockaddr→Address转换,见下方辅助函数定义
            result.timestamp_ms  = Clock::NowMs()
            RETURN result
        IF IS_WOULD_BLOCK_ERROR():
            RETURN std::nullopt                          // 无就绪数据
        // 返回值区分: ICMP错误等不影响继续使用Socket,记录日志
        RETURN std::unexpected(SocketError::FromErrno(GetLastSocketError()))

    // -------------------- 事件循环集成 --------------------

    // 注册可读通知回调 (Socket有数据到达 → EventLoop触发handler.OnReadable())
    FUNCTION SetReadHandler(handler: IEventHandler*) -> void:
        event_loop_.Register(
            EventLoop::EventDesc{fd_, Platform::Current()},  // Platform::Current(): 编译期返回当前平台枚举
                                                               // 实现: #if defined(__linux__)→kLinux, etc.
            EventLoop::IOMask::kReadable | EventLoop::IOMask::kEdgeTriggered,
            handler
        )

    // 启用可写通知 (发送缓冲区从满→可用 转变时通知)
    // 仅在发送遇到kWouldBlock后需要等待恢复时使用
    FUNCTION EnableWriteNotifications(handler: IEventHandler*) -> void:
        event_loop_.Modify(
            EventLoop::EventDesc{fd_, Platform::Current()},
            EventLoop::IOMask::kReadable | EventLoop::IOMask::kWritable
            | EventLoop::IOMask::kEdgeTriggered,
            handler
        )

    // 关闭可写通知 (恢复为仅监听可读)
    FUNCTION DisableWriteNotifications(handler: IEventHandler*) -> void:
        event_loop_.Modify(
            EventLoop::EventDesc{fd_, Platform::Current()},
            EventLoop::IOMask::kReadable | EventLoop::IOMask::kEdgeTriggered,
            handler
        )

    PRIVATE MEMBER fd_: int
    PRIVATE MEMBER event_loop_: EventLoop*
    PRIVATE MEMBER config_: SocketConfig
```

---

## 3. WorkerPool — 工作线程池

```
// ============================================================
// 类名: WorkerPool
// 描述: 固定大小的工作线程池,每个Worker绑定独立的EventLoop
//       支持多种Session→Worker分配策略
// ============================================================
CLASS WorkerPool:
    PRIVATE MEMBER workers_: std::vector<Worker>
    PRIVATE MEMBER strategy_: DispatchStrategy

    // -------------------- 分配策略 --------------------
    ENUM DispatchStrategy:
        kModuloHash       // 按routing_key取模 (默认,适合均匀分布)
        kConsistentHash   // 一致性哈希 (适合动态增减Worker)
        kRoundRobin       // 轮询
        kLeastSessions    // 最少会话优先

    // -------------------- 内部Worker结构 --------------------
    STRUCT Worker:
        thread: std::thread
        event_loop: EventLoop
        session_count: std::atomic<size_t>   // 当前绑定会话数 (kLeastSessions用)

    // -------------------- 构造 --------------------
    CONSTRUCTOR WorkerPool(
            num_workers: size_t = 0,
            strategy: DispatchStrategy = kModuloHash
    ):
        worker_count = (num_workers > 0)
                       ? num_workers
                       : std::thread::hardware_concurrency()
        strategy_ = strategy

        FOR i IN RANGE(0, worker_count):
            worker = Worker{}
            workers_.Push(std::move(worker))
            // 启动线程: EventLoop::Run() 在各自线程阻塞
            workers_[i].thread = std::thread([&workers = workers_, i]():
                workers[i].event_loop.Run()
            )

    // -------------------- 任务调度 --------------------

    // 根据routing_key选择目标Worker并投递任务
    FUNCTION Dispatch(
            routing_key: uint32_t,
            task: std::move_only_function<void()>
    ) -> void:
        index = SelectWorker(routing_key)
        workers_[index].event_loop.PostTask(std::move(task))

    // 递增/递减Worker的会话计数 (由Server/Client在创建/销毁Session时调用)
    // 这些方法是WorkerPool的Public API,供端点层使用以维护kLeastSessions准确性
    FUNCTION IncrementSessionCount(worker_index: size_t) -> void:
        workers_[worker_index].session_count.fetch_add(1, std::memory_order_relaxed)

    FUNCTION DecrementSessionCount(worker_index: size_t) -> void:
        workers_[worker_index].session_count.fetch_sub(1, std::memory_order_relaxed)

    // 获取当前Worker数量 (供端点层计算routing_key取模)
    FUNCTION GetWorkerCount() -> size_t:
        RETURN workers_.size()

    // 选择目标Worker
    PRIVATE FUNCTION SelectWorker(routing_key: uint32_t) -> size_t:
        SWITCH strategy_:
            CASE kModuloHash:
                RETURN routing_key MOD workers_.size()
            CASE kConsistentHash:
                RETURN consistent_hash_ring_.GetNode(routing_key)
            CASE kRoundRobin:
                RETURN round_robin_counter_.FetchAdd(1) MOD workers_.size()
            CASE kLeastSessions:
                RETURN FindWorkerWithMinSessions()

    // -------------------- 生命周期 --------------------
    FUNCTION Shutdown() -> void:
        // 先通知所有Worker停止EventLoop
        FOR EACH worker IN workers_:
            worker.event_loop.Stop()
        // 再等待所有线程结束
        FOR EACH worker IN workers_:
            IF worker.thread.joinable():
                worker.thread.join()
```

---

## 4. TaskQueue — 任务队列

```
// ============================================================
// 类名: TaskQueue
// 描述: 线程安全FIFO任务队列 (多生产者-单消费者)
//       默认: std::mutex + std::condition_variable + std::queue
//       可替换: 无锁MPSC队列 / 优先级队列 / 有界队列 (背压)
// ============================================================
CLASS TaskQueue:
    PRIVATE MEMBER queue_: std::queue<std::move_only_function<void()>>
    PRIVATE MEMBER mutex_: std::mutex
    PRIVATE MEMBER cv_: std::condition_variable

    FUNCTION Push(task: std::move_only_function<void()>) -> void:
        LOCK(mutex_):
            queue_.push(std::move(task))
        cv_.notify_one()

    FUNCTION Pop() -> std::move_only_function<void()>:
        LOCK(mutex_):
            cv_.wait(lock, [this](){ RETURN !queue_.empty() })
            task = std::move(queue_.front())
            queue_.pop()
            RETURN task

    FUNCTION TryPop() -> std::optional<std::move_only_function<void()>>:
        LOCK(mutex_):
            IF queue_.empty():
                RETURN std::nullopt
            task = std::move(queue_.front())
            queue_.pop()
            RETURN task

    // 批量消费: 交换到本地队列后锁外执行,减少锁竞争
    FUNCTION ExecuteAll() -> void:
        local = std::queue<std::move_only_function<void()>>{}
        LOCK(mutex_):
            std::swap(local, queue_)
        WHILE !local.empty():
            local.front()()
            local.pop()
```

---

## 5. TimerQueue — 定时器管理

```
// ============================================================
// 类名: TimerQueue
// 描述: 基于小顶堆的定时器管理器 (可替换为分层时间轮)
//       所有操作线程安全,支持延迟删除
// ============================================================
CLASS TimerQueue:
    STRUCT TimerEntry:
        id: TimerHandle
        expire_time: uint64_t                          // 绝对到期时间(ms)
        interval_ms: uint32_t                          // 重复间隔 (0=一次性)
        callback: std::move_only_function<void()>
        OPERATOR >(other: TimerEntry) -> bool:
            RETURN expire_time > other.expire_time     // 小顶堆: 早到期优先

    PRIVATE MEMBER heap_: std::priority_queue<
        TimerEntry, std::vector<TimerEntry>, std::greater<TimerEntry>>
    PRIVATE MEMBER canceled_: std::unordered_set<TimerHandle>
    PRIVATE MEMBER next_id_: TimerHandle = 1
    PRIVATE MEMBER mutex_: std::mutex

    FUNCTION Add(
            delay_or_interval_ms: uint32_t,
            callback: std::move_only_function<void()>,
            repeat: bool
    ) -> TimerHandle:
        LOCK(mutex_):
            id = next_id_++
            entry = TimerEntry{}
            entry.id = id
            entry.expire_time = Clock::NowMs() + delay_or_interval_ms
            entry.interval_ms = repeat ? delay_or_interval_ms : 0
            entry.callback = std::move(callback)
            heap_.push(std::move(entry))
            RETURN id

    FUNCTION Cancel(id: TimerHandle) -> void:
        LOCK(mutex_):
            canceled_.insert(id)

    // 计算距最近定时器到期的剩余时间 (供EventLoop确定Wait超时)
    FUNCTION GetNextTimeout() -> std::optional<uint32_t>:
        LOCK(mutex_):
            // 惰性清理堆顶已取消条目
            WHILE !heap_.empty() AND canceled_.contains(heap_.top().id):
                canceled_.erase(heap_.top().id)
                heap_.pop()
            IF heap_.empty():
                RETURN std::nullopt             // 无定时器 → EventLoop可无限等待
            now = Clock::NowMs()
            remaining = heap_.top().expire_time - now
            RETURN MAX(0, remaining)

    // 执行所有已到期的定时器回调
    // 注意: 回调在锁内执行; 回调中不得:
    //   a. 调用TimerQueue的Add/Cancel — 会导致死锁 (mutex_非递归)
    //   b. 执行长时间阻塞操作 — 会阻塞所有定时器的触发和GetNextTimeout调用
    // 如回调需要上述操作,应在回调中将任务投递到TaskQueue异步执行
    FUNCTION FireExpired(now: uint64_t) -> void:
        LOCK(mutex_):
            WHILE !heap_.empty() AND heap_.top().expire_time <= now:
                entry = heap_.top()
                heap_.pop()
                IF canceled_.contains(entry.id):
                    canceled_.erase(entry.id)
                    CONTINUE
                entry.callback()            // 执行回调
                IF entry.interval_ms > 0:   // 重复定时器: 更新到期时间后重新入堆
                    entry.expire_time = now + entry.interval_ms
                    heap_.push(std::move(entry))
```

---

## 6. IEventHandler — 事件处理器接口

```
// ============================================================
// 接口: IEventHandler
// 描述: IO事件回调接口,由需要监听Socket事件的类实现
// ============================================================
INTERFACE IEventHandler:
    VIRTUAL FUNCTION OnReadable() -> void = 0           // 描述符可读
    VIRTUAL FUNCTION OnWritable() -> void { /* 默认空 */ }  // 描述符可写
    VIRTUAL FUNCTION OnError(error_code: int) -> void { /* 默认空 */ }  // 异常
    VIRTUAL ~IEventHandler() = default
```

---

## 7. Message — 用户消息封装

```
// ============================================================
// 类名: Message
// 描述: 封装从传输层完整接收的用户数据消息
//       支持零拷贝视图 (span / string_view) 和所有权转移
// ============================================================
CLASS Message:
    PRIVATE MEMBER data_: std::vector<uint8_t>             // 消息体
    PUBLIC MEMBER session_id: uint32_t                     // 来源会话ID
    PUBLIC MEMBER receive_time_ms: uint64_t                // 接收时间戳

    CONSTRUCTOR Message(
            buf: const uint8_t*,     // [in] 数据指针
            len: size_t,             // [in] 数据长度
            sid: uint32_t            // [in] 会话ID
    ):
        data_(buf, buf + len),           // 拷贝数据
        session_id(sid),
        receive_time_ms(Clock::NowMs())
    {}

    // 只读访问 (零拷贝)
    FUNCTION Data() -> const uint8_t*:
        RETURN data_.data()

    FUNCTION Size() -> size_t:
        RETURN data_.size()

    FUNCTION AsSpan() -> std::span<const uint8_t>:
        RETURN std::span<const uint8_t>(data_.data(), data_.size())

    FUNCTION AsStringView() -> std::string_view:
        RETURN std::string_view(
            reinterpret_cast<const char*>(data_.data()), data_.size())

    // 移动取出数据所有权 (跨线程传递,避免拷贝)
    FUNCTION TakeBytes() -> std::vector<uint8_t>:
        RETURN std::move(data_)
```

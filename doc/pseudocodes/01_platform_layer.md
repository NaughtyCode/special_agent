# Platform Layer (平台抽象层) 伪代码

平台层负责封装操作系统资源，向上层提供与具体IO模型和线程模型无关的统一异步接口。所有组件均支持注入和替换。

---

## 1. EventLoop — 统一事件循环

```
// ============================================================
// 类名: EventLoop
// 描述: 跨平台IO事件循环抽象
//       封装 epoll(Linux) / IOCP(Windows) / kqueue(macOS/BSD)
//       统一接口,调用方无需关心底层IO模型差异
// ============================================================
CLASS EventLoop:
    // -------------------- 嵌套类型 --------------------
    // IO事件掩码 (位标志,可组合)
    FLAGS IOMask:
        kReadable  = 0x01   // 可读事件
        kWritable  = 0x02   // 可写事件
        kError     = 0x04   // 错误事件
        kEdgeTriggered = 0x10  // 边缘触发 (推荐用于高性能场景)

    // 统一的事件描述符 (跨平台句柄抽象)
    STRUCT EventDesc:
        fd_or_handle: uintptr_t              // 文件描述符或句柄
        platform_tag: Platform               // 平台标记

    // -------------------- 构造与析构 --------------------
    CONSTRUCTOR EventLoop(backend: IOBackend = kAutoDetect):
        // 自动选择当前平台最优IO模型
        // 也可手动指定: kEpoll / kIocp / kKqueue / kPoll (回退方案)
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

        // 创建内部唤醒机制 (用于跨线程唤醒事件循环)
        // 不同平台采用不同实现:
        //   Linux → eventfd
        //   macOS/BSD → pipe 或 kqueue user event
        //   Windows → PostQueuedCompletionStatus
        wakeup_channel_ = impl_.CreateWakeupChannel()

    DESTRUCTOR ~EventLoop():
        Stop()
        impl_.reset()

    // -------------------- 生命周期管理 --------------------

    // 启动事件循环 (阻塞调用,直到Stop被调用)
    FUNCTION Run() -> void:
        state_ = kRunning
        WHILE state_ == kRunning:
            // 步骤1: 计算等待超时 — 取最近定时器剩余时间
            timeout_ms = timer_queue_.GetNextTimeout()

            // 步骤2: 等待IO事件就绪 (委托给平台实现)
            event_batch = impl_.WaitForEvents(timeout_ms, kMaxEventsPerBatch)

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
                    handler.OnError(event.error_code)

            // 步骤4: 处罚已到期的定时器回调
            timer_queue_.FireExpired(Clock::NowMs())

            // 步骤5: 批量执行投递的异步任务
            pending_tasks_.ExecuteAll()

    // 停止事件循环 (线程安全,可从任何线程调用)
    FUNCTION Stop() -> void:
        state_ = kStopped
        WakeUp()  // 如果Run正在阻塞等待,将其唤醒

    // -------------------- IO事件管理 --------------------

    // 注册文件描述符/句柄及其关注的事件类型
    FUNCTION Register(
            desc: EventDesc,
            mask: IOMask,
            handler: IEventHandler*
    ) -> void:
        // 将 (desc, mask, handler) 三元组注册到底层IO复用器
        // handler的生命周期由调用方管理,必须保证在Unregister之前有效
        impl_.Register(desc, mask, handler)

    // 修改已注册描述符的关注事件掩码
    FUNCTION Modify(desc: EventDesc, new_mask: IOMask) -> void:
        impl_.Modify(desc, new_mask)

    // 取消注册
    FUNCTION Unregister(desc: EventDesc) -> void:
        impl_.Unregister(desc)

    // -------------------- 任务投递 --------------------

    // 向EventLoop线程安全地投递一个闭包任务
    // 常用于: 跨线程操作Session / 延迟执行 / 异步回调
    FUNCTION PostTask(task: std::move_only_function<void()>) -> void:
        pending_tasks_.Push(std::move(task))
        WakeUp()  // 如果EventLoop正在阻塞等待IO,立即唤醒以处理任务

    // -------------------- 定时器管理 --------------------

    // 添加一次性定时器
    FUNCTION AddTimer(
            delay_ms: uint32_t,
            callback: std::move_only_function<void()>
    ) -> TimerHandle:
        RETURN timer_queue_.Add(delay_ms, std::move(callback), /*repeat=*/false)

    // 添加周期性定时器
    FUNCTION AddPeriodicTimer(
            interval_ms: uint32_t,
            callback: std::move_only_function<void()>
    ) -> TimerHandle:
        RETURN timer_queue_.Add(interval_ms, std::move(callback), /*repeat=*/true)

    // 取消定时器 (延迟删除,下次Fire时跳过)
    FUNCTION CancelTimer(handle: TimerHandle) -> void:
        timer_queue_.Cancel(handle)

    // -------------------- 内部唤醒机制 --------------------
    PRIVATE FUNCTION WakeUp() -> void:
        // 向wakeup_channel_写入一个标记,将阻塞的WaitForEvents唤醒
        // 此操作线程安全,且开销很小
        impl_.WakeUp(wakeup_channel_)

    PRIVATE MEMBER impl_: std::unique_ptr<IOBackendImpl>  // 平台相关实现 (Pimpl)
    PRIVATE MEMBER state_: RunState = kStopped
    PRIVATE MEMBER pending_tasks_: TaskQueue               // 异步任务队列
    PRIVATE MEMBER timer_queue_: TimerQueue                // 定时器队列
    PRIVATE MEMBER wakeup_channel_: WakeupHandle           // 跨线程唤醒句柄
```

---

## 2. DatagramSocket — 数据报Socket抽象

```
// ============================================================
// 类名: DatagramSocket
// 描述: 非阻塞数据报Socket的RAII封装
//       抽象底层为通用Datagram,可适配UDP/UDPLite/Unix Domain Dgram
// ============================================================
CLASS DatagramSocket:
    // -------------------- 嵌套类型 --------------------
    // Socket地址 (协议无关的地址表示)
    STRUCT Address:
        ip: std::string         // IPv4/IPv6地址字符串 或 Unix Domain路径
        port: uint16_t          // 端口 (Unix Domain时忽略)
        family: AddressFamily   // kIPv4 / kIPv6 / kUnixDomain

    // 接收结果
    STRUCT RecvResult:
        // 注意: data字段指向调用方传入的缓冲区,非独立内存
        // 调用方需在使用完数据后自行管理缓冲区的生命周期
        data: const uint8_t*      // 数据指针 (生命周期与RecvFrom的buffer参数一致)
        len: size_t               // 实际接收的数据字节数
        sender: Address           // 数据报来源地址
        timestamp_ms: uint64_t    // 接收时间戳 (用于精确RTT计算)

    // -------------------- 构造与析构 --------------------
    CONSTRUCTOR DatagramSocket(
            event_loop: EventLoop*,
            bind_addr: Address = Address::Any(),
            config: SocketConfig = SocketConfig::Default()
    ):
        event_loop_ = event_loop

        // 创建Socket并设置非阻塞模式
        fd_ = ::socket(bind_addr.family.ToSystem(), SOCK_DGRAM, 0)
        SetNonBlocking(fd_, true)

        // 通用Socket选项配置 (从config中读取,无硬编码值)
        SetReuseAddress(fd_, config.reuse_addr)
        SetRecvBufferSize(fd_, config.recv_buf_bytes)
        SetSendBufferSize(fd_, config.send_buf_bytes)
        // 可选: 设置TOS/DSCP (QoS标记), TTL, 等

        // 绑定到指定地址 (port=0 则由OS自动分配)
        Bind(fd_, bind_addr)

    DESTRUCTOR ~DatagramSocket():
        IF fd_ IS VALID:
            CloseSocket(fd_)

    MOVABLE_ONLY(DatagramSocket)   // 禁用拷贝,允许移动

    // -------------------- 数据收发 --------------------

    // 非阻塞发送数据到指定远端地址,立即返回实际发送字节数或错误
    FUNCTION SendTo(
            data: const uint8_t*,    // [in]  待发送数据
            len: size_t,             // [in]  数据长度
            dest: Address            // [in]  目标地址
    ) -> std::expected<int, SocketError>:
        // 非阻塞sendto,返回实际发送字节数
        sent = ::sendto(fd_, data, len, MSG_DONTWAIT,
                        dest.ToSystemSockaddr(), dest.SizeOfSockaddr())
        IF sent >= 0:
            RETURN sent
        IF errno IS EAGAIN OR errno IS EWOULDBLOCK:
            RETURN SocketError::kWouldBlock     // 发送缓冲区满,稍后重试
        RETURN SocketError::FromErrno(errno)    // 其他错误

    // 非阻塞接收数据,无数据时返回 nullopt
    FUNCTION RecvFrom(
            buffer: uint8_t*,        // [out] 接收缓冲区 (调用方提供)
            buffer_capacity: size_t  // [in]  缓冲区容量
    ) -> std::optional<RecvResult>:
        sender_addr: sockaddr_storage
        addr_len: socklen_t = sizeof(sender_addr)
        n = ::recvfrom(fd_, buffer, buffer_capacity, MSG_DONTWAIT,
                       CAST(sockaddr*, &sender_addr), &addr_len)
        IF n > 0:
            RETURN RecvResult{
                .data          = buffer,
                .len           = size_t(n),
                .sender        = Address::FromSystem(&sender_addr, addr_len),
                .timestamp_ms  = Clock::NowMs()
            }
        IF errno IS EAGAIN OR errno IS EWOULDBLOCK:
            RETURN std::nullopt                    // 无就绪数据
        // 其他错误: ISR中断/ICMP错误等 → 记录日志并返回nullopt
        // 不对UDP"连接"产生致命影响
        RETURN std::nullopt

    // -------------------- 事件循环注册 --------------------

    // 设置可读回调 (通常在Socket可读时触发 → 调用RecvFrom)
    FUNCTION SetReadHandler(handler: IEventHandler*) -> void:
        event_loop_.Register(
            EventLoop::EventDesc{fd_, Platform::Current()},
            EventLoop::IOMask::kReadable | EventLoop::IOMask::kEdgeTriggered,
            handler
        )

    // 当发送缓冲区从满变为可写时 (kWouldBlock恢复), 可启用此通知
    FUNCTION SetWriteHandler(handler: IEventHandler*) -> void:
        // 按需注册,一般不需要 (仅在发送缓冲满后等待恢复时使用)
        event_loop_.Modify(
            EventLoop::EventDesc{fd_, Platform::Current()},
            EventLoop::IOMask::kReadable | EventLoop::IOMask::kWritable,
            handler
        )

    // -------------------- 配置结构 --------------------
    STRUCT SocketConfig:
        reuse_addr: bool = true               // SO_REUSEADDR
        recv_buf_bytes: uint32_t = 256*1024   // SO_RCVBUF
        send_buf_bytes: uint32_t = 256*1024   // SO_SNDBUF
        dscp: uint8_t = 0                     // QoS标记 (0=默认)
        ttl: uint8_t = 64                     // TTL

        STATIC FUNCTION Default() -> SocketConfig:
            RETURN SocketConfig{}
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

    // -------------------- 分配策略枚举 --------------------
    ENUM DispatchStrategy:
        kModuloHash       // 按routing_key取模 (默认,适合均匀分布)
        kConsistentHash   // 一致性哈希 (适合动态增减Worker)
        kRoundRobin       // 轮询
        kLeastSessions    // 最少会话数

    // -------------------- 构造 --------------------
    CONSTRUCTOR WorkerPool(
            num_workers: size_t = 0,                     // 0=CPU核心数
            strategy: DispatchStrategy = kModuloHash
    ):
        worker_count = (num_workers > 0) ? num_workers
                                         : std::thread::hardware_concurrency()
        strategy_ = strategy

        FOR i IN RANGE(0, worker_count):
            workers_.EmplaceBack([this, i](WorkerContext ctx):
                ctx.event_loop.Run()   // 每个Worker在自己的EventLoop中阻塞运行
            )

    // -------------------- 会话分配 --------------------

    // 根据策略为Session分配Worker并投递任务
    FUNCTION Dispatch(
            routing_key: uint64_t,
            task: std::move_only_function<void()>
    ) -> void:
        index = SelectWorker(routing_key)
        workers_[index].event_loop.PostTask(std::move(task))

    // 选择目标Worker
    PRIVATE FUNCTION SelectWorker(routing_key: uint64_t) -> size_t:
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
        FOR EACH worker IN workers_:
            worker.event_loop.Stop()
        FOR EACH worker IN workers_:
            worker.thread.join()
```

---

## 4. TaskQueue — 任务队列 (可替换实现)

```
// ============================================================
// 类名: TaskQueue
// 描述: 线程安全FIFO任务队列
//       默认实现: std::mutex + std::condition_variable + std::queue
//       可替换为: 无锁队列 (MPSC)、优先级队列、有界队列
// ============================================================
CLASS TaskQueue:
    PRIVATE MEMBER queue_: std::queue<std::move_only_function<void()>>
    PRIVATE MEMBER mutex_: std::mutex
    PRIVATE MEMBER cv_: std::condition_variable

    // 添加任务 (线程安全, 多生产者)
    FUNCTION Push(task: std::move_only_function<void()>) -> void:
        LOCK(mutex_):
            queue_.push(std::move(task))
        cv_.notify_one()   // 通知等待的消费者

    // 阻塞等待并取出任务 (单消费者)
    FUNCTION Pop() -> std::move_only_function<void()>:
        LOCK(mutex_):
            cv_.wait(lock, [this](){ RETURN !queue_.empty() })
            task = std::move(queue_.front())
            queue_.pop()
            RETURN task

    // 非阻塞尝试取出任务
    FUNCTION TryPop() -> std::optional<std::move_only_function<void()>>:
        LOCK(mutex_):
            IF queue_.empty():
                RETURN std::nullopt
            task = std::move(queue_.front())
            queue_.pop()
            RETURN task

    // 批量消费: 一次性取出所有任务并执行 (避免频繁加锁)
    FUNCTION ExecuteAll() -> void:
        // 先交换到一个本地队列,在锁外执行 → 减少锁竞争
        local_queue = std::queue<std::move_only_function<void()>>{}
        LOCK(mutex_):
            std::swap(local_queue, queue_)
        WHILE !local_queue.empty():
            local_queue.front()()
            local_queue.pop()
```

---

## 5. TimerQueue — 定时器管理

```
// ============================================================
// 类名: TimerQueue
// 描述: 基于小顶堆的定时器管理器
//       也可替换为时间轮 (适合大量短周期定时器) 等更高效结构
// ============================================================
CLASS TimerQueue:
    STRUCT TimerEntry:
        id: TimerHandle
        expire_time: uint64_t                          // 绝对到期时间(ms)
        interval_ms: uint32_t                          // 重复间隔 (0=一次性)
        callback: std::move_only_function<void()>
        // 堆排序: 按expire_time升序
        OPERATOR >(other: TimerEntry) -> bool:
            RETURN expire_time > other.expire_time

    PRIVATE MEMBER heap_: std::priority_queue<
        TimerEntry, std::vector<TimerEntry>, std::greater<TimerEntry>>
    PRIVATE MEMBER canceled_: std::unordered_set<TimerHandle> // 取消集
    PRIVATE MEMBER next_id_: TimerHandle = 1
    PRIVATE MEMBER mutex_: std::mutex

    // 添加定时器,返回句柄
    FUNCTION Add(
            delay_or_interval_ms: uint32_t,
            callback: std::move_only_function<void()>,
            repeat: bool
    ) -> TimerHandle:
        LOCK(mutex_):
            id = next_id_++
            heap_.push(TimerEntry{
                .id          = id,
                .expire_time = Clock::NowMs() + delay_or_interval_ms,
                .interval_ms = repeat ? delay_or_interval_ms : 0,
                .callback    = std::move(callback)
            })
            RETURN id

    // 取消定时器 (延迟删除标记)
    FUNCTION Cancel(id: TimerHandle) -> void:
        LOCK(mutex_):
            canceled_.insert(id)

    // 计算最近超时剩余时间 (供EventLoop确定Wait超时)
    FUNCTION GetNextTimeout() -> std::optional<uint32_t>:
        LOCK(mutex_):
            // 清理堆顶已取消条目
            WHILE !heap_.empty() AND canceled_.contains(heap_.top().id):
                canceled_.erase(heap_.top().id)
                heap_.pop()
            IF heap_.empty():
                RETURN std::nullopt        // 无定时器 → kInfinite
            now = Clock::NowMs()
            remaining = heap_.top().expire_time - now
            RETURN MAX(0, remaining)

    // 执行所有已到期的定时器
    FUNCTION FireExpired(now: uint64_t) -> void:
        LOCK(mutex_):
            WHILE !heap_.empty() AND heap_.top().expire_time <= now:
                entry = heap_.top()
                heap_.pop()
                IF canceled_.contains(entry.id):
                    canceled_.erase(entry.id)
                    CONTINUE
                // 在锁内执行回调 (如回调耗时,可改为投递到任务队列)
                entry.callback()
                // 重复定时器重新入堆
                IF entry.interval_ms > 0:
                    entry.expire_time = now + entry.interval_ms
                    heap_.push(std::move(entry))
```

---

## 6. IEventHandler — 事件处理器接口

```
// ============================================================
// 接口: IEventHandler
// 描述: IO事件回调接口,由需要使用EventLoop的类实现
// ============================================================
INTERFACE IEventHandler:
    // 描述符可读时回调 (如Socket有数据到达)
    VIRTUAL FUNCTION OnReadable() -> void = 0

    // 描述符可写时回调 (如Socket发送缓冲区由满恢复)
    VIRTUAL FUNCTION OnWritable() -> void { /* 默认空实现 */ }

    // 描述符发生错误时回调
    VIRTUAL FUNCTION OnError(error_code: int) -> void { /* 默认空实现 */ }
```

---

## 7. Message — 用户消息封装

```
// ============================================================
// 类名: Message
// 描述: 封装从传输层完整接收的用户数据
//       支持零拷贝访问 (string_view / span) 和移动语义
// ============================================================
CLASS Message:
    // 数据可来自多种底层 (便于后续扩展)
    USING DataBuffer = std::variant<
        std::vector<uint8_t>,           // 自有数据 (默认)
        std::shared_ptr<const uint8_t[]> // 共享数据 (零拷贝)
    >

    PRIVATE MEMBER data_: DataBuffer
    PRIVATE MEMBER data_view_: std::span<const uint8_t>  // 统一视图
    PUBLIC MEMBER session_id: uint32_t                    // 来源会话ID
    PUBLIC MEMBER receive_time_ms: uint64_t               // 接收时间戳

    // 从原始数据构造 (拷贝模式)
    CONSTRUCTOR Message(
            buf: const uint8_t*,       // [in] 数据指针
            len: size_t,               // [in] 数据长度
            sid: uint32_t              // [in] 会话ID
    ):
        data_ = std::vector<uint8_t>(buf, buf + len)
        data_view_ = std::span<const uint8_t>(
            std::get<std::vector<uint8_t>>(data_))
        session_id = sid
        receive_time_ms = Clock::NowMs()

    // 访问接口
    FUNCTION Data() -> const uint8_t*:
        RETURN data_view_.data()

    FUNCTION Size() -> size_t:
        RETURN data_view_.size()

    FUNCTION AsSpan() -> std::span<const uint8_t>:
        RETURN data_view_

    FUNCTION AsStringView() -> std::string_view:
        RETURN std::string_view(
            reinterpret_cast<const char*>(data_view_.data()),
            data_view_.size()
        )

    // 移动数据所有权 (用于跨线程传递,避免拷贝)
    FUNCTION TakeData() -> DataBuffer:
        RETURN std::move(data_)
```

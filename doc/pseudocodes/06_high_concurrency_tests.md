# 高并发单元测试需求

本文档定义网络库各模块在高并发场景下的单元测试需求，覆盖线程安全性、竞态条件、负载压力、内存安全及确定性仿真等维度。

---

## 1. 测试基础设施要求

```
// ============================================================
// 描述: 高并发测试所需的基础设施与工具
// ============================================================

// 1.1 确定性模拟时钟 (SimulatedClock)
//     用途: 消除真实时间的不确定性,精确控制协议超时/重传/定时器行为
//     要求:
//       - Clock::NowMs() 可注入为模拟时钟实现
//       - 支持手动推进时间: AdvanceTime(delta_ms)
//       - 支持精确到ms的时间控制,以便验证重传/RTO等时序敏感逻辑
//       - 定时器到期行为与真实时钟语义一致 (同一AdvanceTime内先到期的先触发)
//     覆盖: 所有TimerQueue相关测试, 协议重传时序测试, 竞态条件复现

// 1.2 网络模拟器 (NetworkSimulator)
//     用途: 在单进程内模拟数据报的延迟/丢包/乱序/重复,无需真实网络
//     要求:
//       - 可注入到 DatagramSocket 或 ProtocolEngine 的 OutputCallback 链路中
//       - 支持配置: delay_ms(min, max), drop_rate(0.0~1.0),
//         duplicate_rate(0.0~1.0), reorder_window(包数)
//       - 确定性: 使用可指定种子的伪随机数生成器,相同种子产生相同网络行为
//       - 支持动态修改链路参数 (模拟网络条件变化)
//     覆盖: Session重传逻辑, 乱序包重组, 流控行为, 网络分区恢复

// 1.3 竞态检测工具集成
//     要求:
//       - CI流水线中使用 ThreadSanitizer (TSan) 编译和运行所有并发测试
//         TSan检测: 数据竞争、未同步的共享变量访问
//       - CI中使用 AddressSanitizer (ASan) 检测内存错误
//         ASan检测: use-after-free、堆/栈缓冲区溢出、内存泄漏
//       - 可选: Helgrind (Valgrind工具) 检测锁顺序问题和潜在死锁
//     覆盖: 所有多线程测试的自动检测

// 1.4 并发压力测试框架
//     要求:
//       - 可配置参数: 线程数 / 每线程操作数 / 操作类型混合比例 / 运行时长
//       - 结果收集: 吞吐量(ops/s) / 延迟分布(P50/P95/P99) / 错误率
//       - 确定性: 相同种子产生相同操作序列 (可复现,便于回归对比)
//       - 操作类型: Send / FeedInput / Close / Connect / Disconnect 按比例混合
//     覆盖: 所有模块的负载和压力测试
```

---

## 2. TaskQueue 并发测试

```
// ============================================================
// 模块: TaskQueue (MPSC队列)
// 关键并发属性: 多生产者安全入队, 单消费者安全出队
// ============================================================

// 2.1 基本MPSC正确性
TEST TaskQueue_MultiProducerSingleConsumer_Correctness:
    // 配置: N个生产者线程 (N=4,8), 1个消费者线程
    // 操作: 每个生产者Push M个任务 (M=100K)
    //       任务内容: 对共享原子计数器执行 fetch_add(1)
    // 验证: 消费到的任务总数 == N * M
    //       原子计数器最终值 == N * M (无重复/无遗漏)
    //       每个任务恰好被执行一次
    //       TSan无数据竞争报告, ASan无内存错误

// 2.2 高竞争下的吞吐量
TEST TaskQueue_HighContention_Throughput:
    // 配置: 8生产者 + 1消费者, 每生产者Push 1M个任务
    // 测量: 吞吐量 (任务/秒), 与单生产者基线对比
    // 验证: 吞吐量不低于单生产者基线吞吐量的60%
    //       随生产者数量增加,吞吐量应单调递增 (至少不递减)
    //       运行期间无活锁/饥饿 (消费者持续消费,生产者持续入队)

// 2.3 ExecuteAll批量消费正确性
TEST TaskQueue_ExecuteAll_BatchConsumption:
    // 配置: 4生产者持续Push, 消费者周期性调用ExecuteAll
    // 验证: 每批ExecuteAll消费当前时刻所有已入队任务 (queue_ swap语义正确)
    //       Push与ExecuteAll并发执行: 交换后新Push的任务留在下一批
    //       无任务丢失: 总消费数 == 总Push数
    //       ExecuteAll返回后内部queue_为空 (swap后local持有全部)

// 2.4 TryPop非阻塞语义
TEST TaskQueue_TryPop_NonBlocking:
    // 验证: 空队列TryPop立即返回std::nullopt (不阻塞调用线程)
    //       有任务时TryPop立即返回任务 (不阻塞)
    //       并发Push和TryPop: TryPop每次调用要么返回一个完整任务,
    //         要么返回nullopt; 不会返回"半任务"或损坏数据
    //       TSan验证无数据竞争

// 2.5 有界队列背压 (仅在替换为有界队列实现时启用)
// 当前默认实现为无界队列 (std::queue),此测试针对BoundedTaskQueue变体
// 当编译期通过TaskQueueVariant= kBounded启用有界实现后,此测试自动激活
TEST TaskQueue_Bounded_Backpressure:
    // 前置: 使用BoundedTaskQueue (capacity=1024) 变体
    // 验证: Push在队列元素数==K时阻塞 (或返回false,取决于实现)
    //       Pop消费一个任务后,阻塞的Push被唤醒并成功入队 (背压释放)
    //       队列元素数始终不超过K
```

---

## 3. TimerQueue 并发测试

```
// ============================================================
// 模块: TimerQueue (线程安全定时器管理器)
// 关键并发属性: Add/Cancel与FireExpired之间的竞态窗口
// ============================================================

// 3.1 并发Add与FireExpired
TEST TimerQueue_ConcurrentAddAndFire:
    // 配置: 4线程并发Add定时器 (不同到期时间,分布在0~1000ms)
    //       同时主线程周期性调用 FireExpired(now) 推进时间
    // 验证: 所有未被Cancel的定时器均被触发 (无遗漏)
    //       无double-fire: 同一回调绝不会被触发两次
    //       堆数据结构无损坏: 操作后验证堆不变量 (父节点 ≤ 子节点)
    //       TSan无数据竞争报告

// 3.2 并发Cancel与FireExpired
TEST TimerQueue_ConcurrentCancelAndFire:
    // 配置: 100个定时器已Add,到期时间集中在狭窄窗口内
    //       4线程并发Cancel这100个定时器,主线程在到期时刻调用FireExpired
    // 验证: 已Cancel的定时器回调绝不触发 (Cancel的保证)
    //       FireExpired不会因Cancel而漏触发未被Cancel的定时器
    //       canceled_集合与heap_内容一致 (无"已取消但未清理"的残留)

// 3.3 Cancel无效句柄的安全性
TEST TimerQueue_CancelNonExistent_Idempotent:
    // 验证: Cancel无效句柄 (从未分配/已触发/已Cancel) 是安全的幂等操作
    //       不崩溃,不破坏内部数据结构
    //       Cancel(0) — 0是无效句柄,应直接忽略
    //       Cancel(已触发定时器的id) — 应无影响

// 3.4 重复定时器的重新入堆
TEST TimerQueue_RepeatingTimer_Reinsertion:
    // 配置: 大量重复定时器 (不同interval),跨多个FireExpired周期
    // 验证: 每个重复定时器每次Fire后:
    //       1. 回调被执行
    //       2. expire_time正确更新为 now + interval_ms
    //       3. 重新入堆后堆不变量成立
    //       总触发次数 == 预期次数 (触发次数 = 总时间 / interval)

// 3.5 GetNextTimeout并发安全
TEST TimerQueue_GetNextTimeout_Concurrent:
    // 配置: 线程A连续Add/Cancel定时器, 线程B连续调用GetNextTimeout
    // 验证: GetNextTimeout返回值始终为有效值 (>=0 或 nullopt)
    //       不会因并发修改而崩溃、返回负值或返回已被Cancel的堆顶条目
    //       返回nullopt当且仅当无有效定时器时

// 3.6 堆顶已取消条目的惰性清理
TEST TimerQueue_LazyCleanup_CanceledTop:
    // 验证: 当堆顶条目被Cancel后:
    //       1. GetNextTimeout返回时已跳过它 (返回次早到期条目的剩余时间)
    //       2. FireExpired不会执行它 (检查canceled_集合)
    //       3. canceled_中该id在惰性清理后被erase (无内存泄漏)
    //       4. 连续Cancel堆顶3次 → GetNextTimeout应逐步跳过3个已取消条目
```

---

## 4. WorkerPool 并发测试

```
// ============================================================
// 模块: WorkerPool (多线程调度器)
// 关键并发属性: Dispatch线程安全, 分配策略正确性
// ============================================================

// 4.1 ModuloHash分配一致性
TEST WorkerPool_ModuloHash_Consistency:
    // 配置: 4 Worker, 1000个不同的routing_key
    // 验证: 相同routing_key始终路由到同一Worker (粘滞性保证)
    //       分布均匀性: 每个Worker分配到 250±15% 的routing_key
    //       不同key的分配独立,无相互影响

// 4.2 并发Dispatch线程安全
TEST WorkerPool_ConcurrentDispatch_Safety:
    // 配置: 8线程并发调用Dispatch, 每线程10K次
    // 验证: 无崩溃, 所有投递的任务均被执行 (总数 == 80K)
    //       每个Worker内部的任务在其EventLoop线程中串行执行
    //       TSan验证: 无跨Worker的data race
    //       (不同Worker的EventLoop在不同线程,各自独立)

// 4.3 RoundRobin轮询均衡
TEST WorkerPool_RoundRobin_Fairness:
    // 配置: RoundRobin策略, 10000次Dispatch (相同routing_key)
    // 验证: 每个Worker获得任务数差值 <= 1 (原子计数器保证)
    //       与routing_key无关 (RoundRobin不依赖key)

// 4.4 LeastSessions负载均衡
TEST WorkerPool_LeastSessions_Balance:
    // 配置: LeastSessions策略, 模拟不均匀的任务负载
    //       预先设置各Worker的session_count为不同值
    // 操作: 持续Dispatch新任务
    // 验证: 新任务优先分配到session_count中位数最小的Worker
    //       随Dispatch进行,session_count分布趋于均匀
    //       session_count的读取是线程安全的 (std::atomic<size_t>)

// 4.5 Shutdown安全
TEST WorkerPool_Shutdown_Safety:
    // 配置: WorkerPool运行中,有未完成的任务在队列中和定时器在等待
    // 操作: 调用Shutdown() (内部依次Stop→join每个Worker)
    // 验证: 所有Worker线程在合理超时内 (如5s) 正常退出
    //       无死锁: Shutdown不卡住
    //       无线程泄露: join后所有线程资源被OS回收
    //       已入队但未执行的任务随EventLoop停止被丢弃 (或提供可选的Drain模式)

// 4.6 ConsistentHash动态增减
TEST WorkerPool_ConsistentHash_Rebalance:
    // 配置: 一致性哈希环,初始N个Worker,记录所有key的分布
    // 操作: 增加1个Worker (或移除1个)
    // 验证: 仅约 1/N 的key映射关系发生变更 (最小化重分配)
    //       其余key的映射保持不变 (粘滞性最大化)
    // 注意: 已分配给旧Worker的Session不受WorkerPool自动迁移;
    //       Session迁移需由上层 (如Server) 根据映射变更自行处理
```

---

## 5. Session 并发安全测试

```
// ============================================================
// 模块: Session (协议会话)
// 设计原则: Session本身非线程安全,所有操作在所属EventLoop线程执行
// 测试重点: 验证跨线程PostTask串行化机制的正确性
//           验证单线程内高频操作的正确性和稳定性
// ============================================================

// 5.1 跨线程Send正确性 (通过PostTask串行化)
TEST Session_CrossThreadSend_ViaPostTask:
    // 配置: Session绑定在Worker-A的EventLoop
    // 操作: Worker-B通过PostTask投递Send操作
    //       Worker-C通过PostTask投递Send操作
    //       投递速率 > Session单线程处理速率 (测试队列背压)
    // 验证: 所有数据按投递顺序串行发送 (EventLoop保证FIFO)
    //       无数据竞争 (TSan验证: Session成员仅被Worker-A线程访问)
    //       stats_.total_bytes_sent 和 total_messages_sent 计数正确

// 5.2 并发Send与Close (通过PostTask串行化)
TEST Session_ConcurrentSendAndClose:
    // 配置: Session在kConnected状态
    // 操作: 线程A PostTask(Send), 线程B PostTask(Close)
    //       两个操作被EventLoop串行化,执行顺序取决于投递顺序
    // 验证: Close先执行 → Send返回kBlocked (安全拒绝)
    //       Send先执行 → 数据正常入队,后续Close正常关闭
    //       无论哪种顺序: 无崩溃,无内存泄漏 (ASan验证)
    //       状态机最终到达kClosed (终态不变)

// 5.3 FeedInput与Update的高频交替
TEST Session_HighFrequencyFeedInputAndUpdate:
    // 配置: 网络模拟器以高频率投递数据包到FeedInput
    // 操作: FeedInput和Update在同一EventLoop线程上串行交替执行
    //       模拟真实IO线程行为: 每轮先FeedInput排空Socket,再Update
    // 验证: 数据完整性: 接收端组装的消息 == 发送端发送的消息 (无损坏/无截断)
    //       乱序到达的分片被正确按序列号重组
    //       协议引擎内部缓冲区无溢出 (recv_buffer_有界保护)
    //       长时间运行无内存泄漏

// 5.4 高频率定时驱动的稳定性
TEST Session_HighFrequencyUpdate:
    // 配置: 1000个Session, update_interval_ms=10 (每10ms一次Update)
    //       使用模拟时钟快速推进 (每秒模拟100轮Update)
    // 操作: 持续运行相当于10M轮Update的模拟时间
    // 验证: 每轮Update总耗时 < 时间预算的80% (10ms × 80% = 8ms)
    //       定时器不漂移: 各Session的Update间隔始终为10ms
    //       长时间运行无内存泄漏 (RSS无单调增长)

// 5.5 Session析构安全性
TEST Session_DestructionSafety:
    // 配置: Session持有未完成定时器 (shutdown_timer_) 和回调闭包
    // 操作: 在Session仍被ProtocolEngine内部引用时,从外部重置shared_ptr
    //       (模拟应用层释放Session的场景)
    // 验证: 析构函数正确取消shutdown_timer_ (CancelTimer)
    //       OutputCallback中捕获的socket_指针在引擎停用前保持有效
    //       无悬挂指针/use-after-free (ASan验证)
    //       所有回调闭包 (message/error/state_change/send_complete) 被正确析构

// 5.6 Send窗口满时的背压行为
TEST Session_SendWindowFull_Backpressure:
    // 配置: send_window_packets=4 (极小发送窗口,易于触发窗口满)
    // 操作: 连续发送大量数据 (10倍于窗口容量),不等待ACK
    //       同时暂停Update (模拟对端不响应,窗口无法滑动)
    // 验证: 前4个Send返回kQueued (窗口填充)
    //       后续Send返回kBlocked (窗口满,拒绝而非丢弃)
    //       恢复Update+模拟收到ACK后窗口滑动,积压数据逐步发出
    //       所有数据最终到达对端 (在网络无损的模拟条件下)
```

---

## 6. Server 并发测试

```
// ============================================================
// 模块: Server (服务端端点)
// 关键并发属性: OnReadable中sessions_操作
//               单EventLoop模式下所有操作串行,天然安全
//               多Worker模式下各Worker独立,无跨Worker共享
// ============================================================

// 6.1 高频率新建会话
TEST Server_HighRateSessionCreation:
    // 配置: 网络模拟器模拟大量新客户端首包到达
    //       使用模拟网络 (非真实Socket) 以实现可控速率
    // 操作: 以每秒10K新会话的速率向OnReadable投递数据报
    // 验证: 所有Session被正确创建并加入sessions_
    //       OnNewSession回调被触发N次 (与会话创建数一致)
    //       无conv冲突导致的路由错误 (不同来源相同conv的会话应隔离,
    //         测试需使用 (conv, sender) 复合键或发送方使用互不冲突的conv)
    //       持续运行10秒 (100K会话) 无内存泄漏

// 6.2 会话创建与驱逐并发
TEST Server_ConcurrentCreateAndEvict:
    // 配置: max_sessions=1000
    // 操作: 持续创建新会话 (每次OnReadable触发) + 健康检测周期性驱逐过期会话
    //       新会话到达速率 > 过期驱逐速率 (测试上限保护)
    // 验证: sessions_.size() 在达到max_sessions后不再增长
    //       (新到达的包被静默丢弃,不创建Session)
    //       驱逐中会话不接收新数据 (sessions_中已erase)
    //       无迭代器失效崩溃 (驱逐使用batch collect模式: 先收集stale列表,再逐个处理)

// 6.3 健康检测与数据收发并发
TEST Server_HealthCheckDuringActiveTraffic:
    // 配置: 1000个Session,每10ms对所有Session调用Update,每秒执行健康检测
    // 操作: 持续收发数据的同时周期性RunHealthCheck
    // 验证: 活跃Session (持续收发数据的) 不被误判为stale
    //       EvaluateHealth检查的是last_recv_time_ms_ (FeedInput中更新)
    //       空闲Session正确进入kIdle状态并触发探活
    //       单EventLoop线程内所有操作串行,TSan无报错

// 6.4 多Worker模式下的Session隔离
TEST Server_MultiWorker_SessionIsolation:
    // 配置: WorkerPool(kModuloHash),Session通过conv取模分配到不同Worker
    //       每个Worker处理分配到的Session子集
    // 操作: 使用不同conv的数据报投递到各Worker
    // 验证: 相同conv的数据报始终路由到同一Worker (ModuloHash粘滞性)
    //       不同Worker的sessions_完全隔离,无跨Worker共享状态
    //       TSan验证: 无不同Worker线程间的data race
    //       一个Worker上的Session驱逐不影响其他Worker

// 6.5 最大会话数限制
TEST Server_MaxSessions_Limit:
    // 配置: max_sessions=100
    // 操作: 150个不同来源发送首包 (模拟150个独立客户端)
    // 验证: 前100个Session被创建 (GetSessionCount()==100)
    //       后50个数据报被静默丢弃 (不创建Session,不触发OnNewSession)
    //       已创建的前100个Session正常工作 (可收发数据)
    //       被拒绝的客户端通过超时感知 (服务器不响应其数据报)
```

---

## 7. Client 并发测试

```
// ============================================================
// 模块: Client (客户端端点)
// 关键并发属性: 连接/重连/断开的状态机并发安全
// ============================================================

// 7.1 连接超时与重连序列
TEST Client_ConnectTimeout_ReconnectSequence:
    // 配置: 模拟服务器不响应任何数据报, connect_timeout_ms=100
    //       reconnect: max_attempts=3, initial_delay=100, backoff=2.0, jitter=0
    //       使用模拟时钟以精确控制时序
    // 操作: Connect() → 等待超时 → 自动重连 (循环)
    // 验证: 重连序列执行3次,每次间隔符合退避公式:
    //       第1次超时: 100ms后重试 (initial)
    //       第2次超时: 200ms后重试 (100×2)
    //       第3次超时: 400ms后重试 (100×4)
    //       第4次超时: on_failure(ConnectError::kMaxRetriesExceeded)
    //       最终状态: ClientState::kDisconnected

// 7.2 连接过程中Disconnect
TEST Client_DisconnectDuringConnecting:
    // 配置: Connect()已调用,已发送握手首包,但服务器尚未响应 (kConnecting)
    //       使用模拟时钟,在connect_timeout触发前介入
    // 操作: 在kConnecting状态下调用Disconnect()
    // 验证: connect_timer被Cancel (不会触发OnConnectTimeout)
    //       session被Close并reset
    //       state_ == ClientState::kDisconnected
    //       success_handler和failure_handler均不被调用 (连接未完成)

// 7.3 重连等待期间Disconnect
TEST Client_DisconnectDuringReconnecting:
    // 配置: 首次连接超时,进入kReconnecting,等待重连延迟定时器触发
    // 操作: 在重连延迟定时器触发前调用Disconnect()
    // 验证: 重连延迟定时器的回调触发后检查状态,因state_!=kReconnecting而跳过
    //       或: Disconnect中主动取消该定时器 (取决于具体实现)
    //       config_.reconnect被reset() (清除重连配置)
    //       state_ == ClientState::kDisconnected

// 7.4 连接成功后服务器断连
TEST Client_ServerDisconnectAfterConnected:
    // 配置: 已处于kConnected,正常通信中
    // 操作: 模拟对端发送CLOSE通知或长时间无响应
    //       → Session检测到错误或远程关闭 → OnError回调 → Client收到通知
    // 验证: 启用重连 (config_.reconnect.has_value()):
    //         state_ → kReconnecting → 开始重连流程
    //       禁用重连 (config_.reconnect == nullopt):
    //         state_ → kDisconnected, failure_handler被调用

// 7.5 快速Connect-Disconnect循环
TEST Client_RapidConnectDisconnectCycle:
    // 配置: 模拟服务器快速响应 (延迟0ms)
    // 操作: Connect() → (收到响应 → kConnected) → Disconnect() → Connect() → ... × 1000次
    // 验证: 无内存泄漏 (ASan: RSS无单调增长)
    //       无文件描述符泄漏 (每次循环后fd计数不变)
    //       每次状态转换正确: Disconnected→Connecting→Connected→Disconnected
    //       无状态卡住 (如卡在kConnecting或kReconnecting)
    //       回调被正确触发: on_success触发1000次, on_failure触发0次

// 7.6 首次响应的竞态: 超时与响应几乎同时到达
TEST Client_RaceBetweenTimeoutAndFirstResponse:
    // 配置: 使用模拟时钟精确控制时序
    //       服务器在connect_timeout临界点发送响应
    // 操作: 安排FeedInput在超时定时器触发前1ms执行
    //       (或: 安排在超时触发后1ms执行,取决于测试意图)
    // 验证 场景A (响应先到): OnServerFirstResponse被调用
    //         connect_timer被取消, state→kConnected, success_handler触发
    // 验证 场景B (超时先到): OnConnectTimeout被调用
    //         进入重连或通知失败
    // 关键: 二者不会同时被触发 (无double-transition)
    //       最终状态一致 (kConnected或kDisconnected,不会卡在中间态)

// 7.7 多线程收发并发 (通过PostTask投递)
TEST Client_ConcurrentSendRecv_MultiThreadPost:
    // 配置: Client绑定在Worker-A的EventLoop
    //       数据发送来自Worker-B和Worker-C (通过PostTask投递)
    // 操作: 10个线程并发PostTask Send操作,同时持续OnReadable接收响应
    //       使用模拟网络: 0延迟,0丢包
    // 验证: 发送总数 == 接收总数 (无数据丢失)
    //       每条消息内容正确 (逐字节比对)
    //       TSan: 无跨线程data race
    //       (Send通过PostTask串行化,FeedInput在EventLoop线程,所有Session访问串行)
```

---

## 8. DatagramSocket 并发测试

```
// ============================================================
// 模块: DatagramSocket (非阻塞Socket封装)
// 关键并发属性: OS保证Socket fd的读写线程安全
//               但EventLoop注册/事件监听应在同一线程
// ============================================================

// 8.1 SendTo在缓冲区满时的行为
TEST DatagramSocket_SendTo_BufferFull:
    // 配置: 发送速率 > 接收速率,直到填满内核发送缓冲区
    // 验证: SendTo在缓冲区满时返回SocketError::kWouldBlock (而非丢弃数据)
    //       EnableWriteNotifications注册后,内核缓冲区可写时触发OnWritable
    //       收到OnWritable后重新SendTo,数据正常发出

// 8.2 RecvFrom在无数据时的行为
TEST DatagramSocket_RecvFrom_NoData:
    // 验证: 无数据时返回std::expected containing std::nullopt
    //       即: recv_result.has_value()==true, recv_result->has_value()==false
    //       (非阻塞模式正常,不表示错误)
    //       不阻塞调用线程,立即返回

// 8.3 边缘触发模式下的读取完整性
TEST DatagramSocket_EdgeTriggered_ReadCompleteness:
    // 配置: Socket向EventLoop注册为边缘触发 (EPOLLET / kEdgeTriggered)
    // 操作: 发送方快速发送1000个数据报 (一次性发送,无间隔)
    // 验证: EventLoop触发一次OnReadable
    //       接收方在一次OnReadable中循环RecvFrom直到返回nullopt
    //       1000个数据报全部收到 (无遗漏)
    // 重要: 边缘触发要求彻底排空Socket recv缓冲区
    //       如果循环在排空前退出,剩余数据报将丢失 (不会触发新的事件通知)
    //       因此测试必须验证: 循环正确排空所有数据报

// 8.4 绑定地址冲突
TEST DatagramSocket_Bind_AddressInUse:
    // 配置: Socket-A绑定到地址X (reuse_addr=false)
    // 操作: Socket-B尝试绑定相同地址X
    // 验证: Socket-B的Bind失败,抛出异常或构造函数失败
    //       reuse_addr=true时,两个Socket均可绑定相同地址 (SO_REUSEADDR)

// 8.5 SendTo无效地址与ICMP错误
TEST DatagramSocket_SendTo_InvalidAddress:
    // 配置: 发送到不存在对端监听进程的地址
    // 验证: 立即SendTo: 通常返回成功 (数据报仅写入内核缓冲区,未实际送达)
    //       后续: 内核收到ICMP Port Unreachable
    //       下一次RecvFrom调用可能返回SocketError::kConnectionRefused
    //       (此错误不影响Socket继续使用,后续SendTo/RecvFrom仍然可用)
    // 注意: ICMP错误到达取决于OS和网络配置,不是100%可靠
```

---

## 9. 端到端集成测试

```
// ============================================================
// 描述: 多组件协作的端到端并发测试
//       所有E2E测试使用模拟网络和模拟时钟以确保确定性和可复现性
// ============================================================

// 9.1 多Client对单Server高并发
TEST E2E_ManyClientsToOneServer:
    // 配置: 1 Server, 1000 Client, 每Client发送100条消息
    //       网络模拟器: 延迟5-15ms均匀分布, 丢包率1%, 无乱序
    // 验证: 所有100K条消息被Server完整接收 (逐条校验内容)
    //       所有1000个连接正常建立 (success_handler触发1000次)
    //       所有连接正常关闭 (Client主动Disconnect)
    //       吞吐量满足预期 (不低于理论最大吞吐量的70%)
    //       持续运行至所有消息交换完成,期间无内存泄漏/性能衰减

// 9.2 P2P对称通信
TEST E2E_PeerToPeer_Symmetric:
    // 配置: 2个Peer实例,各自同时具有Server和Client角色
    //       Peer-A绑定端口A并Start Server, Peer-B绑定端口B并Start Server
    // 操作: Peer-A Connect到Peer-B, Peer-B Connect到Peer-A
    //       (双方互为对方的客户端和服务端)
    // 验证: 双方均能成功建立连接并收发数据
    //       无死锁: 双方同时Connect不导致握手死锁
    //       任一方调用Close关闭会话,对端通过OnError/OnStateChange正确感知

// 9.3 网络分区恢复
TEST E2E_NetworkPartition_Recovery:
    // 配置: Client-Server已建立连接并正常通信
    // 操作: 模拟网络分区 (丢包率设为100%)持续30秒 → 恢复网络 (丢包率设为0%)
    // 验证: 分区期间:
    //       Server检测到stale (last_recv_time > stale_threshold) → 驱逐会话
    //       Client检测到超时 (无ACK导致RTO超时) → OnError → 尝试重连
    //       恢复后: Client重连成功, 通信恢复正常

// 9.4 优雅关闭协议
TEST E2E_GracefulShutdown_Protocol:
    // 配置: Client-Server已建立连接,正在通信中
    // 操作: Server调用GracefulShutdown(timeout_ms=5000)
    //       协议层自动发送CLOSE通知 → Client收到 → Client引擎回复ACK →
    //       Server收到ACK → 双方进入kClosed
    // 验证: 完整四步握手在timeout_ms内完成
    //       双方最终状态均为SessionState::kClosed
    //       优雅关闭期间Server拒绝新Send (返回kBlocked)
    //       超时场景: Client不应答 → Server在timeout_ms后强制Close

// 9.5 长时间运行稳定性
TEST E2E_LongRunning_Stability:
    // 配置: 1 Server, 50 Client (每Client每秒发送10条消息)
    //       使用模拟时钟加速运行 (如1模拟秒 = 1实际毫秒)
    // 操作: 持续运行相当于24小时的模拟时间
    // 验证: 无内存泄漏 (RSS和虚拟内存稳定,无单调增长)
    //       无文件描述符泄漏 (fd计数在创建/销毁循环后回归基线)
    //       吞吐量P50在运行末期不低于初期的90% (无性能衰减)
    //       无未处理的错误累积 (错误日志数量有界,不随时间增长)
```

---

## 10. 内存安全与资源泄漏测试

```
// ============================================================
// 描述: 专项内存和资源泄漏检测测试
//       所有测试必须在ASan/LSan下运行并零报错
// ============================================================

// 10.1 Session创建/销毁循环
TEST Memory_SessionCreateDestroy_Loop:
    // 操作: 创建 → Start → Send(1条消息) → Close → 销毁shared_ptr × 100K次
    // 验证: ASan无内存泄漏报告
    //       LSan (LeakSanitizer) 确认无reachable/indirect泄漏
    //       内存占用无单调增长 (每10K次循环后的RSS应回归到初始值±5%)

// 10.2 Server长时间运行内存稳定性
TEST Memory_Server_LongRunningStability:
    // 配置: 客户端模拟持续连接和断开 (平均会话存活时长5秒)
    // 操作: Server运行1小时,客户端持续: Connect→通信→Disconnect
    // 验证: sessions_.size()有上界 (驱逐正常清理过期会话)
    //       总RSS内存无单调增长 (有界波动)
    //       每个Session析构后其recv_buffer_和ProtocolEngine资源被释放

// 10.3 定时器资源泄漏检测
TEST Memory_TimerQueue_NoLeakAfterCancel:
    // 操作: Add 10K定时器 (混合一次性+重复) → Cancel全部 → 驱动FireExpired清理
    // 验证: heap_最终为空, canceled_集合最终为空
    //       所有定时器条目 (TimerEntry) 和捕获的闭包资源被释放
    //       无内存泄漏 (ASan/LSan验证)

// 10.4 回调闭包链的内存安全
TEST Memory_CallbackChain_NoLeak:
    // 配置: 构建回调链: Session持有lambda, lambda捕获shared_ptr<Session>
    //       (这是常见的循环引用风险场景)
    // 验证: Session::Close()或析构时回调闭包被正确释放
    //       std::move_only_function析构时释放其捕获的所有资源
    // 关键: 若lambda以shared_ptr捕获Session自身,形成循环引用→Session永不析构
    //       解决方案: lambda使用weak_ptr捕获Session, 或OnMessage等回调
    //       在Session析构前被显式重置
    // 此测试验证: 按设计使用Session时 (避免循环引用),Session析构后
    //       所有关联对象可被正确回收

// 10.5 Socket RAII安全性
TEST Memory_Socket_RAII_Safety:
    // 验证场景:
    //   1. 正常路径: DatagramSocket创建→使用→析构,fd被关闭一次
    //   2. Move路径: Socket被move后,原对象不再持有fd (避免double-close)
    //      move后原对象的fd标记为invalid,析构时跳过close
    //   3. 异常路径: 构造函数中Bind失败→fd在异常抛出前被关闭 (无泄漏)
    // 验证方法: 跟踪进程fd数量 (Linux: /proc/self/fd, macOS: lsof)
    //       每次操作前后fd计数应回归基线
```

---

## 11. 性能回归测试

```
// ============================================================
// 描述: 性能基线的建立与回归检测
//       所有性能测试使用Release编译 (-O2/-O3),无sanitizer开销
// ============================================================

// 11.1 EventLoop吞吐量
TEST Perf_EventLoop_Throughput:
    // 度量项目:
    //   a. 空载吞吐量: EventLoop空转 (无IO事件/无定时器/无任务) 每秒循环次数
    //   b. 满载吞吐量: 10K活跃Session,每周期Update+IO处理
    //      满载条件下每秒可完成的循环次数
    // 基线: 记录为后续版本的性能回归检测阈值
    // 回归标准: 吞吐量下降 >10% 视为显著回归,需分析原因

// 11.2 TaskQueue延迟
TEST Perf_TaskQueue_Latency:
    // 度量: 任务从Push到开始执行的端到端延迟分布 (P50/P95/P99)
    // 条件: a) 1生产者 + 1消费者  b) 8生产者 + 1消费者
    // 基线: 有锁队列 P99 < 100μs, 无锁队列 P99 < 10μs
    // 测量方法: 任务内记录Clock::NowUs() - 入队时记录的时间戳

// 11.3 Session Send吞吐量
TEST Perf_Session_SendThroughput:
    // 度量: 单个Session的数据发送吞吐量 (Mbps)
    // 条件: 测试不同MTU组合 (500/1000/1400) 和窗口大小组合 (32/128/512)
    //       网络条件: 0延迟,0丢包 (测量协议引擎本身吞吐上限)
    // 基线: 记录最优配置 (通常MTU=1400, send_window=512) 下的吞吐量

// 11.4 Server会话创建速率
TEST Perf_Server_SessionCreationRate:
    // 度量: Server每秒可创建并完成初始化的Session数
    // 条件: 模拟批量首包到达,测量从OnReadable到OnNewSession回调的创建耗时
    // 回归标准: 与上一版本相比创建速率下降 >5% 视为回归
```

---

## 12. 确定性仿真测试 (可选高级测试)

```
// ============================================================
// 描述: 使用模拟时钟和网络模拟器进行完全确定性的集成测试
//       每个测试用例使用固定随机种子,产生完全可复现的结果
//       适用于CI中检测协议行为的不兼容变更
// ============================================================

// 12.1 精确重传时序验证
TEST Sim_ExactRetransmitTiming:
    // 配置: 模拟时钟, 预设网络丢包模式 (如: 包序列号#3和#7丢失), 固定随机种子
    // 验证: 丢失包在精确的预期时间点被重传
    //       RTO超时重传: 在RTO到期时刻 (±1ms) 触发
    //       快速重传: 在收到第fast_resend_threshold个重复ACK时立即触发
    //       RTO退避: 连续重传时RTO指数增长 (如1s→2s→4s→8s)
    //       重传次数与预设丢包数一致

// 12.2 拥塞窗口行为验证
TEST Sim_CongestionWindowBehavior:
    // 配置: 启用流控 (flow_control_enabled=true), 预设特定丢包序列
    // 验证: 慢启动阶段: 窗口从1开始指数增长
    //       拥塞避免阶段: 窗口线性增长
    //       丢包事件: 窗口减半 (乘性减)
    //       快速恢复: 收到新ACK后进入拥塞避免 (非慢启动)
    //       窗口变化轨迹与协议规范一致

// 12.3 乱序包重组与消息交付
TEST Sim_OutOfOrderReassembly:
    // 配置: 预定义数据包乱序到达序列 (如: 5个分片按[3,1,4,2,5]顺序到达)
    // 验证: 按序列号正确排序存储到接收缓冲区
    //       当最后一个缺口分片到达时,完整消息立即交付给应用层 (TryRecv)
    //       缺口未补齐前,PeekMessageSize()返回0或<0 (消息不完整,不可交付)
    //       超时后缺失分片触发重传请求

// 12.4 完全确定性回归测试套件
TEST Sim_DeterministicRegressionSuite:
    // 配置: 一组预录制的网络trace文件 (包含时序/丢包/乱序/重复的完整序列)
    //       每个trace是二进制格式: [timestamp_ms, action, packet_data...]
    // 验证: 回放相同trace时,库的行为逐帧完全一致:
    //       - 发出的每个数据包的时间戳与baseline一致
    //       - 发出的每个数据包的内容与baseline逐字节一致
    //       - 回调触发的时间点和顺序与baseline一致
    //       - 状态转换的时间点与baseline一致
    // 用途: 检测协议实现的不兼容变更 (即使性能改进也可能改变时序行为)
```

---

## 附录A: 测试优先级与依赖

```
// ============================================================
// 描述: 测试用例的优先级分级和执行依赖关系
// ============================================================

// 优先级定义:
//   P0 (阻断性): 每次commit前必须通过,失败阻断CI合入
//   P1 (高优先级): 每次PR前必须通过
//   P2 (中优先级): 每日构建执行
//   P3 (低优先级): 每周或发版前执行

// P0 测试 (核心正确性):
//   - TaskQueue: 2.1 (MPSC正确性), 2.4 (TryPop非阻塞)
//   - TimerQueue: 3.1 (并发Add+Fire), 3.2 (并发Cancel+Fire)
//   - Session: 5.2 (并发Send+Close), 5.5 (析构安全), 5.6 (窗口背压)
//   - Memory: 10.1 (Session创建销毁循环), 10.3 (定时器泄漏), 10.5 (Socket RAII)

// P1 测试 (线程安全与集成):
//   - WorkerPool: 4.1 (分配一致性), 4.2 (并发Dispatch), 4.5 (Shutdown)
//   - Server: 6.2 (创建驱逐并发), 6.5 (最大会话限制)
//   - Client: 7.1 (超时重连锁), 7.2 (连接中Disconnect), 7.5 (快速循环)
//   - E2E: 9.4 (优雅关闭协议)

// P2 测试 (负载与稳定性):
//   - Session: 5.1 (跨线程Send), 5.4 (高频Update)
//   - Server: 6.1 (高频创建), 6.3 (健康检测收发并发)
//   - Client: 7.7 (多线程收发)
//   - E2E: 9.1 (多Client高并发), 9.3 (网络分区恢复)
//   - Memory: 10.2 (Server长时间运行), 10.4 (回调链)

// P3 测试 (性能与仿真):
//   - Performance: 11.1-11.4 (全部)
//   - Simulation: 12.1-12.4 (全部)
//   - E2E: 9.5 (24h稳定性)

// 测试依赖链:
//   基础模块 (TaskQueue, TimerQueue) → 平台模块 (WorkerPool, DatagramSocket)
//     → 协议模块 (Session) → 端点模块 (Server, Client) → E2E集成
//   基础模块测试必须先行通过,上层模块测试在基础模块不稳定的情况下结果不可信
```

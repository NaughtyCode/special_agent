# 高并发单元测试需求

本文档定义网络库各模块在高并发场景下的单元测试需求，覆盖线程安全性、竞态条件、负载压力、内存安全及确定性仿真等维度。

---

## 1. 测试基础设施要求

```
// ============================================================
// 描述: 高并发测试所需的基础设施与工具
// ============================================================

// 1.1 确定性模拟时钟
//     用途: 消除真实时间的不确定性,精确控制协议超时/重传/定时器行为
//     要求:
//       - Clock::NowMs() 可注入为模拟时钟
//       - 支持手动推进时间: AdvanceTime(delta_ms)
//       - 定时器到期行为与真实时钟一致
//     覆盖: 所有TimerQueue相关测试, 协议重传时序测试

// 1.2 网络模拟器 (NetworkSimulator)
//     用途: 在单进程内模拟数据报的延迟/丢包/乱序/重复
//     要求:
//       - 可注入到 DatagramSocket 或 ProtocolEngine 的 OutputCallback
//       - 支持: delay_ms(min, max), drop_rate(0.0~1.0), duplicate_rate, reorder_window
//       - 确定性: 使用可指定种子的伪随机数生成器
//     覆盖: Session重传逻辑, 乱序包重组, 流控行为

// 1.3 竞态检测工具集成
//     要求:
//       - CI流水线中使用 ThreadSanitizer (TSan) 编译和运行所有并发测试
//       - CI中使用 AddressSanitizer (ASan) 检测内存错误
//       - 可选: helgrind (valgrind) / Relacy Race Detector
//     覆盖: 所有多线程测试

// 1.4 并发压力测试框架
//     要求:
//       - 可配置: 线程数 / 每线程操作数 / 操作类型混合比例 / 运行时间
//       - 结果收集: 吞吐量(ops/s) / 延迟分布(P50/P95/P99) / 错误率
//       - 确定性: 相同种子产生相同操作序列 (可复现)
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
    // 配置: N个生产者线程, 1个消费者线程
    // 操作: 每个生产者Push M个任务 (任务内容: 原子计数器递增)
    // 验证: 消费到的任务总数 == N * M
    //       原子计数器最终值 == N * M (无重复/无遗漏)
    //       ASan/TSan 无报错

// 2.2 高竞争下的吞吐量
TEST TaskQueue_HighContention_Throughput:
    // 配置: 8生产者 + 1消费者, 每生产者1M任务
    // 测量: 吞吐量 (任务/秒), 与理论最大值比较
    // 验证: 吞吐量不低于基线 (单生产者吞吐量的60%以上)
    //       无活锁/饥饿

// 2.3 ExecuteAll批量消费正确性
TEST TaskQueue_ExecuteAll_BatchConsumption:
    // 配置: 4生产者持续Push, 消费者周期性调用ExecuteAll
    // 验证: 每批ExecuteAll消费所有当前已入队任务 (交换语义正确)
    //       Push与ExecuteAll并发执行时无任务丢失
    //       ExecuteAll返回后queue_为空

// 2.4 TryPop非阻塞语义
TEST TaskQueue_TryPop_NonBlocking:
    // 验证: 空队列TryPop立即返回std::nullopt (不阻塞)
    //       有任务时TryPop立即返回任务 (不阻塞)
    //       并发Push和TryPop: TryPop要么返回任务要么返回nullopt,
    //         不会返回"半任务"或损坏数据

// 2.5 有界队列背压 (如替换为有界实现)
TEST TaskQueue_Bounded_Backpressure:
    // 配置: 队列容量上限 = K
    // 验证: Push在队列满时阻塞/返回false
    //       Pop后Push可继续 (背压释放)
```

---

## 3. TimerQueue 并发测试

```
// ============================================================
// 模块: TimerQueue (线程安全定时器管理器)
// 关键并发属性: Add/Cancel与FireExpired之间的竞态
// ============================================================

// 3.1 并发Add与FireExpired
TEST TimerQueue_ConcurrentAddAndFire:
    // 配置: 4线程并发Add定时器 (不同到期时间)
    //       同时主线程周期性调用 FireExpired
    // 验证: 所有定时器均被触发 (无遗漏)
    //       无double-fire (同一回调被触发两次)
    //       heap_无损坏 (TSan验证)

// 3.2 并发Cancel与FireExpired
TEST TimerQueue_ConcurrentCancelAndFire:
    // 配置: 100个定时器同时在执行callback前被Cancel
    // 验证: 已取消的定时器回调绝不触发
    //       canceled_集合与heap_的一致性 (GetNextTimeout跳过已取消堆顶)

// 3.3 Cancel不存在的定时器
TEST TimerQueue_CancelNonExistent:
    // 验证: Cancel无效/已触发/已取消的句柄是安全幂等的
    //       不崩溃,不破坏内部数据结构

// 3.4 重复定时器的重新入堆
TEST TimerQueue_RepeatingTimer_Reinsertion:
    // 配置: 大量重复定时器,跨多个FireExpired周期
    // 验证: 重复定时器每次Fire后正确更新expire_time并重新入堆
    //       触发次数 == 预期次数 (无丢失,无额外触发)

// 3.5 GetNextTimeout并发安全
TEST TimerQueue_GetNextTimeout_Concurrent:
    // 配置: 线程A连续Add/Cancel, 线程B连续调用GetNextTimeout
    // 验证: GetNextTimeout返回值始终 >= 0 或 nullopt
    //       不会因并发修改而崩溃或返回异常值

// 3.6 堆顶已取消条目的惰性清理
TEST TimerQueue_LazyCleanup_CanceledTop:
    // 验证: 当堆顶条目被Cancel后:
    //       1. GetNextTimeout 返回时已跳过它
    //       2. FireExpired 不会执行它
    //       3. canceled_中被正确清理 (无内存泄漏)
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
    // 验证: 相同routing_key始终路由到同一Worker (粘滞性)
    //       分布均匀性: 每个Worker分配到 250±15% 的key

// 4.2 并发Dispatch线程安全
TEST WorkerPool_ConcurrentDispatch_Safety:
    // 配置: 8线程并发Dispatch, 每线程10K次
    // 验证: 无崩溃, 所有任务均被执行
    //       每个Worker的任务执行在其EventLoop线程 (TSan验证无跨线程数据竞争)

// 4.3 RoundRobin轮询均衡
TEST WorkerPool_RoundRobin_Fairness:
    // 配置: RoundRobin策略, 10000次Dispatch (相同routing_key)
    // 验证: 每个Worker获得任务数差值 <= 1

// 4.4 LeastSessions负载均衡
TEST WorkerPool_LeastSessions_Balance:
    // 配置: LeastSessions策略, 模拟不均匀的任务负载
    // 验证: session_count最大的Worker与最小的差值不超过配置阈值
    //       新任务优先分配到session_count最小的Worker

// 4.5 Shutdown安全
TEST WorkerPool_Shutdown_Safety:
    // 配置: 运行中的WorkerPool,有未完成的任务和定时器
    // 操作: 调用Shutdown()
    // 验证: 所有Worker线程在超时内(如5s)正常退出
    //       无死锁,无线程泄露
    //       已PostTask但未执行的任务被丢弃 (或提供drain机制)

// 4.6 ConsistentHash动态增减
TEST WorkerPool_ConsistentHash_Rebalance:
    // 配置: 一致性哈希,初始N个Worker,记录key分布
    // 操作: 增加1个Worker (或移除1个)
    // 验证: 仅 ~1/N 的key转移到新Worker (最小化重分配)
    //       已粘滞在旧Worker的Session不受影响 (由上层管理迁移)
```

---

## 5. Session 并发安全测试

```
// ============================================================
// 模块: Session (协议会话)
// 设计原则: Session本身非线程安全,所有操作在所属EventLoop执行
// 测试重点: 验证跨线程PostTask机制的正确性
// ============================================================

// 5.1 跨线程Send正确性
TEST Session_CrossThreadSend_ViaPostTask:
    // 配置: Session绑定在Worker-A的EventLoop
    // 操作: 从Worker-B通过PostTask投递Send操作
    //       从Worker-C通过PostTask投递Send操作
    // 验证: 所有数据按投递顺序发送 (串行化保证)
    //       无数据竞争 (TSan验证)
    //       stats_计数器正确累加

// 5.2 并发Send与Close
TEST Session_ConcurrentSendAndClose:
    // 配置: Session在kConnected状态
    // 操作: 线程A PostTask(Send), 线程B PostTask(Close)
    // 验证: Close后Send返回kBlocked或正常完成
    //       无崩溃,无内存泄漏 (ASan验证)
    //       状态机最终到达kClosed

// 5.3 并发FeedInput与Update
TEST Session_ConcurrentFeedInputAndUpdate:
    // 配置: 网络模拟器以高频率投递数据包
    // 操作: FeedInput和Update在正确线程上交替高频执行
    // 验证: 数据完整性: 接收到的消息 == 发送的消息 (无损坏/无截断)
    //       乱序包被正确重组
    //       无协议引擎内部缓冲区溢出

// 5.4 高频率定时驱动
TEST Session_HighFrequencyUpdate:
    // 配置: 1000个Session, update_interval_ms=10
    // 操作: 每个周期对所有Session调用Update
    // 验证: 每个周期Update耗时 < 总时间预算的80%
    //       无定时器漂移累积
    //       长时间运行(10M周期)无内存泄漏

// 5.5 Session析构安全
TEST Session_DestructionSafety:
    // 配置: Session持有未完成定时器 (shutdown_timer) 和回调闭包
    // 操作: 直接从外部delete/重置shared_ptr
    // 验证: 析构函数取消定时器 (CancelTimer)
    //       OutputCallback中的socket_指针在被引擎引用期间保持有效
    //       无悬挂指针/use-after-free (ASan验证)

// 5.6 Send窗口满时的背压行为
TEST Session_SendWindowFull_Backpressure:
    // 配置: send_window_packets=4 (极小发送窗口)
    // 操作: 连续发送大量数据,不等待ACK
    // 验证: Send返回kBlocked而非丢失数据
    //       后续Update+收到ACK后窗口滑动,数据被发送
    //       所有数据最终到达 (在网络无损条件下)
```

---

## 6. Server 并发测试

```
// ============================================================
// 模块: Server (服务端端点)
// 关键并发属性: OnReadable中sessions_并发访问
//               (单EventLoop模式下天然安全,测试验证多Worker分发)
// ============================================================

// 6.1 高频率新建会话
TEST Server_HighRateSessionCreation:
    // 配置: 网络模拟器模拟大量新客户端首包到达
    // 操作: 以每秒10K新会话的速率触发OnReadable
    // 验证: 所有Session被正确创建和加入sessions_
    //       OnNewSession回调被触发N次
    //       无conv冲突导致的数据路由错误 (不同来源相同conv的隔离)
    //       长时间运行无内存泄漏

// 6.2 会话创建与驱逐并发
TEST Server_ConcurrentCreateAndEvict:
    // 配置: max_sessions=1000
    // 操作: 持续创建新会话 + 健康检测驱逐过期会话
    // 验证: sessions_.size() 始终 <= max_sessions (如配置了上限驱逐)
    //       驱逐中会话不接收新数据 (已从sessions_移除)
    //       无迭代器失效崩溃 (batch collect模式)

// 6.3 健康检测与数据收发并发
TEST Server_HealthCheckDuringActiveTraffic:
    // 配置: 1000个Session,每10ms Update,每秒健康检测
    // 操作: 持续收发数据 + RunHealthCheck并发
    // 验证: 活跃Session不被误判为stale
    //       EvaluateHealth检查的是 last_recv_time_ms_ (在FeedInput中更新)
    //       无TSan报错

// 6.4 多Worker模式下的Session隔离
TEST Server_MultiWorker_SessionIsolation:
    // 配置: WorkerPool(kModuloHash), 每个Worker独立的Server+EventLoop
    // 操作: 由同一个对端地址的不同conv到达不同Worker
    // 验证: 每个Worker的sessions_独立,无跨Worker数据竞争
    //       相同conv的数据报总是路由到同一Worker (一致性)

// 6.5 最大会话数限制
TEST Server_MaxSessions_Limit:
    // 配置: max_sessions=100
    // 操作: 150个不同来源发送首包
    // 验证: 创建100个Session后,后续50个被拒绝
    //       GetSessionCount()返回100
    //       被拒绝的客户端可通过超时/ICMP感知
```

---

## 7. Client 并发测试

```
// ============================================================
// 模块: Client (客户端端点)
// 关键并发属性: 连接/重连/断开的状态机并发安全
// ============================================================

// 7.1 连接超时与重连时序
TEST Client_ConnectTimeout_ReconnectSequence:
    // 配置: 模拟服务器不响应, connect_timeout_ms=100, reconnect(3次)
    // 操作: Connect() → 等待超时 → 自动重连
    // 验证: 重连锁执行3次
    //       每次重连间隔符合退避公式
    //       第4次超时后: on_failure(MaxRetriesExceeded)
    //       状态: kDisconnected

// 7.2 连接过程中Disconnect
TEST Client_DisconnectDuringConnecting:
    // 配置: Connect()已调用,但服务器尚未响应 (kConnecting)
    // 操作: 调用Disconnect()
    // 验证: connect_timer被取消
    //       session被关闭
    //       state_ == kDisconnected
    //       success_handler和failure_handler均不被调用

// 7.3 重连过程中Disconnect
TEST Client_DisconnectDuringReconnecting:
    // 配置: 首次连接超时,进入kReconnecting,等待重连延迟
    // 操作: 在重连延迟定时器触发前调用Disconnect()
    // 验证: 重连延迟定时器被取消 (或触发后检查状态不再重连)
    //       config_.reconnect被reset()
    //       state_ == kDisconnected

// 7.4 连接成功后服务器断连
TEST Client_ServerDisconnectAfterConnected:
    // 配置: 已kConnected, 服务器随后发送CLOSE或超时
    // 操作: 对端关闭或网络中断 → Session错误 → Client收到通知
    // 验证: 启用重连: 自动进入重连流程
    //       禁用重连: 通知on_failure, state_→kDisconnected

// 7.5 快速Connect-Disconnect-Connect循环
TEST Client_RapidConnectDisconnectCycle:
    // 配置: 模拟服务器快速响应
    // 操作: Connect()→Disconnect()→Connect()→Disconnect() × 1000次
    // 验证: 无内存泄漏 (ASan)
    //       无socket泄漏 (文件描述符耗尽)
    //       每次状态转换正确 (无状态卡住)

// 7.6 首次响应的竞态: 超时与响应几乎同时到达
TEST Client_RaceBetweenTimeoutAndFirstResponse:
    // 配置: 模拟服务器在超时临界点响应
    // 操作: 精确定时: FeedInput在超时定时器触发前1ms执行
    // 验证: OnServerFirstResponse被调用 (非OnConnectTimeout)
    //       或者: 二者之一被调用,不会同时被调用
    //       无double-transition状态错误

// 7.7 收发并发 (多线程PostTask到Client所属EventLoop)
TEST Client_ConcurrentSendRecv_MultiThreadPost:
    // 配置: Client在Worker-A, 数据发送来自Worker-B/C (通过PostTask)
    // 操作: 10线程并发PostTask Send, 同时持续OnReadable接收
    // 验证: 发送和接收数据一致
    //       无TSan报错
```

---

## 8. DatagramSocket 并发测试

```
// ============================================================
// 模块: DatagramSocket (非阻塞Socket封装)
// 关键并发属性: Socket fd本身线程安全 (OS保证)
//               但RecvFrom/SendTo不应并发 (单EventLoop模型保证)
// ============================================================

// 8.1 SendTo在缓冲区满时的行为
TEST DatagramSocket_SendTo_BufferFull:
    // 配置: 发送速率 > 接收速率, 填满内核发送缓冲区
    // 验证: SendTo返回kWouldBlock而非丢弃数据
    //       EnableWriteNotifications后,缓冲区可写时触发OnWritable

// 8.2 RecvFrom在无数据时的行为
TEST DatagramSocket_RecvFrom_NoData:
    // 验证: 无数据时返回std::nullopt (非std::expected error)
    //       不阻塞,不消耗CPU空转

// 8.3 边缘触发模式下的读取完整性
TEST DatagramSocket_EdgeTriggered_ReadCompleteness:
    // 配置: Socket注册为边缘触发 (EPOLLET)
    // 操作: 发送方快速发送1000个数据报
    // 验证: 接收方在一次OnReadable中循环读取,直到nullopt
    //       1000个数据报全部收到 (无遗漏)
    //       如果循环提前退出,剩余数据报不会触发新的事件通知 (边缘触发特征)

// 8.4 绑定地址冲突
TEST DatagramSocket_Bind_AddressInUse:
    // 配置: 两个Socket绑定相同地址 (reuse_addr=false)
    // 验证: 第二个Bind抛出异常或返回错误
    //       reuse_addr=true时两个Socket可绑定相同地址

// 8.5 SendTo无效地址
TEST DatagramSocket_SendTo_InvalidAddress:
    // 验证: 发送到不可达地址时:
    //       立即SendTo: 通常成功(仅写入缓冲区)
    //       后续: 可能收到ICMP错误, 在RecvFrom中返回kConnectionRefused
```

---

## 9. 端到端集成测试

```
// ============================================================
// 描述: 多组件协作的端到端并发测试
// ============================================================

// 9.1 多Client对单Server高并发
TEST E2E_ManyClientsToOneServer:
    // 配置: 1 Server, 1000 Client, 每Client 100条消息
    //       网络模拟器: 延迟5-15ms, 丢包率1%
    // 验证: 所有消息送达, 无丢失
    //       所有连接正常建立和关闭
    //       吞吐量满足预期 (不低于理论值的70%)
    //       长时间运行(30分钟)无内存泄漏/性能衰减

// 9.2 P2P对称通信
TEST E2E_PeerToPeer_Symmetric:
    // 配置: 2个Peer实例 (各为对方的Client+Server)
    // 操作: 双方同时Connect和Listen
    // 验证: 双方均能收发数据
    //       无死锁 (对称握手)
    //       一方Close,对端正确检测

// 9.3 网络分区恢复
TEST E2E_NetworkPartition_Recovery:
    // 配置: Client-Server已建立连接, 模拟网络分区 (100%丢包)
    // 操作: 持续30秒丢包 → 恢复网络
    // 验证: 分区期间: Server检测到stale并驱逐 (或保留)
    //       Client检测到超时/错误, 尝试重连
    //       恢复后: Client重连成功, 通信恢复

// 9.4 优雅关闭协议
TEST E2E_GracefulShutdown_Protocol:
    // 配置: Client-Server已建立, 正在通信
    // 操作: Server调用GracefulShutdown → Client收到CLOSE → ACK → Server收到ACK → 关闭
    // 验证: 完整握手流程在timeout_ms内完成
    //       双方最终状态均为kClosed
    //       优雅关闭期间拒绝新Send (返回kBlocked)

// 9.5 长时间运行稳定性
TEST E2E_LongRunning_Stability:
    // 配置: 1 Server, 50 Client (每Client每秒10条消息)
    // 操作: 持续运行24小时 (或加速模拟等效时长)
    // 验证: 无内存泄漏 (RSS稳定)
    //       无文件描述符泄漏 (lsof计数稳定)
    //       吞吐量在运行末期不低于初期的90%
    //       无未处理的错误累积
```

---

## 10. 内存安全与资源泄漏测试

```
// ============================================================
// 描述: 专项内存和资源泄漏检测测试
// ============================================================

// 10.1 Session创建/销毁循环
TEST Memory_SessionCreateDestroy_Loop:
    // 操作: 创建 → Start → Send一条消息 → Close → 销毁 × 100K次
    // 验证: ASan无泄漏报告
    //       内存占用无单调增长 (RSS稳定)

// 10.2 Server长时间运行内存稳定性
TEST Memory_Server_LongRunningStability:
    // 配置: 模拟客户端连接和断开 (平均会话时长5秒)
    // 操作: 运行1小时,客户端持续连接→通信→断开
    // 验证: sessions_大小有上限 (驱逐正常工作)
    //       总内存无单调增长

// 10.3 定时器泄漏检测
TEST Memory_TimerQueue_NoLeakAfterCancel:
    // 操作: Add 10K定时器 → Cancel全部 → 驱动FireExpired
    // 验证: 所有定时器被清理 (heap_空, canceled_空)
    //       无泄漏

// 10.4 回调闭包链的内存安全
TEST Memory_CallbackChain_NoLeak:
    // 验证: Session的回调闭包在Close/析构时被正确释放
    //       std::move_only_function析构时释放捕获的资源
    //       shared_ptr循环引用: Session持有lambda, lambda捕获shared_ptr<Session>
    //       → 应使用weak_ptr或明确的reset顺序避免循环
    //       此测试验证: Session析构后所有关联对象可被GC回收

// 10.5 Socket RAII安全性
TEST Memory_Socket_RAII_Safety:
    // 操作: DatagramSocket创建后被move → 原对象不应持有fd
    //       多次move → 最终析构只关闭一次fd
    //       异常路径: 构造函数中Bind失败 → fd在抛出前关闭 (无泄漏)
    // 验证: fd泄漏检测 (通过/dev/fd或lsof)
```

---

## 11. 性能回归测试

```
// ============================================================
// 描述: 性能基线与回归检测
// ============================================================

// 11.1 EventLoop吞吐量
TEST Perf_EventLoop_Throughput:
    // 度量: 空载EventLoop每秒钟可完成的循环次数
    //       满载 (10K Session) 每秒钟的Update+IO处理能力
    // 基线: 记录为性能回归检测阈值

// 11.2 TaskQueue延迟
TEST Perf_TaskQueue_Latency:
    // 度量: 任务从Push到开始执行的延迟分布 (P50/P95/P99)
    // 条件: 1生产者/1消费者 vs 8生产者/1消费者
    // 基线: P99 < 100μs (有锁队列) 或 < 10μs (无锁队列)

// 11.3 Session Send吞吐量
TEST Perf_Session_SendThroughput:
    // 度量: 单个Session的数据发送吞吐量 (Mbps)
    // 条件: 不同MTU和窗口大小组合
    // 基线: 记录最优配置下的吞吐量

// 11.4 Server会话创建速率
TEST Perf_Server_SessionCreationRate:
    // 度量: Server每秒可创建并初始化的Session数
    // 验证: 与上版本相比无显著退化 (>5%视为回归)
```

---

## 12. 确定性仿真测试 (可选高级测试)

```
// ============================================================
// 描述: 使用模拟时钟和网络模拟器进行完全确定性的集成测试
//       每个测试用例产生完全可复现的结果
// ============================================================

// 12.1 精确重传时序验证
TEST Sim_ExactRetransmitTiming:
    // 配置: 模拟时钟, 网络丢包模式已知, 固定随机种子
    // 验证: 每个重传包在精确的预期时间点被发送
    //       快速重传在收到确切N个重复ACK后触发
    //       RTO回退策略符合指数增长

// 12.2 拥塞窗口行为验证
TEST Sim_CongestionWindowBehavior:
    // 配置: 启用流控, 模拟特定丢包序列
    // 验证: 发送窗口大小变化符合预期模式 (慢启动→拥塞避免→快速恢复)
    //       丢包后窗口正确减半, ACK后窗口正确增长

// 12.3 乱序包重组验证
TEST Sim_OutOfOrderReassembly:
    // 配置: 预定义数据包乱序序列
    // 验证: 接收端正确重组为原始消息
    //       乱序包到达后消息立即可交付 (不等待)
    //       缺失包导致消息等待 (直到重传到达或超时)

// 12.4 完全确定性回归测试套件
TEST Sim_DeterministicRegressionSuite:
    // 配置: 一组预录制的网络trace (包含延迟/丢包/乱序序列)
    // 验证: 回放相同trace, 库的行为逐帧完全一致
    //       收发的每个包的时间戳和内容与baseline一致
    //       用于检测协议行为的不兼容变更
```

# Issue 6 修改记录

## 概述

基于 Issue 6 要求对 `doc/pseudocodes/` 目录下全部伪代码文件进行完整技术栈分析,提取并整理语言标准、平台支持、IO 模型、传输协议、线程模型、数据结构、设计模式、构建测试工具链及外部依赖等维度的技术选型信息,输出为技术栈文档。

---

## 1. 新增文件

| 文件 | 说明 |
|------|------|
| `doc/pseudocodes/07_tech_stack.md` | 完整技术栈信息文档 (新增) |
| `changelog/change_record_issue6.md` | 本次修改记录 (新增) |

---

## 2. 技术栈分析来源

分析覆盖 `doc/pseudocodes/` 目录下全部 7 个伪代码文件:

| 序号 | 文件 | 分析重点 |
|------|------|---------|
| 0 | `00_architecture_overview.md` | 分层架构、配置体系、线程模型、数据流 |
| 1 | `01_platform_layer.md` | EventLoop/DatagramSocket/WorkerPool/TaskQueue/TimerQueue 实现细节 |
| 2 | `02_session.md` | 传输协议会话抽象、协议引擎接口、状态机、回调体系 |
| 3 | `03_server.md` | 服务端端点、会话管理、健康检测、驱逐策略 |
| 4 | `04_client.md` | 客户端端点、异步连接、重连策略、状态机 |
| 5 | `05_api_reference.md` | 完整 API 签名、类型定义、线程安全约束、ProtocolEngine 接口 |
| 6 | `06_high_concurrency_tests.md` | 测试基础设施、工具链要求、测试优先级体系 |

---

## 3. 技术栈文档结构

`07_tech_stack.md` 包含以下 10 个章节及附录:

### 3.1 编程语言与标准
- C++17 核心标准
- C++20/23 polyfill 策略: `std::span` / `std::expected` / `std::move_only_function`
- 第三方替代: `tl::expected` / `fu2::unique_function` / `gsl::span`

### 3.2 平台与操作系统支持
- Linux (epoll + eventfd)
- Windows (IOCP + PostQueuedCompletionStatus)
- macOS/BSD (kqueue + pipe/kqueue user event)
- POSIX poll (通用回退)

### 3.3 IO 模型与事件驱动
- 边缘触发模式 (EPOLLET)
- 非阻塞数据报 Socket (UDP/UDPLite/Unix Domain Dgram/RAW)
- IPv4/IPv6/Unix Domain 地址族
- Socket 选项: SO_REUSEADDR / SO_RCVBUF / SO_SNDBUF / DSCP / TTL

### 3.4 传输协议
- 默认引擎: KCP (C API 封装)
- 抽象接口: ProtocolEngine (可替换为任意可靠传输协议)
- 4 种协议预设: Fast / Reliable / Balanced / Custom
- 完整协议参数表 (MTU/窗口/nodelay/流控等)

### 3.5 线程模型
- 3 种运行模式: 单线程 EventLoop / 多线程 Worker Pool / 互斥锁模式
- 4 种分配策略: 取模哈希 / 一致性哈希 / 轮询 / 最少会话
- 跨线程安全机制: PostTask 串行化

### 3.6 数据结构与算法
- TimerQueue: 小顶堆 (可替换为分层时间轮)
- TaskQueue: 有锁队列 (可替换为无锁 MPSC)
- Session 路由: unordered_map
- 定时器延迟删除: unordered_set + 惰性清理

### 3.7 设计模式
- 10 种设计模式: Pimpl / 工厂方法 / 策略 / 观察者 / 责任链 / RAII / 接口隔离 / 幂等 / 延迟删除 / 批量消费

### 3.8 构建与测试工具链
- 模拟时钟 + 网络模拟器 (确定性测试基础设施)
- TSan / ASan / LSan / Helgrind (代码质量工具)
- 性能回归指标 (吞吐量/延迟/创建速率)
- P0-P3 四级测试优先级体系

### 3.9 外部依赖
- KCP (ikcp.c/ikcp.h)
- POSIX Socket API
- C++ 标准库
- 可选 polyfill 库

### 3.10 库级全局配置与配置体系分层

---

## 4. 变更影响范围

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `doc/pseudocodes/07_tech_stack.md` | 新增 | 技术栈信息文档 |
| `changelog/change_record_issue6.md` | 新增 | 本次修改记录 |

无现有文件被修改。

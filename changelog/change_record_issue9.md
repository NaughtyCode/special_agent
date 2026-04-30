# Issue 9 修改记录

## 概述

基于 Issue 9 要求分析 `doc/pseudocodes/` 全部文档中分散在各模块的可伸缩参数,设计并实现一个集中的系统配置模块 (`ConfigurationManager`),系统启动时从 JSON 配置文件加载所有参数,支持分层覆盖 (默认值 → JSON → 环境变量 → 命令行) 和运行时热重载。同时同步更新技术栈文档。

---

## 1. 新增文件

| 文件 | 说明 |
|------|------|
| `doc/pseudocodes/08_system_config.md` | 系统配置模块完整伪代码 (新增) |
| `changelog/change_record_issue9.md` | 本次修改记录 (新增) |

---

## 2. 08_system_config.md — 系统配置模块

### 2.1 模块概述

`ConfigurationManager` 集中管理全库所有可伸缩参数,提供 JSON 文件 → 解析 → 验证 → 分发的完整配置管线。

**核心能力:**
- JSON 配置文件加载与解析
- 4 级优先级覆盖: 内置默认值 < JSON 文件 < 环境变量 (NETLIB_*) < 命令行 (--section.field)
- 分层反序列化: 6 个配置 Section 独立解析,缺失的 Section/Key 保留默认值
- 语义验证: 范围检查/逻辑一致性检查/阻塞性错误检测
- 运行时热重载: 原子交换 `shared_ptr<const SystemConfig>`,部分参数即时生效
- 配置变更通知: 观察者模式,组件可注册回调响应配置变更

### 2.2 SystemConfig 顶层结构

```
SystemConfig
  ├── LibraryConfig           // 库级: io_backend / engine_type / log_level / max_workers
  ├── SocketConfig             // Socket默认: reuse_addr / buffer sizes / dscp / ttl
  ├── SessionDefaultsConfig    // Session模板: 全部协议参数 (MTU/窗口/nodelay/流控)
  ├── ServerEndpointConfig     // Server: 监听地址 / 健康检测 / 驱逐策略
  ├── ClientEndpointConfig     // Client: 目标地址 / 重连策略 / 连接超时
  └── WorkerPoolConfig         // 线程池: num_workers / dispatch_strategy
```

### 2.3 配置来源优先级

```
1. 代码内置默认值 (最低)
      ↓ JSON文件覆盖
2. netlib_config.json
      ↓ 环境变量覆盖
3. NETLIB_<SECTION>_<FIELD> 环境变量
      ↓ 命令行覆盖
4. --section.field=value (最高)
```

### 2.4 文件内容章节

| 章节 | 内容 |
|------|------|
| §1 ConfigurationManager 伪代码 | 完整类定义: 构造/LoadFromFile/反序列化/验证/环境变量覆盖/热重载 |
| §2 JSON 配置文件完整示例 | 所有 Section 和字段的完整 JSON,含默认值和注释 |
| §3 按场景的配置 Profile 示例 | 低延迟游戏/公网移动游戏/批量数据同步 三种典型场景的配置 |
| §4 配置加载启动流程 | 从 JSON 加载到各层组件创建的完整 8 步时序 |
| §5 配置优先级与覆盖规则 | 4 级优先级详解 + 标量覆盖 vs 嵌套 Merge 语义 |
| §6 配置热更新分类 | 即时生效/周期性生效/新建Session生效/需重启生效 四类 |

### 2.5 参数汇总 — 从各文件提取的参数

| 来源文件 | 提取的配置参数 |
|---------|-------------|
| `00_architecture_overview.md` | LibraryConfig 全部字段,分层配置体系 |
| `01_platform_layer.md` | SocketConfig (reuse_addr/recv_buf/send_buf/dscp/ttl), WorkerPool num_workers/DispatchStrategy |
| `02_session.md` | SessionDefaultsConfig (engine_type/profile/nodelay/interval/resend/fc/mtu/window/buffer/metrics) |
| `03_server.md` | ServerEndpointConfig (listen/max_sessions/health_check/timeout/eviction/idle) |
| `04_client.md` | ClientEndpointConfig (remote/connect_timeout/local_bind/recv_buf), ReconnectConfig |
| `05_api_reference.md` | 所有枚举值的字符串映射 (IOBackend/EngineType/ProtocolProfile/EvictionPolicy等) |

---

## 3. 00_architecture_overview.md — 架构总览

### 3.1 设计目标 (1)

新增 JSON 配置文件描述:
> 通过 JSON 配置文件 + 分层参数化配置体系适配...系统启动时读取 JSON 配置文件初始化全库参数,支持环境变量和命令行覆盖。

### 3.2 库初始化与全局配置 (3.1)

**重构**: 将原来仅展示默认值结构的静态伪代码,替换为包含完整配置管线的初始化函数:

- 创建 `ConfigurationManager` + 从 JSON 文件加载
- 应用命令行覆盖 (`--server.listen_port=9000`)
- 解析 IOBackend 并创建 EventLoop
- 创建 WorkerPool (如多线程配置)
- 注册 SIGHUP 配置重载
- 配置覆盖范围注释 (列出所有可覆盖字段)

### 3.3 核心模块依赖关系图 (4)

**新增**: `ConfigurationMgr` 作为启动时最先初始化的模块,位于 Application 之上:
```
ConfigurationMgr → Application → Server / Client / Message
```

### 3.4 关键扩展点 (4)

**新增两项**:
- `0. ConfigurationMgr` — 从 JSON 文件加载全库配置,支持环境变量/命令行覆盖和热重载
- `6. JSON Parser` — 可替换为 nlohmann/json / simdjson / rapidjson

---

## 4. 07_tech_stack.md — 技术栈信息

### 4.1 新增 "配置体系" 章节 (7)

在数据结构与算法章节之后插入独立的配置体系章节,包含:

- **配置分级**: SystemConfig 6 层结构树形图
- **配置来源优先级**: 4 级覆盖流程图 (默认值 → JSON → 环境变量 → 命令行)
- **配置热更新分类**: 即时生效/周期性生效/新建Session生效/需重启生效 四类表格

### 4.2 设计模式章节 (8)

新增 4 种设计模式:

| 模式 | 应用位置 |
|------|---------|
| 快照不可变 | `shared_ptr<const SystemConfig>` 多线程无锁读取 |
| 分层反序列化 | 逐 Section 反序列化,缺失 key 保留默认值 |
| 环境注入 | `ApplyEnvOverrides` / `ApplyCmdLineOverrides` 实现 12-factor app |

### 4.3 外部依赖章节 (10)

新增 JSON 解析库依赖:
- `nlohmann/json` (header-only, C++17 友好,推荐)
- `simdjson` (高性能,零拷贝解析)

### 4.4 库级全局配置章节 (11)

**重构**: 将原来仅列出 `LibraryConfig` 两行的内容,扩展为完整配置分层结构树和优先级说明,引用 `08_system_config.md`。

### 4.5 章节重新编号

新增 "7. 配置体系" 章节后,原有章节 7-10 顺延为 8-11,移除过期附录。

---

## 5. 变更影响范围

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `doc/pseudocodes/08_system_config.md` | **新增** | 系统配置模块完整伪代码 (6 个章节,~400 行) |
| `doc/pseudocodes/00_architecture_overview.md` | 修改 (4处) | 设计目标/初始化流程/依赖图/扩展点 |
| `doc/pseudocodes/07_tech_stack.md` | 修改 (5处) | 新增配置体系/设计模式/新增JSON依赖/重构章节11/章节重编号 |
| `changelog/change_record_issue9.md` | 新增 | 本次修改记录 |

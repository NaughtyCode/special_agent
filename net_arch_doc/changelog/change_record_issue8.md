# Issue 8 修改记录

## 概述

基于 Issue 8 要求分析 `doc/pseudocodes/` 全部伪代码文件的协议引擎表述,将 QUIC (Issue 原文记为 "QUICK",应为 IETF 标准传输协议 QUIC 的笔误) 作为与 KCP 并列的正式协议引擎加入所有相关文档。KCP 和 QUIC 均为基于 UDP 的可靠传输协议,通过统一的 `ProtocolEngine` 接口接入,用户可通过 `Session::Config::engine_type` 字段选择。

---

## 1. 新增类型定义

### 1.1 EngineType 枚举

在 `02_session.md` 和 `05_api_reference.md` 中分别新增:

```
enum class EngineType {
    kEngineKCP  = 0,  // KCP协议引擎 (默认,轻量级可靠UDP,无内置加密)
    kEngineQUIC = 1   // QUIC协议引擎 (基于UDP,内置TLS 1.3加密,
                      //  支持连接迁移/0-RTT/多路复用)
};
```

### 1.2 Session::Config 新增字段

在 `02_session.md`、`05_api_reference.md` 和 `00_architecture_overview.md` 的 `Session::Config` 中新增:

```
EngineType engine_type = EngineType::kEngineKCP;  // 协议引擎选择,默认KCP
```

### 1.3 LibraryConfig 新增字段

在 `00_architecture_overview.md` 的 `LibraryConfig` 中新增:

```
.default_engine_type  // EngineType  默认协议引擎 (kEngineKCP / kEngineQUIC)
```

---

## 2. 02_session.md — 传输协议层核心

### 2.1 协议引擎注入注释

**修正前**: `可注入: KCP / 自定义 / Mock`

**修正后**: `可注入: KCP / QUIC / 自定义 / Mock`

### 2.2 发送管线协议头说明

在 KCP 示例后新增 QUIC 示例:
```
//   以QUIC为例: 头部1-20字节 (短头1字节,长头最多20字节) =
//     HeaderForm(1) + FixedBit(1) + SpinBit(1) + ReservedBits(2) +
//     ConnectionID(可变) + PacketNumber(可变) + Payload
```

### 2.3 协议头解析章节标题

**修正前**: `协议头解析 (以KCP为例,Engine可替换)`

**修正后**: `协议头解析 (以KCP和QUIC为例,Engine可替换)`

同时补充 QUIC 最小头部大小说明 (`MIN_HEADER_SIZE = 1 字节` 短头模式)。

---

## 3. 05_api_reference.md — Public API 参考

### 3.1 ProtocolEngine 接口描述

**修正前**:
```
// 描述: 协议引擎抽象接口 — 实现此接口即可替换底层传输协议
//       默认实现: KCP (ikcp_* C API封装)
//       可替换为: 自定义可靠UDP / QUIC-like / Mock引擎 (测试用)
```

**修正后**:
```
// 描述: 协议引擎抽象接口 — 实现此接口即可替换底层传输协议
//       默认实现: KCP (ikcp_* C API封装)
//       第二实现: QUIC (基于UDP的多路复用安全传输,内置TLS 1.3加密)
//       可替换为: 自定义可靠UDP / Mock引擎 (测试用)
```

### 3.2 SendHandshake / SendProbe 虚函数注释

从仅 KCP 示例扩展为双协议对照说明:
- `SendHandshake`: KCP → 空数据包 / QUIC → Initial 包 (TLS 1.3 ClientHello)
- `SendProbe`: KCP → WASK → WINS / QUIC → PING → PONG

### 3.3 ProtocolEngineFactory::Create 注释

**修正前**: `默认: 创建KCP引擎实例`

**修正后**: 改为根据 `Config::engine_type` 分派:
- `kEngineKCP` → 创建 KCP 引擎实例
- `kEngineQUIC` → 创建 QUIC 引擎实例

---

## 4. 07_tech_stack.md — 技术栈信息

### 4.1 传输协议表扩展

QUIC 从 "可替换方案" 升级为 "第二协议引擎",新增独立行:

| 层级 | 选型 | 说明 |
|------|------|------|
| **第二协议引擎** | QUIC | 基于 UDP 的多路复用安全传输;内置 TLS 1.3;支持 0-RTT/连接迁移/无队头阻塞多流复用 |
| **引擎选择** | `engine_type` 字段 | `kEngineKCP` (0,默认) / `kEngineQUIC` (1) |

### 4.2 新增: KCP vs QUIC 选型指南

新增 10 维度对比表:

| 维度 | KCP | QUIC |
|------|-----|------|
| 传输层 | 基于 UDP,自定义可靠性 | 基于 UDP,IETF 标准 (RFC 9000) |
| 加密 | 无内置加密 | 强制 TLS 1.3 |
| 握手延迟 | 0-RTT | 0-RTT / 1-RTT |
| 多路复用 | 单流 | 多流 (Stream ID 隔离) |
| 连接迁移 | 不支持 | 支持 (Connection ID) |
| 拥塞控制 | 固定窗口 | 可插拔算法 |
| 头部开销 | 24 字节 | 1-20 字节 |
| 实现复杂度 | 低 (~2000 行 C) | 高 (需 TLS 库) |
| 适用场景 | 局域网/私有网游戏 | 公网/移动端游戏 |
| 外部依赖 | 仅 ikcp.c/h | TLS 库 |

### 4.3 外部依赖表更新

新增 QUIC 依赖行:
- BoringSSL (推荐) / OpenSSL (Linux/Android) / PicoTLS (嵌入式) / SecureTransport (iOS/macOS 原生)

---

## 5. 00_architecture_overview.md — 架构总览

### 5.1 协议配置模式章节 (3.8)

**新增**: 引擎类型切换示例代码:
```
config.engine_type = EngineType::kEngineQUIC  // 切换为QUIC协议引擎
```

### 5.2 扩展点描述

**修正前**: `Protocol Engine — 实现统一接口即可替换为任意可靠传输协议`

**修正后**: `Protocol Engine — 实现统一接口即可替换为任意可靠传输协议 (内置KCP和QUIC两种实现)`

### 5.3 配置体系新增字段

`LibraryConfig` 新增 `default_engine_type`, `Session::Config` 新增 `engine_type`。

---

## 6. 03_server.md — 服务端抽象层

### 6.1 routing_key 路由键注释

**修正前**: `conv是KCP的概念,泛化为routing_key以支持其他协议`

**修正后**: `conv是KCP的概念,QUIC使用Connection ID,泛化为routing_key以支持多协议`

### 6.2 ExtractRoutingKey 注释扩展

新增 QUIC Connection ID 提取说明:
```
// QUIC: Connection ID 位于偏移0 (长头) 或 偏移1 (短头),长度可变(0-20字节)
//       取后4字节哈希或使用SCID作为路由键
```

### 6.3 探活包注释

从仅 KCP 示例扩展为双协议对照 (WASK/WINS 和 PING/PONG)。

---

## 7. 关于 "QUICK" 的说明

Issue 原文中的 "QUICK" 应为 **QUIC** (Quick UDP Internet Connections) 的笔误。QUIC 是 IETF 标准化传输协议 (RFC 9000),已被 HTTP/3 采用。本文档统一使用 **QUIC** 作为正式名称。

---

## 8. 变更影响范围

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `doc/pseudocodes/02_session.md` | 修改 (5处) | 引擎注入注释/发送管线/头解析/新增EngineType枚举/Config新增字段 |
| `doc/pseudocodes/05_api_reference.md` | 修改 (6处) | ProtocolEngine描述/探活注释/握手注释/工厂注释/新增EngineType枚举/Config新增字段 |
| `doc/pseudocodes/07_tech_stack.md` | 修改 (3处) | 传输协议表/新增选型指南/外部依赖表 |
| `doc/pseudocodes/00_architecture_overview.md` | 修改 (4处) | 配置模式代码/扩展点注释/Config结构/LibraryConfig |
| `doc/pseudocodes/03_server.md` | 修改 (3处) | routing_key注释/ExtractRoutingKey注释/探活包注释 |
| `changelog/change_record_issue8.md` | 新增 | 本次修改记录 |

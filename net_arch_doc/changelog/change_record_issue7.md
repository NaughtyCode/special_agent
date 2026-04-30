# Issue 7 修改记录

## 概述

基于 Issue 7 要求分析 `doc/pseudocodes/` 全部伪代码文件的平台表述,将 iOS 和 Android 平台支持显式加入所有相关文档。iOS 内核为 Darwin (与 macOS 共用 kqueue),Android 内核为 Linux (共用 epoll),二者均可复用现有 IO 后端实现。

---

## 1. 00_architecture_overview.md — 架构总览

### 1.1 架构分层图

**修正前**: `EventLoop (epoll / IOCP / kqueue 统一抽象)`

**修正后**: `EventLoop (epoll / IOCP / kqueue / poll 统一抽象)`

**原因**: 原表述遗漏了 poll 回退方案,补充 poll 使分层图同时覆盖所有 5 个平台 (Linux/Android/Windows/macOS/iOS + 回退)。

### 1.2 扩展点列表 — IOBackend

**修正前**: `IOBackend — 可替换为epoll/IOCP/kqueue/poll`

**修正后**: `IOBackend — 可替换为epoll(Linux/Android)/IOCP(Windows)/kqueue(macOS/BSD/iOS)/poll(回退)`

### 1.3 LibraryConfig 注释

**修正前**: `.io_backend // kAutoDetect / kEpoll / kIocp / kKqueue / kPoll`

**修正后**: `.io_backend // kAutoDetect / kEpoll(Linux/Android) / kIocp(Windows) / kKqueue(macOS/BSD/iOS) / kPoll(回退)`

---

## 2. 01_platform_layer.md — 平台抽象层

### 2.1 EventLoop 类描述

**修正前**: `封装 epoll(Linux) / IOCP(Windows) / kqueue(macOS/BSD)`

**修正后**: `封装 epoll(Linux/Android) / IOCP(Windows) / kqueue(macOS/BSD/iOS)`

### 2.2 平台映射注释 (新增)

在构造函数注释中新增平台映射说明:
```
// 平台映射: Linux/Android → kEpoll, Windows → kIocp,
//          macOS/iOS → kKqueue, 通用回退 → kPoll
```

### 2.3 唤醒通道注释

**修正前**:
```
//   Linux → eventfd
//   macOS/BSD → pipe 或 kqueue user event
```

**修正后**:
```
//   Linux/Android → eventfd
//   macOS/BSD/iOS → pipe 或 kqueue user event
```

**原因**: Android 使用 Linux 内核,支持 eventfd;iOS 使用 Darwin 内核,与 macOS 机制完全一致。

---

## 3. 05_api_reference.md — Public API 参考

### 3.1 EventLoop 类描述

**修正前**: `统一封装epoll/IOCP/kqueue/poll`

**修正后**: `统一封装epoll(Linux/Android)/IOCP(Windows)/kqueue(macOS/BSD/iOS)/poll(回退)`

### 3.2 IOBackend 枚举注释

**修正前**:
```
kEpoll,  // Linux epoll
kKqueue, // macOS/BSD kqueue
```

**修正后**:
```
kEpoll,  // Linux/Android epoll
kKqueue, // macOS/BSD/iOS kqueue
```

---

## 4. 07_tech_stack.md — 技术栈信息

### 4.1 平台支持表

新增两行:

| 平台 | IO 模型 | 唤醒机制 |
|------|---------|---------|
| **Android** | epoll (Linux 内核) | eventfd 或 pipe |
| **iOS** | kqueue (Darwin 内核) | pipe 或 kqueue user event |

### 4.2 后端选择注释

新增平台归属标注和编译说明:
- `kEpoll` (Linux/Android) / `kIocp` (Windows) / `kKqueue` (macOS/BSD/iOS) / `kPoll` (回退)
- Android 通过 NDK 编译说明
- iOS 通过 Xcode 编译说明

### 4.3 移动平台特殊考量 (新增章节)

新增移动平台特有考量表,覆盖:

| 考量点 | 说明 |
|--------|------|
| **网络切换** | WiFi ↔ 蜂窝网络切换时 IP 变更,应用层需感知并触发重连 |
| **应用生命周期** | 后台/前台切换时 OS 可能暂停 Socket,需管理会话暂停/恢复 |
| **省电优化** | 后台网络活动限制,建议降低健康检测和 Update 频率 |
| **NDK 编译** | Android 多 ABI 交叉编译 (armeabi-v7a/arm64-v8a/x86_64) |
| **Xcode 集成** | iOS Framework/静态库构建,arm64 真机 + x86_64 模拟器 |
| **IPv6 就绪** | App Store 审核要求 IPv6-only 网络兼容 |
| **蜂窝网络特征** | 高延迟波动 (50-500ms)、高丢包率,需适应性协议调参 |

### 4.4 事件循环说明

**修正前**: `封装 epoll/IOCP/kqueue/poll`

**修正后**: `封装 epoll(Linux/Android)/IOCP(Windows)/kqueue(macOS/BSD/iOS)/poll(回退)`

### 4.5 POSIX Socket API 依赖说明

**修正前**: `Linux/macOS/BSD 原生`

**修正后**: `Linux/Android/macOS/BSD/iOS 原生`

---

## 5. 技术原理说明

iOS 和 Android 无需新增 IO 后端实现,原因为:

- **Android 内核为 Linux** — 原生支持 epoll 和 eventfd,直接复用现有的 `EpollImpl`
- **iOS 内核为 Darwin** (与 macOS 相同) — 原生支持 kqueue,直接复用现有的 `KqueueImpl`
- 两个平台的 POSIX Socket API (`sendto`/`recvfrom`) 行为与桌面平台一致
- `PlatformDetect::BestAvailable()` 的自动检测逻辑可正确识别 Android (Linux) 和 iOS (Darwin) 并选择对应后端

---

## 6. 变更影响范围

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `doc/pseudocodes/00_architecture_overview.md` | 修改 (3处) | 架构图/扩展点/配置注释加入平台归属 |
| `doc/pseudocodes/01_platform_layer.md` | 修改 (3处) | EventLoop描述/平台映射/唤醒通道加入Android/iOS |
| `doc/pseudocodes/05_api_reference.md` | 修改 (2处) | EventLoop描述/IOBackend枚举注释更新 |
| `doc/pseudocodes/07_tech_stack.md` | 修改 (5处) | 平台表/后端选择/移动考量/IO组件/POSIX依赖 |
| `changelog/change_record_issue7.md` | 新增 | 本次修改记录 |

# core/ 目录迁移报告

> 日期: 2026-06-13
> 目标: 彻底删除 `core/`，所有功能归属到 V2 架构

---

## 1. 原始文件列表

| 文件 | 状态 |
|------|------|
| `core/__init__.py` | 已在 Phase 10 删除 |
| `core/llm.py` | 已在 Phase 10 删除 |
| `core/registry.py` | 已在 Phase 10 删除 |
| `core/state.py` (RuntimeState) | 已在 Phase 4 删除 |
| `core/pidfile.py` | 本次迁移 |

## 2. 实际被使用的部分

仅 `pidfile.py` 被 `interface/daemon.py` 引用（4 个函数）：

| 函数 | 用途 |
|------|------|
| `write(path)` | 守护进程启动时写入 PID 文件 |
| `read(path)` | 守护进程状态检测时读取 PID |
| `is_running(pid)` | 检查进程是否存活（跨平台） |
| `remove(path)` | 守护进程停止时删除 PID 文件 |

## 3. 删除的部分

| 文件 | 原因 |
|------|------|
| `core/__init__.py` | V1 兼容层，功能已迁移到 `model/llm.py` |
| `core/llm.py` | V1 代理层，`runtime/factory.py` 直接使用 `ModelFactory` |
| `core/registry.py` | 死代码，无引用 |
| `core/state.py` | `RuntimeState` 已被 `SessionManager` + `SessionState` 替代 |

## 4. 迁移后的目录

```
core/pidfile.py  →  kernel/pidfile.py
```

职责归属：PID 文件管理属于进程基础设施，应归入 `kernel/`（进程生命周期管理）。

## 5. 修改的引用

| 文件 | 旧 import | 新 import |
|------|----------|----------|
| `interface/daemon.py` | `from haven.core.pidfile import ...` | `from haven.kernel.pidfile import ...` |

## 6. 测试结果

```
208 passed, 0 failed
```

## 7. 删除确认

```
src/haven/core/          → 已删除 ✓
全局引用 haven.core.*    → 零匹配 ✓
```

---

**`core/` 目录已从项目中完全移除。**

# Haven V2 迁移最终报告

> 日期: 2026-06-12
> 状态: 完成

---

## 迁移概览

从旧的 `runtime/` 大杂烩架构迁移到 12 层 V2 架构，共经历 10 个 Phase。

---

## 已删除内容

| 类别 | 删除项 |
|------|--------|
| **目录** | `src/haven/cli/`, `src/haven/channels/`, `src/haven/tools/`, `src/haven/skills/`, `src/haven/middleware/`, `src/haven/runtime/agents/`, `src/haven/runtime/workflows/` |
| **文件** | `runtime/coordinator.py`, `runtime/dispatcher.py`, `runtime/state.py`, `runtime/stream.py`, `runtime/registry.py`, `core/state.py` (RuntimeState), `core/registry.py` (old Registry) |
| **类** | `Coordinator`, `Dispatcher`, `RuntimeState`, `BaseAgent` (renamed to Agent), `ToolRegistry`, `SkillRegistry` (merged to CapabilityRegistry), `ToolLoader` (→ CapabilityLoader), `MemoryPipeline` (→ MemoryManager) |

---

## 新增架构

```
src/haven/
├── kernel/           # Phase 1  — AgentEvent, TraceContext, Lifecycle
├── infrastructure/   # Phase 10 — StreamChunk, 公共类型
├── config/           # Phase 2  — AppConfig, ConfigLoader
├── model/            # Phase 2  — LLMClient, ModelFactory
├── session/          # Phase 4  — Session, SessionManager
├── execution/        # Phase 5  — Planner (LangGraph Flow), Pipeline, Executor
├── agent/            # Phase 6  — Agent (LangChain create_agent)
├── capability/       # Phase 3  — CapabilityRegistry (Tool + Skill 统一)
├── memory/           # Phase 7  — MemoryManager, VectorMemory, ConflictResolver
├── workflow/         # Phase 8  — WorkflowEngine, WorkflowRegistry
├── interface/        # Phase 9  — CLI, HTTP API, WebSocket
└── runtime/          # retained — Runtime 容器, ContextBuilder, factory
```

---

## 架构对比

| 维度 | 旧架构 (V1) | 新架构 (V2) |
|------|------------|------------|
| 执行入口 | `Runtime` → `Coordinator` → `Dispatcher` | `Runtime` → `Executor` (唯一入口) |
| Agent 调用 | Dispatcher 直接调用 Agent | Executor → Pipeline → Agent |
| Skill/Tool | 两个独立 Registry | 统一 CapabilityRegistry |
| Session | 薄 RuntimeState dataclass | SessionManager + SessionState |
| Memory | 手动 `_trigger_memory()` | MemoryManager.after_turn() |
| Workflow | runtime/workflows/ + import side-effect | workflow/definitions/ + 装饰器注册 |
| Config | 全局 settings 单例 | AppConfig 注入 + 4 级优先级 |
| Model | 直接 BaseChatModel | LLMClient 包装，Agent 不知实现 |
| Agent | BaseAgent 耦合 Session | Agent 纯净（thread_id 参数） |
| 事件 | 无 | AgentEvent + Trace |
| Interface | cli/ + channels/ 分离 | 统一 interface/ + HTTP |

---

## 测试结果

```
203 passed, 0 failed, 14 warnings

tests/agent/        15 tests
tests/capability/   43 tests (registry + resolver + loader + tool)
tests/config/       18 tests
tests/execution/    10 tests
tests/kernel/       54 tests
tests/memory/       15 tests
tests/model/        11 tests
tests/session/      23 tests
tests/workflow/     10 tests
```

---

## 最终架构

```
Interface (CLI / HTTP / WebSocket)
    │ 只能调用 Runtime.execute()
    ▼
Runtime (容器, factory assembly)
    │
    ▼
Executor (统一执行入口)
    ├── Planner (LangGraph StateGraph: classify → select_skills → build_plan → validate)
    └── ExecutionPipeline (3 条路径)
        ├── WorkflowEngine → Workflow
        ├── Multi-step 拓扑排序
        └── Direct → Agent
            ├── LLMClient (OpenAI / DeepSeek)
            ├── Capability Registry (Tool + Skill)
            ├── SessionManager → Session
            └── MemoryManager → Fact + Vector
```

**依赖方向（单向）:**
```
Interface → Runtime → Execution → Agent → Capability → Memory
                ↓         ↓          ↓
           Infrastructure ← Kernel ← Config / Model
```

**State 流向:**
```
SessionManager (会话状态)
    ├── Session.id → LangGraph checkpointer (消息持久化)
    └── SessionState (turn_count, active_skills)

MemoryManager (长期记忆)
    ├── FactStore (SQLite 语义事实)
    ├── VectorMemory (ChromaDB 向量检索, 可选)
    └── ConflictResolver (LLM 冲突检测)
```

---

## 合规检查

- [x] 代码库只剩 V2 架构
- [x] 无 legacy / compat / adapter 目录
- [x] 无 RuntimeState 引用
- [x] 无 core.registry 引用
- [x] 无旧 middleware 模块
- [x] 所有执行经过 Executor
- [x] Runtime 不直接调用 Agent
- [x] Agent 不依赖 Session/Memory/CLI
- [x] Tool + Skill 统一注册表
- [x] 203 tests pass
- [x] CLI 可运行
- [x] 文档已更新
